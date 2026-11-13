"""The printed daily plan (D123) hangs where everyone can see it, so it is as
public as the board: names, placements, times and «Diverse info» only."""
import datetime as dt
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, demo, importer, planner, printout, service  # noqa: E402

SHEET_KEYS = {"date", "weekday", "weekend", "published", "has_plan", "shifts", "columns", "crew", "day_info"}
SHIFT_KEYS = {"label", "span", "rotation", "zones"}
ZONE_KEYS = {"zone_id", "name", "functions"}
FUNCTION_KEYS = {"name", "people"}
PERSON_KEYS = {"name", "note", "moves"}
MOVE_KEYS = {"zone_id", "zone_name", "short_name", "at"}
CREW_KEYS = {"name", "span"}
TEMPLATE_NAMES = SHEET_KEYS | {"sheets", "sheet", "shift", "zone", "fn", "p", "m", "printed_at",
                               "autoprint", "back", "loop", "strftime"}


def next_weekday(day: dt.date) -> dt.date:
    while day.weekday() > 4:
        day += dt.timedelta(days=1)
    return day


class PrintSheetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        db.set_mode("demo")
        self.conn = db.get_conn(self.tmp / "t.db")
        db.init_schema(self.conn)
        self.conn.execute("PRAGMA foreign_keys = OFF")
        with self.conn:
            importer.import_seed(self.conn, people=True)
        self.conn.execute("PRAGMA foreign_keys = ON")
        demo.ensure(self.conn)
        self.day = next_weekday(dt.date.today() + dt.timedelta(days=1))
        planner.suggest_day(self.conn, self.day)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_sheet_holds_only_public_fields(self):
        sheet = printout.day_sheet(self.conn, self.day)
        self.assertEqual(set(sheet), SHEET_KEYS)
        self.assertTrue(sheet["shifts"])
        for shift in sheet["shifts"]:
            self.assertEqual(set(shift), SHIFT_KEYS)
            for zone in shift["zones"]:
                self.assertEqual(set(zone), ZONE_KEYS)
                for fn in zone["functions"]:
                    self.assertEqual(set(fn), FUNCTION_KEYS)
                    for person in fn["people"]:
                        self.assertEqual(set(person), PERSON_KEYS)
                        for move in person["moves"]:
                            self.assertEqual(set(move), MOVE_KEYS)
        for person in sheet["crew"]:
            self.assertEqual(set(person), CREW_KEYS)

    def test_everyone_placed_is_on_the_sheet_once_with_their_moves(self):
        sheet = printout.day_sheet(self.conn, self.day)
        rows = service.day_assignments(self.conn, self.day)
        placed = {r["display_name"] for r in rows}
        people = [p for s in sheet["shifts"] for z in s["zones"] for f in z["functions"] for p in f["people"]]
        names = [p["name"] for p in people]
        self.assertEqual(sorted(names), sorted(placed))                 # each person once
        functions = {}
        for r in sorted(rows, key=lambda r: r["start"]):
            functions.setdefault(r["display_name"], [])
            if not functions[r["display_name"]] or functions[r["display_name"]][-1] != r["function_id"]:
                functions[r["display_name"]].append(r["function_id"])
        for p in people:                                                # a chip per change of function
            self.assertEqual(len(p["moves"]), len(functions[p["name"]]) - 1, p["name"])
        self.assertTrue(any(p["moves"] for p in people))

    def test_draft_and_published(self):
        self.assertFalse(printout.day_sheet(self.conn, self.day)["published"])
        with self.conn:
            self.conn.execute("UPDATE plan_days SET status = 'published' WHERE plan_date = ?",
                              (self.day.isoformat(),))
        self.assertTrue(printout.day_sheet(self.conn, self.day)["published"])

    def test_days_without_a_plan_are_left_out_of_a_range(self):
        far = self.day + dt.timedelta(days=200)
        self.assertEqual(printout.sheets(self.conn, far, 7), [])
        self.assertEqual(len(printout.sheets(self.conn, far, 1)), 1)      # one day: say so instead
        self.assertEqual(len(printout.sheets(self.conn, self.day, 1)), 1)
        self.assertLessEqual(len(printout.sheets(self.conn, self.day, 99)), 14)

    def test_the_print_template_uses_nothing_else(self):
        text = (ROOT / "app" / "templates" / "print.html").read_text(encoding="utf-8")
        text = re.sub(r"<script>.*?</script>", lambda m: "".join(re.findall(r"{[{%].*?[}%]}", m.group(0),
                                                                            flags=re.S)), text, flags=re.S)
        names = set()
        for expr in re.findall(r"{[{%](.*?)[}%]}", text, flags=re.S):
            expr = re.sub(r"\"[^\"]*\"|'[^']*'", "", expr)
            expr = re.sub(r"\|\s*[a-z_]+", "", expr)
            expr = re.sub(r"\.[a-z_][a-z0-9_]*", "", expr)             # attributes of allowed names
            names.update(re.findall(r"(?<![\w.])([a-z_][a-z0-9_]*)", expr))
        keywords = {"if", "else", "elif", "endif", "for", "in", "endfor", "not", "and", "or", "block",
                    "endblock", "extends", "set", "is", "none", "true", "false", "title", "body_class",
                    "header", "content"}
        unexpected = names - keywords - TEMPLATE_NAMES
        self.assertFalse(unexpected, f"The print template refers to {sorted(unexpected)} – is that public?")


if __name__ == "__main__":
    unittest.main()

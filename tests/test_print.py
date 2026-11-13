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

SHEET_KEYS = {"date", "weekday", "weekend", "published", "has_plan", "tables", "index", "crew", "day_info"}
TABLE_KEYS = {"label", "span", "columns", "functions"}
FUNCTION_KEYS = {"name", "zone", "zone_id", "cells"}
CELL_KEYS = {"name", "note"}
INDEX_KEYS = {"name", "span", "steps"}
STEP_KEYS = {"function", "zone_id", "at"}
CREW_KEYS = {"name", "span"}
TEMPLATE_NAMES = SHEET_KEYS | {"sheets", "sheet", "table", "col", "fn", "cell", "p", "step", "printed_at",
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
        self.assertTrue(sheet["tables"] and sheet["index"])
        for table in sheet["tables"]:
            self.assertEqual(set(table), TABLE_KEYS)
            for fn in table["functions"]:
                self.assertEqual(set(fn), FUNCTION_KEYS)
                self.assertEqual(len(fn["cells"]), len(table["columns"]))
                for cell in fn["cells"]:
                    for person in cell:
                        self.assertEqual(set(person), CELL_KEYS)
        for person in sheet["index"]:
            self.assertEqual(set(person), INDEX_KEYS)
            for step in person["steps"]:
                self.assertEqual(set(step), STEP_KEYS)
        for person in sheet["crew"]:
            self.assertEqual(set(person), CREW_KEYS)

    def test_everyone_placed_is_on_the_sheet_once_in_the_index(self):
        sheet = printout.day_sheet(self.conn, self.day)
        placed = {r["display_name"] for r in service.day_assignments(self.conn, self.day)}
        names = [p["name"] for p in sheet["index"]]
        self.assertEqual(sorted(set(names)), sorted(placed))
        self.assertEqual(len(names), len(set(names)))
        in_tables = {p["name"] for t in sheet["tables"] for f in t["functions"] for c in f["cells"] for p in c}
        self.assertEqual(in_tables, placed)

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

"""The board is public (D46, D120): it may show names, placements, times and
«Diverse info» – nothing else. These tests make a leak a failing test."""
import datetime as dt
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, demo, importer, kiosk, planner, service  # noqa: E402

MODEL_KEYS = {"now", "plan_date", "day_kind", "zones", "next_change", "arrivals", "adhoc_crew",
              "day_info", "has_plan"}
ZONE_KEYS = {"zone_id", "name", "functions", "adhoc_zone", "optional"}
FUNCTION_KEYS = {"function_name", "adhoc", "order", "people"}
PERSON_KEYS = {"display_name", "next"}
NEXT_KEYS = {"short_name", "zone_id", "zone_name", "time"}
ARRIVAL_KEYS = {"display_name", "function_name", "zone_id"}
CREW_KEYS = {"display_name", "hours"}
# Everything the board template may refer to (besides loop variables).
TEMPLATE_NAMES = MODEL_KEYS | {"preview", "theme", "zone", "fn", "person", "arrival", "loop"}


class BoardContentTest(unittest.TestCase):
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

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_board_model_holds_only_public_fields(self):
        day = dt.date.today()
        planner.suggest_day(self.conn, day)
        with self.conn:
            self.conn.execute("UPDATE plan_days SET status = 'published' WHERE plan_date = ?", (day.isoformat(),))
        for hour in (8, 12, 16, 23):
            model = service.build_display_model(self.conn, dt.datetime.combine(day, dt.time(hour)))
            self.assertEqual(set(model), MODEL_KEYS)
            for zone in model["zones"]:
                self.assertLessEqual(set(zone), ZONE_KEYS)
                for fn in zone["functions"]:
                    self.assertLessEqual(set(fn), FUNCTION_KEYS)
                    for person in fn["people"]:
                        self.assertLessEqual(set(person), PERSON_KEYS)
                        if person["next"]:
                            self.assertLessEqual(set(person["next"]), NEXT_KEYS)
            for arrival in model["arrivals"]:
                self.assertLessEqual(set(arrival), ARRIVAL_KEYS)
            for person in model["adhoc_crew"]:
                self.assertLessEqual(set(person), CREW_KEYS)

    def test_the_board_template_uses_nothing_else(self):
        text = (ROOT / "app" / "templates" / "display.html").read_text(encoding="utf-8")
        names = set()
        for expr in re.findall(r"{[{%](.*?)[}%]}", text, flags=re.S):
            expr = re.sub(r"\"[^\"]*\"|'[^']*'", "", expr)        # string literals
            expr = re.sub(r"\|\s*[a-z_]+", "", expr)              # filters (|length …)
            names.update(re.findall(r"(?<![\w.])([a-z_][a-z0-9_]*)", expr))
        keywords = {"if", "else", "elif", "endif", "for", "in", "endfor", "not", "and", "or", "block",
                    "endblock", "extends", "set", "is", "none", "true", "false", "with", "endwith",
                    "title", "body_class", "header", "head", "content", "range"}
        unexpected = names - keywords - TEMPLATE_NAMES
        self.assertFalse(unexpected, f"The board template refers to {sorted(unexpected)} – is that public?")


class BoardWindowTest(unittest.TestCase):
    def test_only_board_paths_are_open_to_the_board_window(self):
        from app import main
        for path in ("/display", "/static/app.css", "/tavle", "/tavle/av"):
            self.assertTrue(main._board_path(path), path)
        for path in ("/", "/admin", "/plan/dag", "/import", "/displayx", "/admin/regler"):
            self.assertFalse(main._board_path(path), path)

    def test_kiosk_command(self):
        cmd = kiosk.command("edge", "msedge.exe", "http://127.0.0.1:8000/tavle", Path("p"), 1920)
        self.assertEqual(cmd[:3], ["msedge.exe", "--kiosk", "http://127.0.0.1:8000/tavle"])
        self.assertIn("--user-data-dir=p", cmd)
        self.assertIn("--window-position=1920,0", cmd)
        self.assertIn("--app=http://x/tavle", kiosk.command("chrome", "chrome", "http://x/tavle", Path("p"), 0))


if __name__ == "__main__":
    unittest.main()

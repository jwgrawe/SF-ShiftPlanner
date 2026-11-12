"""The zone swap (D107, Q18) and the notice when someone can't rotate."""
import datetime as dt
import shutil
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import checks, db, importer, planner  # noqa: E402

DAY = dt.date(2026, 11, 17)           # a Tuesday: rotation at 11:00 for D shifts
ALL = ["produksjon_uren", "arbeidsbord", "kontrollsone", "sterrad", "poliklinikker_lospakk",
       "produksjon_steril", "ansvarsvakt", "driftskoordinator"]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        db.set_mode("demo")
        self.conn = db.get_conn(self.tmp / "t.db")
        db.init_schema(self.conn)
        self.conn.execute("PRAGMA foreign_keys = OFF")
        with self.conn:
            importer.import_seed(self.conn, people=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        # Sixteen on D (07–15) – enough to cover 07–11 and 11–15 – one of
        # them DK-coded, one (P14) who can't work at Arbeidsbord.
        with self.conn:
            self.conn.execute("INSERT INTO plan_days (plan_date, status) VALUES (?, 'draft')",
                              (DAY.isoformat(),))
            for i in range(1, 17):
                eid = f"P{i:02d}"
                self.conn.execute("INSERT INTO employees (employee_id, source_label, first_name, last_name, "
                                  "display_name, works_at) VALUES (?, ?, ?, ?, ?, 'sf')",
                                  (eid, eid, eid, "X", eid))
                comps = [c for c in ALL if not (eid == "P14" and c == "arbeidsbord")]
                self.conn.executemany("INSERT INTO employee_competencies (employee_id, competency_id, status) "
                                      "VALUES (?, ?, 'qualified')",
                                      [(eid, c) for c in comps])
                self.conn.execute("INSERT INTO roster (date, employee_id, shift_code) VALUES (?, ?, ?)",
                                  (DAY.isoformat(), eid, "DK" if i == 1 else "D"))

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def blocks(self):
        zone = {r[0]: r[1] for r in self.conn.execute("SELECT function_id, zone_id FROM functions")}
        per = defaultdict(dict)
        for r in self.conn.execute("SELECT * FROM assignments WHERE plan_date = ?", (DAY.isoformat(),)):
            per[r["employee_id"]][r["start"]] = r["function_id"]
        return per, zone



class SwapTest(Base):
    def test_uren_and_arbeidsbord_swap_others_stay(self):
        planner.suggest_day(self.conn, DAY)
        per, zone = self.blocks()
        uren_before = {e for e, b in per.items() if zone[b["07:00"]] == "uren"}
        bord_before = {e for e, b in per.items() if b["07:00"] == "ren_arbeidsbord"}
        self.assertTrue(uren_before and bord_before)
        for e in uren_before - {"P14"}:                       # everyone in uren goes across
            self.assertEqual(per[e]["11:00"], "ren_arbeidsbord", e)
        uren_after = {e for e, b in per.items() if zone[b["11:00"]] == "uren"}
        self.assertTrue(uren_after - {"P14"} <= bord_before)  # filled from Arbeidsbord
        for e, b in per.items():                              # outside the swap: continuity
            if b["07:00"] in ("ren_kontrollsone", "ren_dk_ansvarsvakt", "steril_produksjon"):
                self.assertEqual(b["11:00"], b["07:00"], e)
        self.assertEqual(per["P01"]["07:00"], "ren_dk_ansvarsvakt")   # DK code leads to DK

    def test_someone_who_cannot_cross_stays_with_a_light_notice(self):
        # Put P14 in uren first, as a manager might, and plan around it.
        with self.conn:
            self.conn.execute("INSERT INTO assignments (plan_date, employee_id, function_id, start, end, "
                              "locked, source) VALUES (?, 'P14', 'uren_produksjon', '07:00', '11:00', 1, 'manuell')",
                              (DAY.isoformat(),))
        planner.suggest_day(self.conn, DAY)
        per, _ = self.blocks()
        self.assertEqual(per["P14"]["11:00"], "uren_produksjon")
        notes = [f for f in checks.day_checks(self.conn, DAY) if f["kind"] == "no_rotation"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["level"], "info")
        self.assertIn("P14", notes[0]["text"])
        self.assertIn("mangler kompetanse for Arbeidsbord", notes[0]["text"])

    def test_without_the_rule_nobody_is_forced_across(self):
        with self.conn:
            self.conn.execute("UPDATE rotation_swaps SET active = 0")
        planner.suggest_day(self.conn, DAY)
        self.assertEqual([f for f in checks.day_checks(self.conn, DAY) if f["kind"] == "no_rotation"], [])

    def test_kontrollsone_rotation_is_a_switch(self):
        with self.conn:
            self.conn.execute("UPDATE rotation_swaps SET active = 1 WHERE swap_id = 'kontrollsone_arbeidsbord'")
        planner.suggest_day(self.conn, DAY)
        per, _ = self.blocks()
        before = [e for e, b in per.items() if b["07:00"] == "ren_kontrollsone"]
        after = [e for e, b in per.items() if b["11:00"] == "ren_kontrollsone"]
        self.assertTrue(before and after)
        self.assertFalse(set(before) & set(after))
        for e in before:
            self.assertEqual(per[e]["11:00"], "ren_arbeidsbord")

    def test_seed_reload_keeps_an_edited_rule(self):
        with self.conn:
            self.conn.execute("UPDATE rotation_swaps SET active = 1, edited = 1 "
                              "WHERE swap_id = 'kontrollsone_arbeidsbord'")
            self.conn.execute("UPDATE rotation_rules SET rotation_time = '11:30', edited = 1 "
                              "WHERE category = 'tidligvakt'")
            importer.seed_rules(self.conn)
        self.assertEqual(self.conn.execute("SELECT active FROM rotation_swaps WHERE swap_id = "
                                           "'kontrollsone_arbeidsbord'").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT rotation_time FROM rotation_rules WHERE category = "
                                           "'tidligvakt'").fetchone()[0], "11:30")


if __name__ == "__main__":
    unittest.main()


class RulesPageTest(Base):
    def form(self, **fields):
        from starlette.datastructures import FormData
        items = []
        for key, value in fields.items():
            for v in (value if isinstance(value, list) else [value]):
                items.append((key, v))
        return FormData(items)

    def test_a_new_swap_rule_is_validated_and_logged(self):
        from app import rules
        with self.assertRaises(rules.Invalid):
            rules.save_swap(self.conn, self.form(name="X", side_a="ren_kontrollsone", side_b="ren_kontrollsone"))
        with self.assertRaises(rules.Invalid):
            rules.save_swap(self.conn, self.form(name="X", side_a="zone:uren"))
        text = rules.save_swap(self.conn, self.form(name="Kontrollsone ↔ Sterrad", side_a="ren_kontrollsone",
                                                    side_b="ren_sterrad", active="1"))
        self.assertIn("lagt til", text)
        row = self.conn.execute("SELECT * FROM rotation_swaps WHERE name = 'Kontrollsone ↔ Sterrad'").fetchone()
        self.assertEqual((row["side_a"], row["side_b"], row["active"]), ("ren_kontrollsone", "ren_sterrad", 1))
        with self.assertRaises(rules.Invalid):                       # standard rules: switch off instead
            rules.delete_swap(self.conn, "uren_arbeidsbord")
        rules.delete_swap(self.conn, row["swap_id"])
        self.assertTrue(any("Bytteregel" in r[0] for r in self.conn.execute(
            "SELECT text FROM import_log WHERE area = 'regler'")))

    def test_a_whole_zone_absorbs_its_functions(self):
        from app import rules
        rules.save_swap(self.conn, self.form(name="Y", side_a=["zone:uren", "uren_gangen"],
                                             side_b="ren_arbeidsbord"))
        self.assertEqual(self.conn.execute("SELECT side_a FROM rotation_swaps WHERE name = 'Y'").fetchone()[0],
                         "zone:uren")

    def test_times_and_numbers(self):
        from app import rules, service
        rules.save_rotation(self.conn, self.form(time_tidligvakt="1130", time_senvakt="18", time_mellomvakt="",
                                                 time_nattevakt="", time_helgevakt=""))
        times = service.rotation_times(self.conn)
        self.assertEqual((str(times["tidligvakt"]), times["mellomvakt"]), ("11:30:00", None))
        with self.assertRaises(rules.Invalid):
            rules.save_settings(self.conn, self.form(heavy_occurrence_hard_cap_per_week="9"))
        rules.save_settings(self.conn, self.form(heavy_occurrence_hard_cap_per_week="2"))
        self.assertEqual(self.conn.execute("SELECT value, edited FROM planner_settings WHERE key = "
                                           "'heavy_occurrence_hard_cap_per_week'").fetchone()[:], (2.0, 1))
        rules.reset(self.conn)
        self.assertEqual(self.conn.execute("SELECT value FROM planner_settings WHERE key = "
                                           "'heavy_occurrence_hard_cap_per_week'").fetchone()[0], 3.0)
        self.assertEqual(str(service.rotation_times(self.conn)["tidligvakt"]), "11:00:00")

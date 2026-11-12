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

HEAVY = {"uren_produksjon", "steril_produksjon", "ren_kontrollsone"}
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


class ExposureTest(Base):
    """The utjevningsvindu and the weekly rule steer who gets heavy work (D110)."""

    def history(self, eid, day, function_id, start="07:00", end="15:00"):
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO plan_days (plan_date, status) VALUES (?, 'published')",
                              (day.isoformat(),))
            self.conn.execute("INSERT INTO assignments (plan_date, employee_id, function_id, start, end, "
                              "locked, source) VALUES (?, ?, ?, ?, ?, 0, 'forslag')",
                              (day.isoformat(), eid, function_id, start, end))

    def at(self, start):
        return {r["employee_id"]: r["function_id"] for r in self.conn.execute(
            "SELECT * FROM assignments WHERE plan_date = ? AND start = ?", (DAY.isoformat(), start))}

    def test_heavy_work_goes_to_the_least_exposed_within_the_window(self):
        recent = {f"P{i:02d}" for i in range(2, 9)}            # heavy work 5 days ago: counts
        for eid in recent:
            self.history(eid, DAY - dt.timedelta(days=5), "uren_produksjon")
        for i in range(9, 17):                                 # 40 days ago: outside the window
            self.history(f"P{i:02d}", DAY - dt.timedelta(days=40), "uren_produksjon")
        planner.suggest_day(self.conn, DAY)
        morning = self.at("07:00")
        # Heavy in the data: Produksjon uren/steril from 07, Kontrollsone from 12
        # (counted to the end of the shift, since it continues).
        heavy = {e for e, f in morning.items() if f in HEAVY}
        self.assertGreaterEqual(len(heavy), 2)
        self.assertFalse(heavy & recent, morning)

    def test_the_window_length_is_the_setting(self):
        for i in range(9, 17):
            self.history(f"P{i:02d}", DAY - dt.timedelta(days=40), "uren_produksjon")
        with self.conn:
            self.conn.execute("UPDATE planner_settings SET value = 60 WHERE key = 'intensity_ledger_window_days'")
        planner.suggest_day(self.conn, DAY)
        heavy = {e for e, f in self.at("07:00").items() if f in HEAVY}
        self.assertGreaterEqual(len(heavy), 2)
        # P14 can't take Arbeidsbord, so works in uren whatever his history.
        self.assertFalse(heavy & {f"P{i:02d}" for i in range(9, 17) if i != 14})

    def kontrollsone_week(self, eids, days=(-1, 1, 2)):
        for eid in eids:
            for offset in days:
                self.history(eid, DAY + dt.timedelta(days=offset), "ren_kontrollsone", "12:00", "15:00")

    def kontrollsone_after_rotation(self):
        return {e for e, f in self.at("11:00").items() if f == "ren_kontrollsone"}   # 2 from 14:00

    def test_the_weekly_cap_keeps_people_off_full_intensity_work(self):
        self.kontrollsone_week([f"P{i:02d}" for i in range(2, 15)])        # 3 this week: at the cap
        planner.suggest_day(self.conn, DAY)
        self.assertEqual(self.kontrollsone_after_rotation(), {"P15", "P16"})
        self.assertFalse([f for f in checks.day_checks(self.conn, DAY) if f["kind"] == "heavy_cap"])

    def test_the_weekly_target_prefers_those_without_a_heavy_day(self):
        # Kontrollsone 07–11 is light but continues into its heavy afternoon,
        # so the morning pick already looks ahead: someone without a heavy
        # day this week. (The target is soft: the swap and «steril doesn't
        # rotate» come first; only the cap is hard.)
        self.kontrollsone_week([f"P{i:02d}" for i in range(2, 15)], days=(-1,))   # 1 = the target
        planner.suggest_day(self.conn, DAY)
        morning = [e for e, f in self.at("07:00").items() if f == "ren_kontrollsone"]
        self.assertEqual(len(morning), 1)
        self.assertIn(morning[0], {"P15", "P16"})
        self.assertIn(morning[0], self.kontrollsone_after_rotation())

    def test_when_everyone_is_at_the_cap_the_work_is_still_covered_and_warned(self):
        self.kontrollsone_week([f"P{i:02d}" for i in range(1, 17)])
        planner.suggest_day(self.conn, DAY)
        self.assertEqual(len(self.kontrollsone_after_rotation()), 2)
        self.assertTrue([f for f in checks.day_checks(self.conn, DAY) if f["kind"] == "heavy_cap"])


class ContingencyTest(Base):
    """«Avvik og tiltak» (D114): each choice changes what the planner does."""

    def set(self, **values):
        from app import contingency
        from starlette.datastructures import FormData
        contingency.save(self.conn, FormData(list(values.items())))

    def at(self, start):
        return {r["employee_id"]: r["function_id"] for r in self.conn.execute(
            "SELECT * FROM assignments WHERE plan_date = ? AND start = ?", (DAY.isoformat(), start))}

    def test_p5_someone_who_fits_nowhere_goes_ad_hoc_by_default(self):
        planner.suggest_day(self.conn, DAY)
        self.assertEqual(self.at("07:00")["P14"], "adhoc")           # no Arbeidsbord competency
        self.set(P5="sone")
        planner.suggest_day(self.conn, DAY)
        self.assertTrue(self.at("07:00")["P14"].startswith(("uren_", "steril_")))
        self.set(P5="ingen")
        planner.suggest_day(self.conn, DAY)
        self.assertNotIn("P14", self.at("07:00"))
        self.assertTrue([f for f in checks.day_checks(self.conn, DAY) if f["kind"] == "unplanned"])

    def test_p1_rotate_anyway_leaves_uren_short(self):
        # Only three people besides the fixed places: uren needs more after 11.
        with self.conn:
            self.conn.execute("DELETE FROM roster WHERE employee_id IN "
                              "('P10','P11','P12','P13','P15','P16')")
        planner.suggest_day(self.conn, DAY)
        stayed = [f for f in checks.day_checks(self.conn, DAY) if f["kind"] == "no_rotation"]
        self.set(P1="roter")
        planner.suggest_day(self.conn, DAY)
        morning, after = self.at("07:00"), self.at("11:00")
        uren_before = {e for e, f in morning.items() if f.startswith("uren_") and e != "P14"}
        self.assertTrue(stayed)
        self.assertFalse({e for e in uren_before if after.get(e, "").startswith("uren_")})
        self.assertTrue([f for f in checks.day_checks(self.conn, DAY)
                         if f["kind"] == "shortfall" and "Uren" in f["text"]])

    def test_p2_never_past_the_cap_leaves_the_function_short(self):
        for i in range(1, 17):
            for offset in (-1, 1, 2):
                day = DAY + dt.timedelta(days=offset)
                with self.conn:
                    self.conn.execute("INSERT OR IGNORE INTO plan_days (plan_date, status) VALUES (?, 'published')",
                                      (day.isoformat(),))
                    self.conn.execute("INSERT INTO assignments (plan_date, employee_id, function_id, start, end, "
                                      "locked, source) VALUES (?, ?, 'ren_kontrollsone', '12:00', '15:00', 0, 'x')",
                                      (day.isoformat(), f"P{i:02d}"))
        self.set(P2="kort")
        planner.suggest_day(self.conn, DAY)
        self.assertNotIn("ren_kontrollsone", self.at("11:00").values())
        kinds = {f["kind"] for f in checks.day_checks(self.conn, DAY)}
        self.assertIn("shortfall", kinds)
        self.assertNotIn("heavy_cap", kinds)

    def test_p6_full_plans_the_weekend_like_a_weekday(self):
        saturday = dt.date(2026, 11, 21)
        with self.conn:
            self.conn.execute("INSERT INTO plan_days (plan_date, status) VALUES (?, 'draft')", (saturday.isoformat(),))
            for i in range(1, 6):
                self.conn.execute("INSERT INTO roster (date, employee_id, shift_code) VALUES (?, ?, 'H1')",
                                  (saturday.isoformat(), f"P{i:02d}"))
        planner.suggest_day(self.conn, saturday)
        count = lambda: self.conn.execute("SELECT COUNT(DISTINCT employee_id) FROM assignments WHERE plan_date = ?",
                                          (saturday.isoformat(),)).fetchone()[0]
        self.assertEqual(count(), 1)                               # DK/ansvarsvakt only
        self.set(P6="full")
        planner.suggest_day(self.conn, saturday)
        self.assertEqual(count(), 5)

    def test_levels_switch_notices_off_and_bad_values_are_refused(self):
        from app import contingency
        planner.suggest_day(self.conn, DAY)
        self.assertTrue([f for f in checks.day_checks(self.conn, DAY) if f["kind"] == "draft"])
        self.set(N1="av")
        self.assertFalse([f for f in checks.day_checks(self.conn, DAY) if f["kind"] == "draft"])
        with self.assertRaises(contingency.Invalid):
            self.set(S4="3")
        with self.assertRaises(contingency.Invalid):
            self.set(P1="noe")
        self.assertTrue(any("Avvik og tiltak – N1" in r[0] for r in self.conn.execute("SELECT text FROM import_log")))


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

"""Reading the HR exports (hr_export) and building the roster from them
(hr_import), on synthetic files in the real format (tests/hr_fixtures.py)."""
import datetime as dt
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hr_fixtures as fx  # noqa: E402
from app import db, hr_export, hr_import, importer  # noqa: E402

D = dt.date
START = D(2026, 12, 28)              # plan crosses the year: ISO week 53 → week 1
EXPORTED = dt.datetime(2026, 12, 10, 12, 40)
TODAY = D(2027, 1, 4)                # Monday of ISO week 1, 2027
MON = TODAY


def weekdays(code, weeks=4, days=(0, 1, 2, 3, 4)):
    return {START + dt.timedelta(days=7 * w + d): code for w in range(weeks) for d in days}


def people():
    siri = weekdays("D")
    siri[D(2026, 12, 31)] = "DK/F3"      # New Year's Eve: ends 12:00
    siri[D(2027, 1, 5)] = "D2*"          # paid-lunch variant of D2
    siri[D(2027, 1, 6)] = "X9"           # code nobody knows
    return [
        ("Hansen Kari", "Sterilforsyningstekniker", weekdays("D")),
        ("Olsen Tor", "Sterilforsyningstekniker", weekdays("N", days=(1, 2, 3, 4))),
        ("Berg Anne", "IKT-konsulent", weekdays("D")),
        ("Dahl Per", "Driftsleder", weekdays("D2")),
        ("Nilsen Ola", "Sterilforsyningstekniker", {MON: "D"}),
        ("Nilsen Ola", "Sterilforsyningstekniker", {MON: "A"}),     # overlaps (D80)
        ("Vik Siri", "Sterilforsyningstekniker", siri),
    ]


def ukeplan_week1(exported=dt.datetime(2027, 1, 4, 6, 30), kari_wed=None):
    kari = {MON: "D", MON + dt.timedelta(1): "A"}
    if kari_wed:
        kari[MON + dt.timedelta(2)] = kari_wed
    return fx.ukeplan_csv([
        ("1001", "Hansen Kari", kari),                                # Wed–Fri blank = absent
        ("1002", "Olsen Tor", {MON + dt.timedelta(1): "N, M", MON + dt.timedelta(2): "N",
                               MON + dt.timedelta(3): "DX"}),
        ("1153", "Vikar Temp", {MON: "D"}),                           # not in the turnus
    ], MON, exported)


# ------------------------------------------------------------------ parser
class ParsePlanTest(unittest.TestCase):
    def test_reads_structure_across_the_year(self):
        e = hr_export.read(fx.plan_csv(people(), START, 4, EXPORTED), fx.plan_name(EXPORTED))
        self.assertEqual(e.kind, "plan")
        self.assertEqual((e.first_date, e.last_date), (START, D(2027, 1, 24)))
        self.assertEqual(len(e.rows), 7)
        self.assertEqual(e.rows[2].title, "IKT-konsulent")
        self.assertEqual(e.rows[0].cells[D(2027, 1, 4)], "D")
        self.assertEqual(e.legend["D"], ("07:00", "15:00"))   # break segments joined
        self.assertEqual(e.legend["N"], ("22:00", "07:00"))
        self.assertEqual(e.alerts, [])

    def test_blank_line_inside_person_block_is_refused(self):
        raw = fx.plan_csv(people(), START, 4, EXPORTED, blank_inside=True)
        with self.assertRaises(hr_export.Rejected) as ctx:
            hr_export.read(raw, fx.plan_name(EXPORTED))
        self.assertIn("Oppsummeringen", ctx.exception.reasons[0])

    def test_wrong_unit_is_refused(self):
        raw = fx.plan_csv(people(), START, 4, EXPORTED, unit="Kirurgisk sengepost")
        with self.assertRaises(hr_export.Rejected):
            hr_export.read(raw, fx.plan_name(EXPORTED))

    def test_week_labels_must_match_the_dates(self):
        raw = fx.plan_csv(people(), START, 4, EXPORTED, week_shift=1)
        with self.assertRaises(hr_export.Rejected) as ctx:
            hr_export.read(raw, fx.plan_name(EXPORTED))
        self.assertIn("Ukeraden", ctx.exception.reasons[0])

    def test_an_extra_column_is_read_by_its_labels(self):
        e = hr_export.read(fx.plan_csv(people(), START, 4, EXPORTED, extra_column=True),
                           fx.plan_name(EXPORTED))
        self.assertEqual(e.rows[0].cells[D(2027, 1, 4)], "D")
        self.assertIn("Ekstra", e.fingerprint)

    def test_uneven_rows_are_refused(self):
        raw = fx.plan_csv(people(), START, 4, EXPORTED) + b"\r\nen;ekstra;rad"
        with self.assertRaises(hr_export.Rejected):
            hr_export.read(raw, fx.plan_name(EXPORTED))

    def test_name_and_content_must_agree(self):
        with self.assertRaises(hr_export.Rejected):
            hr_export.read(fx.plan_csv(people(), START, 4, EXPORTED), fx.ukeplan_name(EXPORTED))

    def test_without_stamp_in_name_the_report_date_is_used(self):
        e = hr_export.read(fx.plan_csv(people(), START, 4, EXPORTED), "turnus.csv")
        self.assertEqual(e.exported_at, EXPORTED)
        self.assertTrue(any("Filnavnet" in a for a in e.alerts))

    def test_a_turnus_without_personid_is_refused(self):
        raw = fx.plan_csv(people(), START, 4, EXPORTED, with_ids=False)
        with self.assertRaises(hr_export.Rejected) as ctx:
            hr_export.read(raw, fx.plan_name(EXPORTED))
        self.assertIn("PersonID", ctx.exception.reasons[0])

    def test_a_row_without_personid_is_refused(self):
        raw = fx.plan_csv(people(), START, 4, EXPORTED, missing_id_for="Olsen Tor")
        with self.assertRaises(hr_export.Rejected) as ctx:
            hr_export.read(raw, fx.plan_name(EXPORTED))
        self.assertIn("Olsen Tor", ctx.exception.reasons[0])

    def test_personid_is_read_in_the_turnus(self):
        e = hr_export.read(fx.plan_csv(people(), START, 4, EXPORTED), fx.plan_name(EXPORTED))
        self.assertEqual([r.person_id for r in e.rows][:3], ["1001", "1002", "1003"])

    def test_not_an_export(self):
        with self.assertRaises(hr_export.Rejected):
            hr_export.read("a;b;c\r\n1;2;3".encode("cp1252"), "x.csv")


class ParseUkeplanTest(unittest.TestCase):
    def test_reads_week_ids_and_compound_cells(self):
        e = hr_export.read(ukeplan_week1(), fx.ukeplan_name(dt.datetime(2027, 1, 4, 6, 30)))
        self.assertEqual(e.kind, "ajourhold")
        self.assertEqual((e.first_date, e.last_date), (MON, D(2027, 1, 10)))
        self.assertEqual([r.person_id for r in e.rows], ["1001", "1002", "1153"])
        self.assertEqual(e.rows[1].cells[MON + dt.timedelta(1)], "N, M")

    def test_a_person_without_personid_is_refused(self):
        raw = fx.ukeplan_csv([("1001", "Hansen Kari", {MON: "D"})], MON,
                             dt.datetime(2027, 1, 4, 6), orphan_row=True)
        with self.assertRaises(hr_export.Rejected) as ctx:
            hr_export.read(raw, fx.ukeplan_name(dt.datetime(2027, 1, 4, 6)))
        self.assertIn("uten PersonID", ctx.exception.reasons[0])


class InterpretTest(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(hr_import.interpret("N, M"), ("N", None, None))
        self.assertEqual(hr_import.interpret("M, A1"), ("A1", None, None))
        self.assertEqual(hr_import.interpret("DK/F3"), ("DK", "12:00", None))
        self.assertEqual(hr_import.interpret("D2*"), ("D2", None, None))
        self.assertIsNotNone(hr_import.interpret("D, A")[2])
        self.assertEqual(hr_import.interpret("M"), (None, None, None))     # overtime only: no shift
        self.assertIn("ukjent vaktkode", hr_import.interpret("D, A")[2])
        self.assertIsNotNone(hr_import.interpret("D/F9")[2])


# ---------------------------------------------------------------- pipeline
class PipelineBase(unittest.TestCase):
    """Shared set-up and helpers for the pipeline tests."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.inbox = self.tmp / "import"
        self.inbox.mkdir()
        db.set_mode("real")
        self.conn = db.get_conn(self.tmp / "t.db")
        db.init_schema(self.conn)
        self.conn.execute("PRAGMA foreign_keys = OFF")
        with self.conn:
            importer.import_seed(self.conn, people=False)
        self.conn.execute("PRAGMA foreign_keys = ON")

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def drop(self, name, raw):
        path = self.inbox / name
        path.write_bytes(raw)
        os.utime(path, (0, 0))   # old enough: not "still being copied"

    def use_turnus_for_unlisted(self):
        """These tests are about other rules; the week-1 ukeplan only lists a
        few people, so keep the turnus for the rest (S2 = «turnus»)."""
        from app import contingency
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO contingency_settings (rule_id, value) VALUES ('S2', 'turnus')")

    def load(self, ukeplan=True):
        self.drop(fx.plan_name(EXPORTED), fx.plan_csv(people(), START, 4, EXPORTED))
        if ukeplan:
            self.drop(fx.ukeplan_name(dt.datetime(2027, 1, 4, 6, 30)), ukeplan_week1())
        messages = hr_import.scan_inbox(self.conn, self.inbox)
        hr_import.rebuild(self.conn, TODAY)
        return messages

    def roster(self, name):
        return {r["date"]: dict(r) for r in self.conn.execute(
            """SELECT r.* FROM roster r JOIN employees e USING (employee_id)
               WHERE e.full_name = ?""", (name,))}

    def pending(self, name):
        return {r["date"]: r["reason"] for r in self.conn.execute(
            """SELECT p.* FROM roster_pending p JOIN employees e USING (employee_id)
               WHERE e.full_name = ?""", (name,))}

    def findings(self):
        return [r["text"] for r in self.conn.execute("SELECT text FROM import_findings")]

    def change(self, name, day, **fields):
        from app import roster_changes
        from starlette.datastructures import FormData
        eid = self.conn.execute("SELECT employee_id FROM employees WHERE full_name = ?", (name,)).fetchone()[0]
        message = roster_changes.save(self.conn, FormData([("employee_id", eid), ("date", day.isoformat())]
                                                          + list(fields.items())))
        hr_import.rebuild(self.conn, TODAY)
        return eid, message


class PipelineTest(PipelineBase):
    def test_files_leave_the_inbox(self):
        self.load()
        self.assertEqual(sorted(p.name for p in self.inbox.iterdir()), ["arkiv"])
        self.assertEqual(len(list((self.inbox / "arkiv").iterdir())), 2)

    def test_rejected_file_goes_to_avvist_with_reasons(self):
        self.drop("Ukeplan_20270104063000.csv", "tull;og;tøys\r\n1;2;3".encode("cp1252"))
        messages = hr_import.scan_inbox(self.conn, self.inbox)
        self.assertIn("AVVIST", messages[0])
        rejected = self.inbox / "avvist"
        self.assertTrue((rejected / "Ukeplan_20270104063000.csv.txt").exists())
        hr_import.rebuild(self.conn, TODAY)
        self.assertTrue(any("avvist" in f for f in self.findings()))

    def test_same_file_twice_is_ignored(self):
        self.load()
        self.drop("kopi.csv", fx.plan_csv(people(), START, 4, EXPORTED))
        messages = hr_import.scan_inbox(self.conn, self.inbox)
        self.assertIn("allerede behandlet", messages[0])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM import_files").fetchone()[0], 2)

    def test_ukeplan_overrules_the_turnus_for_the_people_in_it(self):
        self.load()
        kari = self.roster("Hansen Kari")
        self.assertEqual(kari["2027-01-04"]["shift_code"], "D")
        self.assertEqual(kari["2027-01-05"]["shift_code"], "A")       # changed
        for day in ("2027-01-06", "2027-01-07", "2027-01-08"):        # blank = absent
            self.assertNotIn(day, kari)
        self.assertEqual(kari["2027-01-11"]["source"], "plan")        # next week: turnus

    def test_people_not_in_the_ukeplan_are_off_that_week_by_default(self):
        self.load()
        siri = self.roster("Vik Siri")
        self.assertNotIn("2027-01-04", siri)                          # week 1: the ukeplan rules
        self.assertEqual(siri["2027-01-11"]["source"], "plan")        # week 2: no ukeplan yet
        # 4 of the 6 with turnus shifts are missing: looks incomplete → alert,
        # saying who, in plain words (R21).
        notice = next(f for f in self.findings() if "ser ufullstendig ut" in f)
        self.assertIn("Uke 1 (04.01–10.01)", notice)
        self.assertIn("4 av de 6 som har vakter i turnusen denne uken, står ikke i den", notice)
        self.assertIn("Siri V.", notice)

    def test_no_coverage_notices_for_weeks_that_are_over(self):
        self.load()
        hr_import.rebuild(self.conn, TODAY + dt.timedelta(days=7))    # week 1 is now past
        self.assertFalse([f for f in self.findings() if "ukeplan" in f and "Uke 1 " in f])

    def test_unplannable_shifts_are_flagged_however_far_ahead(self):
        self.use_turnus_for_unlisted()
        with self.conn:      # red for 5 days only: Siri's X9 (06.01, two days ahead) stays red…
            self.conn.execute("INSERT INTO contingency_settings (rule_id, value) VALUES ('S5', '1')")
        self.load()
        texts = {f[0]: f[1] for f in self.conn.execute("SELECT text, level FROM import_findings")}
        later = [t for t in texts if "Kan ikke planlegges (lenger frem)" in t and "X9" in t]
        self.assertTrue(later)                                       # …now beyond 1 day: yellow
        self.assertEqual(texts[later[0]], "warn")

    def redo_scenario(self, choice):
        from app import planner
        with self.conn:
            self.conn.execute("INSERT INTO contingency_settings (rule_id, value) VALUES ('P8', ?)", (choice,))
        self.load()
        tue = MON + dt.timedelta(1)
        planner.suggest_day(self.conn, tue)          # a draft: Kari on A (14–22) from the ukeplan
        # A newer ukeplan moves Kari's Tuesday to D (07–15).
        newer = dt.datetime(2027, 1, 4, 12, 0)
        self.drop(fx.ukeplan_name(newer), fx.ukeplan_csv([
            ("1001", "Hansen Kari", {MON: "D", tue: "D"}),
            ("1002", "Olsen Tor", {tue: "N, M", MON + dt.timedelta(2): "N", MON + dt.timedelta(3): "DX"}),
            ("1153", "Vikar Temp", {MON: "D"})], MON, newer))
        hr_import.scan_inbox(self.conn, self.inbox)
        hr_import.rebuild(self.conn, TODAY)
        return [r["start"] for r in self.conn.execute(
            """SELECT a.start FROM assignments a JOIN employees e USING (employee_id)
               WHERE e.full_name = 'Hansen Kari' AND a.plan_date = ? ORDER BY a.start""", (tue.isoformat(),))]

    def test_p8_unpublished_drafts_are_remade_when_chosen(self):
        self.assertEqual(self.redo_scenario("utkast")[0], "07:00")
        self.assertTrue(any("Utkast laget på nytt" in r[0] for r in self.conn.execute("SELECT text FROM import_log")))

    def test_p8_by_default_the_plan_is_left_and_warned(self):
        from app import checks
        self.assertEqual(self.redo_scenario("varsle")[0], "14:00")   # left as it was …
        self.assertTrue([f for f in checks.day_checks(self.conn, MON + dt.timedelta(1))
                         if f["kind"] == "shift_changed" and "Kari" in f["text"]])   # … and warned

    def test_roster_changes_win_over_turnus_and_ukeplan(self):
        self.use_turnus_for_unlisted()
        self.load()
        wed, mon2 = MON + dt.timedelta(2), MON + dt.timedelta(7)
        self.change("Hansen Kari", wed, kind="vakt", code="A")          # blank in the ukeplan
        self.change("Hansen Kari", MON, kind="fri")                     # D in the ukeplan
        self.change("Hansen Kari", mon2, kind="tid", start="22", end="7")   # D in the turnus
        kari = self.roster("Hansen Kari")
        self.assertEqual((kari[wed.isoformat()]["shift_code"], kari[wed.isoformat()]["source"]), ("A", "manuell"))
        self.assertNotIn(MON.isoformat(), kari)
        night = kari[mon2.isoformat()]
        self.assertEqual((night["shift_code"], night["start_override"], night["end_override"]), ("MAN", "22:00", "07:00"))
        replaced = {r["date"]: r["replaced"] for r in self.conn.execute("SELECT * FROM roster_overrides")}
        self.assertEqual(replaced[wed.isoformat()], "ingen vakt")
        self.assertEqual(replaced[MON.isoformat()], "D 07:00–15:00")
        # A newer ukeplan doesn't undo it; removing it does.
        newer = dt.datetime(2027, 1, 4, 12, 0)
        self.drop(fx.ukeplan_name(newer), ukeplan_week1(exported=newer))
        hr_import.scan_inbox(self.conn, self.inbox)
        hr_import.rebuild(self.conn, TODAY)
        self.assertNotIn(MON.isoformat(), self.roster("Hansen Kari"))
        from app import roster_changes
        eid = self.conn.execute("SELECT employee_id FROM employees WHERE full_name = 'Hansen Kari'").fetchone()[0]
        roster_changes.remove(self.conn, eid, MON.isoformat())
        hr_import.rebuild(self.conn, TODAY)
        self.assertEqual(self.roster("Hansen Kari")[MON.isoformat()]["shift_code"], "D")

    def test_a_roster_change_settles_a_conflict(self):
        self.use_turnus_for_unlisted()
        self.load()
        self.assertIn("D80", self.pending("Nilsen Ola")[MON.isoformat()])
        self.change("Nilsen Ola", MON, kind="vakt", code="D", note="avklart med leder")
        self.assertEqual(self.roster("Nilsen Ola")[MON.isoformat()]["shift_code"], "D")
        self.assertNotIn(MON.isoformat(), self.pending("Nilsen Ola"))
        levels = {r["text"]: r["level"] for r in self.conn.execute("SELECT * FROM import_findings")}
        settled = [t for t in levels if "to rader" in t and "Ola" in t]
        self.assertTrue(settled and all(levels[t] == "info" and "Avklart" in t for t in settled))

    def test_roster_change_validation(self):
        from app import roster_changes
        from starlette.datastructures import FormData
        self.load()
        eid = self.conn.execute("SELECT employee_id FROM employees WHERE full_name = 'Hansen Kari'").fetchone()[0]
        for fields, text in (([("employee_id", "X999"), ("date", "2027-01-05"), ("kind", "fri")], "ansatt"),
                             ([("employee_id", eid), ("date", "2027-01-05"), ("kind", "vakt"), ("code", "DX")], "Egen tid"),
                             ([("employee_id", eid), ("date", "2027-01-05"), ("kind", "tid"), ("start", "7"), ("end", "07:00")], "like"),
                             ([("employee_id", eid), ("date", "nei"), ("kind", "fri")], "dato")):
            with self.assertRaises(roster_changes.Invalid) as ctx:
                roster_changes.save(self.conn, FormData(fields))
            self.assertIn(text, str(ctx.exception))

    def test_new_titles_can_be_planned_meanwhile(self):
        self.use_turnus_for_unlisted()
        with self.conn:
            self.conn.execute("INSERT INTO contingency_settings (rule_id, value) VALUES ('S1', 'planlegg')")
        self.load()
        self.assertIsNone(self.roster("Dahl Per")["2027-01-04"]["hold"])      # «Driftsleder» is new
        self.assertTrue(any("«Driftsleder» er ny" in f and "planlegges som «vanlig»" in f
                            for f in self.findings()))

    def test_people_not_in_the_ukeplan_keep_the_turnus_when_chosen(self):
        self.use_turnus_for_unlisted()
        self.load()
        self.assertEqual(self.roster("Vik Siri")["2027-01-04"]["source"], "plan")
        self.assertTrue(any("står ikke i ukeplanen" in f and "Siri V." in f
                            for f in self.findings()))

    def test_nights_move_to_the_evening_they_start_and_overtime_is_ignored(self):
        self.load()
        tor = self.roster("Olsen Tor")
        self.assertEqual(tor["2027-01-04"]["shift_code"], "N")    # exported Tue "N, M"
        self.assertEqual(tor["2027-01-05"]["shift_code"], "N")    # exported Wed "N"
        self.assertEqual(tor["2026-12-28"]["shift_code"], "N")    # turnus, across the year
        self.assertIn("DX", self.pending("Olsen Tor")["2027-01-07"])

    def test_f3_asterisk_and_unknown_codes(self):
        self.use_turnus_for_unlisted()
        self.load()
        siri = self.roster("Vik Siri")
        self.assertEqual((siri["2026-12-31"]["shift_code"], siri["2026-12-31"]["end_override"]),
                         ("DK", "12:00"))
        self.assertEqual(siri["2027-01-05"]["shift_code"], "D2")
        self.assertIn("X9", self.pending("Vik Siri")["2027-01-06"])
        self.assertTrue(any("X9" in f for f in self.findings()))

    def test_codes_learned_from_the_legend(self):
        self.load()
        row = self.conn.execute("SELECT * FROM shift_code_defs WHERE code = 'D3'").fetchone()
        self.assertEqual((row["start"], row["end"], row["category"], row["source"], row["reviewed"]),
                         ("09:00", "13:30", "tidligvakt", "turnus", 0))
        self.assertIsNotNone(self.conn.execute(
            "SELECT 1 FROM shift_codes WHERE code = 'D3'").fetchone())
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM shift_code_defs WHERE code = 'D2*'").fetchone())
        self.assertTrue(any("Ny vaktkode D3" in f for f in self.findings()))

    def test_ignored_codes_overtime_and_legend_deviations(self):
        crew = people()
        crew[0][2][D(2027, 1, 13)] = "DMT"       # ignored code (R9): kept out of the plan
        crew[0][2][D(2027, 1, 14)] = "M"         # overtime only: no shift, no question
        crew[0][2][D(2027, 1, 15)] = "D, A"      # never valid: an unknown code
        legend = [r if r[0] != "DK" else ("DK", "07:00", "15:30", "1", "Aktiv") for r in fx.LEGEND]
        self.drop(fx.plan_name(EXPORTED), fx.plan_csv(crew, START, 4, EXPORTED, legend=legend))
        hr_import.scan_inbox(self.conn, self.inbox)
        hr_import.rebuild(self.conn, TODAY)
        kari = self.roster("Hansen Kari")
        self.assertEqual((kari["2027-01-13"]["shift_code"], kari["2027-01-13"]["hold"]), ("DMT", "kode"))
        self.assertNotIn("2027-01-14", kari)
        self.assertNotIn("2027-01-14", self.pending("Hansen Kari"))
        self.assertIn("ukjent vaktkode «D, A»", self.pending("Hansen Kari")["2027-01-15"])
        self.assertTrue(any("Vaktkoden DK er 07:00–15:30 i turnusen" in f for f in self.findings()))
        # The admin takes the turnus's time; a seed reload keeps the edit.
        with self.conn:
            self.conn.execute("UPDATE shift_code_defs SET end = '15:30', edited = 1 WHERE code = 'DK'")
            importer.seed_shift_codes(self.conn)
            db.sync_shift_codes(self.conn)
        hr_import.rebuild(self.conn, TODAY)
        self.assertEqual(self.conn.execute("SELECT end FROM shift_codes WHERE code = 'DK'").fetchone()[0],
                         "15:30")
        self.assertFalse(any("Vaktkoden DK" in f for f in self.findings()))

    def test_a_deleted_code_is_not_learned_again(self):
        self.load()
        with self.conn:
            self.conn.execute("UPDATE shift_code_defs SET deleted_at = 'nå' WHERE code = 'D3'")
            db.sync_shift_codes(self.conn)
        hr_import.rebuild(self.conn, TODAY)
        self.assertIsNotNone(self.conn.execute(
            "SELECT deleted_at FROM shift_code_defs WHERE code = 'D3'").fetchone()[0])
        self.assertIsNone(self.conn.execute("SELECT 1 FROM shift_codes WHERE code = 'D3'").fetchone())

    def test_title_rules_hold_days_out_until_classified(self):
        self.use_turnus_for_unlisted()
        self.load()
        self.assertEqual(self.roster("Berg Anne")["2027-01-04"]["hold"], "aldri")
        self.assertEqual(self.roster("Dahl Per")["2027-01-04"]["hold"], "uavklart")
        self.assertTrue(any("«Driftsleder» er ny" in f for f in self.findings()))
        with self.conn:
            self.conn.execute("UPDATE positions SET rule = 'vanlig' WHERE title = 'Driftsleder'")
        hr_import.rebuild(self.conn, TODAY)
        self.assertIsNone(self.roster("Dahl Per")["2027-01-04"]["hold"])
        self.assertFalse(any("Driftsleder" in f for f in self.findings()))

    def test_two_rows_with_a_shift_the_same_day_are_held(self):
        self.use_turnus_for_unlisted()
        self.load()
        self.assertNotIn("2027-01-04", self.roster("Nilsen Ola"))
        self.assertIn("D80", self.pending("Nilsen Ola")["2027-01-04"])
        self.assertTrue(any("to rader" in f for f in self.findings()))

    def test_identity_person_ids_and_temps(self):
        self.load()
        kari = self.conn.execute(
            "SELECT * FROM employees WHERE full_name = 'Hansen Kari'").fetchone()
        self.assertEqual((kari["person_id"], kari["display_name"]), ("1001", "Kari H."))
        temp = self.roster("Vikar Temp")
        self.assertEqual(temp["2027-01-04"]["shift_code"], "D")
        self.assertIsNone(temp["2027-01-04"]["title"])
        self.assertTrue(any("ikke i turnusen" in f for f in self.findings()))

    def test_one_name_with_two_person_ids_is_two_people(self):
        self.load()
        self.drop(fx.ukeplan_name(dt.datetime(2027, 1, 11, 6)), fx.ukeplan_csv(
            [("9999", "Hansen Kari", {MON + dt.timedelta(7): "D"})],
            MON + dt.timedelta(7), dt.datetime(2027, 1, 11, 6)))
        hr_import.scan_inbox(self.conn, self.inbox)
        hr_import.rebuild(self.conn, TODAY)
        # With PersonIDs on every row these are two people who share a name.
        self.assertTrue(any("To ansatte heter «Hansen Kari»" in f for f in self.findings()))

    def test_newer_ukeplan_for_the_same_week_wins(self):
        self.load()
        self.drop(fx.ukeplan_name(dt.datetime(2027, 1, 6, 9)),
                  ukeplan_week1(dt.datetime(2027, 1, 6, 9), kari_wed="D2"))
        hr_import.scan_inbox(self.conn, self.inbox)
        hr_import.rebuild(self.conn, TODAY)
        self.assertEqual(self.roster("Hansen Kari")["2027-01-06"]["shift_code"], "D2")
        statuses = [r["status"] for r in self.conn.execute(
            "SELECT status FROM import_files WHERE kind = 'ajourhold' ORDER BY exported_at")]
        self.assertEqual(statuses, ["superseded", "active"])

    def test_plans_lose_people_who_are_no_longer_on_duty(self):
        self.load(ukeplan=False)
        kari = self.conn.execute(
            "SELECT employee_id FROM employees WHERE full_name = 'Hansen Kari'").fetchone()[0]
        with self.conn:
            self.conn.execute("INSERT INTO plan_days (plan_date, status) VALUES ('2027-01-06', 'published')")
            self.conn.execute(
                "INSERT INTO assignments (plan_date, employee_id, function_id, start, end, locked) "
                "VALUES ('2027-01-06', ?, 'ren_arbeidsbord', '07:00', '15:00', 1)", (kari,))
        self.drop(fx.ukeplan_name(dt.datetime(2027, 1, 4, 6, 30)), ukeplan_week1())
        hr_import.scan_inbox(self.conn, self.inbox)
        hr_import.rebuild(self.conn, TODAY)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM assignments WHERE plan_date = '2027-01-06'").fetchone()[0], 0)
        log = [r[0] for r in self.conn.execute("SELECT text FROM import_log")]
        self.assertTrue(any("Kari H." in line and "tatt ut" in line for line in log))

    def test_coverage_findings(self):
        hr_import.rebuild(self.conn, TODAY)
        self.assertTrue(any("Ingen turnus er importert" in f for f in self.findings()))
        self.load(ukeplan=False)
        later = D(2027, 1, 18)    # plan ends 24.01 → gap within four weeks
        hr_import.rebuild(self.conn, later)
        texts = self.findings()
        self.assertTrue(any("Turnus mangler fra 25.01.2027" in f for f in texts))
        self.assertTrue(any("Ingen ukeplan for denne uken" in f for f in texts))

    def test_competency_workbook_is_staged_then_applied_by_name(self):
        from openpyxl import Workbook

        from app import competency

        wb = Workbook()
        ws = wb.active
        ws.append(["Kompetanse"])
        ws.append(["Navn", "Arbeidsbord/brikkelegging", "Kontrollsone", "Gangen", "Ansvarsvakt"])
        ws.append(["Hansen Kari", "Ja", "Ukjent", "", "x"])
        ws.append(["Ukjent Person", "Ja", "", "", ""])
        buffer = io.BytesIO()
        wb.save(buffer)
        self.drop("Kompetanse.xlsx", buffer.getvalue())
        self.load()
        # Nothing applied before review (D98) — the file waits.
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM competency_rows").fetchone()[0], 0)
        self.assertTrue(any("venter på gjennomgang" in f for f in self.findings()))
        import_id = competency.pending_imports(self.conn)[0]["import_id"]
        self.assertEqual(competency.review(self.conn, import_id)["step"], "link")
        self.assertEqual(competency.save_links(self.conn, {"Ukjent Person": "__skip__"}), [])
        competency.apply_import(self.conn, import_id, overwrite_conflicts=False)
        hr_import.rebuild(self.conn, TODAY)
        comps = {r["competency_id"]: r["status"] for r in self.conn.execute(
            """SELECT ec.* FROM employee_competencies ec JOIN employees e USING (employee_id)
               WHERE e.full_name = 'Hansen Kari'""")}
        self.assertEqual(comps, {"arbeidsbord": "qualified", "kontrollsone": "uncertain",
                                 "ansvarsvakt": "qualified"})
        self.assertTrue(any("Ingen kompetanse registrert" in f and "Tor O." in f
                            for f in self.findings()))

    def test_two_employees_with_the_same_name_are_told_apart_by_personid(self):
        twins = [("Hansen Kari", "Sterilforsyningstekniker", {MON: "D"}, "1001"),
                 ("Hansen Kari", "Sterilforsyningstekniker", {MON: "A"}, "7777")]
        self.drop(fx.plan_name(EXPORTED), fx.plan_csv(twins, START, 4, EXPORTED))
        hr_import.scan_inbox(self.conn, self.inbox)
        hr_import.rebuild(self.conn, TODAY)
        rows = list(self.conn.execute(
            "SELECT e.person_id, e.display_name, r.shift_code FROM roster r JOIN employees e "
            "USING (employee_id) WHERE r.date = ? ORDER BY e.person_id", (MON.isoformat(),)))
        self.assertEqual([tuple(r) for r in rows],
                         [("1001", "Kari H. (1001)", "D"), ("7777", "Kari H. (7777)", "A")])
        texts = self.findings()
        self.assertTrue(any("To ansatte heter «Hansen Kari»" in f for f in texts))
        self.assertFalse(any("to rader" in f for f in texts))

    def test_purge_removes_what_is_past_retention(self):
        self.load()
        hr_import.purge(self.conn, D(2027, 6, 1))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM import_files").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM roster").fetchone()[0], 0)
        self.assertEqual(list((self.inbox / "arkiv").iterdir()), [])

    def test_rebuild_is_repeatable(self):
        self.load()
        first = self.conn.execute("SELECT COUNT(*) FROM roster").fetchone()[0]
        hr_import.rebuild(self.conn, TODAY)
        hr_import.rebuild(self.conn, TODAY)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM roster").fetchone()[0], first)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM employees WHERE origin = 'import'").fetchone()[0], 7)


class LeaveCodesTest(PipelineBase):
    """Fravær and permisjon (R19, D125): alone, the person is away and the app
    keeps no record of which code; «A (PLB)» is partial leave – the shift is
    held until a manager enters its real time, like DX/AX."""

    WEEK = {MON: "SE", MON + dt.timedelta(1): "A (PLB)", MON + dt.timedelta(2): "PLB",
            MON + dt.timedelta(3): "D (XYZ)", MON + dt.timedelta(4): "D (D2)"}

    def load_leave(self):
        self.use_turnus_for_unlisted()
        self.drop(fx.plan_name(EXPORTED), fx.plan_csv(people(), START, 4, EXPORTED))
        exported = dt.datetime(2027, 1, 4, 6, 30)
        self.drop(fx.ukeplan_name(exported), fx.ukeplan_csv([("1001", "Hansen Kari", self.WEEK)], MON, exported))
        hr_import.scan_inbox(self.conn, self.inbox)
        hr_import.rebuild(self.conn, TODAY)
        self.kari = self.conn.execute("SELECT employee_id FROM employees WHERE full_name = 'Hansen Kari'").fetchone()[0]

    def test_parsing(self):
        self.assertEqual(hr_import.parse_cell("A (PLB)"), ("A", None, None, "PLB"))
        self.assertEqual(hr_import.parse_cell("D/F3 (VB)"), ("D", "12:00", None, "VB"))
        self.assertEqual(hr_import.parse_cell("N (PLB), M"), ("N", None, None, "PLB"))
        self.assertEqual(hr_import.parse_cell("SE"), ("SE", None, None, None))
        self.assertEqual(hr_import.generic_partial("A (PLB)"), "A (permisjon)")

    def test_whole_day_absence_and_leave_mean_not_working_and_leave_no_trace(self):
        self.load_leave()
        kari_roster, kari_pending = self.roster("Hansen Kari"), self.pending("Hansen Kari")
        for day in (MON, MON + dt.timedelta(2)):                       # SE, PLB
            self.assertNotIn(day.isoformat(), kari_roster)
            self.assertNotIn(day.isoformat(), kari_pending)
        stored = " ".join(str(v) for table in ("roster", "roster_pending", "import_findings")
                          for row in self.conn.execute(f"SELECT * FROM {table}") for v in tuple(row))
        for code in ("SE", "PLB"):
            self.assertNotIn(code, stored.split(), f"{code} is kept somewhere")
            self.assertNotIn(f"«{code}»", stored)
            self.assertNotIn(f"({code})", stored)

    def test_partial_leave_waits_for_the_real_time(self):
        from app import service
        self.load_leave()
        tue = (MON + dt.timedelta(1)).isoformat()
        row = self.conn.execute("SELECT * FROM roster_pending WHERE employee_id = ? AND date = ?",
                                (self.kari, tue)).fetchone()
        self.assertEqual((row["raw"], row["fixable"]), ("A (permisjon)", 1))
        self.assertIn("delvis permisjon", row["reason"])
        notices = [r for r in self.conn.execute("SELECT * FROM import_findings WHERE kind = 'vakttid'")]
        self.assertEqual(len(notices), 1)                         # one line, however many (R21)
        self.assertIn("1 vakt mangler tid (DX/AX eller delvis permisjon)", notices[0]["text"])
        self.assertIn("Kari H. tirsdag 05.01", notices[0]["text"])
        item = next(i for p in service.unknown_shifts_model(self.conn, TODAY)["people"] for i in p["items"]
                    if i["raw"] == "A (permisjon)")
        self.assertEqual(item["usual"], ("14:00", "22:00"))           # A, offered as a starting point
        with self.conn:
            self.conn.execute("INSERT INTO manual_shift_times VALUES (?, ?, 'A (permisjon)', '14:00', '18:00', 'nå')",
                              (self.kari, tue))
        hr_import.rebuild(self.conn, TODAY)
        planned = self.roster("Hansen Kari")[tue]
        self.assertEqual((planned["shift_code"], planned["start_override"], planned["end_override"]),
                         ("MAN", "14:00", "18:00"))

    def test_cells_kept_for_problems_carry_no_leave_code_either(self):
        codes = {r["code"]: r for r in self.conn.execute("SELECT * FROM shift_codes")}
        self.assertEqual(hr_import.without_leave_codes("SE", codes), "fravær")
        self.assertEqual(hr_import.without_leave_codes("PLB", codes), "permisjon")
        self.assertEqual(hr_import.without_leave_codes("Q9 (PLB)", codes), "Q9 (permisjon)")   # unknown shift
        self.assertEqual(hr_import.without_leave_codes("D (XYZ)", codes), "D (XYZ)")         # unknown: shown
        self.assertEqual(hr_import.without_leave_codes("D, A", codes), "D, A")

    def test_odd_parentheses_are_flagged(self):
        from app import shift_codes
        self.load_leave()
        pending = self.pending("Hansen Kari")
        self.assertIn("ukjent kode i parentes «XYZ»", pending[(MON + dt.timedelta(3)).isoformat()])
        self.assertIn("«D2» i parentes er ikke en permisjons", pending[(MON + dt.timedelta(4)).isoformat()])
        unknown = {u["code"]: u for u in shift_codes.unknown_codes(self.conn, TODAY)}
        self.assertTrue(unknown["XYZ"]["in_parentheses"])
        self.assertNotIn("permisjon", unknown)                         # «A (permisjon)» is no code
        shift_codes.save(self.conn, {"code": "XYZ", "kind": "permisjon"})
        hr_import.rebuild(self.conn, TODAY)
        self.assertIn("delvis permisjon", self.pending("Hansen Kari")[(MON + dt.timedelta(3)).isoformat()])

    def test_a_roster_change_on_an_absent_day_says_only_fravaer(self):
        self.load_leave()
        self.change("Hansen Kari", MON, kind="vakt", code="D")
        replaced = self.conn.execute("SELECT replaced FROM roster_overrides WHERE employee_id = ?",
                                     (self.kari,)).fetchone()[0]
        self.assertEqual(replaced, "fravær")

    def test_the_standard_list_takes_over_a_leave_code_learned_as_a_shift(self):
        with self.conn:
            self.conn.execute("UPDATE shift_code_defs SET kind = 'vanlig', start = '08:00', end = '16:00', "
                              "category = 'tidligvakt', source = 'turnus' WHERE code = 'PLB'")
            self.conn.execute("UPDATE shift_code_defs SET kind = 'ignoreres', source = 'manuell', edited = 1 "
                              "WHERE code = 'SE'")
            importer.import_seed(self.conn, people=False)
        kinds = {r["code"]: r["kind"] for r in self.conn.execute("SELECT code, kind FROM shift_code_defs")}
        self.assertEqual(kinds["PLB"], "permisjon")                    # learned from the legend: replaced
        self.assertEqual(kinds["SE"], "ignoreres")                     # set by hand here: kept


class PlaceholderRowsTest(PipelineBase):
    """PersonID 0 marks a row that isn't a person (R20, D126): skipped, with a
    yellow notice – no employee, no shifts, no red identity alerts."""

    def load_with_placeholders(self):
        self.use_turnus_for_unlisted()
        plan = people() + [("Ledig stilling", "Sterilforsyningstekniker", weekdays("D"), "0"),
                           ("Ledig stilling 2", "Sterilforsyningstekniker", weekdays("D"), "0")]
        self.drop(fx.plan_name(EXPORTED), fx.plan_csv(plan, START, 4, EXPORTED))
        exported = dt.datetime(2027, 1, 4, 6, 30)
        self.drop(fx.ukeplan_name(exported), fx.ukeplan_csv(
            [("1001", "Hansen Kari", {MON: "D"}), ("0", "Vakant", {MON: "D", MON + dt.timedelta(1): "A"})],
            MON, exported))
        hr_import.scan_inbox(self.conn, self.inbox)
        hr_import.rebuild(self.conn, TODAY)

    def test_rows_with_personid_0_are_skipped_with_a_yellow_notice(self):
        from app import competency
        self.load_with_placeholders()
        names = {r[0] for r in self.conn.execute("SELECT full_name FROM employees")}
        self.assertFalse(names & {"Ledig stilling", "Ledig stilling 2", "Vakant"})
        self.assertIn("Hansen Kari", names)
        levels = {r["text"]: r["level"] for r in self.conn.execute("SELECT * FROM import_findings")}
        notice = [t for t in levels if "PersonID 0" in t]
        self.assertEqual(len(notice), 1)
        self.assertEqual(levels[notice[0]], "warn")
        self.assertIn("3 rader", notice[0])
        self.assertIn("Vakant", notice[0])
        self.assertFalse([t for t, level in levels.items()            # no red alerts about them
                          if level == "alert" and ("Ledig" in t or "Vakant" in t)])
        matrix = {r["full_name"] for r in competency.matrix(self.conn)["rows"]}
        self.assertFalse(matrix & {"Ledig stilling", "Vakant"})

    def test_an_employee_made_from_such_a_row_before_is_removed(self):
        with self.conn:
            self.conn.execute("""INSERT INTO employees (employee_id, display_name, works_at, full_name,
                                     person_id, origin) VALUES ('A0999', 'Vakant', 'sf', 'Vakant', '0', 'import')""")
        self.load_with_placeholders()
        self.assertIsNone(self.conn.execute("SELECT 1 FROM employees WHERE employee_id = 'A0999'").fetchone())


if __name__ == "__main__":
    unittest.main()

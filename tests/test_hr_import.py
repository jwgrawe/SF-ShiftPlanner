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
        self.assertIsNotNone(hr_import.interpret("M")[2])
        self.assertIsNotNone(hr_import.interpret("D/F9")[2])


# ---------------------------------------------------------------- pipeline
class PipelineTest(unittest.TestCase):
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

    def test_people_not_in_the_ukeplan_keep_the_turnus_with_a_warning(self):
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
        self.load()
        siri = self.roster("Vik Siri")
        self.assertEqual((siri["2026-12-31"]["shift_code"], siri["2026-12-31"]["end_override"]),
                         ("DK", "12:00"))
        self.assertEqual(siri["2027-01-05"]["shift_code"], "D2")
        self.assertIn("X9", self.pending("Vik Siri")["2027-01-06"])
        self.assertTrue(any("X9" in f for f in self.findings()))

    def test_codes_learned_from_the_legend(self):
        self.load()
        row = self.conn.execute("SELECT * FROM learned_shift_codes WHERE code = 'D3'").fetchone()
        self.assertEqual((row["start"], row["end"], row["category"]),
                         ("09:00", "13:30", "tidligvakt"))
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM learned_shift_codes WHERE code = 'D2*'").fetchone())

    def test_title_rules_hold_days_out_until_classified(self):
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

    def test_one_name_with_two_person_ids_alerts(self):
        self.load()
        self.drop(fx.ukeplan_name(dt.datetime(2027, 1, 11, 6)), fx.ukeplan_csv(
            [("9999", "Hansen Kari", {MON + dt.timedelta(7): "D"})],
            MON + dt.timedelta(7), dt.datetime(2027, 1, 11, 6)))
        hr_import.scan_inbox(self.conn, self.inbox)
        hr_import.rebuild(self.conn, TODAY)
        self.assertTrue(any("flere PersonID" in f for f in self.findings()))

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


if __name__ == "__main__":
    unittest.main()

"""The shift-code master list (D103): Administrasjon → Vaktkoder."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hr_fixtures as fx  # noqa: E402
from test_competency import EXPORTED, START, TODAY, RealModeBase  # noqa: E402
from app import db, domain, hr_import, importer, shift_codes  # noqa: E402


def overview(conn):
    return shift_codes.overview(conn, TODAY)


class ClockTest(unittest.TestCase):
    def test_typed_times_are_forgiving(self):
        cases = {"7": "07:00", "730": "07:30", "0730": "07:30", "7.30": "07:30", "15,30": "15:30",
                 "1530": "15:30", "24": "00:00", "22:00": "22:00"}
        for typed, expected in cases.items():
            self.assertEqual(domain.parse_clock(typed).strftime("%H:%M"), expected, typed)
        for bad in ("", "25", "7:61", "abc", "12345"):
            with self.assertRaises(ValueError):
                domain.parse_clock(bad)


class ManagerTest(RealModeBase):
    def setUp(self):
        super().setUp()
        # A newer turnus with three new things: an unknown code, a code the
        # legend describes differently, and DMT (ignored).
        crew = [("Hansen Kari", "Sterilforsyningstekniker",
                 {START + dt.timedelta(d): "D" for d in range(28)} | {TODAY + dt.timedelta(9): "Q7",
                                                                    TODAY + dt.timedelta(10): "DMT"}),
                ("Olsen Tor", "Sterilforsyningstekniker", {START + dt.timedelta(d): "A" for d in range(28)})]
        legend = [r if r[0] != "A" else ("A", "14:00", "22:30", "1", "Aktiv") for r in fx.LEGEND]
        stamp = EXPORTED + dt.timedelta(days=1)
        self.drop(fx.plan_name(stamp), fx.plan_csv(crew, START, 4, stamp, legend=legend))
        hr_import.scan_inbox(self.conn, self.inbox)
        hr_import.rebuild(self.conn, TODAY)

    def test_overview_shows_what_needs_attention(self):
        model = overview(self.conn)
        self.assertEqual([u["code"] for u in model["unknown"]], ["Q7"])
        codes = {c["code"]: c for c in model["codes"]}
        self.assertTrue(codes["A"]["deviation"])
        self.assertEqual(codes["A"]["legend"], ("14:00", "22:30"))
        self.assertFalse(codes["D3"]["reviewed"])                 # learned from the legend
        self.assertEqual(codes["DMT"]["kind"], "ignoreres")
        self.assertGreater(codes["DX"]["used"], 0)
        self.assertEqual(model["counts"]["avvik"], 1)
        self.assertEqual(shift_codes.attention(self.conn, TODAY), 1 + 1 + model["counts"]["nye"])

    def test_defining_an_unknown_code_plans_it(self):
        shift_codes.save(self.conn, {"code": "q7", "kind": "vanlig", "start": "9", "end": "1630"})
        hr_import.rebuild(self.conn, TODAY)
        row = self.conn.execute(
            """SELECT r.* FROM roster r JOIN employees e USING (employee_id)
               WHERE e.full_name = 'Hansen Kari' AND r.date = ?""",
            ((TODAY + dt.timedelta(9)).isoformat(),)).fetchone()
        self.assertEqual(row["shift_code"], "Q7")
        code = self.conn.execute("SELECT * FROM shift_codes WHERE code = 'Q7'").fetchone()
        self.assertEqual((code["start"], code["end"], code["category"]), ("09:00", "16:30", "tidligvakt"))
        self.assertEqual(overview(self.conn)["unknown"], [])
        self.assertTrue(any("Q7 lagt til" in r[0] for r in self.conn.execute("SELECT text FROM import_log")))

    def test_a_per_shift_code_asks_for_times(self):
        shift_codes.save(self.conn, {"code": "Q7", "kind": "egen_tid"})
        hr_import.rebuild(self.conn, TODAY)
        fixable = self.conn.execute("SELECT fixable FROM roster_pending WHERE raw = 'Q7'").fetchone()[0]
        self.assertEqual(fixable, 1)

    def test_validation(self):
        for form, text in (({"code": "MAN", "kind": "vanlig"}, "reservert"),
                           ({"code": "M", "kind": "vanlig"}, "overtid"),
                           ({"code": "D 2", "kind": "vanlig"}, "bokstaver"),
                           ({"code": "D", "kind": "vanlig", "start": "7", "end": "15"}, "finnes allerede"),
                           ({"code": "Z1", "kind": "vanlig", "start": "7", "end": "7"}, "like"),
                           ({"code": "Z1", "kind": "vanlig", "start": "x", "end": "7"}, "klokkeslett")):
            with self.assertRaises(shift_codes.Invalid) as ctx:
                shift_codes.save(self.conn, form)
            self.assertIn(text, str(ctx.exception))

    def test_deviation_take_turnus_or_keep(self):
        shift_codes.keep_app_time(self.conn, "A")
        hr_import.rebuild(self.conn, TODAY)
        self.assertFalse({c["code"]: c for c in overview(self.conn)["codes"]}["A"]["deviation"])
        self.assertFalse(any("Vaktkoden A er" in r[0] for r in self.conn.execute(
            "SELECT text FROM import_findings")))
        shift_codes.use_turnus_time(self.conn, "A")
        self.assertEqual(self.conn.execute("SELECT end FROM shift_codes WHERE code = 'A'").fetchone()[0],
                         "22:30")

    def test_ignoring_a_code_holds_its_days_out(self):
        shift_codes.save(self.conn, {"code": "D", "existing": "1", "kind": "ignoreres"})
        hr_import.rebuild(self.conn, TODAY)
        holds = {r[0] for r in self.conn.execute("SELECT hold FROM roster WHERE shift_code = 'D'")}
        self.assertEqual(holds, {"kode"})

    def test_delete_and_restore_survive_a_seed_reload(self):
        shift_codes.delete(self.conn, "D4")
        with self.conn:
            importer.seed_shift_codes(self.conn)
            db.sync_shift_codes(self.conn)
        self.assertIsNone(self.conn.execute("SELECT 1 FROM shift_codes WHERE code = 'D4'").fetchone())
        self.assertEqual([c["code"] for c in overview(self.conn)["deleted"]], ["D4"])
        shift_codes.restore(self.conn, "D4")
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM shift_codes WHERE code = 'D4'").fetchone())

    def test_csv_export_reads_back_as_a_seed(self):
        from app import csvfile
        raw = shift_codes.export_csv(self.conn)
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))                 # Excel: UTF-8
        self.assertTrue(raw.decode("utf-8-sig").startswith(";".join(shift_codes.CSV_COLUMNS)))
        rows = {r["code"]: r for r in csvfile.parse(csvfile.decode(raw))}
        self.assertEqual((rows["D"]["start"], rows["D"]["kind"]), ("07:00", "vanlig"))
        self.assertEqual((rows["DMT"]["kind"], rows["DMT"]["start"]), ("ignoreres", ""))
        self.assertNotIn("MAN", rows)


class CsvFileTest(unittest.TestCase):
    """Seed files open in columns in a Norwegian Excel, and whatever Excel
    saves back still reads (D112)."""

    def test_reads_what_excel_may_write(self):
        from app import csvfile
        expected = [{"kode": "D", "merknad": "fritatt fra én funksjon; i en periode"}]
        variants = {
            "semikolon + BOM": "\ufeffkode;merknad\r\nD;\"fritatt fra én funksjon; i en periode\"\r\n".encode("utf-8"),
            "Windows-1252": "kode;merknad\r\nD;\"fritatt fra én funksjon; i en periode\"\r\n".encode("cp1252"),
            "komma": "kode,merknad\nD,\"fritatt fra én funksjon; i en periode\"\n".encode("utf-8"),
            "sep-linje": "sep=;\r\nkode;merknad\r\nD;\"fritatt fra én funksjon; i en periode\"\r\n".encode("utf-8"),
        }
        for name, raw in variants.items():
            self.assertEqual(csvfile.parse(csvfile.decode(raw)), expected, name)

    def test_every_seed_file_is_excel_friendly(self):
        from app import csvfile, importer
        for path in importer.SEED_DIR.glob("*.csv"):
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), path.name)
            self.assertIn(";", raw.decode("utf-8-sig").splitlines()[0], path.name)
            self.assertTrue(csvfile.read(path), path.name)

if __name__ == "__main__":
    unittest.main()

"""The anonymiser must never let a real name or employee number through."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("anonymise_export", ROOT / "scripts" / "anonymise_export.py")
anonymise = importlib.util.module_from_spec(spec)
spec.loader.exec_module(anonymise)

PEOPLE = [("Hansen", "Kari", "12345"), ("Johansen", "Dag Ole", "23456"),
          ("Berg", "Ingrid M.", "34567"), ("Nilsen", "Per", "45678")]
DATES = ["05.01.2026", "06.01.2026", "07.01.2026"]
SECRETS = ["Hansen", "Kari", "Johansen", "Nilsen", "Ingrid", "12345", "23456", "45678", "912 34 567"]

LAYOUTS = {
    # Plan/turnus today: one row per person, a column per date, names only.
    "turnus.csv": ["Navn;" + ";".join(DATES)]
    + [f"{last}, {first};D;A;N" for last, first, _ in PEOPLE]
    + ["", "D;Dagvakt 07:00-15:00", "Utskrift av Kari Hansen"],
    # Ajourhold: one row per person per day, with employee number and comments.
    "ukeplan.csv": ["Ansattnr;Navn;Dato;Vakt;Kommentar"]
    + [f"{eid};{first} {last};{day};D;Byttet med Per Nilsen etter avtale"
       for last, first, eid in PEOPLE for day in DATES]
    + ["99999;Ola Nordmann;05.01.2026;A;ring 912 34 567"],
    # A person heading a block of rows.
    "blokk.csv": [line for last, first, eid in PEOPLE
                  for line in [f"Ansatt: {first} {last};{eid};"] + [f";{d};D" for d in DATES] + [";;"]],
    # People as columns.
    "kolonner.csv": ["Dato;" + ";".join(f"{first} {last}" for last, first, _ in PEOPLE)]
    + [f"{d};D;A;N;D" for d in DATES],
}


class AnonymiseTest(unittest.TestCase):
    def run_on(self, *extra):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "in").mkdir()
        for name, lines in LAYOUTS.items():
            (tmp / "in" / name).write_text("\n".join(lines), encoding="utf-8")
        files = [str(p) for p in sorted((tmp / "in").glob("*.csv"))]
        anonymise.main(files + ["--ut", str(tmp / "out"), "--nokkel", str(tmp / "key.json"), *extra])
        return tmp / "out"

    def test_no_real_name_or_number_survives(self):
        out = self.run_on("--alle")
        for path in out.iterdir():
            text = path.read_text(encoding="utf-8")
            for secret in SECRETS:
                self.assertNotIn(secret, text, f"{secret!r} leaked into {path.name}")

    def test_structure_and_codes_are_kept(self):
        out = self.run_on("--alle")
        turnus = (out / "turnus.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(turnus), len(LAYOUTS["turnus.csv"]))
        self.assertEqual(turnus[0], LAYOUTS["turnus.csv"][0])
        self.assertIn("D;Dagvakt 07:00-15:00", turnus)
        self.assertTrue(all(row.endswith(";D;A;N") for row in turnus[1:5]))

    def test_same_person_same_fake_name_across_files(self):
        out = self.run_on("--alle")
        turnus = (out / "turnus.csv").read_text(encoding="utf-8").splitlines()
        last, first = turnus[1].split(";")[0].split(", ")
        ukeplan = (out / "ukeplan.csv").read_text(encoding="utf-8")
        self.assertIn(f"{first} {last}", ukeplan)

    def test_sample_keeps_the_same_people_in_every_file(self):
        out = self.run_on("--utvalg", "2")
        turnus = (out / "turnus.csv").read_text(encoding="utf-8").splitlines()
        people = {row.split(";")[0] for row in turnus[1:] if row.endswith(";D;A;N")}
        self.assertEqual(len(people), 2)
        ukeplan = (out / "ukeplan.csv").read_text(encoding="utf-8")
        for name in people:
            last, first = name.split(", ")
            self.assertIn(f"{first} {last}", ukeplan)


if __name__ == "__main__":
    unittest.main()

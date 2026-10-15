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
SECRETS = ["Hansen", "Kari", "Johansen", "Nilsen", "Ingrid", "12345", "23456", "45678", "912 34 567",
           "Anne", "Olsen", "Tor", "Lie", "Mai", "10234", "11902", "1153"]

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
    # The real turnus shape: names under "Person navn", then a summary whose
    # headers sit one column right of their data — here with the summary names
    # in a different column, under an empty cell. Includes a lower-case
    # particle and first names that double as ordinary words (Tor, Mai).
    "turnus_rapport.csv": ["Turnusrapport;;;;", ";;;;", "Person navn;05.01.2026;06.01.2026;;"]
    + ["Hansen Kari;D;A;;", "van der Berg Anne;N;D;;", "Olsen Tor;A;A;;", "Lie Mai;D;N;;"]
    + [";;;;", ";;Person navn;Sum timer;Snitt"]
    + [";Hansen Kari;120,5;30;", ";van der Berg Anne;80;20;", ";Olsen Tor;40;10;", ";Lie Mai;60;15;"],
    # The exact turnus export shape: titles in column B, and a summary whose
    # "Person navn" header sits over the titles column (shifted right).
    "fleksiplan.csv": [";;;", "Person navn;Stillingsbetegnelse;Sum uke;Ma 05.01",
                       "Hansen Kari;Sterilforsyningstekniker;37;D", "Olsen Tor;IKT-konsulent;20;",
                       "Lie Mai;Kvalitetskoordinator;30;A", ";;;",
                       ";Person navn;Stillingsbetegnelse;Sum uke",
                       "Hansen Kari;Sterilforsyningstekniker;37;", "Olsen Tor;IKT-konsulent;20;",
                       "Lie Mai;Kvalitetskoordinator;30;"],
    # Ajourhold's real headers.
    "ukeplan_ekte.csv": ["Ukeplan uke 2;;;", "PersonID;Navn;Dato;Vakt"]
    + ["10234;Kari Hansen;05.01.2026;D", "1153;Anne van der Berg;05.01.2026;N",
       "11902;Tor Olsen;05.01.2026;A", "12007;Mai Lie;05.01.2026;D"],
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
                self.assertNotRegex(text, rf"(?<![A-Za-zæøåÆØÅ0-9]){secret}(?![A-Za-zæøåÆØÅ0-9])",
                                    f"{secret!r} leaked into {path.name}")

    def test_job_titles_are_not_names(self):
        out = self.run_on("--alle")
        text = (out / "fleksiplan.csv").read_text(encoding="utf-8")
        for title in ("Sterilforsyningstekniker", "IKT-konsulent", "Kvalitetskoordinator"):
            self.assertEqual(text.count(title), 2, title)

    def test_turnus_layout_with_shifted_summary_headers(self):
        out = self.run_on("--alle")
        rows = (out / "turnus_rapport.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(rows[2], "Person navn;05.01.2026;06.01.2026;;")
        self.assertEqual(rows[8], ";;Person navn;Sum timer;Snitt")
        first_section = [r.split(";")[0] for r in rows[3:7]]
        summary = [r.split(";")[1] for r in rows[9:13]]
        self.assertEqual(first_section, summary)  # same invented names in both places
        report = (out / "_rapport.txt").read_text(encoding="utf-8")
        self.assertIn("NAVN funnet i:      A4:A7, B10:B13", report)

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

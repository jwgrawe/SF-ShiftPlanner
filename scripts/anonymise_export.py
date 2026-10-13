#!/usr/bin/env python3
"""Anonymise HR exports (Plan/turnus and Ajourhold/ukeplan, CSV) locally.

Runs on the PC that holds the real files. Nothing is sent anywhere. Reads every
*.csv in data/private/ (or the files given as arguments) and writes, to
data/private/anonymisert/:

  <fil>.csv            same layout, encoding and delimiter as the original, but
                       names -> invented names, employee numbers -> invented
                       numbers, person comments -> "[tekst]", e-mail/phone ->
                       placeholders, and only a sample of the employees (--utvalg)
  _rapport.txt         structure report: encoding, delimiter, detected columns,
                       code inventory vs. data/seed/shift_codes.csv, overlap
  _gjennomgang.txt     EVERY distinct text value that survived, for a human
                       read-through before anything is shared

The real->invented key is kept in data/private/anonymiser_nokkel.json so the
same person gets the same invented name in every file and on every run (the
turnus and the ukeplan must still join). That key is personal data: never
share it. Anything the script misses can be forced out by listing it, one per
line, in data/private/ekstra_sladding.txt.

  python scripts/anonymise_export.py                 # all CSVs in data/private
  python scripts/anonymise_export.py --alle          # every employee, not a sample
  python scripts/anonymise_export.py --navn-kolonne "Navn" --id-kolonne "Ansattnr"
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import random
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT / "data" / "private"
OUT_DIR = PRIVATE / "anonymisert"
KEY_PATH = PRIVATE / "anonymiser_nokkel.json"
EXTRA_PATH = PRIVATE / "ekstra_sladding.txt"
SHIFT_CODES_PATH = ROOT / "data" / "seed" / "shift_codes.csv"

L = "A-Za-zÆØÅæøåÄäÖöÜüÉéÈèÁáÓóÍíÑñ"
WORD = re.compile(rf"[{L}]+")
NAME_CELL = re.compile(rf"^[{L}][{L}.'\-]*(?:,?\s+[{L}][{L}.'\-]*){{0,5}},?$")
COMMA_NAME = re.compile(rf"^[{L}][{L}'\-]+(?:\s[{L}][{L}'\-]+)*,\s*[{L}][{L}.'\-]+(?:\s[{L}][{L}.'\-]*)*$")
LABELLED_NAME = re.compile(r"^\s*(ansatt|navn|medarbeider|arbeidstaker)\s*:\s*(.+?)\s*$", re.I)
ID_RE = re.compile(r"^\d{4,11}$")
HHMM = re.compile(r"^([01]\d|2[0-3])[0-5]\d$")
DATE_DMY = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})\b")
DATE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})\b")
CLOCK = re.compile(r"\b\d{1,2}[:.]\d{2}\s*-\s*\d{1,2}[:.]\d{2}\b|\b\d{1,2}:\d{2}\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<!\d)(?:\+47\s?)?[49]\d{2}\s?\d{2}\s?\d{3}(?!\d)")
FNR = re.compile(r"(?<!\d)\d{6}\s?\d{5}(?!\d)")
ID_HEADER = re.compile(
    r"(ansatt|ans\.?|lønns|lonns|ressurs|person|pers\.?|tjeneste)\s*-?\s*(nr|nummer|id)\b|^nr\.?$|^id$",
    re.I)
NAME_HEADER = re.compile(r"\bnavn\b|^ansatt$|^medarbeider$|^ressurs$", re.I)

# Structural words that are never treated as names on their own.
VOCAB = set("""
navn ansatt ansattnr ansattnummer nr nummer id dato uke ukenr dag dager vakt vakter
vaktkode vaktkoder kode koder tid fra til start slutt fravær fravaer årsak arsak type
kommentar merknad beskrivelse forklaring stilling stillingsprosent prosent avdeling
seksjon enhet turnus plan ajourhold ukeplan sum timer totalt mandag tirsdag onsdag
torsdag fredag lørdag søndag man tir ons tor fre lør søn ma ti on to fr lø sø januar
februar mars april mai juni juli august september oktober november desember jan feb
mar apr jun jul aug sep sept okt nov des ferie syk sykdom sykefravær egenmelding
permisjon kurs fri fridag helg helligdag natt kveld aften dagvakt kveldsvakt
nattevakt langvakt senvakt tidligvakt mellomvakt helgevakt sterilforsyning sf og i på
med av for kl rapport utskrift periode side ja nei x ren uren steril sone produksjon
vikar ekstravakt overtid bytte vaktbytte avspasering tilkalling ledig ubesatt
utpost gjelder ukedag hverdag år måned dato tidsrom
""".split())


def load_codes() -> set[str]:
    if not SHIFT_CODES_PATH.exists():
        return set()
    with open(SHIFT_CODES_PATH, newline="", encoding="utf-8") as fh:
        return {row["code"].strip() for row in csv.DictReader(fh) if row.get("code")}


# --------------------------------------------------------------------- io
def read_csv(path: Path) -> dict:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    newline = "\r\n" if "\r\n" in text[:20000] else "\n"
    sample = text[:65536]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
        delimiter, quotechar = dialect.delimiter, dialect.quotechar or '"'
    except csv.Error:
        counts = {c: sample.count(c) for c in ";,\t|"}
        delimiter, quotechar = max(counts, key=counts.get), '"'
    lines = [ln for ln in sample.splitlines() if ln.strip()][:50]
    quote_all = bool(lines) and sum(ln.startswith(quotechar) for ln in lines) > 0.8 * len(lines)
    grid = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, quotechar=quotechar))
    return {
        "grid": grid, "bom": bom, "newline": newline, "delimiter": delimiter,
        "quotechar": quotechar, "quote_all": quote_all,
        "encoding": "utf-8" if encoding == "utf-8-sig" else encoding,
    }


def write_csv(path: Path, meta: dict, grid: list[list[str]]) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=meta["delimiter"], quotechar=meta["quotechar"],
                        quoting=csv.QUOTE_ALL if meta["quote_all"] else csv.QUOTE_MINIMAL,
                        lineterminator=meta["newline"])
    writer.writerows(grid)
    encoding = "utf-8-sig" if meta["bom"] else meta["encoding"]
    path.write_bytes(buf.getvalue().encode(encoding, errors="replace"))


# --------------------------------------------------------------- the key
class Key:
    """Persistent real -> invented mapping, so files and runs stay consistent."""

    SYL1 = ["Ka", "Li", "Mo", "Sa", "Ve", "To", "Ri", "Ne", "Ha", "Jo", "El", "Bo",
            "Ti", "Ru", "Fa", "Ma", "Si", "Gu", "Le", "Da"]
    SYL2 = ["ra", "ne", "vik", "dal", "sen", "lin", "rud", "berg", "nes", "heim",
            "mo", "li", "sta", "ven", "land", "ta"]

    def __init__(self, path: Path):
        self.path = path
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self.ids: dict[str, str] = data.get("ids", {})
        self.tokens: dict[str, str] = data.get("tokens", {})
        self.letters: dict[str, str] = data.get("letters", {})
        self.rng = random.Random()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {"ids": self.ids, "tokens": self.tokens, "letters": self.letters},
            ensure_ascii=False, indent=1), encoding="utf-8")

    def fake_id(self, real: str) -> str:
        if real not in self.ids:
            used = set(self.ids.values()) | set(self.ids)
            while True:
                fake = "9" + "".join(self.rng.choice("0123456789") for _ in range(len(real) - 1))
                if fake not in used:
                    break
            self.ids[real] = fake
        return self.ids[real]

    def fake_token(self, real: str) -> str:
        if len(real) == 1:
            low = real.lower()
            if low not in self.letters:
                pool = [c for c in "abdefghijklmnoprstv" if c not in self.letters.values()] or ["x"]
                self.letters[low] = self.rng.choice(pool)
            fake = self.letters[low]
        else:
            low = real.lower()
            if low not in self.tokens:
                used = set(self.tokens.values())
                for _ in range(500):
                    parts = [self.rng.choice(self.SYL1), self.rng.choice(self.SYL2)]
                    if self.rng.random() < 0.4:
                        parts.append(self.rng.choice(self.SYL2))
                    fake = "".join(parts)
                    if fake not in used and fake.lower() not in VOCAB:
                        break
                self.tokens[low] = fake
            fake = self.tokens[low]
        if real.isupper():
            return fake.upper()
        if real[0].isupper():
            return fake[0].upper() + fake[1:]
        return fake.lower()


# ------------------------------------------------------------ detection
def column(grid, j):
    return [row[j] if j < len(row) else "" for row in grid]


def axis_lines(grid, axis):
    if axis == "row":
        return grid
    width = max((len(r) for r in grid), default=0)
    return [column(grid, j) for j in range(width)]


def is_id(value: str) -> bool:
    return bool(ID_RE.match(value)) and not HHMM.match(value)


def name_part(value: str, codes: set[str]) -> str | None:
    """The name in a cell that holds one ("Hansen, Kari" or "Ansatt: Kari Hansen")."""
    m = LABELLED_NAME.match(value)
    if m and looks_like_full_name(m[2], codes):
        return m[2]
    return value.strip() if looks_like_full_name(value, codes) else None


def looks_like_full_name(value: str, codes: set[str]) -> bool:
    value = value.strip()
    if not NAME_CELL.match(value):
        return False
    words = WORD.findall(value)
    if len(words) < 2 or not all(w[0].isupper() for w in words):
        return False
    return not all(w.lower() in VOCAB or w in codes for w in words)


def find_lines(grid, axis, codes, force_header=None, kind="id"):
    """Indices of columns (axis='col') or rows (axis='row') holding IDs or names."""
    found = []
    for idx, cells in enumerate(axis_lines(grid, axis)):
        values = [c.strip() for c in cells if c.strip()]
        if not values:
            continue
        head = values[0]
        if force_header and any(v.lower() == force_header.lower() for v in values[:15]):
            found.append(idx)
            continue
        if kind == "id":
            hits = [v for v in values if is_id(v)]
            headed = bool(ID_HEADER.search(head))
        else:
            hits = [v for v in values if name_part(v, codes)]
            headed = bool(NAME_HEADER.search(head))
        if (len(set(hits)) >= 3 and len(hits) >= 0.2 * len(values)) or (headed and hits):
            found.append(idx)
    return found


def name_key(value: str) -> str:
    return " ".join(sorted(w.lower() for w in WORD.findall(value)))


def detect_people(grid, codes, id_header=None, name_header=None):
    """Find where people are, and who owns each row (or column)."""
    for axis in ("col", "row"):
        id_lines = find_lines(grid, axis, codes, id_header, "id")
        name_lines = find_lines(grid, axis, codes, name_header, "name")
        if axis == "row":  # a single header row of names = persons as columns
            id_lines = [i for i in id_lines if i < 15]
            name_lines = [i for i in name_lines if i < 15]
        if id_lines or name_lines:
            break
    else:
        return None
    lines = axis_lines(grid, axis)
    key_line = name_lines[0] if name_lines else id_lines[0]
    cells = lines[key_line]
    owners: dict[int, str] = {}
    for entry, value in enumerate(cells):
        value = value.strip()
        if not value:
            continue
        if key_line in name_lines and name_part(value, codes):
            owners[entry] = name_key(name_part(value, codes))
        elif key_line in id_lines and is_id(value):
            owners[entry] = value
    # Sparse key column = block layout (a person heads several rows): fill
    # forward until the next person or a blank line.
    filled = False
    if owners:
        first, last = min(owners), max(owners)
        span = range(first, len(cells))
        if len(owners) < 0.6 * (last - first + 1):
            filled = True
            entries = grid if axis == "col" else axis_lines(grid, "col")
            current = None
            for entry in span:
                if entry in owners:
                    current = owners[entry]
                elif entry < len(entries) and not any(c.strip() for c in entries[entry]):
                    current = None
                elif current:
                    owners[entry] = current
    return {"axis": axis, "id_lines": id_lines, "name_lines": name_lines,
            "key_line": key_line, "owners": owners, "filled": filled}


# ------------------------------------------------------------ anonymise
def valid_date(value: str):
    m = DATE_ISO.match(value)
    try:
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = DATE_DMY.match(value)
        if m:
            year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            return date(year, int(m[2]), int(m[1]))
    except ValueError:
        return None
    return None


class Anonymiser:
    def __init__(self, key: Key, codes: set[str], extra: list[str]):
        self.key, self.codes, self.extra = key, codes, extra
        self.stats = Counter()

    def collect(self, grid, people):
        """First pass: learn every real ID and name token in this file."""
        lines = axis_lines(grid, people["axis"])
        for idx in people["id_lines"]:
            for value in lines[idx]:
                if is_id(value.strip()):
                    self.key.fake_id(value.strip())
        for idx in people["name_lines"]:
            for value in lines[idx]:
                if name_part(value, self.codes):
                    self.learn_name(name_part(value, self.codes))
        for row in grid:
            for value in row:
                m = LABELLED_NAME.match(value)
                if COMMA_NAME.match(value.strip()):
                    self.learn_name(value)
                elif m:
                    self.learn_name(m[2])

    def learn_name(self, value):
        for token in WORD.findall(value):
            self.key.fake_token(token)

    def compile(self):
        tokens = [t for t in self.key.tokens if t not in VOCAB and t.upper() not in self.codes]
        tokens.sort(key=len, reverse=True)
        self.token_re = re.compile(
            rf"(?<![{L}])(" + "|".join(map(re.escape, tokens)) + rf")(?![{L}])", re.I) if tokens else None
        ids = sorted(self.key.ids, key=len, reverse=True)
        self.id_re = re.compile(r"(?<!\d)(" + "|".join(ids) + r")(?!\d)") if ids else None

    def name(self, value):
        """Replace every word of a cell known to be a name, initials included."""
        self.stats["navneceller"] += 1
        return re.sub(rf"[{L}]+", lambda m: self.key.fake_token(m[0]), value)

    def cell(self, value: str, is_name: bool, personal: bool) -> tuple[str, bool]:
        stripped = value.strip()
        if not stripped:
            return value, False
        if is_name:
            return self.name(value), True
        if stripped in self.key.ids:
            self.stats["ansattnr"] += 1
            return value.replace(stripped, self.key.ids[stripped]), True
        m = LABELLED_NAME.match(value)
        if COMMA_NAME.match(stripped) and looks_like_full_name(stripped, self.codes):
            return self.name(value), True
        if m:
            return value.replace(m[2], self.name(m[2])), True
        out = value
        for text in self.extra:
            if text and text.lower() in out.lower():
                out = re.sub(re.escape(text), "[sladdet]", out, flags=re.I)
                self.stats["ekstra sladding"] += 1
        if EMAIL.search(out):
            out = EMAIL.sub("[epost]", out); self.stats["epost"] += 1
        if self.id_re and self.id_re.search(out):
            out = self.id_re.sub(lambda m: self.key.ids[m[1]], out); self.stats["ansattnr i tekst"] += 1
        if FNR.search(out):
            out = FNR.sub("[fnr]", out); self.stats["fødselsnr"] += 1
        if PHONE.search(out):
            out = PHONE.sub("[telefon]", out); self.stats["telefon"] += 1
        when = valid_date(stripped)
        if when and abs((when - date.today()).days) > 3 * 366:
            self.stats["dato utenfor turnusperiode"] += 1
            return "[dato]", False
        if self.token_re:
            replaced = self.token_re.sub(lambda m: self.key.fake_token(m[0]), out)
            if replaced != out:
                self.stats["navn i tekst"] += 1
                out = replaced
        if personal and len(WORD.findall(out)) >= 3 and not CLOCK.search(out):
            self.stats["fritekst på person"] += 1
            return "[tekst]", False
        return out, False


def process(grid, people, anon: Anonymiser, keep: set[str] | None):
    axis, owners = people["axis"], people["owners"]
    name_lines = set(people["name_lines"])
    out, survivors = [], Counter()
    for i, row in enumerate(grid):
        if axis == "col" and i in owners and keep is not None and owners[i] not in keep:
            continue
        new_row = []
        for j, value in enumerate(row):
            entry, line = (i, j) if axis == "col" else (j, i)
            if axis == "row" and entry in owners and keep is not None and owners[entry] not in keep:
                continue
            is_name = line in name_lines and looks_like_full_name(value, anon.codes)
            new, mapped = anon.cell(value, is_name, entry in owners)
            new_row.append(new)
            if not mapped and re.search(rf"[{L}]{{2}}", new):
                survivors[new.strip()] += 1
        out.append(new_row)
    return out, survivors


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Anonymiser turnus-/ukeplan-eksport (CSV) lokalt.")
    parser.add_argument("filer", nargs="*", help="CSV-filer (standard: alle *.csv i data/private)")
    parser.add_argument("--utvalg", type=int, default=20, help="antall ansatte i kopien (standard 20)")
    parser.add_argument("--alle", action="store_true", help="ta med alle ansatte")
    parser.add_argument("--id-kolonne", help="overskrift på kolonnen med ansattnummer")
    parser.add_argument("--navn-kolonne", help="overskrift på kolonnen med navn")
    parser.add_argument("--ut", type=Path, default=OUT_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--nokkel", type=Path, default=KEY_PATH, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    paths = [Path(p) for p in args.filer] or sorted(PRIVATE.glob("*.csv"))
    if not paths:
        print(f"Fant ingen CSV-filer. Legg eksportfilene i {PRIVATE} og kjør på nytt.")
        return 1
    codes = load_codes()
    extra = []
    if EXTRA_PATH.exists():
        extra = [ln.strip() for ln in EXTRA_PATH.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.startswith("#")]
    key = Key(args.nokkel)
    anon = Anonymiser(key, codes, extra)

    files = []
    for path in paths:
        meta = read_csv(path)
        people = detect_people(meta["grid"], codes, args.id_kolonne, args.navn_kolonne)
        files.append((path, meta, people))
        if people:
            anon.collect(meta["grid"], people)
    anon.compile()

    # Same employees in every file, so the files still join after sampling.
    keysets = [set(p["owners"].values()) for _, _, p in files if p]
    keep = None
    if not args.alle and keysets:
        common = set.intersection(*keysets)
        ordered = sorted(common) + sorted(set.union(*keysets) - common)
        keep = set(ordered[:args.utvalg])

    args.ut.mkdir(parents=True, exist_ok=True)
    report, review = [], Counter()
    report.append("ANONYMISERINGSRAPPORT — inneholder kun struktur, ingen personopplysninger\n")
    for n, (path, meta, people) in enumerate(files, 1):
        safe_stem = anon.token_re.sub(lambda m: key.fake_token(m[0]), path.stem) if anon.token_re else path.stem
        grid = meta["grid"]
        report.append(f"== Fil {n}: {safe_stem}{path.suffix}")
        report.append(f"   tegnsett {meta['encoding']}{' med BOM' if meta['bom'] else ''}, "
                      f"skilletegn {meta['delimiter']!r}, linjeskift {meta['newline']!r}, "
                      f"{'alle felt i anførselstegn' if meta['quote_all'] else 'anførselstegn ved behov'}")
        widths = Counter(len(r) for r in grid)
        report.append(f"   {len(grid)} rader; antall felt per rad: "
                      + ", ".join(f"{w}×{c}" for w, c in widths.most_common(6)))
        if not people:
            report.append("   !! Fant verken ansattnummer eller navn — filen er IKKE anonymisert og ble ikke skrevet.")
            report.append("      Kjør igjen med --navn-kolonne \"<overskrift>\" og/eller --id-kolonne \"<overskrift>\".\n")
            print(f"[{n}] {path.name}: fant ingen navn/ansattnr — hoppet over (se rapporten).")
            continue
        where = "kolonne" if people["axis"] == "col" else "rad"
        report.append(f"   personer ligger i {'rader' if people['axis'] == 'col' else 'kolonner'}; "
                      f"ansattnr-{where}: {[i + 1 for i in people['id_lines']] or 'ingen'}; "
                      f"navne-{where}: {[i + 1 for i in people['name_lines']] or 'ingen'}"
                      + ("; blokkoppsett (person over flere rader)" if people["filled"] else ""))
        persons = set(people["owners"].values())
        kept = persons if keep is None else persons & keep
        report.append(f"   {len(persons)} personer i filen, {len(kept)} med i kopien")
        before = Counter(anon.stats)
        out, survivors = process(grid, people, anon, keep)
        dates = sorted(d for row in grid for c in row if (d := valid_date(c.strip())))
        if dates:
            report.append(f"   datoer {dates[0]} – {dates[-1]} ({len(set(dates))} ulike)")
        codes_seen = Counter(c.strip() for row in out for c in row
                             if 0 < len(c.strip()) <= 6 and re.fullmatch(rf"[{L}0-9/+\-.]+", c.strip())
                             and not c.strip().isdigit())
        known = sorted((c, k) for c, k in codes_seen.items() if c in codes)
        unknown = sorted((c, k) for c, k in codes_seen.items() if c not in codes)
        report.append("   kjente vaktkoder: " + (", ".join(f"{c}({k})" for c, k in known) or "–"))
        report.append("   andre korte verdier: " + (", ".join(f"{c}({k})" for c, k in unknown) or "–"))
        changed = anon.stats - before
        report.append("   erstattet: " + (", ".join(f"{k} {v}" for k, v in changed.items()) or "ingenting") + "\n")
        target = args.ut / f"{safe_stem}{path.suffix}"
        write_csv(target, meta, out)
        review.update(survivors)
        print(f"[{n}] {path.name} -> {target.relative_to(ROOT) if target.is_relative_to(ROOT) else target}")

    if len(keysets) > 1:
        report.append(f"Personer felles for alle filene: {len(set.intersection(*keysets))}")
    (args.ut / "_rapport.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    lines = ["GJENNOMGANG: alle tekstverdier som står igjen i kopiene.",
             "Les lista. Ser du et ekte navn eller noe personlig, legg det på en egen linje i",
             f"{EXTRA_PATH.relative_to(ROOT)} og kjør skriptet på nytt.", ""]
    lines += [f"{count:6}  {text}" for text, count in sorted(review.items(), key=lambda kv: (-kv[1], kv[0]))]
    (args.ut / "_gjennomgang.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    key.save()
    print(f"\nFerdig. Les {(args.ut / '_gjennomgang.txt').relative_to(ROOT) if args.ut.is_relative_to(ROOT) else args.ut} før du deler noe.")
    print(f"Del aldri {KEY_PATH.relative_to(ROOT)} — den er nøkkelen tilbake til ekte navn.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

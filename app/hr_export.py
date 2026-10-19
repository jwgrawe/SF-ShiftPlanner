"""Reading the HR system's roster exports by their structure (D85, D90).

Two formats, both specified cell by cell in docs/source-data-findings.md §5:

- **Plan** (`Utskrift_fleksiplan_<stamp>.csv`, the turnus): one row per person
  per position, one column per day for a whole plan year.
- **Ajourhold** (`Ukeplan_<stamp>.csv`, the week plan): one row per person
  with a change or a shift that week, seven day columns.

How a file is read — shape first, words only to confirm:

1. The **day-header row** is found by its shape: a run of cells that all look
   like a weekday plus a date (`Ma 12.01` / `Mandag 31.aug`). Everything is
   located relative to it; nothing depends on fixed rows or row counts.
2. The dates must form one unbroken series whose weekdays match; the year is
   the one that makes that true nearest the export date.
3. The **person block** is every row under the header down to the first blank
   row (Plan) or the first row without a PersonID (Ajourhold). No row in it is
   skipped or judged by its content (D81) — names, codes and titles are data.
4. Every person count is then **cross-checked**: the Plan's summary block
   must repeat the person rows exactly; what follows the Ajourhold's person
   block must be count rows or blank. A blank line inside the person block,
   an extra column, a filtered export — all show up here.
5. Column labels in the header row only tell which meta column is which
   (name, title, PersonID) and form a fingerprint; data values never steer
   the reading.

Anything that makes the reading doubtful raises `Rejected` with every reason,
in Norwegian, saying what was expected and what was found. Things that are
merely surprising are returned as `alerts` and the file is still read.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
from dataclasses import dataclass, field

PLAN_DAY = re.compile(r"^(Ma|Ti|On|To|Fr|Lø|Sø) (\d{2})\.(\d{2})$")
PLAN_WEEKDAYS = ["Ma", "Ti", "On", "To", "Fr", "Lø", "Sø"]
UKE_DAY = re.compile(
    r"^(Mandag|Tirsdag|Onsdag|Torsdag|Fredag|Lørdag|Søndag) (\d{1,2})\."
    r"(jan|feb|mar|apr|mai|jun|jul|aug|sep|okt|nov|des)\.?$", re.I)
UKE_WEEKDAYS = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
MONTHS = ["jan", "feb", "mar", "apr", "mai", "jun", "jul", "aug", "sep", "okt", "nov", "des"]
WEEK_LABEL = re.compile(r"^Uke\s+(\d+)\s*\((\d+)\)$")
UKE_NUMBER = re.compile(r"\bUke:\s*(\d{1,2})\b")
REPORT_DATE = re.compile(r"Rapportdato:\s*(\d{2})\.(\d{2})\.(\d{4})\s+(\d{1,2}):(\d{2})")
FILE_STAMP = re.compile(r"(\d{14})")
TIME = re.compile(r"^\d{1,2}:\d{2}$")
INTEGER = re.compile(r"^-?\d+$")
PERSON_ID = re.compile(r"^\d{1,9}$")

# The unit every export must belong to (D83); overridable in app settings.
DEFAULT_UNIT = "Steril forsyning driftspersonell"


class Rejected(Exception):
    """The file can't be read with confidence. `reasons` says why."""

    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass
class PersonRow:
    row_no: int                    # 1-based line in the file, for messages
    full_name: str
    person_id: str | None
    title: str | None
    cells: dict[dt.date, str]      # export date -> raw cell text (non-empty only)


@dataclass
class Export:
    kind: str                      # 'plan' | 'ajourhold'
    exported_at: dt.datetime
    first_date: dt.date
    last_date: dt.date
    rows: list[PersonRow]
    legend: dict[str, tuple[str, str]] = field(default_factory=dict)
    fingerprint: str = ""
    alerts: list[str] = field(default_factory=list)


# --------------------------------------------------------------- helpers
def col_name(j: int) -> str:
    letters, j = "", j + 1
    while j:
        j, r = divmod(j - 1, 26)
        letters = chr(65 + r) + letters
    return letters


def norm(value: str) -> str:
    return " ".join(value.split())


def norm_label(value: str) -> str:
    return norm(value).lower().replace(".", "")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def decode(raw: bytes) -> str:
    """UTF-8 when the bytes are valid UTF-8 (a BOM is dropped), otherwise
    Windows-1252 — what the HR system writes. Undecodable bytes reject."""
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp1252")
    except UnicodeDecodeError as exc:
        raise Rejected([f"Filen har tegn som verken er UTF-8 eller Windows-1252 "
                        f"(byte {exc.start})."]) from None


def to_grid(text: str) -> list[list[str]]:
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
    while rows and not any(c.strip() for c in rows[-1]):
        rows.pop()
    if not rows:
        raise Rejected(["Filen er tom."])
    if all(len(r) <= 1 for r in rows):
        raise Rejected(["Filen er ikke semikolonseparert (;) som eksportene fra turnussystemet."])
    widths = {len(r) for r in rows}
    if len(widths) > 1:
        odd = [i + 1 for i, r in enumerate(rows) if len(r) != max(widths)][:5]
        raise Rejected([f"Radene har ulikt antall kolonner ({sorted(widths)}); eksporten har "
                        f"alltid like brede rader. Avvikende rader: {odd}."])
    return rows


def blank(row: list[str]) -> bool:
    return not any(c.strip() for c in row)


def day_runs(grid: list[list[str]], pattern: re.Pattern) -> list[tuple[int, int, int]]:
    """(row, first column, length) of the longest run of day-header cells in
    every row that has a run of 7 or more."""
    found = []
    for i, row in enumerate(grid):
        best = (0, 0)
        j = 0
        while j < len(row):
            if pattern.match(row[j].strip()):
                k = j
                while k < len(row) and pattern.match(row[k].strip()):
                    k += 1
                if k - j > best[1]:
                    best = (j, k - j)
                j = k
            else:
                j += 1
        if best[1] >= 7:
            found.append((i, best[0], best[1]))
    return found


def detect_kind(grid: list[list[str]]) -> str:
    plan = day_runs(grid, PLAN_DAY)
    uke = day_runs(grid, UKE_DAY)
    if len(plan) == 1 and not uke:
        return "plan"
    if len(uke) == 1 and not plan:
        return "ajourhold"
    if not plan and not uke:
        raise Rejected(["Fant ingen rad med dager som kolonneoverskrifter (f.eks. «Ma 12.01» "
                        "eller «Mandag 31.aug») – dette ser ikke ut som en turnus- eller "
                        "ukeplaneksport."])
    raise Rejected([f"Fant {len(plan) + len(uke)} rader med dager som kolonneoverskrifter; "
                    "forventet nøyaktig én."])


def export_time(filename: str, grid: list[list[str]], header_row: int,
                alerts: list[str]) -> dt.datetime:
    """When the file was exported: the stamp in its name, checked against the
    «Rapportdato» in its title block."""
    stamp = None
    m = FILE_STAMP.search(filename)
    if m:
        try:
            stamp = dt.datetime.strptime(m[1], "%Y%m%d%H%M%S")
        except ValueError:
            stamp = None
    report = None
    for row in grid[:header_row]:
        for cell in row:
            r = REPORT_DATE.search(cell)
            if r:
                report = dt.datetime(int(r[3]), int(r[2]), int(r[1]), int(r[4]), int(r[5]))
    if stamp and report and abs(stamp - report) > dt.timedelta(days=1):
        alerts.append(f"Tidspunktet i filnavnet ({stamp:%d.%m.%Y %H:%M}) og «Rapportdato» i "
                      f"filen ({report:%d.%m.%Y %H:%M}) er mer enn ett døgn fra hverandre.")
    if stamp is None and report is None:
        raise Rejected(["Fant ikke når filen ble eksportert – verken et tidsstempel i "
                        "filnavnet (…_ÅÅÅÅMMDDttmmss.csv) eller «Rapportdato» i filen."])
    if stamp is None:
        alerts.append("Filnavnet mangler tidsstempel; bruker «Rapportdato» fra filen.")
    return stamp or report


def infer_dates(parts: list[tuple[int, int, int]], anchor: dt.date, what: str) -> list[dt.date]:
    """parts: (day, month, weekday 0=Monday) per column, no year. Returns the
    unbroken series of dates they describe, in the year nearest `anchor`."""
    d0, m0, _ = parts[0]
    best = None
    for year in range(anchor.year - 2, anchor.year + 3):
        try:
            start = dt.date(year, m0, d0)
        except ValueError:
            continue
        series = [start + dt.timedelta(days=i) for i in range(len(parts))]
        if all((d.day, d.month, d.weekday()) == p for d, p in zip(series, parts)):
            if best is None or abs(start - anchor) < abs(best[0] - anchor):
                best = series
    if best is None:
        raise Rejected([f"Datoene i {what} er ikke en sammenhengende rekke der ukedagene "
                        "stemmer med datoene – kan ikke fastslå årstallet sikkert."])
    return best


def check_unit(grid: list[list[str]], header_row: int, unit: str) -> None:
    text = norm(" ".join(c for row in grid[:header_row] for c in row)).lower()
    if norm(unit).lower() not in text:
        raise Rejected([f"Filen gjelder ikke enheten «{unit}» – eksportert for feil "
                        "organisasjonsenhet? (D83)"])


def meta_columns(header: list[str], first_day: int, wanted: dict[str, tuple[str, ...]],
                 required: set[str]) -> dict[str, int]:
    """Which meta column (left of the days) holds what, from the header labels."""
    labels = [norm_label(c) for c in header[:first_day]]
    found: dict[str, int] = {}
    for key, accepted in wanted.items():
        for j, label in enumerate(labels):
            if label in accepted:
                found[key] = j
                break
    missing = sorted(required - set(found))
    if missing:
        names = {k: wanted[k][0] for k in missing}
        raise Rejected([f"Overskriftsraden mangler kolonnen «{names[k]}»." for k in missing]
                       + [f"Fant: {[norm(c) for c in header[:first_day]]}."])
    return found


# ------------------------------------------------------------------ Plan
PLAN_META = {
    "name": ("person navn", "personnavn", "navn"),
    "title": ("stillingsbetegnelse",),
    "person_id": ("personid", "person id"),
}


def parse_plan(grid: list[list[str]], filename: str, unit: str = DEFAULT_UNIT) -> Export:
    alerts: list[str] = []
    (header_row, first_day, n_days), = day_runs(grid, PLAN_DAY)
    header = grid[header_row]
    width = len(header)
    if first_day + n_days != width:
        raise Rejected([f"Dagkolonnene slutter i kolonne {col_name(first_day + n_days - 1)}, "
                        f"men raden fortsetter til {col_name(width - 1)} – uventet oppsett."])
    if n_days % 7:
        raise Rejected([f"Turnusen har {n_days} dager – forventet hele uker."])
    check_unit(grid, header_row, unit)
    exported_at = export_time(filename, grid, header_row, alerts)

    parts = []
    for cell in header[first_day:]:
        m = PLAN_DAY.match(cell.strip())
        parts.append((int(m[2]), int(m[3]), PLAN_WEEKDAYS.index(m[1])))
    dates = infer_dates(parts, exported_at.date(), "turnusens kolonneoverskrifter")
    if dates[0].weekday() != 0:
        raise Rejected([f"Turnusen starter {dates[0]:%d.%m.%Y}, som ikke er en mandag."])

    # The week-label row right above the dates: «Uke  1 (3)» every 7th column,
    # the bracket being the ISO week — a second, independent date check.
    reasons = []
    if header_row == 0:
        reasons.append("Fant ikke ukeraden over dagkolonnene.")
    else:
        week_row = grid[header_row - 1]
        for k in range(n_days // 7):
            cell = week_row[first_day + 7 * k].strip()
            m = WEEK_LABEL.match(cell)
            iso = dates[7 * k].isocalendar().week
            if not m:
                reasons.append(f"Ukeraden har «{cell}» i {col_name(first_day + 7 * k)}"
                               f"{header_row}, forventet «Uke N ({iso})».")
                break
            if int(m[2]) != iso:
                reasons.append(f"Ukeraden sier uke {m[2]} i {col_name(first_day + 7 * k)}"
                               f"{header_row}, men {dates[7 * k]:%d.%m.%Y} er i uke {iso}.")
                break
    if reasons:
        raise Rejected(reasons)

    cols = meta_columns(header, first_day, PLAN_META, {"name", "title"})

    # Person block: everything under the header down to the first blank row.
    rows: list[PersonRow] = []
    i = header_row + 1
    while i < len(grid) and not blank(grid[i]):
        row = grid[i]
        name = norm(row[cols["name"]])
        if not name:
            reasons.append(f"Rad {i + 1} i personblokken mangler navn.")
        person_id = norm(row[cols["person_id"]]) if "person_id" in cols else None
        if person_id is not None and person_id and not PERSON_ID.match(person_id):
            reasons.append(f"Rad {i + 1}: PersonID «{person_id}» er ikke et tall.")
        cells = {dates[k]: norm(c) for k, c in enumerate(row[first_day:]) if c.strip()}
        rows.append(PersonRow(i + 1, name, person_id or None, norm(row[cols["title"]]) or None,
                              cells))
        i += 1
    if not rows:
        reasons.append("Fant ingen personrader under dagkolonnene.")
    if reasons:
        raise Rejected(reasons)

    # What follows: blocks separated by blank rows. The last must be the
    # summary that repeats every person row's meta columns (its header sits
    # one column to the right) — proof the person block was read whole.
    blocks: list[list[tuple[int, list[str]]]] = []
    current: list[tuple[int, list[str]]] = []
    for k in range(i, len(grid)):
        if blank(grid[k]):
            if current:
                blocks.append(current)
                current = []
        else:
            current.append((k, grid[k]))
    if current:
        blocks.append(current)

    person_meta = [[norm(c) for c in grid[r.row_no - 1][:first_day]] for r in rows]
    summary = None
    if blocks:
        last = blocks[-1]
        summary_meta = [[norm(c) for c in row[:first_day]] for _, row in last[1:]]
        if summary_meta == person_meta:
            summary = last
    if summary is None:
        raise Rejected([
            "Oppsummeringen nederst i turnusen gjentar ikke personradene nøyaktig "
            f"({len(rows)} personrader lest). Det kan bety en tom linje midt i personlisten, "
            "en endret eksport, eller at filen er redigert."])

    legend: dict[str, tuple[str, str]] = {}
    for block in blocks[:-1]:
        if any(TIME.match(row[1].strip()) and TIME.match(row[2].strip())
               for _, row in block if len(row) > 2):
            legend.update(_legend(block))
        elif all(_is_count_row(row, first_day) for _, row in block):
            continue
        else:
            alerts.append(f"Ukjent blokk fra rad {block[0][0] + 1} – hoppet over.")
    if not legend:
        alerts.append("Fant ikke vaktkodeforklaringen (Kode/Fra/Til) i turnusen.")

    return Export("plan", exported_at, dates[0], dates[-1], rows, legend,
                  fingerprint=" | ".join(norm(c) for c in header[:first_day]), alerts=alerts)


def _is_count_row(row: list[str], first_day: int) -> bool:
    return all(not c.strip() or INTEGER.match(c.strip()) for c in row[first_day:]) and \
        any(c.strip() for c in row[:first_day])


def _legend(block) -> dict[str, tuple[str, str]]:
    """Code -> (first start, last end) over its segments (breaks included)."""
    legend: dict[str, list[str]] = {}
    current = None
    for _, row in block:
        code, start, end = row[0].strip(), row[1].strip(), row[2].strip()
        if not (TIME.match(start) and TIME.match(end)):
            continue
        if code:
            current = code
            legend[current] = [start, end]
        elif current:
            legend[current][1] = end
    return {code: (span[0].zfill(5), span[1].zfill(5)) for code, span in legend.items()}


# ------------------------------------------------------------- Ajourhold
UKE_META = {
    "person_id": ("personid", "person id"),
    "name": ("navn", "person navn", "personnavn"),
}


def parse_ukeplan(grid: list[list[str]], filename: str, unit: str = DEFAULT_UNIT) -> Export:
    alerts: list[str] = []
    (header_row, first_day, n_days), = day_runs(grid, UKE_DAY)
    header = grid[header_row]
    if n_days != 7:
        raise Rejected([f"Ukeplanen har {n_days} dagkolonner – forventet 7 (mandag–søndag)."])
    check_unit(grid, header_row, unit)
    exported_at = export_time(filename, grid, header_row, alerts)

    parts = []
    for k, cell in enumerate(header[first_day:first_day + 7]):
        m = UKE_DAY.match(cell.strip())
        weekday = UKE_WEEKDAYS.index(m[1].lower())
        if weekday != k:
            raise Rejected([f"Dagkolonnene går ikke mandag–søndag (fant «{cell.strip()}» "
                            f"som dag {k + 1})."])
        parts.append((int(m[2]), MONTHS.index(m[3].lower()) + 1, weekday))
    dates = infer_dates(parts, exported_at.date(), "ukeplanens kolonneoverskrifter")

    week_numbers = {int(m[1]) for row in grid[:header_row] for c in row
                    if (m := UKE_NUMBER.search(c))}
    iso = dates[0].isocalendar().week
    if week_numbers and week_numbers != {iso}:
        raise Rejected([f"Filen sier «Uke: {', '.join(map(str, sorted(week_numbers)))}», men "
                        f"{dates[0]:%d.%m.%Y} er i uke {iso}."])
    if not week_numbers:
        alerts.append("Fant ikke «Uke: NN» øverst i ukeplanen.")

    cols = meta_columns(header, first_day, UKE_META, {"person_id", "name"})

    rows: list[PersonRow] = []
    reasons: list[str] = []
    i = header_row + 1
    while i < len(grid) and grid[i][cols["person_id"]].strip():
        row = grid[i]
        person_id = row[cols["person_id"]].strip()
        name = norm(row[cols["name"]])
        if not PERSON_ID.match(person_id):
            reasons.append(f"Rad {i + 1}: PersonID «{person_id}» er ikke et tall.")
        if not name:
            reasons.append(f"Rad {i + 1}: PersonID {person_id} mangler navn.")
        cells = {dates[k]: norm(c) for k, c in enumerate(row[first_day:first_day + 7])
                 if c.strip()}
        rows.append(PersonRow(i + 1, name, person_id, None, cells))
        i += 1
    if not rows:
        reasons.append("Fant ingen personrader (med PersonID) under dagkolonnene.")
    # After the person block: only blank rows and the Dag/Kveld/Natt counts.
    # Anything else is a person row we'd otherwise silently miss.
    for k in range(i, len(grid)):
        row = grid[k]
        if blank(row) or _is_count_row(row, first_day):
            continue
        reasons.append(f"Rad {k + 1} etter personlisten ser ut som en person uten PersonID "
                       f"(«{norm(row[cols['name']])}»).")
        break
    if reasons:
        raise Rejected(reasons)
    return Export("ajourhold", exported_at, dates[0], dates[-1], rows,
                  fingerprint=" | ".join(norm(c) for c in header[:first_day]), alerts=alerts)


# ------------------------------------------------------------------ entry
def read(raw: bytes, filename: str, unit: str = DEFAULT_UNIT) -> Export:
    """Parse an export of either kind. Raises Rejected."""
    grid = to_grid(decode(raw))
    kind = detect_kind(grid)
    lowered = filename.lower()
    named = ("plan" if lowered.startswith("utskrift_fleksiplan")
             else "ajourhold" if lowered.startswith("ukeplan") else None)
    if named and named != kind:
        raise Rejected([f"Filnavnet sier {'turnus' if named == 'plan' else 'ukeplan'}, men "
                        f"innholdet er en {'turnus' if kind == 'plan' else 'ukeplan'}."])
    export = parse_plan(grid, filename, unit) if kind == "plan" else \
        parse_ukeplan(grid, filename, unit)
    if named is None:
        export.alerts.append("Filnavnet følger ikke mønsteret Utskrift_fleksiplan_… / "
                             "Ukeplan_…; typen er gjenkjent fra innholdet.")
    return export

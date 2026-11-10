"""Synthetic HR exports in exactly the real format (docs/source-data-findings.md §5).

Invented people and patterns only — the real (even anonymised) exports never
enter the repository (D78). Every structural feature the parser relies on is
reproduced: title block, week-label row, header row, person block, count
rows, legend with break segments, and the summary block with its header
shifted one column right.
"""
from __future__ import annotations

import datetime as dt

UNIT = "Steril forsyning driftspersonell"
PLAN_DAYS = ["Ma", "Ti", "On", "To", "Fr", "Lø", "Sø"]
UKE_DAYS = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]
MONTHS = ["jan", "feb", "mar", "apr", "mai", "jun", "jul", "aug", "sep", "okt", "nov", "des"]
STATS = ["37", "35,5", "0", "0", "1846", "1"]
META = ["PersonID", "Person navn", "Stillingsbetegnelse", "Sum uke", "Snitt pr. uke", "Diff person snitt",
        "Total person differanse", "Sum arb. timer", "Beregnet st.andel"]

LEGEND = [
    ("A", "14:00", "22:00", "1", "Aktiv"),
    ("D", "07:00", "11:00", "1", "Aktiv"), ("", "11:00", "11:30", "0", "Pause ikke bet."),
    ("", "11:30", "15:00", "1", "Aktiv"),
    ("D2", "08:00", "11:00", "1", "Aktiv"), ("", "11:00", "11:30", "0", "Pause ikke bet."),
    ("", "11:30", "15:00", "1", "Aktiv"),
    ("DK", "07:00", "15:00", "1", "Aktiv"),
    ("N", "22:00", "07:00", "1", "Aktiv"),
    ("D3", "09:00", "13:30", "1", "Aktiv"),
    ("D2*", "08:00", "15:30", "1", "Aktiv"),
]


def _encode(rows: list[list[str]], width: int) -> bytes:
    lines = [";".join(r + [""] * (width - len(r))) for r in rows]
    return "\r\n".join(lines).encode("cp1252")


def person_id(name: str) -> str:
    """A stable invented PersonID per name (the same in turnus and ukeplan)."""
    return KNOWN_IDS.get(name) or str(5000 + sum(ord(c) for c in name) % 4000)


KNOWN_IDS = {"Hansen Kari": "1001", "Olsen Tor": "1002", "Berg Anne": "1003", "Dahl Per": "1004",
             "Nilsen Ola": "1005", "Vik Siri": "1006"}


def plan_csv(people, start: dt.date, weeks: int, exported: dt.datetime, unit: str = UNIT,
             legend=LEGEND, blank_inside: bool = False, week_shift: int = 0,
             extra_column: bool = False, with_ids: bool = True, ids: dict | None = None,
             missing_id_for: str | None = None) -> bytes:
    """people: [(full name, title, {date: code}[, PersonID])]. Since November 2026 the
    turnus carries PersonID in front of the name, here and in the summary."""
    days = [start + dt.timedelta(days=i) for i in range(weeks * 7)]
    meta = (META if with_ids else META[1:]) + (["Ekstra"] if extra_column else [])
    first = len(meta)
    width = first + len(days)
    rows = [
        ["St. Olavs hospital HF              ", "", "Ressursstyring"],
        [f"Bem.pl/Hoved.pl: {start.year} / {start.year}", "Utskrift fleksiplan",
         f"Orgenhet: STS,{unit}"],
        [],
        ["Saksbehandler", f"Rapportdato: {exported:%d.%m.%Y %H:%M}", "Ressursstyring-Planlegger"],
        ["TOVES-ST Test Testesen", "Utskrift fleksiplan"],
        [],
    ]
    week_row = [""] * width
    for k in range(weeks):
        week_row[first + 7 * k] = f"Uke  {k + 1} ({days[7 * k].isocalendar().week + week_shift})"
    rows.append(week_row)
    rows.append(meta + [f"{PLAN_DAYS[d.weekday()]} {d:%d.%m}" for d in days])
    person_rows = []
    for index, entry in enumerate(people):
        name, title, cells = entry[:3]
        pid = entry[3] if len(entry) > 3 else (ids or {}).get(name) or person_id(name)
        row = ([("" if name == missing_id_for else pid)] if with_ids else []) + [name, title]
        row += STATS + (["x"] if extra_column else [])
        row += [cells.get(d, "") for d in days]
        person_rows.append(row)
        if blank_inside and index == len(people) // 2:
            rows.append([])
        rows.append(row)
    rows.append([])
    for label, codes in (("D", ("D", "D2", "DK", "D3")), ("A", ("A",)), ("N", ("N",))):
        counts = [str(sum(1 for p in people if p[2].get(d) in codes)) for d in days]
        rows.append([""] * (first - 1) + [label] + counts)
    rows.append([])
    rows.append(["Kode", "Fra", "Til", "Faktor", "Aktivitet"])
    rows += [list(r) for r in legend]
    rows.append([])
    rows.append([""] + meta)
    rows += [r[:first] for r in person_rows]
    return _encode(rows, width)


def plan_name(exported: dt.datetime) -> str:
    return f"Utskrift_fleksiplan_{exported:%Y%m%d%H%M%S}.csv"


def ukeplan_csv(people, monday: dt.date, exported: dt.datetime, unit: str = UNIT,
                orphan_row: bool = False) -> bytes:
    """people: [(PersonID, full name, {date: raw})]. Codes get the trailing
    space the real export writes."""
    days = [monday + dt.timedelta(days=i) for i in range(7)]
    width = 10
    rows = [
        ["St. Olavs hospital HF", "", "Ressursstyring"],
        [f"STS - {unit}", "Ukeplan", f"Uke: {monday.isocalendar().week}"],
        [],
        ["Saksbehandler", f"Rapportdato: {exported:%d.%m.%Y %H:%M}", "Ressursstyring"],
        ["TOVES-ST Test Testesen", "Ukeplan"],
        ["", f"St. Olavs hospital HF  STS - {unit}"],
        [],
        ["Gruppe", "PersonID", "Navn"]
        + [f"{UKE_DAYS[d.weekday()]} {d.day:02d}.{MONTHS[d.month - 1]}" for d in days],
    ]
    for pid, name, cells in people:
        rows.append(["", pid, name] + [f"{cells[d]} " if d in cells else "" for d in days])
    if orphan_row:
        rows.append(["", "", "Uten Id Person"] + ["D "] + [""] * 6)
    for label in ("Dag", "Kveld", "Natt"):
        rows.append(["", "", label] + ["3"] * 7)
    return _encode(rows, width)


def ukeplan_name(exported: dt.datetime) -> str:
    return f"Ukeplan_{exported:%Y%m%d%H%M%S}.csv"

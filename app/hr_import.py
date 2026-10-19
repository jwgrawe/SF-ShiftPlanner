"""The roster import pipeline (real mode, D84–D95).

    data/import/  ──scan──▶  hr_export.read()  ──▶  import_files / _rows / _cells
         │                       │ Rejected                    │
         ▼                       ▼                             ▼
    arkiv/ (raw kept         avvist/ (+ .txt with       rebuild(): the effective
    until superseded)        the reasons)               roster + findings

`refresh()` is called on page loads (at most every 30 s) and by the
«Se etter nye filer nå» button, so new files dropped into data/import/ are
picked up without anyone running anything (D91).

`rebuild()` derives everything from the stored files, so it can run any time:

1. **Supersession** – of several ukeplans for one week only the newest counts;
   a turnus is superseded where newer turnuses cover all its remaining days.
2. **Identity** (D82) – people are matched by their full name as exported;
   PersonIDs from the ukeplan are attached; every ambiguity is a finding.
3. **Precedence** (D73/D93) – per person and export date: the newest ukeplan
   for that week if it lists the person (a blank day = not working), else
   the newest turnus covering the date (blank = no shift).
4. **Interpretation** – `M` (overtime) is ignored, `*` (paid lunch) is
   ignored, `/F3` ends the shift at 12:00, a night code moves to the evening
   it starts (D92). Anything else uncertain is held, not guessed (D86).
5. **Title rules** (D87) – a title marked «aldri», or one nobody has
   classified yet, keeps the day out of placement.
6. **Plans** – people no longer on duty are taken out of today's and future
   plans, and the change is logged.
"""
from __future__ import annotations

import datetime as dt
import io
import shutil
import sqlite3
import threading
import time
from collections import defaultdict
from pathlib import Path

from app import db, domain, hr_export, planner
from app.hr_export import Rejected, norm

INBOX = db.DATA_DIR / "import"
ARCHIVE_DIRNAME, REJECTED_DIRNAME = "arkiv", "avvist"
DEFAULT_RETENTION_DAYS = 92
SCAN_INTERVAL_SECONDS = 30
LOOKAHEAD_DAYS = 28
HEADCOUNT_CHANGE_WARN = 0.15

_lock = threading.Lock()
_last_scan = 0.0
_last_purge: dt.date | None = None
last_error: str | None = None   # shown on «Datagrunnlag» if a rebuild failed


# ------------------------------------------------------------------ util
def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _setting(conn: sqlite3.Connection, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def retention_days(conn: sqlite3.Connection) -> int:
    try:
        return max(14, int(_setting(conn, "retention_days", str(DEFAULT_RETENTION_DAYS))))
    except ValueError:
        return DEFAULT_RETENTION_DAYS


def log(conn: sqlite3.Connection, text: str) -> None:
    conn.execute("INSERT INTO import_log (at, text) VALUES (?, ?)", (_now(), text))


def _move(path: Path, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / path.name
    n = 2
    while target.exists():
        target = folder / f"{path.stem} ({n}){path.suffix}"
        n += 1
    shutil.move(str(path), str(target))
    return target


def _unlink(stored: str | None) -> None:
    if stored:
        try:
            Path(stored).unlink()
        except OSError:
            pass


def kind_label(kind: str) -> str:
    return {"plan": "turnus", "ajourhold": "ukeplan", "kompetanse": "kompetansefil"}.get(kind, kind)


# ------------------------------------------------------------ intake
def store_export(conn: sqlite3.Connection, export: hr_export.Export, filename: str,
                 digest: str, stored_path: str | None) -> int:
    cursor = conn.execute(
        """INSERT INTO import_files (kind, filename, sha256, exported_at, first_date, last_date,
               imported_at, status, reason, person_count, fingerprint, stored_path)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
        (export.kind, filename, digest, export.exported_at.isoformat(timespec="seconds"),
         export.first_date.isoformat(), export.last_date.isoformat(), _now(),
         "\n".join(export.alerts) or None, len(export.rows), export.fingerprint, stored_path))
    file_id = cursor.lastrowid
    for row in export.rows:
        dates = sorted(row.cells)
        conn.execute(
            """INSERT INTO import_rows (file_id, row_no, full_name, person_id, title,
                   first_date, last_date) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (file_id, row.row_no, row.full_name, row.person_id, row.title,
             dates[0].isoformat() if dates else None, dates[-1].isoformat() if dates else None))
        conn.executemany(
            "INSERT INTO import_cells (file_id, row_no, export_date, raw) VALUES (?, ?, ?, ?)",
            [(file_id, row.row_no, d.isoformat(), raw) for d, raw in row.cells.items()])
    conn.executemany(
        "INSERT INTO import_legend (file_id, code, start, end) VALUES (?, ?, ?, ?)",
        [(file_id, code, start, end) for code, (start, end) in export.legend.items()])
    return file_id


def parse_competency_workbook(conn: sqlite3.Connection, raw: bytes
                              ) -> tuple[list[tuple[str, str, str]], list[str]]:
    """The competency matrix (same layout as data/source/Kompetanse_*.xlsx),
    with each person named exactly as in the exports (Q40/D82)."""
    from openpyxl import load_workbook

    try:
        ws = load_workbook(io.BytesIO(raw), data_only=True, read_only=True).worksheets[0]
    except Exception as exc:  # noqa: BLE001 - any unreadable workbook
        raise Rejected([f"Regnearket kan ikke åpnes ({exc.__class__.__name__})."]) from None
    mapping: dict[str, list[str]] = defaultdict(list)
    for row in conn.execute("SELECT competency_id, source_column FROM competency_types"):
        if row["source_column"]:
            mapping[norm(row["source_column"]).lower()].append(row["competency_id"])
    rows = [[("" if c is None else str(c)) for c in r] for r in ws.iter_rows(values_only=True)]
    header_index = next(
        (i for i, r in enumerate(rows[:15])
         if sum(1 for c in r[1:] if norm(c).lower() in mapping) >= 3), None)
    if header_index is None:
        raise Rejected(["Fant ingen overskriftsrad med kompetansene som kolonner – er dette "
                        "kompetansefilen?"])
    header = [norm(c) for c in rows[header_index]]
    unknown = [h for h in header[1:] if h and h.lower() not in mapping]
    if unknown:
        raise Rejected([f"Ukjente kompetansekolonner: {unknown}. Legg dem til i "
                        "competency_types.csv (source_column) først."])
    result, notes = [], []
    for r in rows[header_index + 1:]:
        name = norm(r[0]) if r else ""
        if not name:
            continue
        for value, label in zip(r[1:], header[1:]):
            mark = value.strip().lower()
            if not label or not mark:
                continue
            status = {"x": "qualified", "?": "uncertain"}.get(mark)
            if status is None:
                notes.append(f"{name} / {label}: merket «{mark}» ignoreres")
                continue
            for competency_id in mapping[label.lower()]:
                result.append((name, competency_id, status))
    if not result:
        raise Rejected(["Kompetansefilen har ingen avkryssede kompetanser."])
    return result, notes


def process_file(conn: sqlite3.Connection, path: Path, unit: str) -> str:
    """Import one file from the inbox and move it out of the inbox."""
    raw = path.read_bytes()
    digest = hr_export.sha256(raw)
    known = conn.execute(
        "SELECT status FROM import_files WHERE sha256 = ? ORDER BY file_id DESC", (digest,)
    ).fetchone()
    inbox = path.parent
    if known:
        folder = REJECTED_DIRNAME if known["status"] == "rejected" else ARCHIVE_DIRNAME
        if folder == ARCHIVE_DIRNAME:
            path.unlink()
        else:
            _move(path, inbox / folder)
        message = f"{path.name}: samme fil er allerede behandlet – ignorert."
        log(conn, message)
        return message

    try:
        if path.suffix.lower() == ".xlsx":
            competencies, notes = parse_competency_workbook(conn, raw)
            stored = _move(path, inbox / ARCHIVE_DIRNAME)
            conn.execute("UPDATE import_files SET status = 'superseded' "
                         "WHERE kind = 'kompetanse' AND status = 'active'")
            conn.execute("DELETE FROM competency_rows")
            conn.executemany("INSERT OR REPLACE INTO competency_rows VALUES (?, ?, ?)",
                             competencies)
            people = len({name for name, _, _ in competencies})
            conn.execute(
                """INSERT INTO import_files (kind, filename, sha256, imported_at, status, reason,
                       person_count, stored_path) VALUES ('kompetanse', ?, ?, ?, 'active', ?, ?, ?)""",
                (path.name, digest, _now(), "\n".join(notes[:20]) or None, people, str(stored)))
            message = f"{path.name}: kompetansefil importert ({people} personer)."
        else:
            try:
                export = hr_export.read(raw, path.name, unit)
            except Rejected:
                raise
            except Exception as exc:  # noqa: BLE001 - a reader bug must refuse, never misread
                raise Rejected([f"Uventet feil under lesing ({exc.__class__.__name__}: {exc}). "
                                "Filen er ikke importert – meld fra til den som drifter appen."]
                               ) from None
            stored = _move(path, inbox / ARCHIVE_DIRNAME)
            store_export(conn, export, path.name, digest, str(stored))
            message = (f"{path.name}: {kind_label(export.kind)} "
                       f"{export.first_date:%d.%m.%Y}–{export.last_date:%d.%m.%Y} importert "
                       f"({len(export.rows)} rader).")
    except Rejected as exc:
        stored = _move(path, inbox / REJECTED_DIRNAME)
        stored.with_name(stored.name + ".txt").write_text(
            "Filen ble avvist og er IKKE importert:\n\n" + "\n".join(f"- {r}" for r in exc.reasons)
            + "\n\nRett eksporten og legg den nye filen i data/import/.\n", encoding="utf-8")
        conn.execute(
            """INSERT INTO import_files (kind, filename, sha256, imported_at, status, reason,
                   stored_path) VALUES ('ukjent', ?, ?, ?, 'rejected', ?, ?)""",
            (path.name, digest, _now(), "\n".join(exc.reasons), str(stored)))
        message = f"{path.name}: AVVIST – {exc.reasons[0]}"
    log(conn, message)
    return message


def inbox_files(inbox: Path) -> list[Path]:
    if not inbox.exists():
        return []
    ready = time.time() - 2  # skip files still being copied in
    return sorted(
        p for p in inbox.iterdir()
        if p.is_file() and p.suffix.lower() in (".csv", ".xlsx")
        and not p.name.startswith(("~$", ".")) and p.stat().st_mtime < ready)


def scan_inbox(conn: sqlite3.Connection, inbox: Path | None = None) -> list[str]:
    inbox = inbox or INBOX
    unit = _setting(conn, "expected_unit", hr_export.DEFAULT_UNIT)
    messages = []
    for path in inbox_files(inbox):
        with conn:
            messages.append(process_file(conn, path, unit))
    return messages


# ---------------------------------------------------------- the rebuild
def interpret(raw: str) -> tuple[str | None, str | None, str | None]:
    """Raw cell -> (code, end override, problem). Only what is confirmed is
    applied (D86/D92); everything else comes back as a problem."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    parts = [p for p in parts if p.upper() != "M"]          # overtime (Q34)
    if not parts:
        return None, None, "bare overtid (M) registrert – vakttid ukjent"
    if len(parts) > 1:
        return None, None, f"flere koder samme dag («{raw}»)"
    base, _, modifier = parts[0].partition("/")
    base = base.strip().rstrip("*").strip()                  # paid lunch (Q37)
    end_override = None
    if modifier:
        if modifier.strip().upper() == "F3":                 # ends 12:00 (Q36)
            end_override = "12:00"
        else:
            return None, None, f"ukjent tillegg «/{modifier.strip()}»"
    return base, end_override, None


def suggest_category(start: str, end: str) -> str:
    """Advisory category for a code learned from a legend (D59)."""
    s = domain.parse_time(start)
    e = domain.parse_time(end)
    minutes = s.hour * 60 + s.minute
    if (e.hour * 60 + e.minute) <= minutes or minutes >= 21 * 60:
        return "nattevakt"
    if minutes < 12 * 60:
        return "tidligvakt"
    if minutes < 13 * 60:
        return "mellomvakt"
    return "senvakt"


def _supersede(conn: sqlite3.Connection, cutoff: dt.date) -> None:
    def retire(row) -> None:
        conn.execute("UPDATE import_files SET status = 'superseded' WHERE file_id = ?",
                     (row["file_id"],))
        conn.execute("DELETE FROM import_cells WHERE file_id = ?", (row["file_id"],))
        _unlink(row["stored_path"])
        log(conn, f"{row['filename']}: erstattet av nyere {kind_label(row['kind'])} – "
                  "rådata slettet.")

    weeks: dict[str, list] = defaultdict(list)
    for row in conn.execute("SELECT * FROM import_files WHERE kind = 'ajourhold' AND status = "
                            "'active' ORDER BY exported_at DESC, file_id DESC"):
        weeks[row["first_date"]].append(row)
    for rows in weeks.values():
        for row in rows[1:]:
            retire(row)

    plans = list(conn.execute("SELECT * FROM import_files WHERE kind = 'plan' AND status = "
                              "'active' ORDER BY exported_at DESC, file_id DESC"))
    for index, row in enumerate(plans):
        newer = plans[:index]
        start = max(dt.date.fromisoformat(row["first_date"]), cutoff)
        last = dt.date.fromisoformat(row["last_date"])
        if not newer or start > last:
            continue
        day = start
        covered = True
        while day <= last:
            if not any(n["first_date"] <= day.isoformat() <= n["last_date"] for n in newer):
                covered = False
                break
            day += dt.timedelta(days=1)
        if covered:
            retire(row)


class Rebuild:
    """One pass from stored files to roster, competencies and findings."""

    def __init__(self, conn: sqlite3.Connection, today: dt.date):
        self.conn, self.today = conn, today
        self.findings: list[tuple[str, str, str, str | None]] = []

    def find(self, level: str, kind: str, text: str, date: dt.date | None = None) -> None:
        self.findings.append((level, kind, text, date.isoformat() if date else None))

    # -- identity (D82) ------------------------------------------------
    def identities(self, files) -> dict[tuple[int, int], str | None]:
        conn = self.conn
        employees = {r["employee_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM employees WHERE origin = 'import'")}
        by_pid = {e["person_id"]: eid for eid, e in employees.items() if e["person_id"]}
        by_name: dict[str, list[str]] = defaultdict(list)
        for eid, e in employees.items():
            by_name[e["full_name"]].append(eid)
        counter = [max([int(e[1:]) for e in employees if e[1:].isdigit()] or [0])]

        def create(name: str, pid: str | None) -> str:
            counter[0] += 1
            eid = f"A{counter[0]:04d}"
            conn.execute(
                """INSERT INTO employees (employee_id, source_label, first_name, last_name,
                       display_name, works_at, full_name, person_id, origin)
                   VALUES (?, NULL, NULL, NULL, ?, 'sf', ?, ?, 'import')""",
                (eid, name, name, pid))
            employees[eid] = {"employee_id": eid, "full_name": name, "person_id": pid}
            by_name[name].append(eid)
            if pid:
                by_pid[pid] = eid
            return eid

        pid_names: dict[str, set[str]] = defaultdict(set)
        name_pids: dict[str, set[str]] = defaultdict(set)
        mapping: dict[tuple[int, int], str | None] = {}
        # Ukeplans first (newest first) so PersonIDs attach before names are used.
        ordered = ([f for f in files if f["kind"] == "ajourhold"][::-1]
                   + [f for f in files if f["kind"] == "plan"][::-1])
        for f in ordered:
            for r in conn.execute("SELECT * FROM import_rows WHERE file_id = ?", (f["file_id"],)):
                name, pid = r["full_name"], r["person_id"]
                key = (f["file_id"], r["row_no"])
                if pid:
                    pid_names[pid].add(name)
                    name_pids[name].add(pid)
                    eid = by_pid.get(pid)
                    if eid is None:
                        unlinked = [e for e in by_name.get(name, [])
                                    if not employees[e]["person_id"]]
                        if len(unlinked) == 1:
                            eid = unlinked[0]
                            employees[eid]["person_id"] = pid
                            by_pid[pid] = eid
                            conn.execute("UPDATE employees SET person_id = ? WHERE employee_id = ?",
                                         (pid, eid))
                        else:
                            eid = create(name, pid)
                    mapping[key] = eid
                else:
                    candidates = by_name.get(name, [])
                    if len(candidates) == 1:
                        mapping[key] = candidates[0]
                    elif not candidates:
                        mapping[key] = create(name, None)
                    else:
                        mapping[key] = None
        for pid, names in pid_names.items():
            if len(names) > 1:
                self.find("alert", "identitet",
                          f"PersonID {pid} har ulike navn i filene: {', '.join(sorted(names))}. "
                          "Sjekk om det er en navneendring – turnusrader med det gamle navnet "
                          "knyttes ikke til personen.")
        for name, pids in name_pids.items():
            if len(pids) > 1:
                self.find("alert", "identitet",
                          f"Navnet «{name}» har flere PersonID-er ({', '.join(sorted(pids))}). "
                          "Turnusrader med dette navnet kan ikke knyttes sikkert og holdes "
                          "utenfor planen.")
        return mapping

    # -- learned codes and legend drift ----------------------------------
    def legends(self, plan_files) -> None:
        conn = self.conn
        learned = {r["code"] for r in conn.execute("SELECT code FROM learned_shift_codes")}
        seed = {r["code"]: r for r in conn.execute("SELECT * FROM shift_codes")
                if r["code"] not in learned}
        for f in plan_files[:1]:  # the newest turnus describes the codes in use
            for row in conn.execute("SELECT * FROM import_legend WHERE file_id = ?",
                                    (f["file_id"],)):
                code = row["code"]
                if code.endswith("*"):
                    continue  # paid-lunch variant, same shift (Q37)
                if code in seed:
                    if (seed[code]["start"], seed[code]["end"]) != (row["start"], row["end"]):
                        self.find("warn", "vaktkode",
                                  f"Vaktkoden {code} er {row['start']}–{row['end']} i turnusen, men "
                                  f"{seed[code]['start']}–{seed[code]['end']} i appen "
                                  "(data/seed/shift_codes.csv).")
                    continue
                if code not in learned:
                    crosses = "yes" if row["end"] <= row["start"] else "no"
                    s, e = domain.parse_time(row["start"]), domain.parse_time(row["end"])
                    hours = ((e.hour * 60 + e.minute) - (s.hour * 60 + s.minute)) % (24 * 60) / 60
                    conn.execute(
                        """INSERT INTO learned_shift_codes (code, start, end, crosses_midnight,
                               category, utpost_code, duration_hours, confirmed, learned_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                        (code, row["start"], row["end"], crosses,
                         suggest_category(row["start"], row["end"]),
                         "yes" if code.upper().startswith("U") else "no", hours, _now()))
                    log(conn, f"Ny vaktkode {code} ({row['start']}–{row['end']}) lært fra turnusen.")
        db.merge_learned_codes(conn)
        for row in conn.execute("SELECT * FROM learned_shift_codes WHERE confirmed = 0"):
            self.find("info", "vaktkode",
                      f"Ny vaktkode {row['code']} ({row['start']}–{row['end']}) er tatt i bruk som "
                      f"{row['category']}{' (utpost)' if row['utpost_code'] == 'yes' else ''} – "
                      "bekreft eller endre under Administrasjon → Vaktkoder.")

    # -- the roster -------------------------------------------------------
    def roster(self, plans, weeks, mapping, cutoff: dt.date) -> None:
        conn = self.conn
        codes = {r["code"]: r for r in conn.execute("SELECT * FROM shift_codes")}
        rules = {r["title"]: r["rule"] for r in conn.execute("SELECT title, rule FROM positions")}

        def plan_for(day: str):
            for f in plans:
                if f["first_date"] <= day <= f["last_date"]:
                    return f
            return None

        rows = {}
        cells: dict[tuple[int, int], dict[str, str]] = defaultdict(dict)
        for f in plans + list(weeks.values()):
            for r in conn.execute("SELECT * FROM import_rows WHERE file_id = ?", (f["file_id"],)):
                rows[(f["file_id"], r["row_no"])] = r
            for c in conn.execute("SELECT * FROM import_cells WHERE file_id = ? AND export_date >= ?",
                                  (f["file_id"], cutoff.isoformat())):
                cells[(f["file_id"], c["row_no"])][c["export_date"]] = c["raw"]

        # Titles new to the app wait for an admin (D87): «uavklart».
        for (file_id, _), r in rows.items():
            if r["title"] and r["title"] not in rules:
                conn.execute("INSERT OR IGNORE INTO positions (title, rule, first_seen) "
                             "VALUES (?, 'uavklart', ?)", (r["title"], self.today.isoformat()))
                rules[r["title"]] = "uavklart"
                log(conn, f"Ny stillingsbetegnelse «{r['title']}» – må klassifiseres.")

        # Precedence, in export-date space (before nights are moved).
        effective: dict[tuple[str, str], tuple[str, str, tuple[int, int]]] = {}
        conflicts: set[tuple[str, str]] = set()
        unmatched: dict[str, int] = defaultdict(int)
        for f in plans:
            for key, day_cells in cells.items():
                if key[0] != f["file_id"]:
                    continue
                eid = mapping.get(key)
                for day, raw in day_cells.items():
                    if plan_for(day) is not f:
                        continue
                    if eid is None:
                        unmatched[rows[key]["full_name"]] += 1
                        continue
                    if (eid, day) in effective:
                        conflicts.add((eid, day))
                    effective[(eid, day)] = (raw, "plan", key)
        listed_weeks: dict[str, set[str]] = defaultdict(set)
        for monday, f in weeks.items():
            days = [(dt.date.fromisoformat(monday) + dt.timedelta(days=i)).isoformat()
                    for i in range(7)]
            week_rows = [k for k in rows if k[0] == f["file_id"]]
            listed = {mapping[k] for k in week_rows if mapping.get(k)}
            listed_weeks[monday] = listed
            for eid in listed:  # the ukeplan overrules the turnus for these people
                for day in days:
                    effective.pop((eid, day), None)
                    conflicts.discard((eid, day))
            seen: set[tuple[str, str]] = set()
            for key in week_rows:
                eid = mapping.get(key)
                for day, raw in cells.get(key, {}).items():
                    if (eid, day) in seen:
                        conflicts.add((eid, day))
                    seen.add((eid, day))
                    effective[(eid, day)] = (raw, "ajourhold", key)

        names = {r["employee_id"]: r["display_name"] for r in conn.execute(
            "SELECT employee_id, display_name FROM employees")}
        for monday, listed in listed_weeks.items():
            days = {(dt.date.fromisoformat(monday) + dt.timedelta(days=i)).isoformat()
                    for i in range(7)}
            missing = sorted({names.get(eid, eid) for (eid, day), (_, source, _) in effective.items()
                              if source == "plan" and day in days and eid not in listed})
            if missing:
                week = dt.date.fromisoformat(monday).isocalendar().week
                self.find("warn", "ukeplan",
                          f"Uke {week}: {', '.join(missing)} har vakter i turnusen, men står ikke "
                          "i ukeplanen – turnusen brukes for dem. Sjekk at ukeplanen er komplett.")
        for name, count in sorted(unmatched.items()):
            self.find("alert", "identitet",
                      f"{count} turnusvakter for «{name}» kan ikke knyttes til én person og "
                      "holdes utenfor planen.")

        def title_for(eid: str, day: str, source: str, key) -> tuple[str | None, bool]:
            """(title, ambiguous). A ukeplan has no titles: take the person's
            turnus row active that day (Q41)."""
            if source == "plan":
                return rows[key]["title"], False
            plan = plan_for(day)
            if plan is None:
                return None, False
            mine = [r for k, r in rows.items() if k[0] == plan["file_id"] and mapping.get(k) == eid]
            active = {r["title"] for r in mine
                      if r["first_date"] and r["first_date"] <= day <= r["last_date"]}
            if len(active) > 1:
                return None, True
            if active:
                return active.pop(), False
            titles = {r["title"] for r in mine}
            if len(titles) == 1:
                return titles.pop(), False
            return None, len(titles) > 1

        conn.execute("DELETE FROM roster")
        conn.execute("DELETE FROM roster_pending")
        placed: set[tuple[str, str]] = set()
        pending: list[tuple] = []
        not_in_plan: set[str] = set()
        for (eid, day), (raw, source, key) in sorted(effective.items()):
            if (eid, day) in conflicts:
                pending.append((day, eid, raw, "to rader har vakt samme dag (D80)", source))
                continue
            code, end_override, problem = interpret(raw)
            if problem:
                pending.append((day, eid, raw, problem, source))
                continue
            shift = codes.get(code)
            if shift is None:
                pending.append((day, eid, raw, f"ukjent vaktkode «{code}»", source))
                continue
            if end_override and shift["start"] >= end_override:
                pending.append((day, eid, raw, "F3 på en vakt som starter etter kl. 12", source))
                continue
            date = dt.date.fromisoformat(day)
            if shift["crosses_midnight"] == "yes":
                date -= dt.timedelta(days=1)   # exported on the morning it ends (Q33)
            title, ambiguous = title_for(eid, day, source, key)
            hold = None
            if ambiguous:
                hold = "tvetydig"
            elif title:
                rule = rules.get(title, "uavklart")
                hold = rule if rule in ("aldri", "uavklart") else None
            elif source == "ajourhold":
                not_in_plan.add(eid)
            if (eid, date.isoformat()) in placed:
                pending.append((date.isoformat(), eid, raw, "to vakter samme dag", source))
                continue
            placed.add((eid, date.isoformat()))
            conn.execute(
                """INSERT INTO roster (date, employee_id, shift_code, hold, end_override, title,
                       source, raw) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (date.isoformat(), eid, code, hold, end_override, title, source, raw))
        conn.executemany(
            "INSERT OR REPLACE INTO roster_pending (date, employee_id, raw, reason, source) "
            "VALUES (?, ?, ?, ?, ?)", pending)

        horizon = (self.today + dt.timedelta(days=LOOKAHEAD_DAYS)).isoformat()
        grouped: dict[str, list[str]] = defaultdict(list)
        for day, eid, raw, reason, _ in pending:
            if self.today.isoformat() <= day <= horizon:
                grouped[reason].append(f"{names.get(eid, eid)} {dt.date.fromisoformat(day):%d.%m}")
        for reason, who in sorted(grouped.items()):
            self.find("alert", "vakt",
                      f"Kan ikke planlegges – {reason}: {', '.join(who[:12])}"
                      f"{' …' if len(who) > 12 else ''}.")
        held = defaultdict(int)
        for r in conn.execute("SELECT title, COUNT(*) AS n FROM roster WHERE hold = 'uavklart' "
                              "AND date BETWEEN ? AND ? GROUP BY title",
                              (self.today.isoformat(), horizon)):
            held[r["title"]] = r["n"]
        for title in sorted(t for t, rule in rules.items() if rule == "uavklart"):
            self.find("alert", "stilling",
                      f"Stillingen «{title}» er ny og må klassifiseres under Administrasjon → "
                      f"Stillinger. {held.get(title, 0)} vakter de neste fire ukene holdes utenfor "
                      "planen til da.")
        if not_in_plan:
            self.find("info", "ukeplan",
                      f"I ukeplanen, men ikke i turnusen (f.eks. innleid vikar): "
                      f"{', '.join(sorted(names.get(e, e) for e in not_in_plan))}. "
                      "Planlegges som vanlig stilling.")

    # -- competencies ----------------------------------------------------
    def competencies(self) -> None:
        conn = self.conn
        conn.execute("DELETE FROM employee_competencies")
        conn.execute(
            """INSERT INTO employee_competencies (employee_id, competency_id, status)
               SELECT e.employee_id, c.competency_id, c.status FROM employees e
               JOIN competency_rows c ON c.full_name = e.full_name WHERE e.origin = 'import'""")
        horizon = (self.today + dt.timedelta(days=14)).isoformat()
        on_duty = {r["employee_id"]: r["display_name"] for r in conn.execute(
            """SELECT DISTINCT r.employee_id, e.display_name FROM roster r
               JOIN employees e ON e.employee_id = r.employee_id
               WHERE r.hold IS NULL AND r.date BETWEEN ? AND ?""",
            (self.today.isoformat(), horizon))}
        if not on_duty:
            return
        if not conn.execute("SELECT COUNT(*) FROM competency_rows").fetchone()[0]:
            self.find("warn", "kompetanse",
                      "Ingen kompetansefil er importert ennå – ingen kan plasseres automatisk. "
                      "Legg kompetansefilen (.xlsx, navn skrevet som i turnusen) i data/import/.")
            return
        with_comp = {r["employee_id"] for r in conn.execute(
            "SELECT DISTINCT employee_id FROM employee_competencies")}
        lacking = sorted(name for eid, name in on_duty.items() if eid not in with_comp)
        if lacking:
            self.find("warn", "kompetanse",
                      f"Ingen kompetanse registrert for {', '.join(lacking)} – navnet finnes ikke "
                      "i kompetansefilen (skrevet likt som i turnusen?). Kan ikke plasseres "
                      "automatisk.")

    # -- plans that no longer match the roster ---------------------------
    def reconcile_plans(self) -> None:
        conn = self.conn
        names = {r["employee_id"]: r["display_name"] for r in conn.execute(
            "SELECT employee_id, display_name FROM employees")}
        for row in conn.execute("SELECT DISTINCT plan_date FROM assignments WHERE plan_date >= ?",
                                (self.today.isoformat(),)).fetchall():
            date = dt.date.fromisoformat(row["plan_date"])
            on_duty = planner.day_shifts(conn, date)
            gone = sorted({r["employee_id"] for r in conn.execute(
                "SELECT employee_id FROM assignments WHERE plan_date = ?", (row["plan_date"],))}
                - set(on_duty))
            if not gone:
                continue
            conn.executemany("DELETE FROM assignments WHERE plan_date = ? AND employee_id = ?",
                             [(row["plan_date"], eid) for eid in gone])
            log(conn, f"Plan {date:%d.%m.%Y}: {', '.join(names.get(e, e) for e in gone)} tatt ut – "
                      "ikke lenger på vakt ifølge nyeste turnus/ukeplan.")

    # -- coverage and file-level findings --------------------------------
    def coverage(self, plans, weeks) -> None:
        conn = self.conn
        today = self.today
        if not plans:
            self.find("alert", "dekning", "Ingen turnus er importert. Legg turnusfilen "
                      "(Utskrift_fleksiplan_….csv) i data/import/.")
        else:
            gaps = []
            day = today
            while day <= today + dt.timedelta(days=LOOKAHEAD_DAYS - 1):
                if not any(f["first_date"] <= day.isoformat() <= f["last_date"] for f in plans):
                    gaps.append(day)
                day += dt.timedelta(days=1)
            if gaps:
                self.find("alert", "dekning",
                          f"Turnus mangler fra {gaps[0]:%d.%m.%Y}"
                          f"{f' til {gaps[-1]:%d.%m.%Y}' if len(gaps) > 1 else ''} – eksporter "
                          "en ny turnus.", gaps[0])
            if len(plans) > 1 and plans[1]["person_count"]:
                change = abs(plans[0]["person_count"] - plans[1]["person_count"]) / plans[1]["person_count"]
                if change > HEADCOUNT_CHANGE_WARN:
                    self.find("warn", "fil",
                              f"Nyeste turnus har {plans[0]['person_count']} personrader, forrige "
                              f"hadde {plans[1]['person_count']} – sjekk at eksporten er komplett.")
            if len({f["fingerprint"] for f in plans}) > 1:
                self.find("warn", "fil", "Kolonnene foran dagene i turnusen er endret siden "
                          "forrige eksport – sjekk eksportinnstillingene.")
        monday = today - dt.timedelta(days=today.weekday())
        for offset, level in ((0, "warn"), (7, "info")):
            week_start = monday + dt.timedelta(days=offset)
            if week_start.isoformat() not in weeks:
                when = "denne uken" if offset == 0 else "neste uke"
                self.find(level, "dekning",
                          f"Ingen ukeplan for {when} (uke {week_start.isocalendar().week}) – "
                          "turnusen brukes uten siste endringer (fravær, bytter).", week_start)
        # A rejected file alerts for as long as it lies in avvist/ — moving or
        # deleting it there is how a manager says "dealt with".
        for row in conn.execute(
                "SELECT filename, reason, stored_path FROM import_files WHERE status = 'rejected' "
                "ORDER BY file_id DESC"):
            if not row["stored_path"] or not Path(row["stored_path"]).exists():
                continue
            first = (row["reason"] or "").splitlines()[0] if row["reason"] else ""
            self.find("alert", "fil", f"{row['filename']} ble avvist: {first} "
                                      "(se data/import/avvist/).")
        for row in conn.execute("SELECT filename, reason FROM import_files WHERE status = 'active' "
                                "AND kind IN ('plan', 'ajourhold') AND reason IS NOT NULL"):
            for line in row["reason"].splitlines():
                self.find("info", "fil", f"{row['filename']}: {line}")

    def overlaps(self, files) -> None:
        """D80: one person, two rows with a shift the same day, in one file."""
        conn = self.conn
        for f in files:
            for r in conn.execute(
                    """SELECT r.full_name, c.export_date, COUNT(*) AS n FROM import_cells c
                       JOIN import_rows r ON r.file_id = c.file_id AND r.row_no = c.row_no
                       WHERE c.file_id = ? GROUP BY r.full_name, c.export_date HAVING n > 1
                       ORDER BY c.export_date LIMIT 5""", (f["file_id"],)):
                self.find("alert", "identitet",
                          f"«{r['full_name']}» har vakt på to rader {dt.date.fromisoformat(r['export_date']):%d.%m.%Y} "
                          f"i {f['filename']} – to personer med samme navn, eller feil i turnusen?")


def display_names(conn: sqlite3.Connection) -> None:
    """Board names for imported people: «Fornavn E.», the surname prefix
    lengthened until unique. The exports write names surname first (D82)."""
    people = list(conn.execute(
        "SELECT employee_id, full_name FROM employees WHERE origin = 'import'"))
    full = {r["employee_id"]: r["full_name"] for r in people}

    def parts(full: str) -> tuple[str, str]:
        tokens = full.split()
        if len(tokens) < 2:
            return full, ""
        return tokens[1], tokens[0]

    length = {r["employee_id"]: 1 for r in people}
    for _ in range(30):
        labels = {}
        for r in people:
            given, surname = parts(r["full_name"])
            n = length[r["employee_id"]]
            labels[r["employee_id"]] = (given if not surname else
                                        f"{given} {surname[:n]}{'.' if n < len(surname) else ''}")
        clashes = defaultdict(list)
        for eid, label in labels.items():
            clashes[label].append(eid)
        grew = False
        for eids in clashes.values():
            if len(eids) > 1:
                for eid in eids:
                    surname = parts(full[eid])[1]
                    if length[eid] < len(surname):
                        length[eid] += 1
                        grew = True
        if not grew:
            break
    seen: dict[str, int] = defaultdict(int)
    labels = labels if people else {}
    for eid, label in sorted(labels.items()):
        seen[label] += 1
        final = label if seen[label] == 1 else f"{label} ({seen[label]})"
        conn.execute("UPDATE employees SET display_name = ? WHERE employee_id = ?", (final, eid))


def rebuild(conn: sqlite3.Connection, today: dt.date | None = None) -> None:
    """Everything derived from the stored files, recomputed in one transaction."""
    today = today or dt.date.today()
    cutoff = today - dt.timedelta(days=retention_days(conn))
    with conn:
        _supersede(conn, cutoff)
        files = list(conn.execute(
            "SELECT * FROM import_files WHERE status = 'active' AND kind IN ('plan', 'ajourhold') "
            "ORDER BY exported_at DESC, file_id DESC"))
        plans = [f for f in files if f["kind"] == "plan"]
        weeks = {f["first_date"]: f for f in files if f["kind"] == "ajourhold"}
        work = Rebuild(conn, today)
        mapping = work.identities(files)
        display_names(conn)
        work.legends(plans)
        work.overlaps(files)
        work.roster(plans, weeks, mapping, cutoff)
        work.competencies()
        work.reconcile_plans()
        work.coverage(plans, weeks)
        conn.execute("DELETE FROM import_findings")
        order = {"alert": 0, "warn": 1, "info": 2}
        conn.executemany(
            "INSERT INTO import_findings (level, kind, text, date) VALUES (?, ?, ?, ?)",
            sorted(work.findings, key=lambda f: order[f[0]]))
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('roster_built_at', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (_now(),))


def purge(conn: sqlite3.Connection, today: dt.date | None = None) -> int:
    """Delete what is older than the retention period (D94): roster imports,
    raw files, plans, absences and notices. Returns rows of files removed."""
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=retention_days(conn))).isoformat()
    with conn:
        old = list(conn.execute(
            "SELECT * FROM import_files WHERE (last_date IS NOT NULL AND last_date < ?) "
            "OR (status = 'rejected' AND imported_at < ?) "
            "OR (status = 'superseded' AND kind = 'kompetanse' AND imported_at < ?)",
            (cutoff, cutoff, cutoff)))
        for f in old:
            for table in ("import_cells", "import_rows", "import_legend"):
                conn.execute(f"DELETE FROM {table} WHERE file_id = ?", (f["file_id"],))
            conn.execute("DELETE FROM import_files WHERE file_id = ?", (f["file_id"],))
            _unlink(f["stored_path"])
            if f["stored_path"]:
                _unlink(f["stored_path"] + ".txt")
        conn.execute("DELETE FROM import_cells WHERE export_date < ?", (cutoff,))
        for table, column in (("roster", "date"), ("roster_pending", "date"),
                              ("assignments", "plan_date"), ("plan_days", "plan_date"),
                              ("absences", "date"), ("day_info", "plan_date")):
            conn.execute(f"DELETE FROM {table} WHERE {column} < ?", (cutoff,))
        conn.execute("DELETE FROM import_log WHERE at < ?", (cutoff,))
        if old:
            log(conn, f"Sletting etter {retention_days(conn)} dager: {len(old)} gamle filer fjernet.")
    return len(old)


def refresh(conn: sqlite3.Connection, force: bool = False, inbox: Path | None = None) -> list[str]:
    """Pick up new files and rebuild when something changed. Cheap enough to
    call on every page load: it does real work at most every 30 seconds, and
    never twice at once. A no-op in demo mode."""
    global _last_scan, _last_purge, last_error
    if db.is_demo():
        return []
    if not force and time.time() - _last_scan < SCAN_INTERVAL_SECONDS:
        return []
    if not _lock.acquire(blocking=force):
        return []
    try:
        _last_scan = time.time()
        today = dt.date.today()
        try:
            messages = scan_inbox(conn, inbox)
            purged = 0
            if _last_purge != today:
                purged = purge(conn, today)
                _last_purge = today
            if messages or purged or force or not _setting(conn, "roster_built_at", ""):
                rebuild(conn, today)
            last_error = None
        except Exception as exc:  # noqa: BLE001 - pages must keep working
            # The transaction was rolled back: the previous roster stands.
            last_error = f"{exc.__class__.__name__}: {exc}"
            return []
        return messages
    finally:
        _lock.release()


def last_refresh() -> dt.datetime | None:
    return dt.datetime.fromtimestamp(_last_scan) if _last_scan else None

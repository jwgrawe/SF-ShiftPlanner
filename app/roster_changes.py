"""Changes on the floor, recorded by a manager (D119): «Endringer i vaktlisten».

When reality differs from turnus and ukeplan – someone swapped to another
shift, came in extra, went home, worked other hours – the manager records it
here. It wins over both files for that person and day (applied last in the
rebuild, hr_import.Rebuild.apply_overrides), so the plan and the
belastningstimer follow what actually happens. Who stood *where* is changed
in the day's plan instead (also after the fact).

Kept like other roster data: deleted after the retention period (D94).
"""
from __future__ import annotations

import datetime as dt
import sqlite3

from app import applog, domain

KINDS = {"vakt": "Annen vakt", "tid": "Egen tid", "fri": "Ikke på jobb"}
WEEKDAYS = ["man", "tir", "ons", "tor", "fre", "lør", "søn"]


class Invalid(ValueError):
    pass


def people(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT employee_id, display_name, full_name, person_id, is_temp FROM employees
           WHERE origin = 'import' ORDER BY full_name""")]


def model(conn: sqlite3.Connection, today: dt.date, show_past: bool = False) -> dict:
    first = today - dt.timedelta(days=14) if show_past else today
    codes = {r["code"]: r for r in conn.execute("SELECT * FROM shift_codes WHERE code <> 'MAN'")}
    names = {p["employee_id"]: p for p in people(conn)}
    rows = []
    for o in conn.execute("SELECT * FROM roster_overrides WHERE date >= ? ORDER BY date, employee_id",
                          (first.isoformat(),)):
        day = dt.date.fromisoformat(o["date"])
        person = names.get(o["employee_id"], {})
        if o["kind"] == "vakt":
            code = codes.get(o["code"])
            what = (f"{o['code']} {code['start']}–{code['end']}" if code and code["kind"] == "vanlig"
                    else o["code"] if code else f"{o['code']} – koden finnes ikke lenger")
        elif o["kind"] == "tid":
            what = f"{o['start']}–{o['end']}"
        else:
            what = "ikke på jobb"
        rows.append({**dict(o), "day": day, "weekday": WEEKDAYS[day.weekday()],
                     "display": person.get("display_name", o["employee_id"]),
                     "full_name": person.get("full_name", ""), "what": what,
                     "kind_label": KINDS[o["kind"]], "past": day < today,
                     "broken": o["kind"] == "vakt" and o["code"] not in codes})
    choosable = [dict(r) for r in conn.execute(
        "SELECT code, start, end, kind FROM shift_codes WHERE kind = 'vanlig' AND utpost_code <> 'yes' "
        "AND code <> 'MAN' ORDER BY code")]
    return {"rows": rows, "people": list(names.values()), "codes": choosable, "show_past": show_past,
            "today": today}


def _clock(value: str, label: str) -> str:
    try:
        return domain.parse_clock(value).strftime("%H:%M")
    except ValueError:
        raise Invalid(f"{label} må være et klokkeslett (f.eks. 7, 1330 eller 22:00).") from None


def save(conn: sqlite3.Connection, form) -> str:
    eid = (form.get("employee_id") or "").strip()
    person = conn.execute("SELECT display_name FROM employees WHERE employee_id = ? AND origin = 'import'",
                          (eid,)).fetchone()
    if person is None:
        raise Invalid("Velg en ansatt.")
    try:
        day = dt.date.fromisoformat((form.get("date") or "").strip())
    except ValueError:
        raise Invalid("Velg en dato.") from None
    kind = form.get("kind") or ""
    if kind not in KINDS:
        raise Invalid("Velg hva som er endret.")
    code = start = end = None
    if kind == "vakt":
        code = (form.get("code") or "").strip().upper()
        row = conn.execute("SELECT kind FROM shift_codes WHERE code = ?", (code,)).fetchone()
        if row is None or code == "MAN":
            raise Invalid("Velg en vaktkode fra listen.")
        if row["kind"] == "egen_tid":
            raise Invalid(f"{code} har ingen fast tid – velg «Egen tid» og skriv tiden.")
    elif kind == "tid":
        start, end = _clock(form.get("start", ""), "Fra"), _clock(form.get("end", ""), "Til")
        if start == end:
            raise Invalid("Fra og til kan ikke være like.")
    note = (form.get("note") or "").strip()[:200]
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO roster_overrides (employee_id, date, kind, code, start, end, note,
                   entered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (eid, day.isoformat(), kind, code, start, end, note,
             dt.datetime.now().isoformat(timespec="seconds")))
        what = {"vakt": f"vakt {code}", "tid": f"{start}–{end}", "fri": "ikke på jobb"}[kind]
        text = f"{person['display_name']} {day:%d.%m.%Y}: {what}{f' ({note})' if note else ''}."
        applog.log(conn, "vaktliste", f"Endring i vaktlisten – {text}")
    return f"Lagret: {text} Går foran turnus og ukeplan."


def remove(conn: sqlite3.Connection, eid: str, day: str) -> str:
    with conn:
        row = conn.execute(
            """SELECT o.*, e.display_name FROM roster_overrides o JOIN employees e USING (employee_id)
               WHERE o.employee_id = ? AND o.date = ?""", (eid, day)).fetchone()
        if row is None:
            raise Invalid("Fant ikke endringen.")
        conn.execute("DELETE FROM roster_overrides WHERE employee_id = ? AND date = ?", (eid, day))
        text = f"{row['display_name']} {dt.date.fromisoformat(day):%d.%m.%Y}"
        applog.log(conn, "vaktliste", f"Endring i vaktlisten fjernet – {text}; turnus/ukeplan gjelder igjen.")
    return f"Fjernet for {text} – turnus og ukeplan gjelder igjen."


def active_count(conn: sqlite3.Connection, today: dt.date) -> int:
    return conn.execute("SELECT COUNT(*) FROM roster_overrides WHERE date >= ?",
                        (today.isoformat(),)).fetchone()[0]

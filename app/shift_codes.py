"""The shift-code master list (D103): Administrasjon → Vaktkoder.

The app owns the list (table shift_code_defs). It starts from
data/seed/shift_codes.csv, learns codes from the turnus legend, and is then
edited here: add, change, ignore or remove a code. shift_codes, which the
rest of the app joins against, is derived from it by db.sync_shift_codes().

Three kinds of code:
  vanlig     fixed times (D 07:00–15:00) – planned as usual
  egen_tid   no fixed times (DX/AX) – the time is entered per shift
  ignoreres  never planned (DMT/DMK) – the day is shown but held out
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
import sqlite3

from . import applog, db, domain, hr_import

KINDS = {
    "vanlig": "Fast tid",
    "egen_tid": "Tid per vakt",
    "ignoreres": "Ignoreres",
}
KIND_HELP = {
    "vanlig": "Vakten har faste tider og planlegges som vanlig.",
    "egen_tid": "Ingen faste tider (f.eks. DX/AX fra vikarenheten). Tiden angis for hver vakt "
                "under Datagrunnlag → Vakter uten fast tid.",
    "ignoreres": "Vakten planlegges aldri (f.eks. DMT/DMK). Dagen vises, men holdes utenfor.",
}
SOURCES = {"standard": "standard", "turnus": "fra turnusen", "manuell": "lagt til her"}
CODE = re.compile(r"^[A-ZÆØÅ0-9]{1,6}$")
RESERVED = {"MAN": "MAN er reservert for vakter med manuelt angitt tid.",
            "M": "M betyr overtid og leses aldri som en vakt."}
CSV_COLUMNS = ["code", "kind", "start", "end", "crosses_midnight", "category", "utpost_code",
               "duration_hours", "comment"]


class Invalid(ValueError):
    pass


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _time(value: str, label: str) -> str:
    value = (value or "").strip()
    try:
        return domain.parse_clock(value).strftime("%H:%M")
    except ValueError:
        raise Invalid(f"{label} må være et klokkeslett (TT:MM), ikke «{value}».") from None


def _describe(row) -> str:
    if row is None:
        return "–"
    if row["kind"] == "vanlig":
        text = f"{row['start']}–{row['end']}, {row['category']}"
        return text + (", utpost" if row["utpost_code"] == "yes" else "")
    return KINDS[row["kind"]].lower()


def unknown_codes(conn: sqlite3.Connection, today: dt.date) -> list[dict]:
    """Codes in the turnus/ukeplan that the list doesn't have (from today on)."""
    active = {r["code"] for r in conn.execute("SELECT code FROM shift_codes")}
    names = {r["employee_id"]: r["display_name"] for r in conn.execute(
        "SELECT employee_id, display_name FROM employees")}
    deleted = {r["code"] for r in conn.execute(
        "SELECT code FROM shift_code_defs WHERE deleted_at IS NOT NULL")}
    found: dict[str, dict] = {}
    for r in conn.execute("SELECT * FROM roster_pending WHERE date >= ? ORDER BY date",
                          (today.isoformat(),)):
        code, _, problem = hr_import.interpret(r["raw"])
        if problem or not code or code in active:
            continue
        entry = found.setdefault(code, {"code": code, "count": 0, "examples": [],
                                        "deleted": code in deleted})
        entry["count"] += 1
        if len(entry["examples"]) < 4:
            entry["examples"].append(
                f"{names.get(r['employee_id'], r['employee_id'])} "
                f"{dt.date.fromisoformat(r['date']):%d.%m}")
    return sorted(found.values(), key=lambda e: e["code"])


def attention(conn: sqlite3.Connection, today: dt.date) -> int:
    """What the tab badge counts: unknown codes, deviations, unreviewed."""
    model = overview(conn, today)
    return len(model["unknown"]) + model["counts"]["avvik"] + model["counts"]["nye"]


def overview(conn: sqlite3.Connection, today: dt.date) -> dict:
    legend = hr_import.newest_legend(conn)
    horizon = (today + dt.timedelta(days=hr_import.LOOKAHEAD_DAYS)).isoformat()
    used = {r["code"]: r["n"] for r in conn.execute(
        "SELECT shift_code AS code, COUNT(*) AS n FROM roster WHERE date BETWEEN ? AND ? "
        "GROUP BY shift_code", (today.isoformat(), horizon))}
    for r in conn.execute("SELECT raw FROM roster_pending WHERE date BETWEEN ? AND ?",
                          (today.isoformat(), horizon)):
        code = hr_import.interpret(r["raw"])[0]
        if code:
            used[code] = used.get(code, 0) + 1
    manual = conn.execute("SELECT COUNT(*) FROM roster WHERE shift_code = 'MAN' "
                          "AND date BETWEEN ? AND ?", (today.isoformat(), horizon)).fetchone()[0]
    codes, deleted = [], []
    for r in conn.execute("SELECT * FROM shift_code_defs ORDER BY code"):
        item = dict(r)
        item["kind_label"] = KINDS.get(r["kind"], r["kind"])
        item["source_label"] = SOURCES.get(r["source"], r["source"])
        item["legend"] = legend.get(r["code"])
        item["deviation"] = bool(item["legend"] and r["kind"] == "vanlig"
                                 and item["legend"] != (r["start"], r["end"])
                                 and r["legend_ack"] != "-".join(item["legend"]))
        item["used"] = used.get(r["code"], 0)
        (deleted if r["deleted_at"] else codes).append(item)
    counts = {
        "alle": len(codes),
        "vanlig": sum(1 for c in codes if c["kind"] == "vanlig"),
        "egen_tid": sum(1 for c in codes if c["kind"] == "egen_tid"),
        "ignoreres": sum(1 for c in codes if c["kind"] == "ignoreres"),
        "utpost": sum(1 for c in codes if c["kind"] == "vanlig" and c["utpost_code"] == "yes"),
        "avvik": sum(1 for c in codes if c["deviation"]),
        "nye": sum(1 for c in codes if not c["reviewed"]),
    }
    return {"codes": codes, "deleted": deleted, "unknown": unknown_codes(conn, today),
            "counts": counts, "manual_count": manual, "has_turnus": bool(legend),
            "not_in_turnus": sorted(c["code"] for c in codes
                                    if legend and c["kind"] == "vanlig" and c["code"] not in legend)}


def save(conn: sqlite3.Connection, form: dict) -> str:
    """Add or change one code. Returns a message; raises Invalid."""
    code = (form.get("code") or "").strip().upper()
    is_new = not form.get("existing")
    if code in RESERVED:
        raise Invalid(RESERVED[code])
    if not CODE.match(code):
        raise Invalid("Koden kan bare ha bokstaver og tall (maks 6 tegn), uten mellomrom, "
                      "komma, skråstrek eller stjerne.")
    kind = form.get("kind") or "vanlig"
    if kind not in KINDS:
        raise Invalid("Velg hva slags kode det er.")
    start = end = category = None
    utpost = "yes" if form.get("utpost") else "no"
    if kind == "vanlig":
        start = _time(form.get("start", ""), "Start")
        end = _time(form.get("end", ""), "Slutt")
        if start == end:
            raise Invalid("Start og slutt kan ikke være like.")
        category = form.get("category") or hr_import.suggest_category(start, end)
        from .service import SHIFT_CATEGORY_ORDER
        if category not in SHIFT_CATEGORY_ORDER:
            raise Invalid("Ukjent vaktkategori.")
    else:
        utpost = "no"
    comment = (form.get("comment") or "").strip()[:300]
    before = conn.execute("SELECT * FROM shift_code_defs WHERE code = ?", (code,)).fetchone()
    if is_new and before is not None and before["deleted_at"] is None:
        raise Invalid(f"Koden {code} finnes allerede – endre den i listen i stedet.")
    if not is_new and before is None:
        raise Invalid(f"Fant ikke koden {code}.")
    with conn:
        if before is None:
            conn.execute(
                """INSERT INTO shift_code_defs (code, kind, start, end, category, utpost_code, comment,
                       source, reviewed, edited, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'manuell', 1, 1, ?)""",
                (code, kind, start, end, category, utpost, comment, _now()))
            text = f"Vaktkoden {code} lagt til: {_describe({'kind': kind, 'start': start, 'end': end, 'category': category, 'utpost_code': utpost})}."
        else:
            conn.execute(
                """UPDATE shift_code_defs SET kind = ?, start = ?, end = ?, category = ?,
                       utpost_code = ?, comment = ?, reviewed = 1, edited = 1, deleted_at = NULL,
                       updated_at = ? WHERE code = ?""",
                (kind, start, end, category, utpost, comment, _now(), code))
            after = conn.execute("SELECT * FROM shift_code_defs WHERE code = ?", (code,)).fetchone()
            was = "slettet" if before["deleted_at"] else _describe(before)
            text = f"Vaktkoden {code} endret: {was} → {_describe(after)}."
        applog.log(conn, "vaktkode", text)
        db.sync_shift_codes(conn)
    return text


def confirm(conn: sqlite3.Connection, codes: list[str]) -> int:
    with conn:
        n = 0
        for code in codes:
            n += conn.execute("UPDATE shift_code_defs SET reviewed = 1, updated_at = ? "
                              "WHERE code = ? AND reviewed = 0", (_now(), code)).rowcount
            applog.log(conn, "vaktkode", f"Vaktkoden {code} bekreftet slik den kom fra turnusen.")
    return n


def use_turnus_time(conn: sqlite3.Connection, code: str) -> str:
    legend = hr_import.newest_legend(conn)
    if code not in legend:
        raise Invalid(f"Turnusen beskriver ikke koden {code}.")
    start, end = legend[code]
    before = conn.execute("SELECT * FROM shift_code_defs WHERE code = ?", (code,)).fetchone()
    if before is None:
        raise Invalid(f"Fant ikke koden {code}.")
    with conn:
        conn.execute("UPDATE shift_code_defs SET start = ?, end = ?, reviewed = 1, edited = 1, "
                     "updated_at = ? WHERE code = ?", (start, end, _now(), code))
        text = f"Vaktkoden {code} endret til turnusens tid: {before['start']}–{before['end']} → {start}–{end}."
        applog.log(conn, "vaktkode", text)
        db.sync_shift_codes(conn)
    return text


def keep_app_time(conn: sqlite3.Connection, code: str) -> str:
    legend = hr_import.newest_legend(conn)
    if code not in legend:
        raise Invalid(f"Turnusen beskriver ikke koden {code}.")
    row = conn.execute("SELECT * FROM shift_code_defs WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise Invalid(f"Fant ikke koden {code}.")
    start, end = legend[code]
    with conn:
        conn.execute("UPDATE shift_code_defs SET legend_ack = ?, reviewed = 1, updated_at = ? "
                     "WHERE code = ?", (f"{start}-{end}", _now(), code))
        text = (f"Vaktkoden {code} beholder appens tid {row['start']}–{row['end']} selv om turnusen "
                f"sier {start}–{end}. Endrer turnusen tiden igjen, varsles det på nytt.")
        applog.log(conn, "vaktkode", text)
    return text


def delete(conn: sqlite3.Connection, code: str) -> str:
    before = conn.execute("SELECT * FROM shift_code_defs WHERE code = ? AND deleted_at IS NULL",
                          (code,)).fetchone()
    if before is None:
        raise Invalid(f"Fant ikke koden {code}.")
    with conn:
        conn.execute("UPDATE shift_code_defs SET deleted_at = ?, updated_at = ? WHERE code = ?",
                     (_now(), _now(), code))
        text = f"Vaktkoden {code} fjernet (var {_describe(before)})."
        applog.log(conn, "vaktkode", text)
        db.sync_shift_codes(conn)
    return text


def restore(conn: sqlite3.Connection, code: str) -> str:
    with conn:
        n = conn.execute("UPDATE shift_code_defs SET deleted_at = NULL, updated_at = ? "
                         "WHERE code = ? AND deleted_at IS NOT NULL", (_now(), code)).rowcount
        if not n:
            raise Invalid(f"Fant ikke en fjernet kode {code}.")
        text = f"Vaktkoden {code} hentet tilbake."
        applog.log(conn, "vaktkode", text)
        db.sync_shift_codes(conn)
    return text


def export_csv(conn: sqlite3.Connection) -> bytes:
    """The list in the seed's format – a backup, and a file that can replace
    data/seed/shift_codes.csv if this list should become the standard."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for r in conn.execute("SELECT * FROM shift_codes WHERE code <> 'MAN' ORDER BY code"):
        timed = r["kind"] == "vanlig"
        writer.writerow([r["code"], r["kind"], r["start"] if timed else "", r["end"] if timed else "",
                         r["crosses_midnight"], r["category"] if timed else "", r["utpost_code"],
                         r["duration_hours"] if timed else "", r["comment"]])
    return ("﻿" + out.getvalue()).encode("utf-8")

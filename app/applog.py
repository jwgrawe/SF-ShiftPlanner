"""The app's log (D100): one line per thing that changed, with its area.

Cheap and always on. Pages show their own area collapsed at the bottom;
Administrasjon → Innstillinger shows everything. Kept a year — longer than the
92-day roster data, since it is the record of who/what changed master data.
"""
from __future__ import annotations

import datetime as dt
import sqlite3

LOG_RETENTION_DAYS = 365

AREAS = {
    "import": "Import",
    "kompetanse": "Kompetanse",
    "stilling": "Stillinger",
    "vaktkode": "Vaktkoder",
    "plan": "Plan",
    "fravaer": "Fravær",
    "innstilling": "Innstillinger",
}


def log(conn: sqlite3.Connection, area: str, text: str) -> None:
    """Write one line. Runs inside the caller's transaction if there is one."""
    conn.execute("INSERT INTO import_log (at, text, area) VALUES (?, ?, ?)",
                 (dt.datetime.now().isoformat(timespec="seconds"), text, area))


def write(conn: sqlite3.Connection, area: str, text: str) -> None:
    """Write one line in its own transaction."""
    with conn:
        log(conn, area, text)


def entries(conn: sqlite3.Connection, area: str | None = None, limit: int = 200) -> list[dict]:
    if area:
        rows = conn.execute(
            "SELECT at, text, area FROM import_log WHERE area = ? ORDER BY log_id DESC LIMIT ?",
            (area, limit))
    else:
        rows = conn.execute(
            "SELECT at, text, area FROM import_log ORDER BY log_id DESC LIMIT ?", (limit,))
    return [{"at": dt.datetime.fromisoformat(r["at"]), "text": r["text"],
             "area": AREAS.get(r["area"], r["area"])} for r in rows]


def purge(conn: sqlite3.Connection, today: dt.date) -> None:
    cutoff = (today - dt.timedelta(days=LOG_RETENTION_DAYS)).isoformat()
    conn.execute("DELETE FROM import_log WHERE at < ?", (cutoff,))

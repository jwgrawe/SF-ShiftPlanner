"""The app's log (D100): one line per thing that changed, with its area.

Cheap and always on. Pages show their own area collapsed at the bottom;
Administrasjon → Innstillinger shows everything. Kept a year — longer than the
92-day roster data, since it is the record of who/what changed master data.
"""
from __future__ import annotations

import contextvars
import datetime as dt
import sqlite3

LOG_RETENTION_DAYS = 365

AREAS = {
    "import": "Import",
    "kompetanse": "Kompetanse",
    "stilling": "Stillinger",
    "vaktkode": "Vaktkoder",
    "regler": "Planregler",
    "tilgang": "Tilgang",
    "plan": "Plan",
    "fravaer": "Fravær",
    "vaktliste": "Endringer i vaktlisten",
    "innstilling": "Innstillinger",
}


# Who is acting (D121): set per request by the login gate; empty for what the
# app does by itself (imports, rebuilds) – shown as «system».
CURRENT_USER: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user", default=None)


def log(conn: sqlite3.Connection, area: str, text: str) -> None:
    """Write one line. Runs inside the caller's transaction if there is one."""
    conn.execute("INSERT INTO import_log (at, text, area, who) VALUES (?, ?, ?, ?)",
                 (dt.datetime.now().isoformat(timespec="seconds"), text, area, CURRENT_USER.get()))


def write(conn: sqlite3.Connection, area: str, text: str) -> None:
    """Write one line in its own transaction."""
    with conn:
        log(conn, area, text)


def entries(conn: sqlite3.Connection, area: str | None = None, limit: int = 200) -> list[dict]:
    if area:
        rows = conn.execute(
            "SELECT at, text, area, who FROM import_log WHERE area = ? ORDER BY log_id DESC LIMIT ?",
            (area, limit))
    else:
        rows = conn.execute(
            "SELECT at, text, area, who FROM import_log ORDER BY log_id DESC LIMIT ?", (limit,))
    return [{"at": dt.datetime.fromisoformat(r["at"]), "text": r["text"],
             "area": AREAS.get(r["area"], r["area"]), "who": r["who"] or "system"} for r in rows]


def purge(conn: sqlite3.Connection, today: dt.date) -> None:
    cutoff = (today - dt.timedelta(days=LOG_RETENTION_DAYS)).isoformat()
    conn.execute("DELETE FROM import_log WHERE at < ?", (cutoff,))

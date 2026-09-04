"""Absence registration (D27/D46/D60).

Absences affect supply only. Registering one immediately removes the
employee's affected assignments, so an absent person can never linger on the
wall display — which shows the current plan and never the absence itself.
"""
from __future__ import annotations

import datetime as dt
import sqlite3

from app import domain

# Interim list pending Q29.
ABSENCE_TYPES = ["Syk", "Ferie", "Kurs/opplæring", "Permisjon", "Annet"]


def day_absences(conn: sqlite3.Connection, date: dt.date) -> list[sqlite3.Row]:
    return list(conn.execute(
        """SELECT ab.*, e.display_name FROM absences ab
           JOIN employees e ON e.employee_id = ab.employee_id
           WHERE ab.date = ? ORDER BY e.display_name""",
        (date.isoformat(),),
    ))


def register(
    conn: sqlite3.Connection, employee_id: str, date: dt.date, absence_type: str,
    start: str | None = None, end: str | None = None, note: str = "",
) -> int:
    """Record an absence and drop the assignments it invalidates.
    Returns how many assignments were removed."""
    date_str = date.isoformat()
    with conn:
        conn.execute(
            """INSERT INTO absences (employee_id, date, start, end, type, note)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (employee_id, date_str, start or None, end or None, absence_type, note),
        )
        if start and end:
            absent_from = dt.datetime.combine(date, domain.parse_time(start))
            absent_to = dt.datetime.combine(date, domain.parse_time(end))
            if absent_to <= absent_from:
                absent_to += dt.timedelta(days=1)
            doomed = []
            for row in conn.execute(
                "SELECT assignment_id, start, end FROM assignments "
                "WHERE plan_date = ? AND employee_id = ?", (date_str, employee_id),
            ):
                a_start = dt.datetime.combine(date, domain.parse_time(row["start"]))
                a_end = dt.datetime.combine(date, domain.parse_time(row["end"]))
                if a_end <= a_start:
                    a_end += dt.timedelta(days=1)
                if a_start < absent_to and absent_from < a_end:
                    doomed.append(row["assignment_id"])
            for assignment_id in doomed:
                conn.execute(
                    "DELETE FROM assignments WHERE assignment_id = ?", (assignment_id,))
            removed = len(doomed)
        else:
            cursor = conn.execute(
                "DELETE FROM assignments WHERE plan_date = ? AND employee_id = ?",
                (date_str, employee_id),
            )
            removed = cursor.rowcount or 0
        if removed:
            conn.execute(
                "UPDATE plan_days SET manually_edited = 1 WHERE plan_date = ?", (date_str,))
    return removed


def remove(conn: sqlite3.Connection, absence_id: int) -> None:
    """Delete an absence. Assignments are not restored — regenerate the day."""
    with conn:
        conn.execute("DELETE FROM absences WHERE absence_id = ?", (absence_id,))

"""Heavy-work exposure (D50–D52, D110): what a stretch of work weighs, the
rolling ledger per person and the weekly full-intensity occurrences.

Shared by the planner (to choose people) and the checks (to warn), so both
count exactly the same way:

- intensity windows: (function, start, end, intensity) from function_intensity;
- weighted hours: intensity × hours spent inside a window (D52);
- an occurrence: a day on which someone works inside a window whose
  intensity is at or above the threshold (D51); part of a shift counts as
  a whole occurrence (D38);
- the ledger: weighted hours over the last N days (the «utjevningsvindu»).
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from collections import defaultdict

from app import domain

Window = tuple[str, dt.time, dt.time, float]


def windows(conn: sqlite3.Connection) -> list[Window]:
    return [
        (row["function_id"], domain.parse_time(row["start"]),
         domain.parse_time(row["end"]) if row["end"] != "24:00" else dt.time(23, 59, 59),
         row["intensity"])
        for row in conn.execute(
            "SELECT function_id, start, end, intensity FROM function_intensity WHERE intensity > 0")
    ]


def load(wins: list[Window], function_id: str, start: dt.datetime, end: dt.datetime
         ) -> tuple[float, float]:
    """(weighted hours, highest intensity touched) for working `function_id`
    from `start` to `end` (which may cross midnight)."""
    weighted, peak = 0.0, 0.0
    for fn, w_start, w_end, intensity in wins:
        if fn != function_id:
            continue
        for offset in (-1, 0, 1):
            base = start.date() + dt.timedelta(days=offset)
            lo = max(start, dt.datetime.combine(base, w_start))
            hi = min(end, dt.datetime.combine(base, w_end))
            if lo < hi:
                weighted += (hi - lo).total_seconds() / 3600 * intensity
                peak = max(peak, intensity)
    return weighted, peak


def _span(plan_date: dt.date, start: str, end: str) -> tuple[dt.datetime, dt.datetime]:
    a = dt.datetime.combine(plan_date, domain.parse_time(start))
    b = dt.datetime.combine(plan_date, domain.parse_time(end))
    if b <= a:
        b += dt.timedelta(days=1)
    return a, b


def ledger(conn: sqlite3.Connection, first: dt.date, last: dt.date,
           wins: list[Window] | None = None) -> dict[str, float]:
    """employee -> weighted heavy hours in the plans from `first` to `last`."""
    wins = windows(conn) if wins is None else wins
    total: dict[str, float] = defaultdict(float)
    for row in conn.execute(
            "SELECT plan_date, employee_id, function_id, start, end FROM assignments "
            "WHERE plan_date BETWEEN ? AND ?", (first.isoformat(), last.isoformat())):
        a, b = _span(dt.date.fromisoformat(row["plan_date"]), row["start"], row["end"])
        total[row["employee_id"]] += load(wins, row["function_id"], a, b)[0]
    return dict(total)


def week_occurrences(conn: sqlite3.Connection, monday: dt.date, threshold: float,
                     exclude: dt.date | None = None,
                     wins: list[Window] | None = None) -> dict[str, int]:
    """employee -> days with full-intensity work in the week from `monday`,
    leaving out `exclude` (the day being planned)."""
    wins = windows(conn) if wins is None else wins
    days: dict[str, set[str]] = defaultdict(set)
    for row in conn.execute(
            "SELECT plan_date, employee_id, function_id, start, end FROM assignments "
            "WHERE plan_date BETWEEN ? AND ?",
            (monday.isoformat(), (monday + dt.timedelta(days=6)).isoformat())):
        if exclude is not None and row["plan_date"] == exclude.isoformat():
            continue
        a, b = _span(dt.date.fromisoformat(row["plan_date"]), row["start"], row["end"])
        if load(wins, row["function_id"], a, b)[1] >= threshold:
            days[row["employee_id"]].add(row["plan_date"])
    return {e: len(d) for e, d in days.items()}


def settings(conn: sqlite3.Connection) -> dict[str, float]:
    values = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM planner_settings")}
    return {
        "threshold": float(values.get("heavy_occurrence_intensity_threshold", 1.0)),
        "target": int(values.get("heavy_occurrence_target_per_week", 1)),
        "cap": int(values.get("heavy_occurrence_hard_cap_per_week", 3)),
        "window_days": int(values.get("intensity_ledger_window_days", 28)),
    }

"""Plan checks: what a day's plan misses or bends (D53).

Read-only detection for now — the acknowledge/override flow arrives with the
real generator in M3. Each check returns dicts of
{level, kind, text, date} where level is 'alert' (must be fixed),
'warn' (should be looked at) or 'info' (worth knowing).
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from collections import defaultdict

from app import domain, planner

DK_FUNCTION = "ren_dk_ansvarsvakt"


def _settings(conn: sqlite3.Connection) -> dict[str, float]:
    return {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM planner_settings")}


def _demand_groups(conn: sqlite3.Connection, day_type: str) -> list[dict]:
    """Demand rows, keeping function groups together so combined demand
    (Q20) is checked against the group's total coverage."""
    groups: dict[tuple, dict] = {}
    for row in conn.execute(
        "SELECT * FROM staffing_demand WHERE day_type = ? AND category = 'normal'", (day_type,)
    ):
        if row["row_type"] not in ("function", "function_group", "zone_total"):
            continue
        key = (row["row_type"], row["zone_id"], row["function_ids"])
        group = groups.setdefault(key, {
            "row_type": row["row_type"], "zone_id": row["zone_id"],
            "function_ids": (row["function_ids"] or "").split(";") if row["function_ids"] else [],
            "hours": {},
        })
        group["hours"][row["hour"]] = row["required"]
    return list(groups.values())


def _coverage(conn: sqlite3.Connection, plan_date: dt.date) -> dict[str, dict[int, int]]:
    """function_id -> hour -> number of people assigned."""
    coverage: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for row in conn.execute(
        "SELECT function_id, start, end FROM assignments WHERE plan_date = ?",
        (plan_date.isoformat(),),
    ):
        start = dt.datetime.combine(plan_date, domain.parse_time(row["start"]))
        end = dt.datetime.combine(plan_date, domain.parse_time(row["end"]))
        if end <= start:
            end += dt.timedelta(days=1)
        for hour in planner.segment_hours(domain.Segment(start, end)):
            coverage[row["function_id"]][hour] += 1
    return coverage


def _hour_ranges(hours: list[int]) -> str:
    """Compress [7,8,9,14] into '07–10, 14–15' for readable messages."""
    if not hours:
        return ""
    spans, start, previous = [], hours[0], hours[0]
    for hour in hours[1:]:
        if hour == previous + 1:
            previous = hour
            continue
        spans.append((start, previous))
        start = previous = hour
    spans.append((start, previous))
    return ", ".join(f"{a:02d}–{(b + 1) % 24:02d}" for a, b in spans)


def week_heavy_counts(conn: sqlite3.Connection, monday: dt.date) -> dict[str, int]:
    """Full-intensity occurrences per employee in the week starting `monday`
    (D51). One occurrence per day touched; partial shifts count fully (D38)."""
    threshold = _settings(conn).get("heavy_occurrence_intensity_threshold", 1.0)
    windows = [
        (row["function_id"], domain.parse_time(row["start"]),
         domain.parse_time(row["end"]) if row["end"] != "24:00" else dt.time(23, 59, 59))
        for row in conn.execute(
            "SELECT function_id, start, end FROM function_intensity WHERE intensity >= ?",
            (threshold,),
        )
    ]
    if not windows:
        return {}
    days: dict[str, set[str]] = defaultdict(set)
    for row in conn.execute(
        """SELECT plan_date, employee_id, function_id, start, end FROM assignments
           WHERE plan_date BETWEEN ? AND ?""",
        (monday.isoformat(), (monday + dt.timedelta(days=6)).isoformat()),
    ):
        plan_date = dt.date.fromisoformat(row["plan_date"])
        a_start = dt.datetime.combine(plan_date, domain.parse_time(row["start"]))
        a_end = dt.datetime.combine(plan_date, domain.parse_time(row["end"]))
        if a_end <= a_start:
            a_end += dt.timedelta(days=1)
        for function_id, w_start, w_end in windows:
            if function_id != row["function_id"]:
                continue
            for day_offset in (0, 1):
                base = plan_date + dt.timedelta(days=day_offset)
                overlap_start = max(a_start, dt.datetime.combine(base, w_start))
                overlap_end = min(a_end, dt.datetime.combine(base, w_end))
                if overlap_start < overlap_end:
                    days[row["employee_id"]].add(row["plan_date"])
    return {employee_id: len(dates) for employee_id, dates in days.items()}


def day_checks(conn: sqlite3.Connection, plan_date: dt.date) -> list[dict]:
    """All findings for one day, most serious first."""
    date_str = plan_date.isoformat()
    day_type = domain.day_kind(plan_date)
    findings: list[dict] = []

    roster = planner.day_roster(conn, plan_date)
    plan = conn.execute(
        "SELECT * FROM plan_days WHERE plan_date = ?", (date_str,)
    ).fetchone()
    assignment_count = conn.execute(
        "SELECT COUNT(*) FROM assignments WHERE plan_date = ?", (date_str,)
    ).fetchone()[0]

    if not roster:
        return findings  # nothing rostered: nothing to check
    if not assignment_count:
        findings.append({"level": "warn", "kind": "no_plan", "date": plan_date,
                         "text": "Ingen plan er laget for dagen."})
        return findings
    if plan is not None and plan["status"] != "published":
        findings.append({"level": "info", "kind": "draft", "date": plan_date,
                         "text": "Planen er et utkast – den vises ikke på tavlen før den publiseres."})

    names = {row["function_id"]: row["name"] for row in conn.execute(
        "SELECT function_id, name FROM functions")}
    zone_names = {row["zone_id"]: row["name"] for row in conn.execute(
        "SELECT zone_id, name FROM zones")}
    coverage = _coverage(conn, plan_date)

    for group in _demand_groups(conn, day_type):
        if group["row_type"] == "zone_total":
            function_ids = [row["function_id"] for row in conn.execute(
                "SELECT function_id FROM functions WHERE zone_id = ?", (group["zone_id"],))]
            label = zone_names.get(group["zone_id"], group["zone_id"])
        else:
            function_ids = group["function_ids"]
            label = " / ".join(names.get(f, f) for f in function_ids)
        missing = [
            hour for hour, required in sorted(group["hours"].items())
            if required > sum(coverage[f].get(hour, 0) for f in function_ids)
        ]
        if not missing:
            continue
        is_dk = DK_FUNCTION in function_ids
        findings.append({
            "level": "alert" if is_dk else "warn",
            "kind": "shortfall", "date": plan_date,
            "text": (f"Ingen DK/ansvarsvakt på vakt kl. {_hour_ranges(missing)}."
                     if is_dk else
                     f"For få på {label} kl. {_hour_ranges(missing)}."),
        })

    # Absent people who are still assigned — must never reach the display.
    for row in conn.execute(
        """SELECT DISTINCT e.display_name FROM absences ab
           JOIN employees e ON e.employee_id = ab.employee_id
           JOIN assignments a ON a.employee_id = ab.employee_id AND a.plan_date = ab.date
           WHERE ab.date = ?""", (date_str,),
    ):
        findings.append({"level": "alert", "kind": "absent_assigned", "date": plan_date,
                         "text": f"{row['display_name']} er meldt fraværende, men står "
                                 "fortsatt i planen."})

    # Rostered but unplanned (weekdays; weekends are ad hoc by design, D21).
    if day_type == "weekday":
        assigned = {row["employee_id"] for row in conn.execute(
            "SELECT DISTINCT employee_id FROM assignments WHERE plan_date = ?", (date_str,))}
        idle = sorted(
            row["display_name"] for row in conn.execute(
                "SELECT employee_id, display_name FROM employees")
            if row["employee_id"] in roster and row["employee_id"] not in assigned
        )
        if idle:
            findings.append({"level": "info", "kind": "unplanned", "date": plan_date,
                             "text": f"På vakt uten plassering: {', '.join(idle)}."})

    # Weekly heavy-exposure cap (D51).
    settings = _settings(conn)
    cap = int(settings.get("heavy_occurrence_hard_cap_per_week", 3))
    counts = week_heavy_counts(conn, plan_date - dt.timedelta(days=plan_date.weekday()))
    # Only flag people who actually work this day, so the day view stays
    # about this day rather than repeating the whole week's tally.
    over = sorted(
        (row["display_name"], counts[row["employee_id"]])
        for row in conn.execute("SELECT employee_id, display_name FROM employees")
        if row["employee_id"] in roster and counts.get(row["employee_id"], 0) > cap
    )
    for name, count in over:
        findings.append({"level": "warn", "kind": "heavy_cap", "date": plan_date,
                         "text": f"{name} har {count} økter med tungt arbeid denne uken "
                                 f"(grensen er {cap})."})

    order = {"alert": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: order[f["level"]])
    return findings


def intensity_hours(
    conn: sqlite3.Connection, employee_id: str, first: dt.date, last: dt.date
) -> float:
    """Weighted heavy-exposure hours (D52): sum of intensity × hours actually
    spent in each function's intensity windows."""
    windows = [
        (row["function_id"], domain.parse_time(row["start"]),
         domain.parse_time(row["end"]) if row["end"] != "24:00" else dt.time(23, 59, 59),
         row["intensity"])
        for row in conn.execute(
            "SELECT function_id, start, end, intensity FROM function_intensity WHERE intensity > 0")
    ]
    total = 0.0
    for row in conn.execute(
        """SELECT plan_date, function_id, start, end FROM assignments
           WHERE employee_id = ? AND plan_date BETWEEN ? AND ?""",
        (employee_id, first.isoformat(), last.isoformat()),
    ):
        plan_date = dt.date.fromisoformat(row["plan_date"])
        a_start = dt.datetime.combine(plan_date, domain.parse_time(row["start"]))
        a_end = dt.datetime.combine(plan_date, domain.parse_time(row["end"]))
        if a_end <= a_start:
            a_end += dt.timedelta(days=1)
        for function_id, w_start, w_end, intensity in windows:
            if function_id != row["function_id"]:
                continue
            for day_offset in (0, 1):
                base = plan_date + dt.timedelta(days=day_offset)
                overlap_start = max(a_start, dt.datetime.combine(base, w_start))
                overlap_end = min(a_end, dt.datetime.combine(base, w_end))
                if overlap_start < overlap_end:
                    hours = (overlap_end - overlap_start).total_seconds() / 3600
                    total += hours * intensity
    return round(total, 1)

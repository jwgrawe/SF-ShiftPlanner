"""Read-side services: eligibility resolution and view models for the pages.

Eligibility (assessment §2.1, D17/D32/D40/D44/D56): an employee may hold a
function iff they have a qualifying competency for it, are not restricted
from it (per-function or heavy-work fritak), the function is on their
preference allowlist when one exists, and they work in SF.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from collections import defaultdict

from app import domain


def rotation_times(conn: sqlite3.Connection) -> dict[str, dt.time | None]:
    return {
        row["category"]: domain.parse_time(row["rotation_time"]) if row["rotation_time"] else None
        for row in conn.execute("SELECT category, rotation_time FROM rotation_rules")
    }


def heavy_function_ids(conn: sqlite3.Connection) -> set[str]:
    """Functions with any intensity > 0 window — the scope of a heavy-work fritak."""
    return {
        row["function_id"]
        for row in conn.execute("SELECT DISTINCT function_id FROM function_intensity WHERE intensity > 0")
    }


def eligible_functions(conn: sqlite3.Connection, on_date: dt.date) -> dict[str, set[str]]:
    """employee_id -> set of function_ids the employee may be assigned on that date."""
    qualified: dict[str, set[str]] = defaultdict(set)  # employee -> competencies
    for row in conn.execute(
        "SELECT employee_id, competency_id FROM employee_competencies WHERE status = 'qualified'"
    ):
        qualified[row["employee_id"]].add(row["competency_id"])

    function_accepts: dict[str, set[str]] = defaultdict(set)  # function -> competencies
    for row in conn.execute("SELECT function_id, competency_id FROM function_competencies"):
        function_accepts[row["function_id"]].add(row["competency_id"])

    preferences: dict[str, set[str]] = defaultdict(set)
    for row in conn.execute("SELECT employee_id, function_id FROM employee_preferences"):
        preferences[row["employee_id"]].add(row["function_id"])

    date_str = on_date.isoformat()
    heavy = heavy_function_ids(conn)
    blocked: dict[str, set[str]] = defaultdict(set)
    for row in conn.execute(
        """SELECT employee_id, restriction_type, function_id FROM employee_restrictions
           WHERE (valid_from IS NULL OR valid_from <= ?)
             AND (valid_to IS NULL OR valid_to >= ?)""",
        (date_str, date_str),
    ):
        if row["restriction_type"] == "heavy_work":
            blocked[row["employee_id"]] |= heavy
        elif row["function_id"]:
            blocked[row["employee_id"]].add(row["function_id"])

    sf_employees = [
        row["employee_id"]
        for row in conn.execute("SELECT employee_id FROM employees WHERE works_at = 'sf'")
    ]

    result: dict[str, set[str]] = {}
    for employee_id in sf_employees:
        functions = {
            function_id
            for function_id, accepts in function_accepts.items()
            if accepts & qualified.get(employee_id, set())
        }
        functions -= blocked.get(employee_id, set())
        if preferences.get(employee_id):
            functions &= preferences[employee_id]
        result[employee_id] = functions
    return result


def day_assignments(conn: sqlite3.Connection, plan_date: dt.date) -> list[sqlite3.Row]:
    return list(conn.execute(
        """SELECT a.*, e.display_name, f.name AS function_name, f.zone_id, f.staffing_mode,
                  z.name AS zone_name, z.sort_order AS zone_order, f.sort_order AS function_order
           FROM assignments a
           JOIN employees e ON e.employee_id = a.employee_id
           JOIN functions f ON f.function_id = a.function_id
           JOIN zones z ON z.zone_id = f.zone_id
           WHERE a.plan_date = ?
           ORDER BY z.sort_order, f.sort_order, a.start, e.display_name""",
        (plan_date.isoformat(),),
    ))


def _to_datetimes(plan_date: dt.date, row: sqlite3.Row) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(plan_date, domain.parse_time(row["start"]))
    end = dt.datetime.combine(plan_date, domain.parse_time(row["end"]))
    if end <= start:
        end += dt.timedelta(days=1)
    return start, end


def build_display_model(conn: sqlite3.Connection, now: dt.datetime) -> dict:
    """Everything the wall display needs for the operational day containing `now`."""
    plan_date = domain.operational_day(now)
    kind = domain.day_kind(plan_date)
    rows = day_assignments(conn, plan_date)

    active, upcoming_times = [], set()
    for row in rows:
        start, end = _to_datetimes(plan_date, row)
        if start <= now < end:
            active.append((row, start, end))
        elif start > now:
            upcoming_times.add(start)

    next_change = min(upcoming_times) if upcoming_times else None
    takeovers = []
    if next_change is not None:
        current_function: dict[str, str] = {}
        current_by_function: dict[str, list[str]] = defaultdict(list)
        for row, _, _ in active:
            current_function[row["employee_id"]] = row["function_id"]
            current_by_function[row["function_id"]].append(row["display_name"])
        for row in rows:
            start, _ = _to_datetimes(plan_date, row)
            if start != next_change:
                continue
            # Only actual changes: skip people continuing on the same function.
            if current_function.get(row["employee_id"]) == row["function_id"]:
                continue
            # "Overtar for" only makes sense for explicit demand functions,
            # not the remainder pools or ad-hoc zones.
            replaces = (
                ", ".join(current_by_function.get(row["function_id"], []))
                if row["staffing_mode"] == "demand" else ""
            )
            takeovers.append({
                "display_name": row["display_name"],
                "function_name": row["function_name"],
                "zone_id": row["zone_id"],
                "replaces": replaces,
            })

    zones: list[dict] = []
    for zone in conn.execute("SELECT * FROM zones ORDER BY sort_order"):
        zone_active = [
            {"display_name": row["display_name"], "function_name": row["function_name"],
             "adhoc": row["staffing_mode"] == "adhoc_zone"}
            for row, _, _ in active if row["zone_id"] == zone["zone_id"]
        ]
        has_active_functions = conn.execute(
            "SELECT COUNT(*) FROM functions WHERE zone_id = ? AND active = 'yes'",
            (zone["zone_id"],),
        ).fetchone()[0]
        if has_active_functions:
            zones.append({"zone_id": zone["zone_id"], "name": zone["name"],
                          "people": zone_active,
                          "adhoc_zone": all(p["adhoc"] for p in zone_active) and bool(zone_active)})

    # Weekend/holiday: the crew largely self-manages (D21) — show the rostered
    # crew, not only explicit assignments.
    adhoc_crew = []
    if kind == "weekend_holiday":
        assigned_ids = {row["employee_id"] for row, _, _ in active}
        for row in conn.execute(
            """SELECT r.employee_id, e.display_name, r.shift_code, s.start, s.end
               FROM roster r JOIN employees e ON e.employee_id = r.employee_id
               JOIN shift_codes s ON s.code = r.shift_code
               WHERE r.date = ? ORDER BY e.display_name""",
            (plan_date.isoformat(),),
        ):
            if row["employee_id"] not in assigned_ids:
                adhoc_crew.append({"display_name": row["display_name"],
                                   "hours": f"{row['start']}–{row['end']}"})

    return {
        "now": now,
        "plan_date": plan_date,
        "day_kind": kind,
        "zones": zones,
        "next_change": next_change,
        "takeovers": takeovers,
        "adhoc_crew": adhoc_crew,
        "has_plan": bool(rows),
    }


def build_plan_model(conn: sqlite3.Connection, plan_date: dt.date) -> dict:
    """Manager view: the whole day as blocks × functions × people."""
    rows = day_assignments(conn, plan_date)
    blocks: dict[tuple[dt.datetime, dt.datetime], list] = defaultdict(list)
    for row in rows:
        start, end = _to_datetimes(plan_date, row)
        blocks[(start, end)].append(row)

    block_list = []
    for (start, end) in sorted(blocks):
        by_function: dict[str, dict] = {}
        for row in blocks[(start, end)]:
            entry = by_function.setdefault(row["function_id"], {
                "function_name": row["function_name"], "zone_name": row["zone_name"],
                "zone_id": row["zone_id"], "people": [],
                "order": (row["zone_order"], row["function_order"]),
            })
            entry["people"].append(row["display_name"] + (" 🔒" if row["locked"] else ""))
        block_list.append({
            "start": start, "end": end,
            "functions": sorted(by_function.values(), key=lambda item: item["order"]),
        })

    roster_rows = list(conn.execute(
        """SELECT e.display_name, r.shift_code, s.category, s.start, s.end
           FROM roster r JOIN employees e ON e.employee_id = r.employee_id
           JOIN shift_codes s ON s.code = r.shift_code
           WHERE r.date = ? ORDER BY s.start, e.display_name""",
        (plan_date.isoformat(),),
    ))
    return {
        "plan_date": plan_date,
        "day_kind": domain.day_kind(plan_date),
        "blocks": block_list,
        "roster": roster_rows,
        "has_plan": bool(rows),
    }

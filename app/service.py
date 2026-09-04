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

WEEKDAYS_NB = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]


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


def day_assignments(
    conn: sqlite3.Connection, plan_date: dt.date, published_only: bool = False
) -> list[sqlite3.Row]:
    status_filter = "AND p.status = 'published'" if published_only else ""
    return list(conn.execute(
        f"""SELECT a.*, e.display_name, f.name AS function_name, f.short_name,
                   f.zone_id, f.staffing_mode,
                   z.name AS zone_name, z.sort_order AS zone_order,
                   f.sort_order AS function_order
            FROM assignments a
            JOIN plan_days p ON p.plan_date = a.plan_date
            JOIN employees e ON e.employee_id = a.employee_id
            JOIN functions f ON f.function_id = a.function_id
            JOIN zones z ON z.zone_id = f.zone_id
            WHERE a.plan_date = ? {status_filter}
            ORDER BY z.sort_order, f.sort_order, a.start, e.display_name""",
        (plan_date.isoformat(),),
    ))


def plan_day_row(conn: sqlite3.Connection, plan_date: dt.date) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM plan_days WHERE plan_date = ?", (plan_date.isoformat(),)
    ).fetchone()


def _to_datetimes(plan_date: dt.date, row: sqlite3.Row) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(plan_date, domain.parse_time(row["start"]))
    end = dt.datetime.combine(plan_date, domain.parse_time(row["end"]))
    if end <= start:
        end += dt.timedelta(days=1)
    return start, end


# --------------------------------------------------------------------------
# Display (wall screen)

def build_display_model(conn: sqlite3.Connection, now: dt.datetime) -> dict:
    """Everything the wall display needs for the operational day containing
    `now`. Shows published plans only (D22)."""
    plan_date = domain.operational_day(now)
    kind = domain.day_kind(plan_date)
    rows = day_assignments(conn, plan_date, published_only=True)

    active, upcoming_times = [], set()
    next_by_employee: dict[str, list] = defaultdict(list)
    for row in rows:
        start, end = _to_datetimes(plan_date, row)
        if start <= now < end:
            active.append((row, start, end))
        elif start > now:
            upcoming_times.add(start)
            next_by_employee[row["employee_id"]].append((start, row))

    next_change = min(upcoming_times) if upcoming_times else None

    def next_move(employee_id: str, current_function: str):
        """The employee's own next segment, if it changes their function."""
        upcoming = sorted(next_by_employee.get(employee_id, []), key=lambda item: item[0])
        if not upcoming:
            return None
        start, row = upcoming[0]
        if row["function_id"] == current_function:
            return None
        return {
            "short_name": row["short_name"],
            "zone_id": row["zone_id"],
            "adhoc": row["staffing_mode"] == "adhoc_zone",
            "time": start.strftime("%H:%M") if next_change and start != next_change else None,
        }

    active_ids = {row["employee_id"] for row, _, _ in active}
    arrivals = []
    if next_change is not None:
        for row in rows:
            start, _ = _to_datetimes(plan_date, row)
            if start == next_change and row["employee_id"] not in active_ids:
                arrivals.append({
                    "display_name": row["display_name"],
                    "function_name": row["function_name"],
                    "zone_id": row["zone_id"],
                })

    zones: list[dict] = []
    for zone in conn.execute("SELECT * FROM zones ORDER BY sort_order"):
        zone_people = []
        for row, _, _ in active:
            if row["zone_id"] != zone["zone_id"]:
                continue
            zone_people.append({
                "display_name": row["display_name"],
                "function_name": row["function_name"],
                "adhoc": row["staffing_mode"] == "adhoc_zone",
                "next": next_move(row["employee_id"], row["function_id"]),
            })
        has_active_functions = conn.execute(
            "SELECT COUNT(*) FROM functions WHERE zone_id = ? AND active = 'yes'",
            (zone["zone_id"],),
        ).fetchone()[0]
        if has_active_functions:
            zones.append({"zone_id": zone["zone_id"], "name": zone["name"],
                          "people": zone_people,
                          "adhoc_zone": all(p["adhoc"] for p in zone_people) and bool(zone_people)})

    # Weekend/holiday: the crew largely self-manages (D21) — show the rostered
    # crew, not only explicit assignments.
    adhoc_crew = []
    if kind == "weekend_holiday":
        for row in conn.execute(
            """SELECT r.employee_id, e.display_name, r.shift_code, s.start, s.end
               FROM roster r JOIN employees e ON e.employee_id = r.employee_id
               JOIN shift_codes s ON s.code = r.shift_code
               WHERE r.date = ? ORDER BY e.display_name""",
            (plan_date.isoformat(),),
        ):
            if row["employee_id"] not in active_ids:
                adhoc_crew.append({"display_name": row["display_name"],
                                   "hours": f"{row['start']}–{row['end']}"})

    return {
        "now": now,
        "plan_date": plan_date,
        "day_kind": kind,
        "zones": zones,
        "next_change": next_change,
        "arrivals": arrivals,
        "adhoc_crew": adhoc_crew,
        "has_plan": bool(rows),
    }


# --------------------------------------------------------------------------
# Planning views (manager)

def monday_of(date: dt.date) -> dt.date:
    return date - dt.timedelta(days=date.weekday())


def _day_status(conn: sqlite3.Connection, date: dt.date) -> dict:
    date_str = date.isoformat()
    plan = plan_day_row(conn, date)
    roster_count = conn.execute(
        "SELECT COUNT(*) FROM roster WHERE date = ?", (date_str,)
    ).fetchone()[0]
    assignment_count = conn.execute(
        "SELECT COUNT(*) FROM assignments WHERE plan_date = ?", (date_str,)
    ).fetchone()[0]
    return {
        "date": date,
        "weekday": WEEKDAYS_NB[date.weekday()],
        "day_kind": domain.day_kind(date),
        "roster_count": roster_count,
        "assignment_count": assignment_count,
        "status": plan["status"] if plan else None,
        "manually_edited": bool(plan["manually_edited"]) if plan else False,
    }


def build_overview_model(conn: sqlite3.Connection, from_date: dt.date, n_weeks: int = 5) -> dict:
    start = monday_of(from_date)
    weeks = []
    for week_index in range(n_weeks):
        monday = start + dt.timedelta(days=7 * week_index)
        days = [_day_status(conn, monday + dt.timedelta(days=i)) for i in range(7)]
        weeks.append({
            "monday": monday,
            "iso_week": monday.isocalendar().week,
            "days": days,
            "has_roster": any(day["roster_count"] for day in days),
            "planned_days": sum(1 for day in days if day["status"]),
            "published_days": sum(1 for day in days if day["status"] == "published"),
        })
    return {"weeks": weeks}


def build_week_model(conn: sqlite3.Connection, monday: dt.date) -> dict:
    """Compact week preview: employees × days, cells showing the day's
    function sequence in short form."""
    days = [_day_status(conn, monday + dt.timedelta(days=i)) for i in range(7)]

    cells: dict[str, dict[str, dict]] = defaultdict(dict)  # employee -> date_str -> cell
    names: dict[str, str] = {}
    for offset in range(7):
        date = monday + dt.timedelta(days=offset)
        date_str = date.isoformat()
        for row in day_assignments(conn, date):
            names[row["employee_id"]] = row["display_name"]
            cell = cells[row["employee_id"]].setdefault(
                date_str, {"parts": [], "locked": False}
            )
            start, _ = _to_datetimes(date, row)
            cell["parts"].append((start, row["short_name"], row["zone_id"]))
            if row["locked"]:
                cell["locked"] = True
        # People rostered but without assignments (e.g. ad hoc weekends).
        for row in conn.execute(
            """SELECT r.employee_id, e.display_name, s.category FROM roster r
               JOIN employees e ON e.employee_id = r.employee_id
               JOIN shift_codes s ON s.code = r.shift_code WHERE r.date = ?""",
            (date_str,),
        ):
            names.setdefault(row["employee_id"], row["display_name"])
            cells[row["employee_id"]].setdefault(
                date_str, {"parts": [], "locked": False, "category": row["category"]}
            )

    employees = []
    for employee_id in sorted(cells, key=lambda e: names.get(e, e)):
        row_cells = []
        for offset in range(7):
            date_str = (monday + dt.timedelta(days=offset)).isoformat()
            cell = cells[employee_id].get(date_str)
            if cell is None:
                row_cells.append(None)
            else:
                parts = sorted(cell["parts"])
                seen, sequence = set(), []
                for _, short_name, zone_id in parts:
                    if short_name not in seen:
                        seen.add(short_name)
                        sequence.append({"short_name": short_name, "zone_id": zone_id})
                row_cells.append({
                    "sequence": sequence,
                    "locked": cell["locked"],
                    "adhoc": not sequence,
                })
        employees.append({"name": names.get(employee_id, employee_id), "cells": row_cells})

    return {
        "monday": monday,
        "iso_week": monday.isocalendar().week,
        "prev_monday": (monday - dt.timedelta(days=7)).isoformat(),
        "next_monday": (monday + dt.timedelta(days=7)).isoformat(),
        "days": days,
        "employees": employees,
    }


def build_day_model(conn: sqlite3.Connection, plan_date: dt.date) -> dict:
    """Manager day view: the whole day as blocks × functions × people."""
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
            entry["people"].append(
                {"name": row["display_name"], "locked": bool(row["locked"])}
            )
        block_list.append({
            "start": start, "end": end,
            "functions": sorted(by_function.values(), key=lambda item: item["order"]),
        })

    # Alternative grouping: per zone -> function, people laid out along the
    # day's timeline (chronological, left to right).
    zone_groups: dict[str, dict] = {}
    for row in rows:
        start, end = _to_datetimes(plan_date, row)
        zone = zone_groups.setdefault(row["zone_id"], {
            "zone_id": row["zone_id"], "zone_name": row["zone_name"],
            "order": row["zone_order"], "functions": {},
        })
        fn = zone["functions"].setdefault(row["function_id"], {
            "function_name": row["function_name"], "order": row["function_order"],
            "entries": [],
        })
        fn["entries"].append({
            "start": start, "end": end,
            "name": row["display_name"], "locked": bool(row["locked"]),
        })
    zone_list = []
    for zone in sorted(zone_groups.values(), key=lambda z: z["order"]):
        functions = sorted(zone["functions"].values(), key=lambda f: f["order"])
        for fn in functions:
            fn["entries"].sort(key=lambda e: (e["start"], e["name"]))
        zone_list.append({**zone, "functions": functions})

    roster_rows = list(conn.execute(
        """SELECT e.display_name, r.shift_code, s.category, s.start, s.end
           FROM roster r JOIN employees e ON e.employee_id = r.employee_id
           JOIN shift_codes s ON s.code = r.shift_code
           WHERE r.date = ? ORDER BY s.start, e.display_name""",
        (plan_date.isoformat(),),
    ))
    status = _day_status(conn, plan_date)
    plan = plan_day_row(conn, plan_date)
    return {
        "zones": zone_list,
        "plan_date": plan_date,
        "weekday": WEEKDAYS_NB[plan_date.weekday()],
        "day_kind": status["day_kind"],
        "status": status["status"],
        "manually_edited": status["manually_edited"],
        "generated_at": plan["generated_at"] if plan else None,
        "blocks": block_list,
        "roster": roster_rows,
        "roster_count": status["roster_count"],
        "has_plan": bool(rows),
        "monday": monday_of(plan_date).isoformat(),
    }


def build_edit_model(conn: sqlite3.Connection, plan_date: dt.date) -> dict:
    """Edit form: every assignment with the functions its employee may hold."""
    eligibility = eligible_functions(conn, plan_date)
    functions = list(conn.execute(
        """SELECT f.function_id, f.name, f.zone_id, z.name AS zone_name
           FROM functions f JOIN zones z ON z.zone_id = f.zone_id
           WHERE f.active = 'yes' ORDER BY f.sort_order"""))

    rows = day_assignments(conn, plan_date)
    blocks: dict[tuple[dt.datetime, dt.datetime], list] = defaultdict(list)
    for row in rows:
        start, end = _to_datetimes(plan_date, row)
        allowed = eligibility.get(row["employee_id"], set())
        options = [
            {"function_id": fn["function_id"],
             "label": f"{fn['name']} ({fn['zone_name']})",
             "eligible": fn["function_id"] in allowed}
            for fn in functions
            if fn["function_id"] in allowed or fn["function_id"] == row["function_id"]
        ]
        blocks[(start, end)].append({
            "assignment_id": row["assignment_id"],
            "display_name": row["display_name"],
            "function_id": row["function_id"],
            "locked": bool(row["locked"]),
            "options": options,
        })

    model = build_day_model(conn, plan_date)
    model["edit_blocks"] = [
        {"start": start, "end": end, "rows": sorted(items, key=lambda r: r["display_name"])}
        for (start, end), items in sorted(blocks.items())
    ]
    return model

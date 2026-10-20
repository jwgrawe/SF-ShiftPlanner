"""Read-side services: eligibility resolution and view models for the pages.

Eligibility (assessment §2.1, D17/D32/D40/D44/D56/D87): an employee may hold
a function iff they have a qualifying competency for it, are not restricted
from it (per-function or heavy-work fritak), the function is on their
preference allowlist when one exists, they work in SF, and the job title they
work under that day doesn't exclude it.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from collections import defaultdict

from app import domain

WEEKDAYS_NB = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]
WEEKDAYS_SHORT_NB = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"]

# Display order and labels for shift categories (D35/D36).
SHIFT_CATEGORY_ORDER = ["tidligvakt", "mellomvakt", "senvakt", "nattevakt", "helgevakt"]
SHIFT_CATEGORY_LABELS = {
    "tidligvakt": "Tidligvakt", "mellomvakt": "Mellomvakt", "senvakt": "Senvakt",
    "nattevakt": "Nattevakt", "helgevakt": "Helgevakt", "": "Ukjent vaktkategori",
}


def rotation_times(conn: sqlite3.Connection) -> dict[str, dt.time | None]:
    return {
        row["category"]: domain.parse_time(row["rotation_time"]) if row["rotation_time"] else None
        for row in conn.execute("SELECT category, rotation_time FROM rotation_rules")
    }


def heavy_function_ids(conn: sqlite3.Connection) -> set[str]:
    """Functions with any intensity > 0 window — the scope of a heavy-work fritak."""
    return {
        row["function_id"]
        for row in conn.execute(
            "SELECT DISTINCT function_id FROM function_intensity WHERE intensity > 0")
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

    # Title rules (D87): «aldri»/«uavklart» exclude every function (those days
    # are also held out of the roster), «begrenset» excludes the listed ones.
    rules = {row["title"]: row["rule"] for row in conn.execute("SELECT title, rule FROM positions")}
    excluded: dict[str, set[str]] = defaultdict(set)
    for row in conn.execute("SELECT title, function_id FROM position_exclusions"):
        excluded[row["title"]].add(row["function_id"])
    titles = {
        row["employee_id"]: row["title"]
        for row in conn.execute(
            "SELECT employee_id, title FROM roster WHERE date = ? AND title IS NOT NULL", (date_str,))
    }

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
        title = titles.get(employee_id)
        rule = rules.get(title) if title else None
        if rule in ("aldri", "uavklart"):
            functions = set()
        elif rule == "begrenset":
            functions -= excluded[title]
        result[employee_id] = functions
    return result


def day_assignments(
    conn: sqlite3.Connection, plan_date: dt.date, published_only: bool = False
) -> list[sqlite3.Row]:
    """Assignments for a day, joined with the employee's roster shift so views
    can group by shift category (tidligvakt/mellomvakt/…)."""
    status_filter = "AND p.status = 'published'" if published_only else ""
    return list(conn.execute(
        f"""SELECT a.*, e.display_name, f.name AS function_name, f.short_name,
                   f.zone_id, f.staffing_mode,
                   z.name AS zone_name, z.sort_order AS zone_order,
                   f.sort_order AS function_order,
                   r.shift_code, COALESCE(r.category_override, sc.category, '') AS shift_category
            FROM assignments a
            JOIN plan_days p ON p.plan_date = a.plan_date
            JOIN employees e ON e.employee_id = a.employee_id
            JOIN functions f ON f.function_id = a.function_id
            JOIN zones z ON z.zone_id = f.zone_id
            LEFT JOIN roster r ON r.date = a.plan_date AND r.employee_id = a.employee_id
            LEFT JOIN shift_codes sc ON sc.code = r.shift_code
            WHERE a.plan_date = ? {status_filter}
            ORDER BY z.sort_order, f.sort_order, a.start, e.display_name""",
        (plan_date.isoformat(),),
    ))


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute(
            """INSERT INTO app_settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )


def day_info(conn: sqlite3.Connection, plan_date: dt.date) -> str:
    """Free-text notice for the day, shown at the foot of the wall display."""
    row = conn.execute(
        "SELECT info FROM day_info WHERE plan_date = ?", (plan_date.isoformat(),)
    ).fetchone()
    return (row["info"] if row else "") or ""


def set_day_info(conn: sqlite3.Connection, plan_date: dt.date, info: str) -> None:
    text = info.strip()
    with conn:
        if text:
            conn.execute(
                """INSERT INTO day_info (plan_date, info, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(plan_date) DO UPDATE SET info = excluded.info,
                                                        updated_at = excluded.updated_at""",
                (plan_date.isoformat(), text, dt.datetime.now().isoformat(timespec="seconds")),
            )
        else:
            conn.execute("DELETE FROM day_info WHERE plan_date = ?", (plan_date.isoformat(),))


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
    `now`. Grouped zone -> function -> employees. Published plans only (D22)."""
    plan_date = domain.operational_day(now)
    kind = domain.day_kind(plan_date)
    rows = day_assignments(conn, plan_date, published_only=True)

    active, upcoming_times = [], set()
    next_by_employee: dict[str, list] = defaultdict(list)
    for row in rows:
        start, end = _to_datetimes(plan_date, row)
        if start <= now < end:
            active.append(row)
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
            "zone_name": row["zone_name"],
            "time": start.strftime("%H:%M") if next_change and start != next_change else None,
        }

    active_ids = {row["employee_id"] for row in active}
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
        functions: dict[str, dict] = {}
        for row in active:
            if row["zone_id"] != zone["zone_id"]:
                continue
            entry = functions.setdefault(row["function_id"], {
                "function_name": row["function_name"],
                "adhoc": row["staffing_mode"] == "adhoc_zone",
                "order": row["function_order"],
                "people": [],
            })
            entry["people"].append({
                "display_name": row["display_name"],
                "next": next_move(row["employee_id"], row["function_id"]),
            })
        function_list = sorted(functions.values(), key=lambda f: f["order"])
        has_active_functions = conn.execute(
            "SELECT COUNT(*) FROM functions WHERE zone_id = ? AND active = 'yes'",
            (zone["zone_id"],),
        ).fetchone()[0]
        if has_active_functions:
            zones.append({
                "zone_id": zone["zone_id"], "name": zone["name"],
                "functions": function_list,
                "adhoc_zone": bool(function_list) and all(f["adhoc"] for f in function_list),
            })

    # Weekend/holiday: the crew largely self-manages (D21) — show the rostered
    # crew, not only explicit assignments.
    adhoc_crew = []
    if kind == "weekend_holiday":
        for row in conn.execute(
            """SELECT r.employee_id, e.display_name, r.shift_code,
                      COALESCE(r.start_override, s.start) AS start,
                      COALESCE(r.end_override, s.end) AS end
               FROM roster r JOIN employees e ON e.employee_id = r.employee_id
               JOIN shift_codes s ON s.code = r.shift_code
               WHERE r.date = ? AND r.hold IS NULL AND s.utpost_code <> 'yes'
               ORDER BY e.display_name""",
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
        "day_info": day_info(conn, plan_date),
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
        "SELECT COUNT(*) FROM roster WHERE date = ? AND hold IS NULL", (date_str,)
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


def day_status(conn: sqlite3.Connection, date: dt.date) -> dict:
    """Public wrapper: one day's roster/plan state."""
    return _day_status(conn, date)


def build_overview_model(conn: sqlite3.Connection, from_date: dt.date, n_weeks: int = 5) -> dict:
    start = monday_of(from_date)
    weeks = []
    for week_index in range(n_weeks):
        monday = start + dt.timedelta(days=7 * week_index)
        days = [_day_status(conn, monday + dt.timedelta(days=i)) for i in range(7)]
        weeks.append({
            "monday": monday,
            "iso_week": monday.isocalendar().week,
            "sources": week_sources(conn, monday),
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
            """SELECT r.employee_id, e.display_name,
                      COALESCE(r.category_override, s.category) AS category FROM roster r
               JOIN employees e ON e.employee_id = r.employee_id
               JOIN shift_codes s ON s.code = r.shift_code
               WHERE r.date = ? AND r.hold IS NULL""",
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
        employees.append({
            "employee_id": employee_id,
            "name": names.get(employee_id, employee_id),
            "cells": row_cells,
        })

    return {
        "monday": monday,
        "iso_week": monday.isocalendar().week,
        "prev_monday": (monday - dt.timedelta(days=7)).isoformat(),
        "next_monday": (monday + dt.timedelta(days=7)).isoformat(),
        "days": days,
        "employees": employees,
    }


def _timeline_axis(
    conn: sqlite3.Connection, plan_date: dt.date, spans: list[tuple[dt.datetime, dt.datetime]]
) -> dict | None:
    """Time axis for the swimlane view: hour ticks, rotation marks and the
    30-minute grid, all as percentages of the day's actual span."""
    if not spans:
        return None
    axis_start = min(start for start, _ in spans)
    axis_end = max(end for _, end in spans)
    total = (axis_end - axis_start).total_seconds() / 60
    if total <= 0:
        return None

    def pct(when: dt.datetime) -> float:
        return (when - axis_start).total_seconds() / 60 / total * 100

    step = 1 if total <= 12 * 60 else 2
    ticks = []
    cursor = axis_start.replace(minute=0, second=0, microsecond=0)
    if cursor < axis_start:
        cursor += dt.timedelta(hours=1)
    while cursor <= axis_end:
        if cursor.hour % step == 0:
            ticks.append({"label": cursor.strftime("%H"), "pct": round(pct(cursor), 4)})
        cursor += dt.timedelta(hours=1)

    # Rotation markers (D35): mellomvakt's 16:00 is drawn subtler than the
    # main 11:00/18:00 points, since only mid shifts use it.
    marks: dict[dt.datetime, dict] = {}
    for row in conn.execute(
        """SELECT category, rotation_time FROM rotation_rules
           WHERE rotation_time IS NOT NULL AND rotation_time <> ''"""
    ):
        rotation = domain.parse_time(row["rotation_time"])
        kind = "secondary" if row["category"] == "mellomvakt" else "primary"
        for day_offset in (0, 1):
            when = dt.datetime.combine(plan_date + dt.timedelta(days=day_offset), rotation)
            if axis_start < when < axis_end:
                existing = marks.get(when)
                if existing is None or kind == "primary":
                    marks[when] = {
                        "pct": round(pct(when), 4), "label": when.strftime("%H:%M"), "kind": kind,
                    }
    return {
        "start": axis_start, "end": axis_end, "total_minutes": total,
        "ticks": ticks,
        "marks": [marks[key] for key in sorted(marks)],
        "segment_pct": round(30 / total * 100, 4),
    }


def build_day_model(conn: sqlite3.Connection, plan_date: dt.date) -> dict:
    """Manager day view, in two shapes: grouped per zone as a timeline
    (default), and grouped by shift category → time block."""
    rows = day_assignments(conn, plan_date)
    spans = {row["assignment_id"]: _to_datetimes(plan_date, row) for row in rows}
    axis = _timeline_axis(conn, plan_date, list(spans.values()))

    # Every assignment the employee holds that day, so a bar's ends can say
    # whether they mark a rotation to/from another function or the shift edge.
    per_employee: dict[str, list[tuple[dt.datetime, dt.datetime, str]]] = defaultdict(list)
    for row in rows:
        start, end = spans[row["assignment_id"]]
        per_employee[row["employee_id"]].append((start, end, row["function_id"]))

    function_names = {row["function_id"]: row["function_name"] for row in rows}

    def edge(employee_id: str, when: dt.datetime, function_id: str, side: str
             ) -> tuple[str, str | None]:
        """The meaning of one end of a bar: 'rotation' (changes function here,
        with the other function's name), 'same' (continues in the same
        function) or 'shift' (start/end of the working day)."""
        for other_start, other_end, other_function in per_employee[employee_id]:
            neighbour = other_end if side == "from" else other_start
            if neighbour == when:
                if other_function == function_id:
                    return "same", None
                return "rotation", function_names.get(other_function, other_function)
        return "shift", None

    def bar(row) -> dict:
        start, end = spans[row["assignment_id"]]
        left = (start - axis["start"]).total_seconds() / 60 / axis["total_minutes"] * 100
        width = (end - start).total_seconds() / 60 / axis["total_minutes"] * 100
        employee_id, function_id = row["employee_id"], row["function_id"]
        from_kind, from_function = edge(employee_id, start, function_id, "from")
        to_kind, to_function = edge(employee_id, end, function_id, "to")
        return {
            "left": round(left, 4), "width": round(width, 4),
            "start": start, "end": end, "locked": bool(row["locked"]),
            "label": f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}",
            "from_kind": from_kind, "from_function": from_function,
            "to_kind": to_kind, "to_function": to_function,
        }

    # --- shape 1: zone -> function -> one row per employee (timeline)
    zone_groups: dict[str, dict] = {}
    for row in rows:
        zone = zone_groups.setdefault(row["zone_id"], {
            "zone_id": row["zone_id"], "zone_name": row["zone_name"],
            "order": row["zone_order"], "functions": {},
        })
        fn = zone["functions"].setdefault(row["function_id"], {
            "function_name": row["function_name"], "order": row["function_order"],
            "people": {},
        })
        person = fn["people"].setdefault(row["employee_id"], {
            "employee_id": row["employee_id"], "name": row["display_name"], "bars": [],
        })
        if axis:
            person["bars"].append(bar(row))

    zone_list = []
    for zone in sorted(zone_groups.values(), key=lambda z: z["order"]):
        functions = []
        for fn in sorted(zone["functions"].values(), key=lambda f: f["order"]):
            people = []
            for person in fn["people"].values():
                person["bars"].sort(key=lambda b: b["start"])
                people.append(person)
            people.sort(key=lambda p: (p["bars"][0]["start"] if p["bars"] else dt.datetime.max,
                                       p["name"]))
            functions.append({"function_name": fn["function_name"], "people": people})
        zone_list.append({
            "zone_id": zone["zone_id"], "zone_name": zone["zone_name"], "functions": functions,
        })

    # --- shape 2: shift category -> time block -> function -> people
    by_category: dict[str, dict] = {}
    for row in rows:
        start, end = spans[row["assignment_id"]]
        category = row["shift_category"] or ""
        group = by_category.setdefault(category, {})
        block = group.setdefault((start, end), {})
        entry = block.setdefault(row["function_id"], {
            "function_name": row["function_name"], "zone_name": row["zone_name"],
            "zone_id": row["zone_id"], "order": (row["zone_order"], row["function_order"]),
            "people": [],
        })
        entry["people"].append({"name": row["display_name"], "locked": bool(row["locked"])})

    category_list = []
    for category in sorted(
        by_category,
        key=lambda c: SHIFT_CATEGORY_ORDER.index(c) if c in SHIFT_CATEGORY_ORDER else 99,
    ):
        blocks = [
            {"start": start, "end": end,
             "functions": sorted(block.values(), key=lambda item: item["order"])}
            for (start, end), block in sorted(by_category[category].items())
        ]
        category_list.append({
            "category": category,
            "label": SHIFT_CATEGORY_LABELS.get(category, category.capitalize()),
            "blocks": blocks,
        })

    roster_rows = list(conn.execute(
        """SELECT e.display_name, r.shift_code,
                  COALESCE(r.category_override, s.category) AS category,
                  COALESCE(r.start_override, s.start) AS start,
                  COALESCE(r.end_override, s.end) AS end, r.end_override, r.hold, r.title,
                  r.raw, r.source, s.utpost_code, NULL AS pending
           FROM roster r JOIN employees e ON e.employee_id = r.employee_id
           JOIN shift_codes s ON s.code = r.shift_code
           WHERE r.date = ?
           UNION ALL
           SELECT e.display_name, p.raw, '', '', '', NULL, NULL, NULL, p.raw, p.source, 'no',
                  p.reason
           FROM roster_pending p JOIN employees e ON e.employee_id = p.employee_id
           WHERE p.date = ?
           ORDER BY 4, 1""",
        (plan_date.isoformat(), plan_date.isoformat()),
    ))
    status = _day_status(conn, plan_date)
    plan = plan_day_row(conn, plan_date)
    return {
        "zones": zone_list,
        "axis": axis,
        "categories": category_list,
        "plan_date": plan_date,
        "weekday": WEEKDAYS_NB[plan_date.weekday()],
        "day_kind": status["day_kind"],
        "status": status["status"],
        "manually_edited": status["manually_edited"],
        "generated_at": plan["generated_at"] if plan else None,
        "roster": roster_rows,
        "roster_count": status["roster_count"],
        "has_plan": bool(rows),
        "day_info": day_info(conn, plan_date),
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


def employee_options(conn: sqlite3.Connection, plan_date: dt.date) -> list[sqlite3.Row]:
    """Everyone rostered that day — the candidate list for absence reporting."""
    return list(conn.execute(
        """SELECT r.employee_id, e.display_name, r.shift_code
           FROM roster r JOIN employees e ON e.employee_id = r.employee_id
           WHERE r.date = ? AND r.hold IS NULL ORDER BY e.display_name""",
        (plan_date.isoformat(),),
    ))


def build_person_model(
    conn: sqlite3.Connection, employee_id: str, first: dt.date, last: dt.date
) -> dict | None:
    """One employee's period: shifts, placements and rotation pattern.
    Preferences and fritak are deliberately absent — those live only in the
    admin view (D32/D11)."""
    employee = conn.execute(
        "SELECT * FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
    if employee is None:
        return None

    competencies = [
        {"name": row["name"], "status": row["status"]}
        for row in conn.execute(
            """SELECT ct.name, ec.status FROM employee_competencies ec
               JOIN competency_types ct ON ct.competency_id = ec.competency_id
               WHERE ec.employee_id = ? ORDER BY ct.name""", (employee_id,))
    ]

    shifts = {
        row["date"]: row["shift_code"]
        for row in conn.execute(
            "SELECT date, shift_code FROM roster WHERE employee_id = ? AND date BETWEEN ? AND ?",
            (employee_id, first.isoformat(), last.isoformat()))
    }
    placements: dict[str, list] = defaultdict(list)
    for row in conn.execute(
        """SELECT a.plan_date, a.start, a.end, a.locked, f.name AS function_name,
                  f.zone_id, f.sort_order
           FROM assignments a JOIN functions f ON f.function_id = a.function_id
           WHERE a.employee_id = ? AND a.plan_date BETWEEN ? AND ?
           ORDER BY a.plan_date, a.start""",
        (employee_id, first.isoformat(), last.isoformat()),
    ):
        placements[row["plan_date"]].append({
            "function_name": row["function_name"], "zone_id": row["zone_id"],
            "span": f"{row['start']}–{row['end']}", "locked": bool(row["locked"]),
        })
    absences = {
        row["date"]: row["type"]
        for row in conn.execute(
            "SELECT date, type FROM absences WHERE employee_id = ? AND date BETWEEN ? AND ?",
            (employee_id, first.isoformat(), last.isoformat()))
    }

    days = []
    cursor = first
    while cursor <= last:
        key = cursor.isoformat()
        if key in shifts or key in placements or key in absences:
            days.append({
                "date": cursor,
                "weekday": WEEKDAYS_SHORT_NB[cursor.weekday()],
                "shift_code": shifts.get(key),
                "placements": placements.get(key, []),
                "absence": absences.get(key),
            })
        cursor += dt.timedelta(days=1)

    return {
        "employee": employee,
        "competencies": competencies,
        "days": days,
        "first": first,
        "last": last,
    }


# --------------------------------------------------------------------------
# Data sources (real mode): which turnus/ukeplan each week rests on (D75)

def week_sources(conn: sqlite3.Connection, monday: dt.date) -> dict:
    """The newest turnus and ukeplan behind one week."""
    first, last = monday.isoformat(), (monday + dt.timedelta(days=6)).isoformat()
    plan = conn.execute(
        """SELECT * FROM import_files WHERE kind = 'plan' AND status = 'active'
           AND first_date <= ? AND last_date >= ? ORDER BY exported_at DESC LIMIT 1""",
        (last, first)).fetchone()
    full_plan = plan is not None and plan["first_date"] <= first and plan["last_date"] >= last
    ukeplan = conn.execute(
        """SELECT * FROM import_files WHERE kind = 'ajourhold' AND status = 'active'
           AND first_date = ? ORDER BY exported_at DESC LIMIT 1""", (first,)).fetchone()
    return {
        "plan": plan, "plan_full": full_plan, "ukeplan": ukeplan,
        "ukeplan_at": dt.datetime.fromisoformat(ukeplan["exported_at"]) if ukeplan else None,
    }


def import_findings(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM import_findings ORDER BY finding_id"))


def build_import_model(conn: sqlite3.Connection, today: dt.date) -> dict:
    monday = monday_of(today)
    weeks = []
    for offset in range(-1, 9):
        start = monday + dt.timedelta(days=7 * offset)
        sources = week_sources(conn, start)
        on_duty = conn.execute(
            "SELECT COUNT(DISTINCT employee_id) FROM roster WHERE date BETWEEN ? AND ? "
            "AND hold IS NULL",
            (start.isoformat(), (start + dt.timedelta(days=6)).isoformat())).fetchone()[0]
        weeks.append({"monday": start, "sunday": start + dt.timedelta(days=6),
                      "iso_week": start.isocalendar().week,
                      "current": offset == 0, "past": offset < 0, "on_duty": on_duty,
                      **sources})
    files = []
    for row in conn.execute("SELECT * FROM import_files ORDER BY imported_at DESC, file_id DESC"):
        files.append({
            **dict(row),
            "exported": dt.datetime.fromisoformat(row["exported_at"]) if row["exported_at"] else None,
            "imported": dt.datetime.fromisoformat(row["imported_at"]),
            "first": dt.date.fromisoformat(row["first_date"]) if row["first_date"] else None,
            "last": dt.date.fromisoformat(row["last_date"]) if row["last_date"] else None,
            "reasons": (row["reason"] or "").splitlines(),
        })
    log = [{"at": dt.datetime.fromisoformat(r["at"]), "text": r["text"]} for r in conn.execute(
        "SELECT at, text FROM import_log WHERE area = 'import' ORDER BY log_id DESC LIMIT 100")]
    pending = [
        {**dict(r), "date": dt.date.fromisoformat(r["date"])}
        for r in conn.execute(
            """SELECT p.date, p.raw, p.reason, p.fixable, p.employee_id, e.display_name
               FROM roster_pending p JOIN employees e ON e.employee_id = p.employee_id
               WHERE p.date >= ? ORDER BY p.date, e.display_name""", (today.isoformat(),))
    ]
    manual = [
        {**dict(r), "date": dt.date.fromisoformat(r["export_date"])}
        for r in conn.execute(
            """SELECT m.*, e.display_name FROM manual_shift_times m
               JOIN employees e ON e.employee_id = m.employee_id
               WHERE m.export_date >= ? ORDER BY m.export_date, e.display_name""",
            (today.isoformat(),))
    ]
    return {"weeks": weeks, "files": files, "log": log, "pending": pending, "manual": manual,
            "findings": import_findings(conn),
            "built_at": get_setting(conn, "roster_built_at", "")}


def positions_model(conn: sqlite3.Connection) -> list[dict]:
    exclusions: dict[str, set[str]] = defaultdict(set)
    for row in conn.execute("SELECT title, function_id FROM position_exclusions"):
        exclusions[row["title"]].add(row["function_id"])
    counts = {row["title"]: row["n"] for row in conn.execute(
        "SELECT title, COUNT(DISTINCT employee_id) AS n FROM roster WHERE title IS NOT NULL "
        "GROUP BY title")}
    return [
        {**dict(row), "excluded": exclusions[row["title"]], "people": counts.get(row["title"], 0)}
        for row in conn.execute(
            "SELECT * FROM positions ORDER BY rule = 'uavklart' DESC, title")
    ]

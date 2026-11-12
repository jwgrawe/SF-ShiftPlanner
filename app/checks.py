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

from app import contingency, domain, exposure, planner, service


def rotation_misses(conn: sqlite3.Connection, plan_date: dt.date) -> list[dict]:
    """People who should have gone across at the rotation point (D107) but
    stayed on the same side – a light notice, since the swap is for their
    sake. Reason: they can't work on the other side (competency, fritak or
    preference), or there were too few on the other side to swap with."""
    swaps = service.rotation_swaps(conn)
    if not swaps:
        return []
    date_str = plan_date.isoformat()
    names = {r["function_id"]: r["name"] for r in conn.execute("SELECT function_id, name FROM functions")}
    people = {r["employee_id"]: r["display_name"] for r in conn.execute(
        "SELECT employee_id, display_name FROM employees")}
    eligibility = service.eligible_functions(conn, plan_date)
    qualified: dict[str, set[str]] = {}
    for r in conn.execute("SELECT employee_id, competency_id FROM employee_competencies "
                          "WHERE status = 'qualified'"):
        qualified.setdefault(r["employee_id"], set()).add(r["competency_id"])
    accepts: dict[str, set[str]] = {}
    for r in conn.execute("SELECT function_id, competency_id FROM function_competencies"):
        accepts.setdefault(r["function_id"], set()).add(r["competency_id"])
    rows = list(conn.execute(
        "SELECT employee_id, function_id, start, end FROM assignments WHERE plan_date = ? "
        "ORDER BY employee_id, start", (date_str,)))
    grouped: dict[tuple[str, str, str], list[str]] = {}
    for before, after in zip(rows, rows[1:]):
        if before["employee_id"] != after["employee_id"] or before["end"] != after["start"]:
            continue
        for swap in swaps:
            if before["function_id"] in swap["a"] and after["function_id"] in swap["a"]:
                e = before["employee_id"]
                other = " / ".join(sorted(names.get(f, f) for f in swap["b"]))
                if swap["b"] & eligibility.get(e, set()):
                    reason = f"for få på {other} å bytte med"
                elif not any(accepts.get(f, set()) & qualified.get(e, set()) for f in swap["b"]):
                    reason = f"mangler kompetanse for {other}"
                else:
                    reason = f"fritak eller preferanse hindrer {other}"
                grouped.setdefault((after["start"], swap["name"], reason), []).append(
                    people.get(e, e))
                break
    return [{"level": "info", "kind": "no_rotation", "date": plan_date,
             "text": f"Rullerer ikke kl. {at} ({swap_name}): {', '.join(sorted(who))} – {reason}."}
            for (at, swap_name, reason), who in sorted(grouped.items())]


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
    return exposure.week_occurrences(conn, monday, exposure.settings(conn)["threshold"])


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
    choice = contingency.values(conn)
    if plan is not None and plan["status"] != "published" and choice["N1"] != "av":
        findings.append({"level": "info", "kind": "draft", "date": plan_date,
                         "text": "Planen er et utkast – den vises ikke på tavlen før den publiseres."})

    names = {row["function_id"]: row["name"] for row in conn.execute(
        "SELECT function_id, name FROM functions")}
    zone_names = {row["zone_id"]: row["name"] for row in conn.execute(
        "SELECT zone_id, name FROM zones")}
    coverage = _coverage(conn, plan_date)
    lead_functions = {r[0] for r in conn.execute(
        "SELECT function_id FROM functions WHERE COALESCE(lead_codes, '') <> ''")}

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
        # A function with lead codes (DK/DKK → DK/ansvarsvakt) is the one
        # that must never be empty (D41/D57/D109).
        is_lead = bool(set(function_ids) & lead_functions)
        findings.append({
            "level": "alert" if is_lead else "warn",
            "kind": "shortfall", "date": plan_date,
            "text": (f"Ingen på {label} kl. {_hour_ranges(missing)}."
                     if is_lead else
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

    # Placed but not (or no longer) on duty, or outside their shift's hours —
    # e.g. a newer ukeplan changed the shift after the plan was made (D93).
    shifts = planner.day_shifts(conn, plan_date)
    off_duty, moved = set(), set()
    for row in conn.execute(
        """SELECT a.employee_id, a.start, a.end, e.display_name FROM assignments a
           JOIN employees e ON e.employee_id = a.employee_id WHERE a.plan_date = ?""",
        (date_str,),
    ):
        shift = shifts.get(row["employee_id"])
        if shift is None:
            off_duty.add(row["display_name"])
            continue
        s_start = dt.datetime.combine(plan_date, domain.parse_time(shift["start"]))
        s_end = dt.datetime.combine(plan_date, domain.parse_time(shift["end"]))
        if s_end <= s_start:
            s_end += dt.timedelta(days=1)
        a_start = dt.datetime.combine(plan_date, domain.parse_time(row["start"]))
        a_end = dt.datetime.combine(plan_date, domain.parse_time(row["end"]))
        if a_end <= a_start:
            a_end += dt.timedelta(days=1)
        if a_start < s_start or a_end > s_end:
            moved.add(row["display_name"])
    if off_duty:
        findings.append({"level": "alert", "kind": "off_duty", "date": plan_date,
                         "text": f"I planen, men ikke på vakt (lenger): {', '.join(sorted(off_duty))}."})
    if moved:
        findings.append({"level": "warn", "kind": "shift_changed", "date": plan_date,
                         "text": f"Vakttiden er endret etter at planen ble laget for "
                                 f"{', '.join(sorted(moved))} – lag forslag på nytt."})

    # On duty without a placement for some or all of the shift (weekdays, or
    # weekends when they are planned in full – D21, P6).
    if day_type == "weekday" or choice["P6"] == "full":
        covered: dict[str, list[tuple[dt.datetime, dt.datetime]]] = {}
        for row in conn.execute("SELECT employee_id, start, end FROM assignments WHERE plan_date = ?",
                                (date_str,)):
            a = dt.datetime.combine(plan_date, domain.parse_time(row["start"]))
            b = dt.datetime.combine(plan_date, domain.parse_time(row["end"]))
            covered.setdefault(row["employee_id"], []).append((a, b if b > a else b + dt.timedelta(days=1)))
        idle = []
        names_by_id = {r["employee_id"]: r["display_name"] for r in conn.execute(
            "SELECT employee_id, display_name FROM employees")}
        for e, shift in shifts.items():
            s_start = dt.datetime.combine(plan_date, domain.parse_time(shift["start"]))
            s_end = dt.datetime.combine(plan_date, domain.parse_time(shift["end"]))
            if s_end <= s_start:
                s_end += dt.timedelta(days=1)
            gaps, cursor = [], s_start
            for a, b in sorted(covered.get(e, [])):
                if a > cursor:
                    gaps.append((cursor, a))
                cursor = max(cursor, b)
            if cursor < s_end:
                gaps.append((cursor, s_end))
            if gaps and e in names_by_id:
                when = "" if gaps == [(s_start, s_end)] else " (" + ", ".join(
                    f"{a:%H:%M}–{b:%H:%M}" for a, b in gaps) + ")"
                idle.append(names_by_id[e] + when)
        level = contingency.finding_level(conn, "N2", choice)
        if idle and level:
            findings.append({"level": level, "kind": "unplanned", "date": plan_date,
                             "text": f"På vakt uten plassering: {', '.join(sorted(idle))}."})

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
    # Over the weekly target – the soft rule gave way to rotation or a fixed
    # place (P3); shown so the managers see it (P3N).
    target = int(settings.get("heavy_occurrence_target_per_week", 1))
    above = sorted(f"{row['display_name']} ({counts[row['employee_id']]})"
                   for row in conn.execute("SELECT employee_id, display_name FROM employees")
                   if row["employee_id"] in roster and target < counts.get(row["employee_id"], 0) <= cap)
    level = contingency.finding_level(conn, "P3N", choice)
    if above and level:
        findings.append({"level": level, "kind": "heavy_target", "date": plan_date,
                         "text": f"Over ukemålet på {target} tung{'e' if target != 1 else ''} dag"
                                 f"{'er' if target != 1 else ''}: {', '.join(above)}."})

    level = contingency.finding_level(conn, "P4", choice)
    if level:
        findings.extend({**f, "level": level} for f in rotation_misses(conn, plan_date))

    order = {"alert": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: order[f["level"]])
    return findings


def intensity_hours(
    conn: sqlite3.Connection, employee_id: str, first: dt.date, last: dt.date
) -> float:
    """Weighted heavy-exposure hours (D52): sum of intensity × hours actually
    spent in each function's intensity windows."""
    return round(exposure.ledger(conn, first, last).get(employee_id, 0.0), 1)

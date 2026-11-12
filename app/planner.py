"""Plan suggestion, v1: an hour-by-hour filler with the zone swap.

Not yet the full M3 engine — no weekly heavy-exposure balancing or
intensity ledger in the choice of people. It does respect:

- the eligibility formula (competency + preferences + restrictions + works_at),
- roster presence per block (shift codes cut at each category's rotation time),
- U-coded roster days (excluded from SF planning, D55),
- roster days held out by a title or code rule (D87/D103) and F3-shortened shifts (D92),
- full-day absences,
- shift codes that lead to a function (DK/DKK → DK/ansvarsvakt, D41),
- the zone swap (D107): at the rotation point the people on one side of a
  swap rule (uren sone) move to the other (arbeidsbord) and that side's
  people take their place. Whoever can't go across (competency, fritak)
  stays where they were; checks.py points it out,
- continuity: someone on a function outside the swap keeps it after the
  rotation point while it is still needed (Kontrollsone, Sterrad, DK, steril),
- locked assignments: regeneration plans around them and never touches them (D22).

Nothing department-specific is written here (D109): fill order, lead codes,
zone remainders and swap rules all come from the data.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from collections import defaultdict

from app import domain, service

def segment_hours(segment: domain.Segment) -> list[int]:
    hours, cursor = [], segment.start
    while cursor < segment.end:
        hours.append(cursor.hour)
        cursor += dt.timedelta(hours=1)
    return hours


def load_demand(conn: sqlite3.Connection, day_type: str):
    required: dict[str, dict[int, int]] = defaultdict(dict)
    zone_total: dict[str, dict[int, int]] = defaultdict(dict)
    for row in conn.execute(
        "SELECT * FROM staffing_demand WHERE day_type = ? AND category = 'normal'", (day_type,)
    ):
        if row["row_type"] == "function":
            required[row["function_ids"]][row["hour"]] = row["required"]
        elif row["row_type"] == "function_group":
            # Combined demand (Q20) is booked on the group's first member.
            required[row["function_ids"].split(";")[0]][row["hour"]] = row["required"]
        elif row["row_type"] == "zone_total":
            zone_total[row["zone_id"]][row["hour"]] = row["required"]
    return required, zone_total


def day_shifts(conn: sqlite3.Connection, date: dt.date) -> dict[str, dict]:
    """employee_id -> {code, start, end, category} for everyone SF can plan
    that day. Left out: U-coded days (D55), full-day absences, and roster days
    held out by a job-title rule (D87). `end` honours an F3 short day (D92)."""
    date_str = date.isoformat()
    absent = {
        row["employee_id"]
        for row in conn.execute(
            "SELECT employee_id FROM absences WHERE date = ? AND (start IS NULL OR start = '')",
            (date_str,),
        )
    }
    shifts = {}
    for row in conn.execute(
        """SELECT r.employee_id, r.shift_code, r.hold, r.end_override,
                  COALESCE(r.start_override, s.start) AS start, s.end,
                  COALESCE(r.category_override, s.category) AS category,
                  s.utpost_code FROM roster r
           JOIN shift_codes s ON s.code = r.shift_code WHERE r.date = ?""",
        (date_str,),
    ):
        if row["utpost_code"] == "yes" or row["employee_id"] in absent or row["hold"]:
            continue
        shifts[row["employee_id"]] = {
            "code": row["shift_code"], "start": row["start"],
            "end": row["end_override"] or row["end"], "category": row["category"],
        }
    return shifts


def day_roster(conn: sqlite3.Connection, date: dt.date) -> dict[str, str]:
    """employee_id -> shift_code for everyone SF can plan that day."""
    return {employee_id: shift["code"] for employee_id, shift in day_shifts(conn, date).items()}


def plan_structure(conn: sqlite3.Connection) -> dict:
    """What the department's data says about filling a day (D109)."""
    functions = list(conn.execute(
        "SELECT * FROM functions WHERE active = 'yes' ORDER BY sort_order"))
    zone_order = [r[0] for r in conn.execute("SELECT zone_id FROM zones ORDER BY sort_order")]
    total_zones = {r[0] for r in conn.execute(
        "SELECT DISTINCT zone_id FROM staffing_demand WHERE row_type = 'zone_total' "
        "AND category = 'normal' AND zone_id IS NOT NULL")}
    zone_fill = {}
    for zone in zone_order:
        if zone in total_zones:
            fill = next((f["function_id"] for f in functions if f["zone_id"] == zone
                         and f["staffing_mode"] in ("remainder", "adhoc_zone")), None)
            if fill:
                zone_fill[zone] = fill
    remainder = next((f["function_id"] for f in functions if f["staffing_mode"] == "remainder"
                      and f["zone_id"] not in zone_fill), None)
    return {
        "zone_of": {f["function_id"]: f["zone_id"] for f in functions},
        "fill_order": [f["function_id"] for f in sorted(
            (f for f in functions if f["fill_priority"] is not None),
            key=lambda f: f["fill_priority"])],
        "lead_codes": {f["function_id"]: set((f["lead_codes"] or "").split(";")) - {""}
                       for f in functions},
        "zone_fill": zone_fill,
        "remainder": remainder,
    }


def swap_maps(conn: sqlite3.Connection) -> tuple[dict, dict, set]:
    """(leave_to, pulls, on_swap) from the active swap rules: side-A function
    -> where its people go; function -> whose people it draws first; every
    function in a swap."""
    leave_to: dict[str, set[str]] = defaultdict(set)
    pulls: dict[str, set[str]] = defaultdict(set)
    on_swap: set[str] = set()
    for swap in service.rotation_swaps(conn):
        for f in swap["a"]:
            leave_to[f] |= swap["b"]
            pulls[f] |= swap["b"]
        for f in swap["b"]:
            pulls[f] |= swap["a"]
        on_swap |= swap["a"] | swap["b"]
    return leave_to, pulls, on_swap


def suggest_day(conn: sqlite3.Connection, date: dt.date, source: str = "forslag") -> int:
    """(Re)generate the suggestion for one day. Locked assignments are kept
    and planned around; all other assignments for the day are replaced.
    Returns the number of assignments written (locked ones excluded)."""
    date_str = date.isoformat()
    day_type = domain.day_kind(date)
    shifts = day_shifts(conn, date)
    roster = {employee_id: shift["code"] for employee_id, shift in shifts.items()}
    required, zone_total = load_demand(conn, day_type)
    eligibility = service.eligible_functions(conn, date)
    rotations = service.rotation_times(conn)
    plan = plan_structure(conn)
    leave_to, pulls, on_swap = swap_maps(conn)
    zone_functions: dict[str, list[str]] = defaultdict(list)
    for function_id, zone in plan["zone_of"].items():
        zone_functions[zone].append(function_id)

    groups: dict[domain.Segment, list[str]] = defaultdict(list)
    for employee_id, shift in shifts.items():
        for segment in domain.shift_segments(
            date, domain.parse_time(shift["start"]), domain.parse_time(shift["end"]),
            rotations.get(shift["category"]),
        ):
            groups[segment].append(employee_id)

    coverage: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    assigned: dict[tuple[str, dt.datetime], str] = {}
    segment_end: dict[tuple[str, dt.datetime], dt.datetime] = {}
    ends: dict[tuple[str, dt.datetime], str] = {}   # (person, end) -> function: the block before

    def register(employee_id: str, segment: domain.Segment, function_id: str) -> None:
        assigned[(employee_id, segment.start)] = function_id
        segment_end[(employee_id, segment.start)] = segment.end
        ends[(employee_id, segment.end)] = function_id
        for hour in segment_hours(segment):
            coverage[function_id][hour] += 1

    # Locked assignments are fixed points: seed coverage from them, plan around.
    locked_keys: set[tuple[str, dt.datetime]] = set()
    for row in conn.execute(
        "SELECT * FROM assignments WHERE plan_date = ? AND locked = 1", (date_str,)
    ):
        start = dt.datetime.combine(date, domain.parse_time(row["start"]))
        end = dt.datetime.combine(date, domain.parse_time(row["end"]))
        if end <= start:
            end += dt.timedelta(days=1)
        segment = domain.Segment(start, end)
        register(row["employee_id"], segment, row["function_id"])
        locked_keys.add((row["employee_id"], start))

    def free_people(segment: domain.Segment) -> list[str]:
        return sorted(e for e in groups[segment] if (e, segment.start) not in assigned)

    for segment in sorted(groups, key=lambda s: (s.start, s.end)):
        hours = segment_hours(segment)

        def short(function_id: str) -> int:
            return max((required.get(function_id, {}).get(h, 0) - coverage[function_id][h]
                        for h in hours), default=0)

        def zone_short(zone: str) -> int:
            return max((zone_total.get(zone, {}).get(h, 0)
                        - sum(coverage[f][h] for f in zone_functions[zone]) for h in hours),
                       default=0)

        prev = {e: ends.get((e, segment.start)) for e in groups[segment]}
        must_leave = {e: leave_to[p] for e, p in prev.items() if p in leave_to}
        stuck = {e for e, targets in must_leave.items()
                 if not targets & eligibility.get(e, set())}

        def rank(e: str, function_id: str) -> int:
            """0 = drawn here by a swap, 1 = new on duty, 2 = other,
            3 = should go across instead (taken only if nobody else can)."""
            p = prev.get(e)
            if e in must_leave and function_id not in must_leave[e]:
                return 3
            if p is not None and p in pulls.get(function_id, ()):
                return 0
            return 1 if p is None else 2

        # 0) Continuity: who can't cross over stays put; functions outside the
        #    swap keep their people while still needed.
        for e in free_people(segment):
            p = prev.get(e)
            if p is None or p not in eligibility.get(e, set()):
                continue
            if e in stuck:
                register(e, segment, p)
            elif p in on_swap:
                continue
            elif p in plan["fill_order"] and short(p) > 0:
                register(e, segment, p)
            elif p in plan["zone_fill"].values() and zone_short(plan["zone_of"][p]) > 0:
                register(e, segment, p)
        # 1) Demand functions, in the department's fill order.
        for function_id in plan["fill_order"]:
            needed = short(function_id)
            if needed <= 0:
                continue
            lead = plan["lead_codes"].get(function_id, set())
            candidates = [e for e in free_people(segment) if function_id in eligibility.get(e, set())]
            candidates.sort(key=lambda e: (roster.get(e) not in lead, rank(e, function_id), e))
            for employee_id in candidates[:needed]:
                register(employee_id, segment, function_id)
        # 2) Zone totals -> each zone's own remainder (Produksjon uren/steril).
        for zone, function_id in plan["zone_fill"].items():
            needed = zone_short(zone)
            if needed <= 0:
                continue
            candidates = [e for e in free_people(segment) if function_id in eligibility.get(e, set())]
            candidates.sort(key=lambda e: (rank(e, function_id), e))
            for employee_id in candidates[:needed]:
                register(employee_id, segment, function_id)
        # 3) Everyone left -> the department's remainder (Arbeidsbord, D13/D14).
        #    Weekends self-manage (D21): only demand functions are planned there.
        if day_type == "weekday" and plan["remainder"]:
            for employee_id in free_people(segment):
                if plan["remainder"] in eligibility.get(employee_id, set()):
                    register(employee_id, segment, plan["remainder"])
        # 4) Anyone still free who can't take the remainder (e.g. no Arbeidsbord
        #    competency) helps out in a zone they can work in, rather than idle.
        if day_type == "weekday":
            for employee_id in free_people(segment):
                fill = next((f for f in plan["zone_fill"].values()
                             if f in eligibility.get(employee_id, set())), None)
                if fill:
                    register(employee_id, segment, fill)

    new_rows = [
        (date_str, employee_id, function_id,
         start.strftime("%H:%M"), segment_end[(employee_id, start)].strftime("%H:%M"),
         0, source)
        for (employee_id, start), function_id in sorted(assigned.items())
        if (employee_id, start) not in locked_keys
    ]

    with conn:
        conn.execute(
            "DELETE FROM assignments WHERE plan_date = ? AND locked = 0", (date_str,)
        )
        row = conn.execute(
            "SELECT status, manually_edited FROM plan_days WHERE plan_date = ?", (date_str,)
        ).fetchone()
        status = row["status"] if row else "draft"
        edited = row["manually_edited"] if row else 0
        conn.execute(
            "INSERT OR REPLACE INTO plan_days (plan_date, status, generated_at, manually_edited, note) "
            "VALUES (?, ?, ?, ?, COALESCE((SELECT note FROM plan_days WHERE plan_date = ?), ''))",
            (date_str, status, dt.datetime.now().isoformat(timespec="seconds"), edited, date_str),
        )
        conn.executemany(
            "INSERT INTO assignments (plan_date, employee_id, function_id, start, end, locked, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", new_rows,
        )
    return len(new_rows)

"""Plan suggestion, v2: an hour-by-hour filler with the zone swap and
heavy-work balancing.

Day by day, in order, so each day sees the days planned before it. It
respects:

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
- heavy work (D110): the weekly cap on full-intensity days is hard – broken
  only when nobody else can do it, and then warned (D53); the weekly target
  is soft; within that, heavy work goes to whoever has the fewest weighted
  heavy hours in the «utjevningsvindu» (default 28 days), light work to the
  most exposed,
- locked assignments: regeneration plans around them and never touches them (D22).

Order of preference when picking someone: the lead code, the weekly cap, the
swap and continuity (structure), the weekly target, then the balance.

Nothing department-specific is written here (D109): fill order, lead codes,
zone remainders and swap rules all come from the data.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import sqlite3
from collections import defaultdict

from app import contingency, domain, exposure, service

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
        "adhoc": next((f["function_id"] for f in functions if f["staffing_mode"] == "adhoc"), None),
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


def plan_out_of_date(conn: sqlite3.Connection, date: dt.date) -> bool:
    """Does the day's plan no longer match the roster? (someone placed who
    isn't on duty or outside their hours, or someone on duty not placed)"""
    shifts = day_shifts(conn, date)
    placed: set[str] = set()
    for row in conn.execute("SELECT employee_id, start, end FROM assignments WHERE plan_date = ?",
                            (date.isoformat(),)):
        shift = shifts.get(row["employee_id"])
        if shift is None:
            return True
        s_start, s_end = (dt.datetime.combine(date, domain.parse_time(t)) for t in (shift["start"], shift["end"]))
        if s_end <= s_start:
            s_end += dt.timedelta(days=1)
        a, b = (dt.datetime.combine(date, domain.parse_time(t)) for t in (row["start"], row["end"]))
        if b <= a:
            b += dt.timedelta(days=1)
        if a < s_start or b > s_end:
            return True
        placed.add(row["employee_id"])
    full = domain.day_kind(date) == "weekday" or contingency.value(conn, "P6") == "full"
    return full and bool(set(shifts) - placed)


def redo_changed_drafts(conn: sqlite3.Connection, today: dt.date, touched: set[str] = frozenset()) -> list[dt.date]:
    """P8 «utkast»: remake unpublished plans from `today` on whose roster
    changed. Locked rows are kept (suggest_day plans around them)."""
    redone = []
    for row in conn.execute("SELECT plan_date FROM plan_days WHERE status <> 'published' AND plan_date >= ? "
                            "ORDER BY plan_date", (today.isoformat(),)).fetchall():
        date = dt.date.fromisoformat(row["plan_date"])
        if row["plan_date"] in touched or plan_out_of_date(conn, date):
            suggest_day(conn, date)
            redone.append(date)
    return redone


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
    choice = contingency.values(conn)          # «Avvik og tiltak» (D114)
    plan_all = day_type == "weekday" or choice["P6"] == "full"

    def tie(e: str) -> str:
        """Last resort between equals: varies from day to day, so the same
        employee numbers don't always win (D116), yet reproducible."""
        return hashlib.sha1(f"{date_str}|{e}".encode()).hexdigest()
    leave_to, pulls, on_swap = swap_maps(conn)
    # A function whose people some swap draws elsewhere (Arbeidsbord → uren).
    pulls_from = {f: {g for g, sources in pulls.items() if f in sources and g not in leave_to.get(f, ())}
                  for f in on_swap}
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

    shift_end = {e: max(s.end for s, people in groups.items() if e in people) for e in shifts}

    # Exposure (D110): weighted heavy hours over the «utjevningsvindu» before
    # this day, and this week's full-intensity days apart from this one.
    rules = exposure.settings(conn)
    wins = exposure.windows(conn)
    history = exposure.ledger(conn, date - dt.timedelta(days=rules["window_days"]),
                              date - dt.timedelta(days=1), wins)
    week = exposure.week_occurrences(conn, date - dt.timedelta(days=date.weekday()),
                                     rules["threshold"], exclude=date, wins=wins)
    today_hours: dict[str, float] = defaultdict(float)
    heavy_today: set[str] = set()
    load_cache: dict[tuple, tuple[float, float]] = {}

    def load(function_id: str, start: dt.datetime, end: dt.datetime) -> tuple[float, float]:
        key = (function_id, start, end)
        if key not in load_cache:
            load_cache[key] = exposure.load(wins, function_id, start, end)
        return load_cache[key]

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
        weighted, peak = load(function_id, segment.start, segment.end)
        today_hours[employee_id] += weighted
        if peak >= rules["threshold"]:
            heavy_today.add(employee_id)

    def exposure_key(e: str, function_id: str, segment: domain.Segment) -> tuple:
        """How suitable `e` is for `function_id` from `segment` on, as far as
        heavy work goes: (breaks the weekly cap, passes the weekly target,
        balance). A function outside the swap is counted to the end of the
        shift, since the person keeps it after the rotation point."""
        end = segment.end if function_id in on_swap else shift_end.get(e, segment.end)
        weighted, peak = load(function_id, segment.start, end)
        new_occurrence = peak >= rules["threshold"] and e not in heavy_today
        done = week.get(e, 0)
        exposed = history.get(e, 0.0) + today_hours[e]
        return (new_occurrence and done >= rules["cap"],
                new_occurrence and done >= rules["target"],
                # Heavy work goes to the least exposed; light work to the most
                # exposed, which keeps the less exposed free for heavy work.
                exposed if weighted > 0 else -exposed)

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

        def continuing(e: str) -> str | None:
            """The function outside the swap that `e` would simply keep."""
            p = prev.get(e)
            if p is None or p in on_swap or p not in eligibility.get(e, set()):
                return None
            if p in plan["fill_order"] and short(p) > 0:
                return p
            if p in plan["zone_fill"].values() and zone_short(plan["zone_of"][p]) > 0:
                return p
            return None

        def rank(e: str, function_id: str) -> int:
            """0 = drawn here by a swap, 1 = new on duty, 2 = free after the
            rotation point, 3 = wanted by a swap elsewhere, 4 = should go
            across instead, 5 = keeps a function outside the swap (steril,
            Kontrollsone …: those don't rotate, so they are taken last)."""
            p = prev.get(e)
            if continuing(e) not in (None, function_id):
                return 5
            if e in must_leave and function_id not in must_leave[e]:
                return 4
            if p is not None and p in pulls.get(function_id, ()):
                return 0
            if p is not None and pulls_from.get(p):
                return 3
            return 1 if p is None else 2

        def order(e: str, function_id: str, segment: domain.Segment, lead: set[str]) -> tuple:
            """Who first: the lead code, then never past the weekly cap unless
            nobody else can, the swap, the weekly target, the exposure balance."""
            over_cap, over_target, balance = exposure_key(e, function_id, segment)
            if choice["P3"] == "maal":             # the weekly target before structure
                return (roster.get(e) not in lead, over_cap, over_target, rank(e, function_id),
                        balance, tie(e))
            return (roster.get(e) not in lead, over_cap, rank(e, function_id), over_target,
                    balance, tie(e))

        def allowed(e: str, function_id: str) -> bool:
            """Candidates the chosen contingency rules rule out entirely."""
            if function_id not in eligibility.get(e, set()):
                return False
            if choice["P1"] == "roter" and rank(e, function_id) == 4:
                return False                        # rotate anyway, leave it short
            if choice["P2"] == "kort" and exposure_key(e, function_id, segment)[0]:
                return False                        # never past the weekly cap
            return True

        def keep(function_id: str, still_short) -> None:
            """Continuity: people already on `function_id` (outside the swap)
            keep it while it is short – unless that breaks the weekly cap."""
            for e in free_people(segment):
                if continuing(e) != function_id or still_short() <= 0:
                    continue
                over_cap, over_target, _ = exposure_key(e, function_id, segment)
                if over_cap or (over_target and choice["P3"] == "maal"):
                    continue
                register(e, segment, function_id)

        # 0) Whoever can't cross over stays where they were.
        for e in free_people(segment):
            if e in stuck and prev[e] in eligibility.get(e, set()):
                register(e, segment, prev[e])
        # 1) Demand functions, in the department's fill order: first those
        #    continuing, then the best of the rest.
        for function_id in plan["fill_order"]:
            keep(function_id, lambda f=function_id: short(f))
            needed = short(function_id)
            if needed <= 0:
                continue
            lead = plan["lead_codes"].get(function_id, set())
            candidates = [e for e in free_people(segment) if allowed(e, function_id)]
            candidates.sort(key=lambda e: order(e, function_id, segment, lead))
            for employee_id in candidates[:needed]:
                register(employee_id, segment, function_id)
        # 2) Zone totals -> each zone's own remainder (Produksjon uren/steril).
        for zone, function_id in plan["zone_fill"].items():
            keep(function_id, lambda z=zone: zone_short(z))
            needed = zone_short(zone)
            if needed <= 0:
                continue
            candidates = [e for e in free_people(segment) if allowed(e, function_id)]
            candidates.sort(key=lambda e: order(e, function_id, segment, set()))
            for employee_id in candidates[:needed]:
                register(employee_id, segment, function_id)
        # 3) Everyone left -> the department's remainder (Arbeidsbord, D13/D14).
        #    Weekends self-manage unless chosen otherwise (D21, P6).
        if plan_all and plan["remainder"]:
            for employee_id in free_people(segment):
                if plan["remainder"] in eligibility.get(employee_id, set()):
                    register(employee_id, segment, plan["remainder"])
        # 4) Anyone still free (e.g. no Arbeidsbord competency): «Ad hoc», a
        #    zone they can work in, or nothing – as chosen (P5, D115).
        if plan_all and choice["P5"] != "ingen":
            for employee_id in free_people(segment):
                if choice["P5"] == "adhoc":
                    fill = plan["adhoc"] if plan["adhoc"] in eligibility.get(employee_id, set()) else None
                else:
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

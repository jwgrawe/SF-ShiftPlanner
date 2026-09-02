#!/usr/bin/env python3
"""Create a DEMO roster and a naively filled plan for one week.

THIS IS NOT THE PLANNING ENGINE (that is milestone M3). It exists so the M1
views have realistic content: it fills demand hour-by-hour with eligible
employees (competency + preferences + restrictions are respected), varies
people across rotation blocks, and pours the remainder into the default
pools — but it knows nothing about fairness ledgers, the zone-swap rules or
occurrence caps.

Demo week: Monday 2026-09-07 through Sunday 2026-09-13. Deterministic.

Usage:  python scripts/make_demo_data.py   (after python -m app.importer)
"""
from __future__ import annotations

import datetime as dt
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, domain, service  # noqa: E402

WEEK_START = dt.date(2026, 9, 7)  # a Monday

# Weekday crews (16 early / 15 late / 7 night, matching total_on_duty) and
# weekend crews of 6 (H1/H2, D36). Crews are picked deterministically below.
WEEKDAY_CODES = {"early": ["DK"] + ["D"] * 13 + ["D2"] * 2,
                 "late": ["A"] * 13 + ["ME"] * 2,
                 "night": ["N"] * 7}
WEEKEND_CODES = ["H1"] * 3 + ["H2"] * 3

# Demand functions are filled hardest-first; the merged DK/ansvarsvakt comes
# first so someone is always in charge (D41/D57).
FILL_ORDER = [
    "ren_dk_ansvarsvakt", "ren_kontrollsone", "ren_sterrad",
    "uren_daglige_rutiner", "uren_manuell_rengjoring", "uren_gangen",
]


def segment_hours(segment: domain.Segment) -> list[int]:
    hours, cursor = [], segment.start
    while cursor < segment.end:
        hours.append(cursor.hour)
        cursor += dt.timedelta(hours=1)
    return hours


def pick_crews(conn) -> dict[str, list[str]]:
    """Deterministic crews with the qualifications each shift needs."""
    eligibility = service.eligible_functions(conn, WEEK_START)
    employees = sorted(eligibility)

    def can(employee_id: str, function_id: str) -> bool:
        return function_id in eligibility.get(employee_id, set())

    taken: set[str] = set()

    def take(count: int, *required_functions: str) -> list[str]:
        picked = []
        for employee_id in employees:
            if employee_id in taken:
                continue
            if all(can(employee_id, fn) for fn in required_functions):
                picked.append(employee_id)
                taken.add(employee_id)
                if len(picked) == count:
                    return picked
        raise SystemExit(f"demo: not enough employees qualified for {required_functions}")

    # Reserve the scarce qualifications first, so the bulk picks below don't
    # consume everyone who can hold DK/ansvarsvakt or Kontrollsone.
    dk = take(5, "ren_dk_ansvarsvakt")
    kontroll = take(5, "ren_kontrollsone")
    sterrad = take(2, "ren_sterrad")
    steril = take(1, "steril_produksjon")

    crews = {
        # Each crew opens with its DK/ansvarsvakt holder (gets the DK code).
        "early": [dk[0], kontroll[0], kontroll[1], sterrad[0]]
        + take(9, "uren_produksjon") + take(3, "ren_arbeidsbord"),
        "late": [dk[1], kontroll[2], kontroll[3], sterrad[1]]
        + take(8, "uren_produksjon") + take(3, "ren_arbeidsbord"),
        "night": [dk[2], kontroll[4], steril[0]]
        + take(2, "uren_produksjon") + take(2, "ren_arbeidsbord"),
        "sat": [dk[3]] + take(5, "ren_arbeidsbord"),
        "sun": [dk[4]] + take(5, "ren_arbeidsbord"),
    }
    return crews


def load_demand(conn, day_type: str):
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


def plan_day(conn, date: dt.date, roster: dict[str, str]) -> list[tuple]:
    """Naive fill for one day. Returns assignment tuples."""
    day_type = domain.day_kind(date)
    required, zone_total = load_demand(conn, day_type)
    eligibility = service.eligible_functions(conn, date)
    rotations = service.rotation_times(conn)
    shift_rows = {row["code"]: row for row in conn.execute("SELECT * FROM shift_codes")}
    uren_functions = [row["function_id"] for row in conn.execute(
        "SELECT function_id FROM functions WHERE zone_id = 'uren'")]

    # One entry per person-segment, chronological.
    person_segments: list[tuple[domain.Segment, str]] = []
    for employee_id, code in roster.items():
        shift = shift_rows[code]
        segments = domain.shift_segments(
            date, domain.parse_time(shift["start"]), domain.parse_time(shift["end"]),
            rotations[shift["category"]],
        )
        for segment in segments:
            person_segments.append((segment, employee_id))
    person_segments.sort(key=lambda item: (item[0].start, item[0].end, item[1]))

    coverage: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    assigned: dict[tuple[str, dt.datetime], str] = {}
    worked_uren: set[str] = set()
    dk_coded = {e for e, code in roster.items() if code in ("DK", "DKK")}

    groups: dict[domain.Segment, list[str]] = defaultdict(list)
    for segment, employee_id in person_segments:
        groups[segment].append(employee_id)

    def assign(employee_id: str, segment: domain.Segment, function_id: str) -> None:
        assigned[(employee_id, segment.start)] = function_id
        for hour in segment_hours(segment):
            coverage[function_id][hour] += 1
        if function_id in uren_functions:
            worked_uren.add(employee_id)

    def free_people(segment: domain.Segment) -> list[str]:
        return [e for e in groups[segment] if (e, segment.start) not in assigned]

    for segment in sorted(groups, key=lambda s: (s.start, s.end)):
        hours = segment_hours(segment)
        # 1) Explicit demand functions.
        for function_id in FILL_ORDER:
            needed = max(
                (required.get(function_id, {}).get(h, 0) - coverage[function_id][h] for h in hours),
                default=0,
            )
            candidates = [e for e in free_people(segment) if function_id in eligibility.get(e, set())]
            # DK-coded employees take DK/ansvarsvakt first (D41); otherwise
            # crude variety: prefer people who have not been in uren today.
            if function_id == "ren_dk_ansvarsvakt":
                candidates.sort(key=lambda e: (e not in dk_coded, e))
            else:
                candidates.sort(key=lambda e: (e in worked_uren, e))
            for employee_id in candidates[:max(needed, 0)]:
                assign(employee_id, segment, function_id)
        # 2) Uren remainder up to the zone total -> Produksjon, uren sone.
        needed = max(
            (zone_total.get("uren", {}).get(h, 0)
             - sum(coverage[f][h] for f in uren_functions) for h in hours),
            default=0,
        )
        candidates = [e for e in free_people(segment) if "uren_produksjon" in eligibility.get(e, set())]
        candidates.sort(key=lambda e: (e in worked_uren, e))
        for employee_id in candidates[:max(needed, 0)]:
            assign(employee_id, segment, "uren_produksjon")
        # 3) Steril zone total -> Produksjon, steril sone (ad hoc internally, D58).
        needed = max(
            (zone_total.get("steril", {}).get(h, 0) - coverage["steril_produksjon"][h]
             for h in hours),
            default=0,
        )
        for employee_id in [e for e in free_people(segment)
                            if "steril_produksjon" in eligibility.get(e, set())][:max(needed, 0)]:
            assign(employee_id, segment, "steril_produksjon")
        # 4) Everyone left -> Arbeidsbord/brikkelegging (D13/D14). On weekends
        #    the crew self-manages (D21), so only DK/ansvarsvakt is planned.
        if day_type == "weekday":
            for employee_id in free_people(segment):
                if "ren_arbeidsbord" in eligibility.get(employee_id, set()):
                    assign(employee_id, segment, "ren_arbeidsbord")

    return [
        (date.isoformat(), employee_id, function_id,
         start.strftime("%H:%M"),
         next(s.end for s in groups if s.start == start and employee_id in groups[s]).strftime("%H:%M"),
         "demo")
        for (employee_id, start), function_id in sorted(assigned.items())
    ]


def main() -> None:
    conn = db.get_conn()
    db.init_schema(conn)
    crews = pick_crews(conn)

    with conn:
        conn.execute("DELETE FROM assignments WHERE source = 'demo'")
        conn.execute("DELETE FROM plan_days WHERE note = 'demo'")
        conn.execute("DELETE FROM roster WHERE date BETWEEN ? AND ?",
                     (WEEK_START.isoformat(), (WEEK_START + dt.timedelta(days=6)).isoformat()))

        for offset in range(7):
            date = WEEK_START + dt.timedelta(days=offset)
            if domain.day_kind(date) == "weekday":
                roster = {}
                for phase in ("early", "late", "night"):
                    for employee_id, code in zip(crews[phase], WEEKDAY_CODES[phase]):
                        roster[employee_id] = code
            else:
                crew = crews["sat"] if date.weekday() == 5 else crews["sun"]
                roster = dict(zip(crew, WEEKEND_CODES))

            conn.executemany(
                "INSERT INTO roster (date, employee_id, shift_code) VALUES (?, ?, ?)",
                [(date.isoformat(), e, c) for e, c in roster.items()],
            )
            rows = plan_day(conn, date, roster)
            conn.execute(
                "INSERT OR REPLACE INTO plan_days (plan_date, status, generated_at, note) "
                "VALUES (?, 'published', ?, 'demo')",
                (date.isoformat(), dt.datetime.now().isoformat(timespec="seconds")),
            )
            conn.executemany(
                "INSERT INTO assignments (plan_date, employee_id, function_id, start, end, source) "
                "VALUES (?, ?, ?, ?, ?, ?)", rows,
            )
            print(f"{date} ({domain.day_kind(date)}): {len(roster)} rostered, {len(rows)} assignments")

    print("Demo week written. Try /display?date=2026-09-07&time=10:30")


if __name__ == "__main__":
    main()

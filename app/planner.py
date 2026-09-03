"""Plan suggestion, v0: a naive hour-by-hour filler.

This is NOT the M3 planning engine — it knows nothing about the zone-swap
rules (Q18), the weekly heavy-exposure cap or the intensity ledger. It
exists so managers can exercise the full generate → review → edit → publish
flow with plausible plans. It does respect:

- the eligibility formula (competency + preferences + restrictions + works_at),
- roster presence per block (shift codes cut at each category's rotation time),
- U-coded roster days (excluded from SF planning, D55),
- full-day absences,
- DK/DKK priority for DK/ansvarsvakt (D41),
- locked assignments: regeneration plans around them and never touches them (D22).
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from collections import defaultdict

from app import domain, service

# Demand functions are filled hardest-first; DK/ansvarsvakt comes first so
# someone is always in charge (D41/D57).
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


def day_roster(conn: sqlite3.Connection, date: dt.date) -> dict[str, str]:
    """employee_id -> shift_code for SF planning that day: U-coded days (D55)
    and employees with a full-day absence are excluded."""
    date_str = date.isoformat()
    absent = {
        row["employee_id"]
        for row in conn.execute(
            "SELECT employee_id FROM absences WHERE date = ? AND (start IS NULL OR start = '')",
            (date_str,),
        )
    }
    roster = {}
    for row in conn.execute(
        """SELECT r.employee_id, r.shift_code, s.utpost_code FROM roster r
           JOIN shift_codes s ON s.code = r.shift_code WHERE r.date = ?""",
        (date_str,),
    ):
        if row["utpost_code"] == "yes" or row["employee_id"] in absent:
            continue
        roster[row["employee_id"]] = row["shift_code"]
    return roster


def suggest_day(conn: sqlite3.Connection, date: dt.date, source: str = "forslag") -> int:
    """(Re)generate the suggestion for one day. Locked assignments are kept
    and planned around; all other assignments for the day are replaced.
    Returns the number of assignments written (locked ones excluded)."""
    date_str = date.isoformat()
    day_type = domain.day_kind(date)
    roster = day_roster(conn, date)
    required, zone_total = load_demand(conn, day_type)
    eligibility = service.eligible_functions(conn, date)
    rotations = service.rotation_times(conn)
    shift_rows = {row["code"]: row for row in conn.execute("SELECT * FROM shift_codes")}
    uren_functions = [row["function_id"] for row in conn.execute(
        "SELECT function_id FROM functions WHERE zone_id = 'uren'")]
    dk_coded = {e for e, code in roster.items() if code in ("DK", "DKK")}

    groups: dict[domain.Segment, list[str]] = defaultdict(list)
    for employee_id, code in roster.items():
        shift = shift_rows[code]
        for segment in domain.shift_segments(
            date, domain.parse_time(shift["start"]), domain.parse_time(shift["end"]),
            rotations[shift["category"]],
        ):
            groups[segment].append(employee_id)

    coverage: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    assigned: dict[tuple[str, dt.datetime], str] = {}
    segment_end: dict[tuple[str, dt.datetime], dt.datetime] = {}
    worked_uren: set[str] = set()

    def register(employee_id: str, segment: domain.Segment, function_id: str) -> None:
        assigned[(employee_id, segment.start)] = function_id
        segment_end[(employee_id, segment.start)] = segment.end
        for hour in segment_hours(segment):
            coverage[function_id][hour] += 1
        if function_id in uren_functions:
            worked_uren.add(employee_id)

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
            if function_id == "ren_dk_ansvarsvakt":
                candidates.sort(key=lambda e: (e not in dk_coded, e))
            else:
                candidates.sort(key=lambda e: (e in worked_uren, e))
            for employee_id in candidates[:max(needed, 0)]:
                register(employee_id, segment, function_id)
        # 2) Uren remainder up to the zone total -> Produksjon, uren sone.
        needed = max(
            (zone_total.get("uren", {}).get(h, 0)
             - sum(coverage[f][h] for f in uren_functions) for h in hours),
            default=0,
        )
        candidates = [e for e in free_people(segment) if "uren_produksjon" in eligibility.get(e, set())]
        candidates.sort(key=lambda e: (e in worked_uren, e))
        for employee_id in candidates[:max(needed, 0)]:
            register(employee_id, segment, "uren_produksjon")
        # 3) Steril zone total -> Produksjon, steril sone (ad hoc internally, D58).
        needed = max(
            (zone_total.get("steril", {}).get(h, 0) - coverage["steril_produksjon"][h]
             for h in hours),
            default=0,
        )
        for employee_id in [e for e in free_people(segment)
                            if "steril_produksjon" in eligibility.get(e, set())][:max(needed, 0)]:
            register(employee_id, segment, "steril_produksjon")
        # 4) Everyone left -> Arbeidsbord/brikkelegging (D13/D14). Weekends
        #    self-manage (D21): only DK/ansvarsvakt is planned there.
        if day_type == "weekday":
            for employee_id in free_people(segment):
                if "ren_arbeidsbord" in eligibility.get(employee_id, set()):
                    register(employee_id, segment, "ren_arbeidsbord")

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

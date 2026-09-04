"""Deterministic demo data: a four-week roster and a published first week.

Stands in for the real roster export (Q1). Week 1 gets a published plan so
the display works out of the box; weeks 2–4 have only a roster, so managers
can exercise the generate → review → edit → publish flow themselves.
"""
from __future__ import annotations

import datetime as dt
import sqlite3

from app import domain, planner, service

N_WEEKS = 4


def week_start(today: dt.date | None = None) -> dt.date:
    """Demo data is anchored to the current week, so "today" always has a
    roster. (With the real roster import this whole module goes away.)"""
    today = today or dt.date.today()
    return today - dt.timedelta(days=today.weekday())


# 16 early / 15 late / 7 night on weekdays (matching total_on_duty), 6 on
# weekend days (H1/H2, D36).
WEEKDAY_CODES = {"early": ["DK"] + ["D"] * 13 + ["D2"] * 2,
                 "late": ["A"] * 13 + ["ME"] * 2,
                 "night": ["N"] * 7}
WEEKEND_CODES = ["H1"] * 3 + ["H2"] * 3


def demo_range() -> tuple[str, str]:
    start = week_start()
    return start.isoformat(), (start + dt.timedelta(days=N_WEEKS * 7 - 1)).isoformat()


def pick_crews(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Deterministic crews with the qualifications each shift needs."""
    eligibility = service.eligible_functions(conn, week_start())
    employees = sorted(eligibility)
    taken: set[str] = set()

    def take(count: int, *required_functions: str) -> list[str]:
        picked = []
        for employee_id in employees:
            if employee_id in taken:
                continue
            if all(fn in eligibility.get(employee_id, set()) for fn in required_functions):
                picked.append(employee_id)
                taken.add(employee_id)
                if len(picked) == count:
                    return picked
        raise RuntimeError(f"demo: not enough employees qualified for {required_functions}")

    # Reserve the scarce qualifications first, so the bulk picks below don't
    # consume everyone who can hold DK/ansvarsvakt or Kontrollsone.
    dk = take(5, "ren_dk_ansvarsvakt")
    kontroll = take(5, "ren_kontrollsone")
    sterrad = take(2, "ren_sterrad")
    steril = take(1, "steril_produksjon")

    return {
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


def build(conn: sqlite3.Connection, verbose: bool = True) -> None:
    """Rebuild the demo roster (4 weeks) and the published week-1 plan."""
    first, last = demo_range()
    start = week_start()
    crews = pick_crews(conn)
    with conn:
        # Demo-only: the roster table holds nothing but demo rows at this
        # stage, so a rebuild clears it wholesale (including an older anchor).
        conn.execute("DELETE FROM assignments WHERE plan_date IN "
                     "(SELECT plan_date FROM plan_days WHERE note = 'demo')")
        conn.execute("DELETE FROM plan_days WHERE note = 'demo'")
        conn.execute("DELETE FROM roster")

        for offset in range(N_WEEKS * 7):
            date = start + dt.timedelta(days=offset)
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

    for offset in range(7):  # plans for week 1 only, published
        date = start + dt.timedelta(days=offset)
        count = planner.suggest_day(conn, date, source="demo")
        with conn:
            conn.execute(
                "UPDATE plan_days SET status = 'published', note = 'demo' WHERE plan_date = ?",
                (date.isoformat(),),
            )
        if verbose:
            print(f"{date} ({domain.day_kind(date)}): {count} assignments (published)")
    if verbose:
        print(f"Demo: roster {first} – {last}; plans published for week 1 only.")


def ensure(conn: sqlite3.Connection) -> None:
    """Build demo data when today has no roster — unless someone has made
    manual edits, in which case their work is left alone."""
    today = dt.date.today().isoformat()
    if conn.execute("SELECT COUNT(*) FROM roster WHERE date = ?", (today,)).fetchone()[0]:
        return
    hand_edited = conn.execute(
        "SELECT COUNT(*) FROM assignments WHERE locked = 1 OR source = 'manuell'"
    ).fetchone()[0]
    has_roster = conn.execute("SELECT COUNT(*) FROM roster").fetchone()[0]
    if has_roster and hand_edited:
        return
    print("Bygger demo-data (vaktliste 4 uker fra denne uken, plan for uke 1) ...")
    build(conn, verbose=False)

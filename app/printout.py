"""The daily plan on paper (D123), until the board screen is in place.

One A4 sheet per day to hang where everyone can see it, laid out like the
board (light theme – a dark page would only use up ink): zone cards with the
zone's colour band, function names in capitals over a rule, each person on
their own row with a chip saying where they go at the rotation.

The board shows one moment; a sheet shows the whole day, so it has a section
per shift (Tidligvakt, Mellomvakt, Senvakt, Nattevakt) with that shift's
rotation time. Each person is listed once, under the function they start in,
with a chip per move («→ Ren sone (Brikkelegging)», plus the time when it
isn't the shift's usual rotation). A start or end that differs from the
shift's usual hours is written after the name. Weekends add the crew working
ad hoc, as on the board.

Public content only, like the board (D46/D120): names, placements, times and
«Diverse info». A clear «UTKAST» mark when the day isn't published, and the
time it was printed, since the plan can change after printing.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from collections import Counter, defaultdict

from app import service

ORDER = service.SHIFT_CATEGORY_ORDER


def _short(t: dt.datetime) -> str:
    return t.strftime("%H") if t.minute == 0 else t.strftime("%H:%M")


def _span(start: dt.datetime, end: dt.datetime) -> str:
    return f"{_short(start)}–{_short(end)}"


def day_sheet(conn: sqlite3.Connection, date: dt.date) -> dict:
    rows = service.day_assignments(conn, date)
    rotations = service.rotation_times(conn)
    status = service.day_status(conn, date)

    # Each person's segments, in the shift category they belong to.
    segments: dict[str, list] = defaultdict(list)
    category_of: dict[str, str] = {}
    for row in rows:
        start, end = service._to_datetimes(date, row)
        segments[row["employee_id"]].append((start, end, row))
        category_of.setdefault(row["employee_id"], row["shift_category"] or "")

    by_category: dict[str, list] = defaultdict(list)
    for employee, parts in segments.items():
        parts.sort(key=lambda p: p[0])
        by_category[category_of[employee]].append(parts)

    shifts = []
    for category in sorted(by_category, key=lambda c: ORDER.index(c) if c in ORDER else 99):
        people = by_category[category]
        first = min(p[0][0] for p in people)
        last = max(p[-1][1] for p in people)
        usual = Counter((p[0][0], p[-1][1]) for p in people).most_common(1)[0][0]
        rotation = rotations.get(category)
        cut = dt.datetime.combine(date, rotation) if rotation else None
        if cut is not None and not first < cut < last:
            cut = None
        zones: dict[str, dict] = {}
        for parts in people:
            start, end, row = parts[0]
            moves, current = [], row["function_id"]
            for s_, _, later in parts[1:]:
                if later["function_id"] == current:
                    continue
                moves.append({"zone_id": later["zone_id"], "zone_name": later["zone_name"],
                              "short_name": later["short_name"] or later["function_name"],
                              "at": "" if s_ == cut else _short(s_)})
                current = later["function_id"]
            own = (parts[0][0], parts[-1][1])
            zone = zones.setdefault(row["zone_id"], {"zone_id": row["zone_id"], "name": row["zone_name"],
                                                     "order": row["zone_order"], "functions": {}})
            fn = zone["functions"].setdefault(row["function_id"], {
                "name": row["function_name"], "order": row["function_order"], "people": []})
            fn["people"].append({"name": row["display_name"], "start": own[0],
                                 "note": "" if own == usual else _span(*own), "moves": moves})
        zone_list = []
        for zone in sorted(zones.values(), key=lambda z: z["order"]):
            functions = []
            for fn in sorted(zone["functions"].values(), key=lambda f: f["order"]):
                fn["people"].sort(key=lambda p: (p["start"], p["name"].lower()))
                functions.append({"name": fn["name"],
                                  "people": [{k: p[k] for k in ("name", "note", "moves")} for p in fn["people"]]})
            zone_list.append({"zone_id": zone["zone_id"], "name": zone["name"], "order": zone["order"],
                              "functions": functions})
        shifts.append({"label": service.SHIFT_CATEGORY_LABELS.get(category, category or "Vakt"),
                       "span": _span(first, last),
                       "rotation": cut.strftime("%H:%M") if cut and any(
                           m["at"] == "" for z in zone_list for f in z["functions"] for p in f["people"]
                           for m in p["moves"]) else "",
                       "zones": zone_list})

    # A fixed column per zone, the same on every shift (uren | ren | steril),
    # so a zone is always in the same place on the sheet.
    columns, seen = [], set()
    for zone in sorted((z for sh in shifts for z in sh["zones"]), key=lambda z: z["order"]):
        if zone["zone_id"] not in seen:
            seen.add(zone["zone_id"])
            columns.append({"zone_id": zone["zone_id"], "name": zone["name"]})
    for shift in shifts:
        present = {z["zone_id"]: z for z in shift["zones"]}
        shift["zones"] = [{"zone_id": c["zone_id"], "name": c["name"],
                           "functions": present[c["zone_id"]]["functions"] if c["zone_id"] in present else []}
                          for c in columns]

    crew = []
    if status["day_kind"] == "weekend_holiday":
        placed = {row["employee_id"] for row in rows}
        for r in conn.execute(
                """SELECT r.employee_id, e.display_name, COALESCE(r.start_override, s.start) AS start,
                          COALESCE(r.end_override, s.end) AS end
                   FROM roster r JOIN employees e ON e.employee_id = r.employee_id
                   JOIN shift_codes s ON s.code = r.shift_code
                   WHERE r.date = ? AND r.hold IS NULL AND s.utpost_code <> 'yes'
                   ORDER BY e.display_name""", (date.isoformat(),)):
            if r["employee_id"] not in placed:
                crew.append({"name": r["display_name"], "span": f"{r['start']}–{r['end']}"})

    return {
        "date": date,
        "weekday": service.WEEKDAYS_NB[date.weekday()],
        "weekend": status["day_kind"] == "weekend_holiday",
        "published": status["status"] == "published",
        "has_plan": bool(rows),
        "shifts": shifts,
        "columns": len(columns),
        "crew": crew,
        "day_info": service.day_info(conn, date),
    }


def sheets(conn: sqlite3.Connection, first: dt.date, days: int) -> list[dict]:
    """One sheet per day that has a plan (days without one are left out)."""
    out = []
    for offset in range(max(1, min(days, 14))):
        sheet = day_sheet(conn, first + dt.timedelta(days=offset))
        if sheet["has_plan"] or sheet["crew"] or days == 1:
            out.append(sheet)
    return out

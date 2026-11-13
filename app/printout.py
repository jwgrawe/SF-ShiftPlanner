"""The daily plan on paper (D123), until the board screen is in place.

One A4 sheet per day to hang where everyone can see it. Public content only,
like the board (D46/D120): names, placements, times and «Diverse info».

Laid out for reading on a wall:
- one table per shift category (Tidligvakt, Mellomvakt, …): a row per
  function, one column before and one after the category's rotation time,
  so «where am I before and after 11:00» is one glance along a row;
- an alphabetical list of everyone on the plan with their placements, for
  finding yourself quickly;
- on weekends, the crew working ad hoc;
- a clear «UTKAST» mark when the day isn't published, and when it was
  printed, since the plan can change after printing.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from collections import Counter, defaultdict

from app import service

ORDER = service.SHIFT_CATEGORY_ORDER


def _short(t: dt.datetime) -> str:
    return t.strftime("%H") if t.minute == 0 else t.strftime("%H:%M")


def day_sheet(conn: sqlite3.Connection, date: dt.date) -> dict:
    rows = service.day_assignments(conn, date)
    rotations = service.rotation_times(conn)
    status = service.day_status(conn, date)

    categories: dict[str, dict] = {}
    people: dict[str, list] = defaultdict(list)
    for row in rows:
        start, end = service._to_datetimes(date, row)
        category = row["shift_category"] or ""
        rotation = rotations.get(category)
        cut = dt.datetime.combine(date, rotation) if rotation else None
        group = categories.setdefault(category, {"cut": cut, "functions": {}, "spans": []})
        column = 0 if group["cut"] is None or start < group["cut"] else 1
        fn = group["functions"].setdefault(row["function_id"], {
            "name": row["function_name"], "zone": row["zone_name"], "zone_id": row["zone_id"],
            "order": (row["zone_order"], row["function_order"]), "cells": [[], []]})
        fn["cells"][column].append({"name": row["display_name"], "start": start, "end": end})
        group["spans"].append((start, end))
        people[row["display_name"]].append((start, end, row["short_name"] or row["function_name"],
                                            row["zone_id"]))

    tables = []
    for category in sorted(categories, key=lambda c: ORDER.index(c) if c in ORDER else 99):
        group = categories[category]
        cut = group["cut"]
        first = min(s for s, _ in group["spans"])
        last = max(e for _, e in group["spans"])
        if cut is not None and not first < cut < last:
            cut = None                                # nobody works on both sides: one column
        columns = ([f"{_short(first)}–{_short(cut)}", f"{_short(cut)}–{_short(last)}"]
                   if cut else [f"{_short(first)}–{_short(last)}"])
        functions = []
        for fn in sorted(group["functions"].values(), key=lambda f: f["order"]):
            cells = fn["cells"] if cut else [fn["cells"][0] + fn["cells"][1], []]
            out = []
            for entries in cells[:len(columns)]:
                usual = Counter((e["start"], e["end"]) for e in entries).most_common(1)
                usual = usual[0][0] if usual else None
                out.append([{"name": e["name"],
                             "note": "" if (e["start"], e["end"]) == usual
                             else f"{_short(e['start'])}–{_short(e['end'])}"}
                            for e in sorted(entries, key=lambda e: (e["start"], e["name"]))])
            functions.append({"name": fn["name"], "zone": fn["zone"], "zone_id": fn["zone_id"],
                              "cells": out})
        tables.append({"label": service.SHIFT_CATEGORY_LABELS.get(category, category or "Vakt"),
                       "span": f"{_short(first)}–{_short(last)}", "columns": columns,
                       "functions": functions})

    index = []
    for name in sorted(people, key=str.lower):
        parts = sorted(people[name])
        steps, previous = [], None
        for start, end, function, zone_id in parts:
            if previous == function:
                continue
            steps.append({"function": function, "zone_id": zone_id,
                          "at": start.strftime("%H:%M") if steps else ""})
            previous = function
        index.append({"name": name, "span": f"{_short(parts[0][0])}–{_short(parts[-1][1])}",
                      "steps": steps})

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
        "tables": tables,
        "index": index,
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

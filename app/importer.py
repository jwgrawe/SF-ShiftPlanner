"""Import data/seed/*.csv into the SQLite database.

Usage:  python -m app.importer [--demo] [--db PATH]

M1 scope: master data is fully reloaded (wipe + insert) from the seed CSVs;
runtime tables (roster, absences, plans) are left untouched. The richer
import pipeline — Excel workbooks in data/import/, structure-drift warnings
(D54), diff summaries, refusal to break published plans — lands with the
admin UI. Run scripts/validate_seed.py first; this importer assumes valid
seed files.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

from app import db

SEED_DIR = db.REPO_ROOT / "data" / "seed"


def read_csv(name: str) -> list[dict]:
    with open(SEED_DIR / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def insert(conn: sqlite3.Connection, table: str, columns: list[str], rows: list[tuple]) -> int:
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", rows
    )
    return len(rows)


def import_seed(conn: sqlite3.Connection, people: bool = True) -> dict[str, int]:
    """Reload master data from data/seed/. With people=False (real mode, D89)
    the people tables are left alone — real staff come from the imports and
    the seed's fictional staff must never mix with them."""
    counts: dict[str, int] = {}
    for table in db.MASTER_TABLES:
        if people or table not in db.PEOPLE_TABLES:
            conn.execute(f"DELETE FROM {table}")

    counts["zones"] = insert(conn, "zones", ["zone_id", "name", "sort_order", "notes"], [
        (r["zone_id"], r["name"], int(r["sort_order"]), r["notes"]) for r in read_csv("zones.csv")
    ])
    counts["functions"] = insert(
        conn, "functions",
        ["function_id", "zone_id", "name", "short_name", "staffing_mode", "active",
         "sort_order", "notes"],
        [(r["function_id"], r["zone_id"], r["name"], r["short_name"], r["staffing_mode"],
          r["active"], int(r["sort_order"]), r["notes"]) for r in read_csv("functions.csv")],
    )
    counts["competency_types"] = insert(
        conn, "competency_types", ["competency_id", "name", "source_column", "notes"],
        [(r["competency_id"], r["name"], r["source_column"], r["notes"])
         for r in read_csv("competency_types.csv")],
    )
    counts["function_competencies"] = insert(
        conn, "function_competencies", ["function_id", "competency_id", "priority", "notes"],
        [(r["function_id"], r["competency_id"], int(r["priority"]), r["notes"])
         for r in read_csv("function_competencies.csv")],
    )
    counts["function_intensity"] = insert(
        conn, "function_intensity", ["function_id", "start", "end", "intensity", "notes"],
        [(r["function_id"], r["start"], r["end"], float(r["intensity"]), r["notes"])
         for r in read_csv("function_intensity.csv")],
    )

    demand_rows = []
    for r in read_csv("staffing_demand.csv"):
        for hour in range(24):
            value = r[f"h{hour:02d}"]
            demand_rows.append((
                r["row_type"], r["zone_id"] or None, r["function_id"] or None,
                r["category"], r["day_type"], hour, int(value or 0), r["notes"],
            ))
    counts["staffing_demand"] = insert(
        conn, "staffing_demand",
        ["row_type", "zone_id", "function_ids", "category", "day_type", "hour", "required", "notes"],
        demand_rows,
    )

    counts["shift_codes"] = insert(
        conn, "shift_codes",
        ["code", "start", "end", "crosses_midnight", "category", "utpost_code",
         "duration_hours", "comment"],
        [(r["code"], r["start"], r["end"], r["crosses_midnight"], r["category"],
          r["utpost_code"], float(r["duration_hours"]), r["comment"])
         for r in read_csv("shift_codes.csv")],
    )
    counts["rotation_rules"] = insert(
        conn, "rotation_rules", ["category", "rotation_time", "notes"],
        [(r["category"], r["rotation_time"] or None, r["notes"])
         for r in read_csv("rotation_rules.csv")],
    )
    counts["planner_settings"] = insert(
        conn, "planner_settings", ["key", "value", "notes"],
        [(r["key"], float(r["value"]), r["notes"]) for r in read_csv("planner_settings.csv")],
    )
    counts["opening_hours"] = insert(
        conn, "opening_hours",
        ["period_type", "shift_type", "sort_order", "weekday", "weekday_num", "start", "end"],
        [(r["period_type"], r["shift_type"], int(r["sort_order"]), r["weekday"],
          int(r["weekday_num"]), r["start"], r["end"]) for r in read_csv("opening_hours.csv")],
    )
    counts["worktable_types"] = insert(
        conn, "worktable_types", ["worktable_type", "notes"],
        [(r["worktable_type"], r["notes"]) for r in read_csv("worktable_types.csv")],
    )
    counts["weekday_rules"] = insert(
        conn, "weekday_rules",
        ["function_id", "category", "weekday", "rule", "start", "end", "count", "source_text"],
        [(r["function_id"], r["category"], r["weekday"], r["rule"], r["start"], r["end"],
          int(r["count"] or 0), r["source_text"]) for r in read_csv("weekday_rules.csv")],
    )
    db.merge_learned_codes(conn)
    seed_positions(conn)
    if not people:
        return counts
    counts["employees"] = insert(
        conn, "employees",
        ["employee_id", "source_label", "first_name", "last_name", "display_name", "works_at"],
        [(r["employee_id"], r["source_label"], r["first_name"], r["last_name"],
          r["display_name"], r["works_at"]) for r in read_csv("employees.csv")],
    )
    counts["employee_competencies"] = insert(
        conn, "employee_competencies", ["employee_id", "competency_id", "status"],
        [(r["employee_id"], r["competency_id"], r["status"])
         for r in read_csv("employee_competencies.csv")],
    )
    counts["employee_preferences"] = insert(
        conn, "employee_preferences", ["employee_id", "function_id", "note"],
        [(r["employee_id"], r["function_id"], r["note"])
         for r in read_csv("employee_preferences.csv")],
    )
    counts["employee_restrictions"] = insert(
        conn, "employee_restrictions",
        ["employee_id", "restriction_type", "function_id", "valid_from", "valid_to", "note"],
        [(r["employee_id"], r["restriction_type"], r["function_id"] or None,
          r["valid_from"] or None, r["valid_to"] or None, r["note"])
         for r in read_csv("employee_restrictions.csv")],
    )
    return counts


def seed_positions(conn: sqlite3.Connection) -> None:
    """Default rules per job title (D79/D87). Only fills in titles the
    database doesn't know yet — an admin's classification always stands."""
    for r in read_csv("positions.csv"):
        conn.execute(
            "INSERT OR IGNORE INTO positions (title, rule, first_seen, classified_at, notes) "
            "VALUES (?, ?, NULL, 'standard', ?)", (r["title"].strip(), r["rule"], r["notes"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="the demo database (with seed staff)")
    parser.add_argument("--db", default=None)
    args = parser.parse_args()
    db.set_mode("demo" if args.demo else "real")
    args.db = args.db or str(db.current_db_path())

    conn = db.get_conn(args.db)
    db.init_schema(conn)
    # Master tables are wiped and reloaded while runtime tables (roster,
    # assignments) keep referencing them, so FK enforcement is suspended for
    # the reload and integrity is verified afterwards — a violation (e.g. a
    # roster row pointing at a removed shift code) rolls everything back.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with conn:
            counts = import_seed(conn, people=db.is_demo())
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                details = ", ".join(
                    f"{row[0]} row {row[1]} -> {row[2]}" for row in violations[:10]
                )
                raise SystemExit(
                    f"Import rolled back: {len(violations)} rows in runtime tables "
                    f"would lose their reference ({details}). Remove or update those "
                    "rows first, or restore the missing master data."
                )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    print(f"Imported seed data into {args.db}:")
    for table, count in counts.items():
        print(f"  {table:24s} {count:5d} rows")


if __name__ == "__main__":
    main()

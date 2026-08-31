#!/usr/bin/env python3
"""Sanity-check the CSV files in data/seed/ for internal consistency.

Run after editing any seed file:  python scripts/validate_seed.py
Exits non-zero if a check fails.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent.parent / "data" / "seed"

errors: list[str] = []


def load(name: str) -> list[dict]:
    path = SEED_DIR / name
    if not path.exists():
        errors.append(f"{name}: file missing")
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def check_unique(rows: list[dict], key: str, name: str) -> None:
    seen: set[str] = set()
    for row in rows:
        value = row[key]
        if value in seen:
            errors.append(f"{name}: duplicate {key} {value!r}")
        seen.add(value)


def main() -> int:
    zones = load("zones.csv")
    functions = load("functions.csv")
    demand = load("staffing_demand.csv")
    shift_codes = load("shift_codes.csv")
    employees = load("employees.csv")
    competencies = load("competencies.csv")
    weekday_rules = load("weekday_rules.csv")

    check_unique(zones, "zone_id", "zones.csv")
    check_unique(functions, "function_id", "functions.csv")
    check_unique(shift_codes, "code", "shift_codes.csv")
    check_unique(employees, "employee_id", "employees.csv")

    zone_ids = {r["zone_id"] for r in zones}
    function_ids = {r["function_id"] for r in functions}
    employee_ids = {r["employee_id"] for r in employees}

    for row in functions:
        if row["zone_id"] not in zone_ids:
            errors.append(f"functions.csv: unknown zone_id {row['zone_id']!r}")
        if row["staffing_mode"] not in {"demand", "remainder", "adhoc_zone"}:
            errors.append(
                f"functions.csv: {row['function_id']}: bad staffing_mode {row['staffing_mode']!r}"
            )
        if row["heavy"] not in {"always", "after_12", "no", "unknown"}:
            errors.append(
                f"functions.csv: {row['function_id']}: bad heavy {row['heavy']!r}"
            )

    hour_cols = [f"h{h:02d}" for h in range(24)]
    for row in demand:
        label = f"{row['row_type']}/{row['zone_id']}/{row['function_id']}"
        if row["row_type"] not in {"zone_total", "function", "total_on_duty"}:
            errors.append(f"staffing_demand.csv: {label}: bad row_type")
        if row["row_type"] == "function" and row["function_id"] not in function_ids:
            errors.append(f"staffing_demand.csv: unknown function_id {row['function_id']!r}")
        if row["row_type"] == "zone_total" and row["zone_id"] not in zone_ids:
            errors.append(f"staffing_demand.csv: unknown zone_id {row['zone_id']!r}")
        for col in hour_cols:
            value = row[col]
            if value != "" and not value.isdigit():
                errors.append(f"staffing_demand.csv: {label}: {col}={value!r} not a number")

    for row in weekday_rules:
        if row["function_id"] not in function_ids:
            errors.append(f"weekday_rules.csv: unknown function_id {row['function_id']!r}")
        if row["weekday"] not in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}:
            errors.append(f"weekday_rules.csv: bad weekday {row['weekday']!r}")

    for row in competencies:
        if row["employee_id"] not in employee_ids:
            errors.append(f"competencies.csv: unknown employee_id {row['employee_id']!r}")
        if row["function_id"] not in function_ids:
            errors.append(f"competencies.csv: unknown function_id {row['function_id']!r}")

    if errors:
        print(f"FAILED – {len(errors)} problem(s):")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("OK – all seed files consistent")
    print(f"  zones: {len(zones)}, functions: {len(functions)}, demand rows: {len(demand)}")
    print(f"  shift codes: {len(shift_codes)}, employees: {len(employees)}, "
          f"competency rows: {len(competencies)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

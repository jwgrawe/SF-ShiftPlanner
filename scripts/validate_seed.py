#!/usr/bin/env python3
"""Sanity-check the CSV files in data/seed/ for internal consistency.

Run after editing any seed file:  python scripts/validate_seed.py
Exits non-zero if a check fails.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent.parent / "data" / "seed"

TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$|^24:00$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

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
    intensity = load("function_intensity.csv")
    demand = load("staffing_demand.csv")
    shift_codes = load("shift_codes.csv")
    employees = load("employees.csv")
    competencies = load("competencies.csv")
    restrictions = load("employee_restrictions.csv")
    weekday_rules = load("weekday_rules.csv")

    check_unique(zones, "zone_id", "zones.csv")
    check_unique(functions, "function_id", "functions.csv")
    check_unique(shift_codes, "code", "shift_codes.csv")
    check_unique(employees, "employee_id", "employees.csv")
    check_unique(employees, "source_label", "employees.csv")

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

    for row in intensity:
        if row["function_id"] not in function_ids:
            errors.append(f"function_intensity.csv: unknown function_id {row['function_id']!r}")
        for col in ("start", "end"):
            if not TIME_RE.match(row[col]):
                errors.append(
                    f"function_intensity.csv: {row['function_id']}: bad {col} {row[col]!r}"
                )
        try:
            value = float(row["intensity"])
            if not 0.0 <= value <= 1.0:
                raise ValueError
        except ValueError:
            errors.append(
                f"function_intensity.csv: {row['function_id']}: intensity {row['intensity']!r} "
                "not a number in [0, 1]"
            )

    hour_cols = [f"h{h:02d}" for h in range(24)]
    for row in demand:
        label = f"{row['row_type']}/{row['zone_id']}/{row['function_id']}"
        if row["row_type"] not in {"zone_total", "function", "function_group", "total_on_duty"}:
            errors.append(f"staffing_demand.csv: {label}: bad row_type")
        if row["row_type"] == "function" and row["function_id"] not in function_ids:
            errors.append(f"staffing_demand.csv: unknown function_id {row['function_id']!r}")
        if row["row_type"] == "function_group":
            members = row["function_id"].split(";")
            if len(members) < 2:
                errors.append(f"staffing_demand.csv: {label}: function_group needs >= 2 ids")
            for member in members:
                if member not in function_ids:
                    errors.append(f"staffing_demand.csv: unknown function_id {member!r} in group")
        if row["row_type"] == "zone_total" and row["zone_id"] not in zone_ids:
            errors.append(f"staffing_demand.csv: unknown zone_id {row['zone_id']!r}")
        if row["category"] not in {"normal", "fast", "rullering_fra_sf"}:
            errors.append(f"staffing_demand.csv: {label}: bad category {row['category']!r}")
        for col in hour_cols:
            value = row[col]
            if value != "" and not value.isdigit():
                errors.append(f"staffing_demand.csv: {label}: {col}={value!r} not a number")

    for row in shift_codes:
        for col in ("start", "end"):
            if not TIME_RE.match(row[col]):
                errors.append(f"shift_codes.csv: {row['code']}: bad {col} {row[col]!r}")
        if row["category_proposed"] not in {"tidligvakt", "senvakt", "nattevakt", "helgevakt"}:
            errors.append(
                f"shift_codes.csv: {row['code']}: bad category {row['category_proposed']!r}"
            )

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
        if row["status"] not in {"qualified", "uncertain"}:
            errors.append(f"competencies.csv: bad status {row['status']!r}")

    for row in restrictions:
        if row["employee_id"] not in employee_ids:
            errors.append(f"employee_restrictions.csv: unknown employee_id {row['employee_id']!r}")
        if row["restriction_type"] not in {"function", "heavy_work"}:
            errors.append(
                f"employee_restrictions.csv: bad restriction_type {row['restriction_type']!r}"
            )
        if row["restriction_type"] == "function" and row["function_id"] not in function_ids:
            errors.append(
                f"employee_restrictions.csv: {row['employee_id']}: restriction_type=function "
                f"requires a valid function_id, got {row['function_id']!r}"
            )
        for col in ("valid_from", "valid_to"):
            if row[col] and not DATE_RE.match(row[col]):
                errors.append(
                    f"employee_restrictions.csv: {row['employee_id']}: bad {col} {row[col]!r}"
                )

    if errors:
        print(f"FAILED – {len(errors)} problem(s):")
        for error in errors:
            print(f"  - {error}")
        return 1

    qualified = sum(1 for r in competencies if r["status"] == "qualified")
    print("OK – all seed files consistent")
    print(f"  zones: {len(zones)}, functions: {len(functions)}, "
          f"intensity windows: {len(intensity)}, demand rows: {len(demand)}")
    print(f"  shift codes: {len(shift_codes)}, employees: {len(employees)}, "
          f"competency rows: {len(competencies)} ({qualified} qualified), "
          f"restrictions: {len(restrictions)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

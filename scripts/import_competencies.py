#!/usr/bin/env python3
"""Import the anonymized competency workbook into data/seed/competencies.csv.

Reads data/source/Kompetanse_Anonymisert.xlsx (requires openpyxl) and writes
one row per (employee, function) with a status:

  x  -> qualified
  ?  -> uncertain   (meaning unclarified – see docs/open-questions.md; the
                     planner treats "uncertain" as NOT eligible until decided)

Anonymized rows "Employee N" map to employee_id E<NNN>, matching the
source_label column produced by scripts/generate_fake_employees.py.

Notes on the mapping (see docs/source-data-findings.md §4):
- The combined source column "Sterrad + poliklinikker/løspakk" maps to BOTH
  ren_sterrad and ren_poliklinikker_lospakk, since the functions were split
  by decision D16 but the competency data is still combined.
- Five source columns contain no marks at all (Daglige rutiner, Manuell
  rengjøring, Gangen, Driftskoordinator, Gang/vognvaskemaskiner); they yield
  no rows here. How to interpret them is an open question.

Usage:  python scripts/import_competencies.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from openpyxl import load_workbook

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "data" / "source" / "Kompetanse_Anonymisert.xlsx"
OUT = REPO_ROOT / "data" / "seed" / "competencies.csv"

COLUMN_TO_FUNCTIONS = {
    "Produksjon, uren sone": ["uren_produksjon"],
    "Daglige rutiner (uren sone)": ["uren_daglige_rutiner"],
    "Manuell rengjøring": ["uren_manuell_rengjoring"],
    "Gangen": ["uren_gangen"],
    "Driftskoordinator": ["ren_driftskoordinator"],
    "Ansvarsvakt": ["ren_ansvarsvakt"],
    "Kontrollsone": ["ren_kontrollsone"],
    "Arbeidsbord/brikkelegging": ["ren_arbeidsbord"],
    "Sterrad + poliklinikker/løspakk": ["ren_sterrad", "ren_poliklinikker_lospakk"],
    "Produksjon, steril sone": ["steril_produksjon"],
    "Gang/vognvaskemaskiner": ["steril_gang_vognvask"],
    "Kirurgisk poliklinikk": ["utpost_kir_pol"],
    "Gastro lab.": ["utpost_gastrolab"],
    "KOP barn": ["utpost_kop_barn"],
}
STATUS = {"x": "qualified", "?": "uncertain"}


def main() -> int:
    if not SOURCE.exists():
        print(f"Source file not found: {SOURCE}")
        return 1

    ws = load_workbook(SOURCE, data_only=True).worksheets[0]
    headers = [cell.value for cell in ws[2]]

    unknown = [h for h in headers[1:] if h and h not in COLUMN_TO_FUNCTIONS]
    if unknown:
        print(f"Unmapped competency columns: {unknown}")
        return 1

    rows: list[tuple[str, str, str]] = []
    n_employees = 0
    for row in ws.iter_rows(min_row=3):
        label = row[0].value
        if label is None:
            continue
        label = str(label).strip()
        if not label.startswith("Employee "):
            print(f"Unexpected row label {label!r} – expected 'Employee N'")
            return 1
        employee_id = f"E{int(label.split()[1]):03d}"
        n_employees += 1
        for cell, header in zip(row[1:], headers[1:]):
            if header is None:
                continue
            mark = str(cell.value).strip().lower() if cell.value is not None else ""
            if not mark:
                continue
            if mark not in STATUS:
                print(f"Unexpected mark {mark!r} for {label} / {header!r}")
                return 1
            for function_id in COLUMN_TO_FUNCTIONS[header]:
                rows.append((employee_id, function_id, STATUS[mark]))

    rows.sort()
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["employee_id", "function_id", "status"])
        writer.writerows(rows)

    print(f"Imported {n_employees} employees, {len(rows)} competency rows -> {OUT}")
    per_function: dict[str, int] = {}
    for _, function_id, status in rows:
        if status == "qualified":
            per_function[function_id] = per_function.get(function_id, 0) + 1
    for functions in COLUMN_TO_FUNCTIONS.values():
        for function_id in functions:
            print(f"  {function_id:28s} {per_function.get(function_id, 0):3d} qualified")
    return 0


if __name__ == "__main__":
    sys.exit(main())

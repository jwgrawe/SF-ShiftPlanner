#!/usr/bin/env python3
"""Generate 69 fictional employees and a placeholder competency matrix.

Deterministic (fixed random seed), so re-running the script reproduces the
exact same files. Output:

  data/seed/employees.csv      employee_id, first_name, last_name, display_name
  data/seed/competencies.csv   employee_id, function_id  (long format: one row
                               per employee/function the employee is eligible for)

The competency matrix is a PLACEHOLDER: the real "Kompetanse - Anonymisert"
file was not available when this was written, so eligibility is drawn from
rough probabilities per function, with minimum head-counts enforced so that
planning is always feasible. Replace with a real import once the source file
and its structure are known (see docs/open-questions.md, section D).

Usage:  python scripts/generate_fake_employees.py
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

SEED = 42
N_EMPLOYEES = 69

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = REPO_ROOT / "data" / "seed"

FIRST_NAMES = [
    "Anne", "Bjørn", "Camilla", "Dag", "Eva", "Frode", "Grete", "Håkon",
    "Ingrid", "Jan", "Kari", "Lars", "Mona", "Nils", "Oda", "Per",
    "Randi", "Stein", "Tone", "Ulf", "Vigdis", "Wenche", "Yngve", "Åse",
    "Bente", "Cato", "Dina", "Espen", "Frida", "Geir", "Hilde", "Ivar",
    "Jorunn", "Knut", "Line", "Marit", "Nora", "Odd", "Pål", "Ruth",
    "Silje", "Trond", "Unni", "Vidar",
]
LAST_NAMES = [
    "Hansen", "Johansen", "Olsen", "Larsen", "Andersen", "Pedersen",
    "Nilsen", "Kristiansen", "Jensen", "Karlsen", "Johnsen", "Pettersen",
    "Eriksen", "Berg", "Haugen", "Hagen", "Johannessen", "Andreassen",
    "Jacobsen", "Dahl", "Jørgensen", "Halvorsen", "Henriksen", "Lund",
    "Sørensen", "Jakobsen", "Moen", "Gundersen", "Iversen", "Strand",
    "Solberg", "Svendsen", "Eide", "Knutsen", "Martinsen", "Paulsen",
]

# Rough share of staff assumed eligible per function (placeholder values).
COMPETENCY_PROBABILITY = {
    "uren_produksjon": 0.90,
    "uren_daglige_rutiner": 0.50,
    "uren_manuell_rengjoring": 0.60,
    "uren_gangen": 0.70,
    "ren_driftskoordinator": 0.15,
    "ren_ansvarsvakt": 0.25,
    "ren_kontrollsone": 0.50,
    "ren_arbeidsbord": 0.95,
    "ren_sterrad_poliklinikker": 0.40,
    "steril_produksjon": 0.60,
    "steril_gang_vognvask": 0.60,
    "utpost_kir_pol": 0.15,
    "utpost_gastrolab": 0.15,
    "utpost_kop_barn": 0.10,
}

# Ensure at least this many eligible employees per function, so a generated
# plan can always cover peak demand plus absences.
MINIMUM_ELIGIBLE = {
    "ren_driftskoordinator": 6,
    "ren_ansvarsvakt": 12,
    "utpost_kir_pol": 6,
    "utpost_gastrolab": 8,
    "utpost_kop_barn": 4,
}


def main() -> None:
    rng = random.Random(SEED)

    pairs: set[tuple[str, str]] = set()
    while len(pairs) < N_EMPLOYEES:
        pairs.add((rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)))
    names = sorted(pairs)
    rng.shuffle(names)

    employees = [
        {
            "employee_id": f"E{i + 1:03d}",
            "first_name": first,
            "last_name": last,
            "display_name": f"{first} {last[0]}.",
        }
        for i, (first, last) in enumerate(names)
    ]

    eligible: dict[str, set[str]] = {f: set() for f in COMPETENCY_PROBABILITY}
    for emp in employees:
        for function_id, probability in COMPETENCY_PROBABILITY.items():
            if rng.random() < probability:
                eligible[function_id].add(emp["employee_id"])

    for function_id, minimum in MINIMUM_ELIGIBLE.items():
        missing = minimum - len(eligible[function_id])
        if missing > 0:
            candidates = [
                e["employee_id"]
                for e in employees
                if e["employee_id"] not in eligible[function_id]
            ]
            eligible[function_id].update(rng.sample(candidates, missing))

    SEED_DIR.mkdir(parents=True, exist_ok=True)

    with open(SEED_DIR / "employees.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["employee_id", "first_name", "last_name", "display_name"]
        )
        writer.writeheader()
        writer.writerows(employees)

    with open(SEED_DIR / "competencies.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["employee_id", "function_id"])
        for emp in employees:
            for function_id in COMPETENCY_PROBABILITY:
                if emp["employee_id"] in eligible[function_id]:
                    writer.writerow([emp["employee_id"], function_id])

    print(f"Wrote {len(employees)} employees to {SEED_DIR / 'employees.csv'}")
    total = sum(len(v) for v in eligible.values())
    print(f"Wrote {total} competency rows to {SEED_DIR / 'competencies.csv'}")
    for function_id in COMPETENCY_PROBABILITY:
        print(f"  {function_id:28s} {len(eligible[function_id]):3d} eligible")


if __name__ == "__main__":
    main()

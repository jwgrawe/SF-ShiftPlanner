#!/usr/bin/env python3
"""Generate 69 fictional employee identities.

Each fictional employee maps 1:1 (by row order) to an anonymized row
("Employee N") in the real competency file (data/source/Kompetanse_Anonymisert.xlsx),
recorded in the source_label column. Competencies are imported separately by
scripts/import_competencies.py and keyed to the same employee_ids, so the test
data carries the department's *real* competency patterns under fictional names.

Deterministic (fixed random seed): re-running reproduces the exact same file.

Usage:  python scripts/generate_fake_employees.py
Output: data/seed/employees.csv
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


def main() -> None:
    rng = random.Random(SEED)

    pairs: set[tuple[str, str]] = set()
    while len(pairs) < N_EMPLOYEES:
        pairs.add((rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)))
    names = sorted(pairs)
    rng.shuffle(names)

    SEED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SEED_DIR / "employees.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["employee_id", "source_label", "first_name", "last_name", "display_name"]
        )
        for i, (first, last) in enumerate(names):
            writer.writerow(
                [f"E{i + 1:03d}", f"Employee {i + 1}", first, last, f"{first} {last[0]}."]
            )

    print(f"Wrote {N_EMPLOYEES} employees to {out_path}")


if __name__ == "__main__":
    main()

# SF-ShiftPlanner

Prototype planning tool for daily **worker placement** in a hospital CSSD
("Sterilforsyning", SF): distributing ~69 employees across functions in three
zones (uren, ren, steril) plus utposter, planning the mid-shift rotations
("rullering" at 11:00 and 18:00), handling absences, and showing the day's
plan on a wall display.

**Status: pre-development.** The repo currently contains the decoded source
data, fictional test data, and the design assessment. No application code yet.

## Start here

| Document | Contents |
|---|---|
| [docs/assessment.md](docs/assessment.md) | Proposed architecture, domain model, planning engine, roadmap |
| [docs/open-questions.md](docs/open-questions.md) | **Everything that must be clarified or delivered** to keep building, prioritised |
| [docs/source-data-findings.md](docs/source-data-findings.md) | What the source workbooks contain, how they were restructured, all inconsistencies found |

## Repository layout

```
data/source/   Original Excel workbooks, committed unmodified (provenance)
data/seed/     Editable master data as CSV — decoded from the workbooks.
               These are the app's source of truth until an admin UI exists;
               edit in Excel/LibreOffice, then run scripts/validate_seed.py
scripts/       generate_fake_employees.py  (deterministic fictional test data)
               validate_seed.py            (consistency checks for data/seed/)
docs/          Assessment, open questions, data findings
app/           (future) FastAPI web app — display / manager / admin modes
```

## Seed data overview

| File | Contents |
|---|---|
| `zones.csv` | The three zones + utposter |
| `functions.csv` | 14 functions with zone, heaviness (`always` / `after_12` / `no`) and staffing mode (`demand` / `remainder` / `adhoc_zone`) |
| `staffing_demand.csv` | Required head-count per function/zone × hour (h00–h23), weekdays |
| `weekday_rules.csv` | Per-weekday deviations (utposter), structured from free text |
| `shift_codes.csv` | 21 vaktkoder with cleaned times and proposed category mapping |
| `opening_hours.csv` | Opening hours / period types per weekday |
| `worktable_types.csv` | The 8 listed worktable types under Arbeidsbord/brikkelegging |
| `employees.csv` | **69 fictional employees** (no real data in this repo) |
| `competencies.csv` | **Placeholder** employee×function eligibility, pending the real competency file |

All assumptions made while decoding are marked in `notes` columns and listed
in the docs — nothing was silently guessed.

```bash
# regenerate fictional employees + competencies (deterministic, seed=42)
python scripts/generate_fake_employees.py

# check all seed files for consistency after editing
python scripts/validate_seed.py
```

Requires Python ≥ 3.11, standard library only.

## Glossary

| Norwegian (UI) | English / code | Meaning |
|---|---|---|
| Sone | zone | Uren, Ren, Steril + Utposter |
| Funksjon | function | A staffed duty/place within a zone — the unit people are placed on |
| Grunnbemanning | staffing demand | Required head-count per function per hour |
| Rullering | rotation | Mid-shift change of crews on heavy functions (11:00 / 18:00) |
| Tungt arbeid | heavy work | Functions marked `always` or `after_12` |
| Vaktkode | shift code | e.g. `D` 07–15; classified as tidlig-/sen-/natte-/helgevakt |
| Ansvarsvakt, Driftskoordinator | (kept as-is) | Responsibility roles in ren sone |
| Utpost | outpost | CSSD work site elsewhere in the hospital |

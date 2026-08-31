# SF-ShiftPlanner

Prototype planning tool for daily **worker placement** in a hospital CSSD
("Sterilforsyning", SF): distributing ~69 employees across functions in three
zones (uren, ren, steril) plus utposter, planning the mid-shift rotations
("rullering" at 11:00 and 18:00), handling absences, and showing the day's
plan on a portrait display.

**Status: pre-development.** The repo contains the decoded source data,
test data (real competency structure under fictional names), the design
assessment, the decision log, and the open questions. Application code starts
with milestone M1.

## Start here

| Document | Contents |
|---|---|
| [docs/assessment.md](docs/assessment.md) | Proposed architecture, domain model, planning engine, roadmap |
| [docs/decisions.md](docs/decisions.md) | **Decision log** — everything settled so far, as referenceable D-numbers |
| [docs/open-questions.md](docs/open-questions.md) | **Open questions Q1–Q17** — the current clarification list |
| [docs/source-data-findings.md](docs/source-data-findings.md) | What the source workbooks contain, how they were restructured, inconsistencies found |

## Repository layout

```
data/source/   Original Excel workbooks, committed unmodified (provenance)
data/seed/     Editable master data as CSV — decoded from the workbooks.
               Source of truth for development; edit in Excel/LibreOffice,
               then run scripts/validate_seed.py
data/import/   Spec for the runtime import folder (Excel files managers edit)
scripts/       generate_fake_employees.py  (fictional identities, deterministic)
               import_competencies.py      (real competency matrix -> CSV)
               validate_seed.py            (consistency checks for data/seed/)
docs/          Assessment, decisions, open questions, data findings
app/           (future) FastAPI web app — display / manager / admin modes
```

## Seed data overview

| File | Contents |
|---|---|
| `zones.csv` | The three zones + utposter |
| `functions.csv` | 15 functions with zone and staffing mode (`demand` / `remainder` / `adhoc_zone`) |
| `function_intensity.csv` | Intensity windows per function — continuous scale 0–1 (D10); today 1 = "tungt", absent = normal |
| `staffing_demand.csv` | Required head-count per function/zone × hour (h00–h23), weekdays |
| `weekday_rules.csv` | Per-weekday deviations (utposter), structured from free text |
| `shift_codes.csv` | 21 vaktkoder with cleaned times and proposed category mapping |
| `opening_hours.csv` | Opening hours / period types per weekday |
| `worktable_types.csv` | The 8 listed (generic) worktable types under Arbeidsbord/brikkelegging |
| `employees.csv` | **69 fictional identities**, each mapped (via `source_label`) to a row of the anonymized competency file |
| `competencies.csv` | The **real** anonymized competency matrix: employee × function, status `qualified`/`uncertain` |
| `employee_restrictions.csv` | Exemptions from heavy work / specific functions (fictional examples) |

All assumptions made while decoding are marked in `notes` columns with D/Q
references — nothing was silently guessed.

```bash
# regenerate fictional identities (deterministic, seed=42)
python scripts/generate_fake_employees.py

# re-import the anonymized competency workbook (requires openpyxl)
python scripts/import_competencies.py

# check all seed files for consistency after editing
python scripts/validate_seed.py
```

Requires Python ≥ 3.11; only `import_competencies.py` needs a package
(`openpyxl`).

## Glossary

| Norwegian (UI) | English / code | Meaning |
|---|---|---|
| Sone | zone | Uren, Ren, Steril + Utposter |
| Funksjon | function | A staffed duty/place within a zone — the unit people are placed on |
| Grunnbemanning | staffing demand | Required head-count per function per hour |
| Rullering | rotation | Mid-shift change of crews on heavy functions (11:00 / 18:00) |
| Tungt arbeid / intensitet | heavy work / intensity | Modeled as a 0–1 scalar per function and time window |
| Fritak | restriction / exemption | Per-employee exemption from heavy work or specific functions |
| Vaktkode | shift code | e.g. `D` 07–15; classified as tidlig-/sen-/natte-/helgevakt |
| Turnus | roster | Who works which shift code on which date (10-week periods, imported) |
| Ansvarsvakt, Driftskoordinator | (kept as-is) | Responsibility roles in ren sone |
| Utpost | outpost | CSSD work site elsewhere in the hospital |

# SF-ShiftPlanner

Prototype planning tool for daily **worker placement** in a hospital CSSD
("Sterilforsyning", SF): distributing ~69 employees across functions in three
zones (uren, ren, steril), planning the mid-shift zone rotations
("rullering"), handling absences, and showing the day's plan on a portrait
display.

**Status: pre-development.** The repo contains the decoded source data,
test data (real competency structure under fictional names), the design
assessment, the decision log, and the open questions. Application code starts
with milestone M1.

## Start here

| Document | Contents |
|---|---|
| [docs/assessment.md](docs/assessment.md) | Proposed architecture, eligibility model, rotation framework, planning engine, roadmap |
| [docs/decisions.md](docs/decisions.md) | **Decision log** — everything settled, as referenceable D-numbers (superseded ones struck through) |
| [docs/open-questions.md](docs/open-questions.md) | **Open questions** — stable Q-numbers; currently Q1 + Q18–Q26 |
| [docs/source-data-findings.md](docs/source-data-findings.md) | What the source workbooks contain, how they were restructured, and how each flag got resolved |

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
| `functions.csv` | 14 functions with zone, staffing mode (`demand` / `remainder` / `adhoc_zone`) and `active` flag (utposter parked, D39) |
| `competency_types.csv` | The competency catalog — decoupled from functions (D40), mirroring the competency sheet's columns |
| `function_competencies.csv` | Which competencies qualify for which function, with priority (handles DK/ansvarsvakt merge, uren fallbacks, the Sterrad split) |
| `function_intensity.csv` | Intensity windows per function — continuous 0–1 scale (D10) |
| `staffing_demand.csv` | Required head-count per function/zone × hour (h00–h23), weekdays |
| `rotation_rules.csv` | Rotation time per shift category (11:00 / 16:00 / 18:00 / none) — configuration, not code (D35) |
| `shift_codes.csv` | 21 vaktkoder with confirmed categories (incl. mellomvakt and helgevakt) |
| `opening_hours.csv` | Opening hours / period types per weekday |
| `weekday_rules.csv` | Per-weekday deviations (utposter — currently parked), structured from free text |
| `worktable_types.csv` | The 8 generic worktable types under Arbeidsbord/brikkelegging |
| `employees.csv` | **69 fictional identities** mapped (via `source_label`) to the anonymized competency rows; `works_at` marks SF vs. fast utpost staff |
| `employee_competencies.csv` | The **real** anonymized competency matrix: employee × competency, status `qualified`/`uncertain` |
| `employee_preferences.csv` | Per-employee allowlists of functions (admin-only information, D32) — fictional example |
| `employee_restrictions.csv` | Exemptions from heavy work / specific functions — fictional examples |

All assumptions are marked in `notes` columns with D/Q references — nothing
was silently guessed.

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
| Sone | zone | Uren, Ren, Steril (+ Utposter, currently parked) |
| Funksjon | function | A staffed duty/place within a zone — the unit people are placed on |
| Kompetanse | competency | First-class entity; functions accept one or more competencies with priority |
| Preferanse | preference | Admin-only per-employee allowlist of assignable functions |
| Fritak | restriction | Per-employee exemption from heavy work or specific functions |
| Grunnbemanning | staffing demand | Required head-count per function per hour |
| Rullering | rotation | The once-per-shift zone swap uren ↔ ren (11:00 / 16:00 / 18:00 by shift category) |
| Tungt arbeid / intensitet | heavy work / intensity | 0–1 scalar per function and time window; exposure limited per week |
| Vaktkode | shift code | e.g. `D` 07–15; categorized tidlig-/sen-/mellom-/natte-/helgevakt |
| Mellomvakt | mid shift | Shift spanning both ordinary rotation points; rotates at 16:00 |
| Turnus | roster | Who works which shift code on which date (10-week base, repeats ~6 months) |
| DK/ansvarsvakt | (kept as-is) | Merged responsible-person function — always someone in charge |
| Utpost | outpost | CSSD work site elsewhere in the hospital |

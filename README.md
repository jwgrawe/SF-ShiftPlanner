# SF-ShiftPlanner

Prototype planning tool for daily **worker placement** in a hospital CSSD
("Sterilforsyning", SF): distributing ~69 employees across functions in three
zones (uren, ren, steril), planning the mid-shift zone rotations
("rullering"), handling absences, and showing the day's plan on a portrait
display.

**Status: milestone M2 in progress** — a runnable prototype:

- **`/`** «I dag» — the manager's morning page: today's status, plan findings
  for today and the next two days, a three-week outlook, today's absences.
- **`/display`** — the wall board (published plans only), grouped
  zone → funksjon → ansatt, each row showing where that person goes at the
  next rullering.
- **`/plan`** — overview → week matrix → day → editor. The day view is a
  swimlane timeline per zone (one row per employee, time left→right, rotation
  markers) or, optionally, blocks grouped by shift category. Generate,
  publish, edit with locks, report absences, and open a person view.
- **`/admin`** — master-data browser, incl. preferences and fritak (only here).

Demo data covers four weeks of roster from the current week, with week 1
pre-published. Remaining in M2: PINs, the real roster adapter (Q1) and the
Excel import UI.

## Running the prototype

No admin rights, no virtual environment, and no scripts that group policy
can block (D61). Two steps:

```bat
:: one-time, from any terminal (installs to your user profile):
python -m pip install --user -r requirements.txt

:: start the app (from any directory):
python run.py
```

`run.py` prepares the database on first start (seed import + demo week),
opens the browser, and serves on <http://127.0.0.1:8000/>. Stop with Ctrl+C.
Demo data covers four weeks from the Monday of the current week, so "today"
always has a roster. Preview any moment with e.g.
`/display?date=ÅÅÅÅ-MM-DD&time=10:30`.

Easiest way to open a terminal in the project folder: open the folder in
Explorer and type `cmd` in the address bar, or right-click → "Åpne i
terminal". For one-click startup, make a Windows shortcut (Ny → Snarvei)
with this target — shortcuts launch the whitelisted `python.exe`, so group
policy doesn't object:

```
"C:\Program Files\Python311\python.exe" "C:\...\Planlegger\run.py"
```

`start.bat` / `start.sh` do the same install-check + `run.py` for you, but
many org policies block `.bat` execution ("blokkert for gruppepolicy") — if
you see that, use `python run.py` as above; nothing is lost.

Tips for the hospital PC:
- **OneDrive**: mark the folder "Always keep on this device" (or keep it
  outside OneDrive) so sync never locks the SQLite database file. Avoid
  network drives (H:) — SQLite and network filesystems disagree about file
  locking.
- Rebuild data manually if needed: `python -m app.importer` (from the project
  folder) reloads the seed CSVs; `python scripts/make_demo_data.py` rebuilds
  the demo week.

## Start here

| Document | Contents |
|---|---|
| [docs/assessment.md](docs/assessment.md) | Proposed architecture, eligibility model, rotation framework, planning engine, roadmap |
| [docs/decisions.md](docs/decisions.md) | **Decision log** — everything settled, as referenceable D-numbers (superseded ones struck through) |
| [docs/open-questions.md](docs/open-questions.md) | **Open questions** — stable Q-numbers; currently Q1, Q18–Q20, Q27, Q29 |
| [docs/source-data-findings.md](docs/source-data-findings.md) | What the source workbooks contain, how they were restructured, and how each flag got resolved |

## Repository layout

```
app/           FastAPI web app: db.py (schema), importer.py (seed -> SQLite),
               domain.py (operational day, blocks, holidays), service.py
               (eligibility + view models), planner.py (suggestion filler),
               checks.py (plan findings + intensity ledger), absences.py,
               demo.py (stand-in roster), main.py + templates/ (Norwegian UI),
               static/app.css (all styling and design tokens)
data/source/   Original Excel workbooks, committed unmodified (provenance)
data/seed/     Editable master data as CSV — decoded from the workbooks.
               Source of truth for development; edit in Excel/LibreOffice,
               then run scripts/validate_seed.py and python -m app.importer
data/import/   Spec for the runtime import folder (Excel files managers edit)
scripts/       generate_fake_employees.py  (fictional identities, deterministic)
               import_competencies.py      (real competency matrix -> CSV)
               validate_seed.py            (consistency checks for data/seed/)
               make_demo_data.py           (demo roster + naive demo plan;
                                            NOT the planning engine)
tests/         Unit tests for the domain logic (python -m unittest discover -s tests)
docs/          Assessment, decisions, open questions, data findings
start.sh/.bat  Convenience wrappers (blocked by group policy on some PCs)
run.py         Canonical launch: python run.py, from any folder
```

## Seed data overview

| File | Contents |
|---|---|
| `zones.csv` | The three zones + utposter |
| `functions.csv` | 14 functions with zone, staffing mode (`demand` / `remainder` / `adhoc_zone`) and `active` flag (utposter parked, D39) |
| `competency_types.csv` | The competency catalog — decoupled from functions (D40), mirroring the competency sheet's columns |
| `function_competencies.csv` | Which competencies qualify for which function, with priority (handles DK/ansvarsvakt merge, uren fallbacks, the Sterrad split) |
| `function_intensity.csv` | Intensity windows per function and time of day — two tiers today: Kontrollsone 1.0, other heavy work 0.5; nights carry none (D50) |
| `planner_settings.csv` | Admin-adjustable planner parameters: occurrence threshold/target/cap, ledger window (D51) |
| `staffing_demand.csv` | Required head-count per function/zone × hour (h00–h23), weekdays |
| `rotation_rules.csv` | Rotation time per shift category (11:00 / 16:00 / 18:00 / none) — configuration, not code (D35) |
| `shift_codes.csv` | 21 vaktkoder with confirmed categories (incl. mellomvakt and helgevakt) and the U-code flag that keeps utpost days out of SF planning (D55) |
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
| Fritak | restriction | Per-employee exemption from heavy work or specific functions — also the home of tilrettelegging (D56) |
| Grunnbemanning | staffing demand | Required head-count per function per hour |
| Rullering | rotation | The once-per-shift zone swap uren ↔ ren (11:00 / 16:00 / 18:00 by shift category) |
| Tungt arbeid / intensitet | heavy work / intensity | 0–1 scalar per function and time window; exposure limited per week |
| Vaktkode | shift code | e.g. `D` 07–15; categorized tidlig-/sen-/mellom-/natte-/helgevakt |
| Mellomvakt | mid shift | Shift spanning both ordinary rotation points; rotates at 16:00 |
| Turnus | roster | Who works which shift code on which date (10-week base, repeats ~6 months) |
| DK/ansvarsvakt | (kept as-is) | Merged responsible-person function — always someone in charge |
| Utpost | outpost | CSSD work site elsewhere in the hospital |
| Fravær | absence | Affects supply only; never shown on the display (D46) |
| Utkast / publisert | draft / published | Only published plans reach the wall display |

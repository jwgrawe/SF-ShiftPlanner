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
  next rullering (`→ Ren sone (Brikkelegging)`), plus a «Diverse info» notice
  at the foot when the day has one (multi-line). Light or dark palette is set
  in the admin view.
- **`/plan`** — overview → week matrix → day → editor. The day view is a
  swimlane timeline per zone (one row per employee, time left→right, rotation
  markers, and bar ends that distinguish a rullering from the shift's own
  start/end) or, optionally, blocks grouped by shift category. Generate,
  publish (and unpublish, or delete a draft), edit with locks, report
  absences, set the day's «Diverse info», and open a person view.
- **`/import`** «Datagrunnlag» — the real roster's sources: which turnus
  (Plan) and ukeplan (Ajourhold) each week rests on, what needs attention,
  files read or refused, upload, and a log.
- **`/admin`** — in tabs: *Innstillinger* (board palette, retention, the
  full log), *Stillinger* (job-title rules), *Kompetanse* (the competency
  matrix: edit in place, import from Excel with review and name linking,
  download a fill-in form, the temps' standard set), *Vaktkoder* (codes
  learned from the turnus), *Grunndata* (master data, preferences and
  fritak — only here).

Two modes (D89): **`python run.py`** is the real planner — the roster comes
from the HR exports in `data/import/`; **`python run.py --demo`** is the
presentation demo with fictional staff and a generated four-week roster, in
its own database, marked DEMO. Remaining in M2: PINs, and the competency file
in export name form (Q40).

## Running the prototype

No admin rights, no virtual environment, and no scripts that group policy
can block (D61). Two steps:

```bat
:: one-time, from any terminal (installs to your user profile):
python -m pip install --user -r requirements.txt

:: start the app (from any directory):
python run.py
```

`run.py` prepares the database (seed import, then the files in
`data/import/`), opens the browser, and serves on <http://127.0.0.1:8000/>.
Stop with Ctrl+C. For presentations use `python run.py --demo` (fictional
staff; the demo roster covers four weeks from the Monday of the current
week). Preview any moment with e.g. `/display?date=ÅÅÅÅ-MM-DD&time=10:30`.

### The weekly routine (real mode)

1. Export from the HR system and save the file in **`data\import\`** — or
   upload it under «Datagrunnlag»:
   - **turnus** (Plan → «Utskrift fleksiplan»): `Utskrift_fleksiplan_….csv`,
     whenever a new or revised turnus exists;
   - **ukeplan** (Ajourhold): `Ukeplan_….csv`, one file per week, e.g. every
     Monday morning (re-exporting a week later in the week is fine — the
     newest wins);
   - **kompetansefil** (`.xlsx`, today's layout): it waits for review under
     Administrasjon → Kompetanse, where names are linked and every change is
     shown before anything is applied. Day-to-day, edit competencies right in
     that tab instead.
2. That's it. The app picks files up within 30 seconds while it's open,
   moves them to `arkiv/` (or `avvist/` with a .txt saying why), rebuilds the
   roster, and shows on «I dag» and «Datagrunnlag» if anything is missing or
   odd — e.g. no ukeplan for this week, turnus running out, a new job title
   to classify, an unknown shift code.

Nothing in `data/import/` or the databases ever reaches git (the repository
is public, D78); data older than 92 days is deleted automatically (D94).

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
| [docs/open-questions.md](docs/open-questions.md) | **Open questions** — stable Q-numbers; currently Q18–Q20, Q27, Q40 |
| [docs/source-data-findings.md](docs/source-data-findings.md) | What the source workbooks contain, how they were restructured, and how each flag got resolved |

## Repository layout

```
app/           FastAPI web app: db.py (schema, modes), importer.py (seed ->
               SQLite), hr_export.py (reads the turnus/ukeplan exports by
               structure), hr_import.py (inbox, roster building, findings,
               retention), competency.py (matrix, Excel in/out, name linking),
               applog.py (the app-wide log), domain.py (operational day, blocks, holidays),
               service.py (eligibility + view models), planner.py (suggestion
               filler), checks.py (plan findings + intensity ledger),
               absences.py, demo.py (demo roster), main.py + templates/
               (Norwegian UI), static/app.css (all styling and design tokens)
data/source/   Original Excel workbooks, committed unmodified (provenance)
data/seed/     Editable master data as CSV — decoded from the workbooks.
               Source of truth for development; edit in Excel/LibreOffice,
               then run scripts/validate_seed.py and python -m app.importer
data/import/   Real HR exports (Plan/Ajourhold CSV) and, later, the Excel files
               managers edit — git-ignored except its README (repo is public, D78)
data/private/  The anonymiser's key and output — git-ignored except its README
scripts/       generate_fake_employees.py  (fictional identities, deterministic)
               import_competencies.py      (real competency matrix -> CSV)
               validate_seed.py            (consistency checks for data/seed/)
               anonymise_export.py         (data/import/*.csv -> anonymised copies
                                            in data/private/, run locally)
               make_demo_data.py           (demo roster + naive demo plan;
                                            NOT the planning engine)
tests/         Unit tests (python -m unittest discover -s tests); hr_fixtures.py
               builds synthetic exports in the real format
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
| `positions.csv` | Default rule per job title (planned normally / never on the functions); new titles are classified once in the app (D87) |

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
| Plan *(HR system)* | planned roster | The turnus export — planned shifts, a whole year per file |
| Ajourhold *(HR system)* | roster maintenance | The ukeplan export — the freshest changes (absence, leave), one week per file; wins over Plan for its week (D73) |
| DK/ansvarsvakt | (kept as-is) | Merged responsible-person function — always someone in charge |
| Utpost | outpost | CSSD work site elsewhere in the hospital |
| Fravær | absence | Affects supply only; never shown on the display (D46) |
| Utkast / publisert | draft / published | Only published plans reach the wall display |

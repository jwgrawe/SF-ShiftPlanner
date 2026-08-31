# SF-ShiftPlanner — assessment & proposed design

*Status: v0.2 (2026-08-31). Updated after the first round of clarifications —
all agreed points are recorded in [decisions.md](decisions.md) (D-numbers);
everything still unsettled is in [open-questions.md](open-questions.md)
(Q-numbers).*

A prototype web app for a hospital CSSD (sterilforsyning, "SF") of ~69
employees that (1) suggests a daily placement of employees onto functions per
zone, (2) plans the mid-shift rotations ("rullering"), (3) lets managers
adjust plans and register absences, and (4) shows the day's plan on a
portrait display.

## 1. Terminology *(settled — D1)*

**Funksjon / function** is the canonical domain term: it matches the
department's own documents, and several entries (Ansvarsvakt, rullering to an
utpost) are duties rather than physical stations. Zone → function, with
worktable types as a dormant finer level (D18). UI text in Norwegian bokmål
(D3); identifiers in code/data in English snake_case.

## 2. Core domain model

```
Zone 1─* Function 1─* IntensityWindow(start, end, intensity 0..1)
              │                Employee 1─* Competency *─1 Function
              │ demand per hour     │ 1─* Restriction (function | heavy work)
              ▼ × day-type          │ roster: (date, shift_code)  [import]
        StaffingDemand              ▼ absence: (date, [start–end], type)
              └──────────┬── Availability (derived)
                         ▼
              PlanDay (operational day 07:00→07:00)
                 └─* Assignment (employee, function, block, locked?, source)
                         │
                         ▼ history feeds fairness scoring
                  IntensityLedger (rolling intensity-hours per employee)
```

Key decisions:

1. **Operational day 07:00 → 07:00.** A night shift belongs to the day it
   starts; the date-rollover lives in one place, and all intervals are
   half-open `[start, end)`. This is *internal plumbing only*: every screen
   speaks the staff's own categories — tidligvakt, senvakt, nattevakt,
   helgevakt (D23) — and can show who arrives when and which function they
   take over.

2. **Planning blocks cut at the rotation points** (D4, D8, D30):

   | Day type | Blocks |
   |---|---|
   | Weekday early (07–15) | 07:00–11:00 → **rullering** → 11:00–15:00 |
   | Weekday late (15–22) | 15:00–18:00 → **rullering** → 18:00–22:00 |
   | Friday late *(interim)* | 15:00–17:00 → **rullering 17:00** → 17:00–22:00 (Q6) |
   | Weekday night (22–07) | one block, no rotation |
   | Weekend & holiday (08–18) | one block, ad hoc (D21) |

3. **Three staffing modes** (resolves the source sheet's empty rows):
   `demand` (explicit hourly head-count), `remainder` (the zone default pool
   — Produksjon uren sone, and Arbeidsbord/brikkelegging which absorbs the
   *whole department's* remainder, nights included, per D13/D14), and
   `adhoc_zone` (steril sone: staffed via the zone total, distributed
   internally).

4. **Intensity is a continuous scalar, not a flag** (D10).
   `function_intensity.csv` holds windows of `(function, start, end,
   intensity ∈ [0,1])`; today's data is exactly the old model — 1 all day
   for `*` functions, 1 from 12:00 for `**` functions, 0 otherwise — but the
   representation buys real options at no cost:
   - the fairness ledger is simply ∑ intensity × hours, so "heavy hours"
     and any future graded intensity use the same arithmetic;
   - future per-employee *preferences* (an employee × function weight
     matrix) slot into the same soft-scoring machinery, and the whole
     objective stays a weighted sum — which is also the form a drop-in
     optimizer (e.g. CP-SAT) wants;
   - the crisp rules stay crisp: "heavy block" is defined as intensity above
     a configurable threshold (default: > 0), so the hard back-to-back rule
     (D9) doesn't blur as values get nuanced.
   The one discipline required: the UI always shows labels ("tungt",
   "normalt"), never raw numbers.

5. **Restrictions** (D11): per-employee exemptions from heavy work and/or
   any set of functions, with validity periods and no stored reason. Applied
   as hard filters in planning.

6. **Plan vs. reality are separate records** (D22): suggestion → published
   plan → audited same-day edits; locked assignments always survive
   regeneration — which doubles as the manager's tweaking tool: lock what
   must hold, regenerate the rest.

## 3. Architecture

Unchanged from v0.1 in substance (D2): one Python process — FastAPI +
Jinja2 templates + vendored htmx, SQLite file storage — running on **one
machine** for now (D31); the wall display comes later and will just be a
browser pointed at the same app.

| Mode | URL | Access (D25) | Does |
|---|---|---|---|
| Display | `/display` | none, read-only | Portrait layout, grouped by the three zones + utposter (D23): every person's current function, and who takes over what at the next rotation point; "fordeles ad hoc"-badges on weekends/holidays; fast utpost staff shown but marked as not planned here (D20) |
| Manager | `/plan` | shared PIN | Day/week board per block; generate, edit, lock, publish; absences (full-day and time-range, D27) |
| Admin | `/admin` | separate PIN | Master data, restrictions, re-import, intensity/fairness settings, ledger reports |

All user-facing text in professional, plain bokmål (D3). Names as first name
+ initial (D24). The SQLite file lives on a local/shared drive (D26) and the
app writes a dated backup copy on start.

## 4. Data flow: the import folder *(proposal, per D29)*

Managers should maintain a small number of Excel files, not many CSVs. A
folder `import/` next to the app, watched by a "Importer på nytt" button in
admin (and a CLI command):

```
import/
├── grunndata.xlsx     admin-owned config, one sheet per table:
│                        Funksjoner · Bemanningsbehov · Intensitet ·
│                        Vaktkoder · Åpningstider · Ukedagsregler
├── personal.xlsx      manager-owned people data:
│                        Ansatte · Kompetanse · Fritak · (Fravær as fallback —
│                        normally entered in-app)
└── turnus_*.xlsx      the roster export, dropped in as-is (10-week periods,
                       D28); parsed by a dedicated adapter written against
                       the real export format (Q1)
```

Import is idempotent and defensive: validate first (the `validate_seed.py`
checks, grown into the importer), show a diff summary ("3 endringer i
Kompetanse …"), refuse to delete master data referenced by published plans,
then upsert. The `data/seed/` CSVs in this repo remain the developer/test
fixtures and document the exact table shapes; the two Excel workbooks are
generated from them when M1 starts, so the department edits familiar files
from day one.

**Competency import today** (real, anonymized data): `Kompetanse_Anonymisert.xlsx`
→ `scripts/import_competencies.py` → `competencies.csv`, with `x` →
`qualified` and `?` → `uncertain` (treated as not eligible pending Q4).
Fictional identities in `employees.csv` map 1:1 to the anonymized rows via
`source_label`, so the test data carries the department's *real* competency
structure. Interim eligibility rules for the five empty competency columns
are defined in Q3.

## 5. The planning engine

Per day in the 2-week rolling horizon (D22):

1. **Resolve the day**: weekday/weekend/holiday (Norwegian holidays computed
   in code; holidays follow the weekend regime, D21), blocks per §2.
2. **Determine supply**: rostered employees minus absences, mapped to blocks
   via shift-code hours.
3. **Pin roster-decided functions** (D19): DK/DKK → Driftskoordinator,
   U-codes → utposter. Fast utpost staff render on the plan but are not
   planned (D20).
4. **Fill `demand` functions** block by block, hardest-to-staff first.
   Hard filters: competency (with Q3 interim rules), restrictions (D11),
   presence, the rotation rule (D5/D6: a heavy block forces a function
   change at the rotation point; at most one change per shift), no
   back-to-back heavy days (D9).
   Soft scoring: low rolling intensity-hours, continuity across non-heavy
   boundaries, variety across days, saving scarce competencies.
5. **Pour the remainder**: uren's leftover to Produksjon uren sone;
   everyone else to Arbeidsbord/brikkelegging (D13/D14); steril staffed via
   its zone total. Shortfalls become visible warnings, never silent drops.
6. **Update the intensity ledger** so tomorrow's run sees today's load.

Properties over optimality: **explainability** (every suggestion carries its
reasoning) and **determinism** (same input → same plan; regeneration after a
small edit changes little). The scoring function is a weighted sum by design
— see §2.4 — so a real optimizer can later replace the greedy loop behind
the same interface, and employee preferences can join the objective without
re-architecture.

## 6. Getting it running on the hospital PC *(for Q16)*

No administrator rights are needed for any of this — Python packages can be
installed per-user. Two things to test, in order:

```bat
:: 1) Can pip reach the package index at all?
python -m pip install --user --upgrade pip

:: 2) Install the prototype's few dependencies to your user profile:
python -m pip install --user fastapi uvicorn jinja2 openpyxl
```

If the hospital proxy blocks pip, the error will say so (timeouts /
ConnectionError) — report back and we either get the packages whitelisted,
install from downloaded wheel files (`pip install --user *.whl` works fully
offline), or fall back to a stdlib-only build (kept feasible by design: the
architecture uses nothing conceptually beyond what `http.server`, `sqlite3`
and string templates can do — it's just more work).

A tidier variant once pip is confirmed working: a virtual environment in the
user profile (`python -m venv %USERPROFILE%\sf-planner-env`), which also
never needs admin rights. Browser: Edge is fine.

## 7. Best practices adopted

- **Decision log** ([decisions.md](decisions.md)): every settled point gets a
  D-number; seed data and code reference them, so "why is it like this?"
  always has an answer.
- **Ubiquitous language** (D1/D3) and a glossary in the README.
- **Provenance**: originals unmodified in `data/source/`; all decoding
  documented; assumptions carried as data (`notes` columns) with Q-number
  references, not baked into code.
- **Real structure, fictional identities**: test data mirrors the actual
  competency matrix under fictional names, deterministically generated.
- **Validation as a habit**: `scripts/validate_seed.py` after every table
  edit; the same checks become the importer's gatekeeper.
- **Suggestion ≠ decision**; locked edits survive; audit trail on changes.
- **Small dependency surface**, vendored assets, stdlib-fallback ceiling.
- **Time in one place**: operational day, half-open intervals, Europe/Oslo
  wall-clock; DST Sundays get unit tests.

## 8. Roadmap

| Milestone | Content | Exit criterion |
|---|---|---|
| **M0 — done** | Repo, decoded seed data, real competency structure under fictional names, decision log | Wednesday meeting resolves Q1–Q10 |
| **M1 — data foundation** | SQLite schema, importer (+ generate the two Excel workbooks from seed), read-only browsing, first `/display` with a hand-made plan | Display shows a real day correctly, night shift included |
| **M2 — manual planning** | Manager board per block, absences (incl. partial-day), locking, publish; **roster adapter** against the real export sample | A manager plans tomorrow faster than on paper |
| **M3 — suggestions** | Engine v1 (greedy + intensity ledger), 2-week horizon, regenerate-with-locks, shortfall warnings | A normal week accepted with < ~10 manual corrections |
| **M4 — hardening** | Admin CRUD, holiday calendar, reports, backup routine, DST tests | A live pilot week on the single machine |
| **Later** | Wall display, GAT/API integration, SSO, preferences in the objective, per-worktable planning | — |

## 9. Risks

- **The roster sample is the critical path** (Q1): M2's adapter and all of
  M3 depend on it. Until it arrives, a hand-written `roster.csv` in the same
  spirit keeps development moving.
- **Empty competency columns** (Q3): if the interim eligibility rules are
  wrong, plans put people on functions they can't do. Surface the rules in
  the UI ("antatt kvalifisert via sonekompetanse") so wrong assumptions are
  caught by eyeballs early.
- **Utposter conflict** (Q10) unresolved → utpost planning stays
  display-only until it is.
- **Scope creep toward rostering**: this app places people who are already
  rostered; it must not drift into generating turnus.
- **pip access unknown** (Q16): tested with a 10-minute experiment before M1
  begins; fallback path defined in §6.

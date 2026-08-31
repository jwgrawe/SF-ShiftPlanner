# SF-ShiftPlanner — assessment & proposed design

*Status: proposal, v0.1 (2026-08-31). Nothing here is set in stone — it is the
basis for discussion before development starts in earnest.*

A prototype web app for a hospital CSSD (sterilforsyning, "SF") of ~60–69
employees that (1) suggests a daily placement of employees onto functions per
zone, (2) plans the mid-shift rotations ("rullering") at 11:00 and 18:00,
(3) lets managers adjust plans and register absences, and (4) shows the day's
plan on a wall display.

## 1. Terminology

Recommendation: use **funksjon / function** as the canonical domain term, not
"station"/"workstation".

- It matches the department's own documents ("Grunnbemanning *funksjonsvis*",
  column header "Funksjon/ansvar").
- Several entries are responsibilities rather than physical places
  (Ansvarsvakt, Driftskoordinator, "rullering fra SF" to an utpost).
- Best practice (domain-driven design's *ubiquitous language*): the words in
  the UI, the database and conversations with staff should be the same words.

So: **zone → function**, with worktable types (ORT, ORTA, …) as an optional
finer level under `Arbeidsbord/brikkelegging` if per-table planning turns out
to be needed. UI text in Norwegian; identifiers in code/data in English-ish
snake_case (`ren_kontrollsone`).

A small glossary lives in the README.

## 2. Core domain model

```
Zone 1─* Function                     Employee 1─* Competency *─1 Function
              │                            │
              │ demand: required people    │ roster: (date, shift_code)
              ▼ per hour × day-type        ▼ absence: (date, type, [hours])
        StaffingDemand              Availability (derived)
              └──────────┬───────────────┘
                         ▼
              PlanDay (per operational day, 07:00→07:00)
                 └─* Assignment (employee, function, segment, locked?, source)
                         │
                         ▼ history feeds fairness scoring
                  HeavyWorkLedger (rolling heavy-hours per employee)
```

Key modelling decisions (and the reasoning):

1. **The operational day runs 07:00 → 07:00 next day.** A night shift
   (22:00–07:00) belongs to the day it starts. This makes "today's plan" a
   single coherent unit and pushes the date-rollover problem into one place
   in the code instead of everywhere. All intervals are half-open
   `[start, end)` so 15:00 belongs to the late shift only, never to two blocks.

2. **Shifts are segmented into planning blocks by the rotation points:**

   | Day type | Blocks |
   |---|---|
   | Weekday early (07–15) | 07:00–11:00 → **rullering** → 11:00–15:00 |
   | Weekday late (15–22) | 15:00–18:00 → **rullering** → 18:00–22:00 |
   | Weekday night (22–07) | one block, no rotation |
   | Weekend/holiday (08–18) | one block, marked **ad hoc** (self-managed) |

   An *assignment* is "employee X works function Y during block Z". A person
   with a mid shift (`ME` 12–20) simply participates in whichever block
   overlaps their presence — how they rotate is open question B10.

3. **Three staffing modes for functions** (this resolves the "empty rows"
   ambiguity in the source sheet):
   - `demand` — explicit required head-count per hour (e.g. Kontrollsone: 2
     from 14:00);
   - `remainder` — the zone's default pool that absorbs everyone left over
     (Produksjon uren sone; Arbeidsbord/brikkelegging);
   - `adhoc_zone` — the zone is staffed as a whole and distributes itself
     (Steril sone; the entire department on weekends/holidays). The plan and
     the display then show *who* is in the zone, with an "fordeles ad hoc"
     badge instead of per-function detail.

4. **Heaviness is a property of (function, time):** `always`, `after_12`, or
   `no`. An assignment's *heavy hours* = overlap between its segment and the
   function's heavy window. Fairness is then arithmetic on the ledger, not
   special cases in the planner.

5. **Demand is effective-dated configuration.** When admins later tweak the
   numbers, old plans must not silently change. Config rows get
   `valid_from`/`valid_to`; plans reference what was in force. (Prototype: a
   single active version is fine, but the schema should leave room.)

6. **Plan vs. reality are separate records.** A generated *suggestion*
   becomes a *published plan*; same-day changes (sickness) edit the published
   plan with an audit note ("changed by manager 09:12"). Manually edited
   assignments are **locked**: regeneration never overwrites them.

## 3. Proposed architecture

**A single-process Python web app, server-rendered, with SQLite — one
`pip install`, one command to run, one browser tab (or three).**

| Layer | Choice | Why |
|---|---|---|
| Web framework | **FastAPI + Jinja2 templates** (Flask as fallback) | Tiny footprint; FastAPI gives a typed JSON API "for free" under `/api/...`, which is exactly the seam future integrations (GAT, HR) will plug into. If pip access on the work PC is a problem, the same design ports to stdlib-only. |
| Interactivity | **htmx, vendored locally** (one static JS file committed to the repo) | Drag-free, build-free: no Node toolchain, nothing fetched from a CDN (hospital networks often block those). Server-rendered fragments keep all logic in Python. |
| Storage | **SQLite** (stdlib `sqlite3`), file `sf_shiftplanner.db` | Zero-install, single file, trivially backed up by copying. Handles this scale (69 employees) with ease. |
| Config/master data | **CSV files in `data/seed/` remain the source of truth** until the admin UI matures; an idempotent **re-import command** loads them into SQLite | Managers/admins can edit the tables in Excel today; the "re-import" workflow the briefing asks for is then one button/command. The admin UI can later take over table by table. |
| Planner | Pure-Python **greedy heuristic with explainable scoring** (see §5) | Deterministic, dependency-free, debuggable. A real optimizer (OR-tools CP-SAT) can replace it behind the same interface *if* the heuristic proves insufficient — don't start there. |
| Display screen | Browser in kiosk/fullscreen mode pointing at `/display`; page refreshes itself (htmx polling every ~60 s) | Any smart screen or a mini-PC with a browser works; no special client software. |

Run it with `python -m uvicorn app.main:app` on the manager's PC; the wall
display and other PCs on the ward network open `http://<pc-name>:8000/`.

**Why browser-based rather than a desktop GUI:** the wall display, multi-user
access (several managers), and the future integration story all favour a web
app; and it keeps the prototype→production path smooth (the same app can later
be hosted by IT). This answers the briefing's open stack question: yes, aim
for the browser.

### The three modes

| Mode | URL | Auth (prototype) | Capabilities |
|---|---|---|---|
| Display | `/display` | none (read-only) | Today's placement per zone, big type; countdown + preview of the next rullering; "ad hoc" badges on weekends |
| Manager | `/plan` | shared PIN | Day/week board; generate & publish suggestions; drag/reassign; register absences; lock assignments |
| Admin | `/admin` | separate PIN | Edit functions, demand matrix, shift codes, employees, competencies; trigger CSV re-import; view heavy-work ledger |

Real authentication (hospital SSO/AD) is explicitly deferred; PINs merely
prevent accidental edits from the wall display. Do not pretend it is security.

### Repository layout (target)

```
app/            FastAPI app: routes, templates/, static/ (vendored htmx), db.py, planner/
data/source/    Original workbooks, unmodified (provenance)
data/seed/      Editable CSV master data — imported into SQLite
scripts/        generate_fake_employees.py, validate_seed.py, (later: import_db.py)
docs/           This assessment, open questions, data findings
```

## 4. Data pipeline

1. **Seed CSVs** (done, in `data/seed/`) — decoded from the workbooks, with
   every assumption marked in `notes` columns:
   `zones`, `functions` (with `heavy` + `staffing_mode`), `staffing_demand`
   (24 h columns × day-type, plus zone totals), `weekday_rules` (structured
   version of the free-text "Dagsvis" sheet), `shift_codes` (cleaned, with
   proposed category mapping), `opening_hours`, `worktable_types`,
   `employees` (69 fictional), `competencies` (placeholder).
2. **Missing inputs** (see open-questions.md): the roster
   (`date, employee_id, shift_code`) — the biggest gap — the real competency
   file, and an absence table. Proposed stop-gap formats are specified there
   so the department can start filling them in Excel immediately.
3. **Import command** (milestone 1): validates (extending
   `scripts/validate_seed.py`), then upserts into SQLite. Re-running is safe;
   it refuses to delete master data that published plans reference.

## 5. The planning engine

A per-day pipeline, run for each day in the horizon (proposal: 2 rolling weeks):

1. **Resolve the day**: weekday/weekend/holiday (Norwegian holidays computed
   in code — Easter arithmetic, fixed dates), opening window, blocks.
2. **Determine supply**: everyone rostered that operational day, minus
   absences, mapped to blocks via their shift code's hours.
3. **Pre-assign the "decided by roster" people**: DK/DKK → Driftskoordinator,
   U-codes → their utpost, (likely) Ansvarsvakt. These are fixed points the
   planner plans *around*.
4. **Fill `demand` functions block by block**, hardest-to-staff first (fewest
   eligible employees first). Each candidate gets a score:
   - hard filters: competency, presence during the block, not already
     assigned, heavy-rotation rule (no two heavy blocks in one shift; no
     heavy block if yesterday was a heavy day — pending C11);
   - soft scoring: low rolling heavy-hours (for heavy functions), continuity
     (stay on the same function across a block boundary *unless* it is
     heavy — then rotation is the point), variety (avoid the same function
     day after day), fewest alternative uses (save flexible people).
5. **Pour the remainder** into the zone default pools (`uren_produksjon`,
   `ren_arbeidsbord`) and the steril zone total; anything unfillable becomes a
   visible **shortfall warning** on the plan, never a silent drop.
6. **Update the heavy-work ledger** from the resulting assignments so the next
   day's run sees today's load.

Two properties matter more than optimality:

- **Explainability** — every suggested assignment carries its score breakdown
  ("Kari → Kontrollsone: qualified, 0 heavy hrs last 7 days, was here before
  lunch"). Managers will only trust and adopt a planner they can interrogate.
- **Determinism** — same inputs, same plan (seeded tie-breaking), so
  regenerating after a small edit produces a mostly-unchanged plan
  (minimal-disruption re-planning).

The weekend/holiday planner is trivially different: pick the 5–6 rostered
people, verify competency coverage across zones, mark everything ad hoc.

## 6. Best practices adopted

- **Ubiquitous language**: Norwegian domain terms everywhere users see text;
  a glossary in the README maps them to code identifiers.
- **Provenance**: original workbooks committed unmodified under
  `data/source/`; every transformation into `data/seed/` documented in
  [source-data-findings.md](source-data-findings.md); every assumption
  carried as data (a `notes` column), not silently baked into code.
- **Fictional data only** in the repo until data-handling questions (G30) are
  settled; the fake-data generator is deterministic so everyone reproduces
  identical test data.
- **Validation as a habit**: `scripts/validate_seed.py` runs after any table
  edit and in CI later.
- **Suggestion ≠ decision**: the app proposes, the manager disposes. Locked
  manual edits always survive regeneration; the audit trail says who changed
  what.
- **Small dependency surface**, all assets vendored — built for a locked-down
  hospital PC and a slow IT pipeline.
- **Time handled in one place**: operational-day abstraction, half-open
  intervals, Europe/Oslo naive local times (a wall-clock domain; no UTC
  round-tripping to introduce DST bugs — but the two DST Sundays get a unit
  test each).

## 7. Suggested roadmap

| Milestone | Content | Exit criterion |
|---|---|---|
| **M0 — done** | Repo, decoded seed data, fake employees, docs | This document agreed; open questions A–C answered |
| **M1 — data foundation** | SQLite schema, CSV→DB import, read-only web UI: browse functions/demand/employees; first cut of `/display` showing a *hand-made* plan | Wall display shows a manually entered day correctly, incl. a night shift |
| **M2 — manual planning** | Manager board: assign people to functions per block, absences, locking, publish; roster import (stop-gap CSV) | A manager can plan tomorrow fully by hand faster than on paper |
| **M3 — suggestions** | Planning engine v1 (greedy + fairness ledger), regenerate-with-locks, 2-week horizon, shortfall warnings | Suggested plan for a normal week accepted with < ~10 manual corrections |
| **M4 — hardening** | Admin CRUD for master data, holiday calendar, heavy-work reports, backups, DST tests | Department runs on it for a pilot week |
| **Later** | Real competency import, GAT/roster integration via `/api`, SSO, per-worktable planning | — |

M1+M2 before M3 is deliberate: the manual board produces the exact data
structures the engine must fill, and the department gets value (display +
manual planning) even before the clever part exists.

## 8. Risks

- **Garbage-in for fairness**: without a real roster and competency data the
  heavy-work balancing cannot be validated — it will look fine on fake data.
  Mitigation: milestone gate — M3 starts only after A1/A2 and D14 are
  delivered.
- **The two sheets disagree on utposter** (see findings). Building on the
  wrong one wastes a milestone; resolve E20 early.
- **Scope creep toward a rostering system**: this app plans *placement of
  people who are already rostered*; it must not drift into generating
  shifts/turnus (a legally regulated, solved-elsewhere problem). Saying no
  here keeps the prototype shippable.
- **Single-PC deployment**: the manager's PC being off = blank wall display.
  Acceptable for a prototype; note for later hosting.

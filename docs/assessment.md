# SF-ShiftPlanner — assessment & proposed design

*Status: v0.3 (2026-09-02). Updated after the department's question round —
settled points in [decisions.md](decisions.md) (D-numbers), unsettled ones in
[open-questions.md](open-questions.md) (Q-numbers). The headline changes in
this version: competencies became first-class entities, "preference" joined
the eligibility model, and rotation was redefined as a zone swap with a
separate heavy-exposure rule.*

A prototype web app for a hospital CSSD (sterilforsyning, "SF") of ~69
employees that (1) suggests a daily placement of employees onto functions,
(2) plans the mid-shift rotations, (3) lets managers adjust plans and
register absences, and (4) shows the day's plan on a portrait display.

## 1. Terminology *(settled — D1)*

**Funksjon / function** is the canonical term. Zone → function, worktable
types dormant beneath Arbeidsbord (D18). UI in Norwegian bokmål (D3);
identifiers in English snake_case.

## 2. Core domain model

```
Zone 1─* Function 1─* IntensityWindow(start, end, intensity 0..1)
              │  *│
              │   └── FunctionCompetency ──1 CompetencyType
              │        (priority)              │
              │                     EmployeeCompetency (qualified | uncertain)
              │ demand per hour × day-type     │
              ▼                            Employee ── works_at: sf | utpost_fast
        StaffingDemand                         │ 1─* Preference (allowlist, admin-only)
              │                                │ 1─* Restriction (function | heavy work)
              │                                │ roster: (date, shift_code)  [import]
              │                                ▼ absence: (date, [start–end], type)
              └──────────┬──────── Availability & Eligibility (derived)
                         ▼
              PlanDay (operational day 07:00→07:00)
                 └─* Assignment (employee, function, block, locked?, source)
                         │
                         ▼ history feeds fairness scoring
                  IntensityLedger (rolling intensity-hours per employee)
```

### 2.1 Eligibility: who may be assigned what

Four independent layers combine (D17, D32, D40, D44); all four must pass:

```
eligible(employee, function) =
      holds a qualifying competency for the function     (status = qualified;
        via function_competencies, e.g. produksjon_uren   "?" and unknown marks
        also qualifies for the other uren functions)      never qualify)
  AND not restricted from it                             (heavy-work or
                                                          per-function exemption)
  AND (no preference list OR function is on it)          (allowlist; admin-only
                                                          visibility)
  AND employee works in SF                               (works_at = sf; fast
                                                          utpost staff excluded)
```

**Competencies are decoupled from functions** (D40): a catalog
(`competency_types.csv`) mirrors the columns of the department's competency
sheet, and `function_competencies.csv` says which competencies qualify for
which function, with priority. This one mapping absorbs every special case
without special-casing the code:

- **DK/ansvarsvakt** (D41): the merged function accepts *driftskoordinator*
  (priority 1) and *ansvarsvakt* (priority 2); employees on DK/DKK shift
  codes are prioritized above both. Demand is 1 around the clock — someone is
  always in charge.
- **Empty uren columns** (D42): the three uren demand functions accept
  *produksjon_uren* as a fallback competency.
- **Sterrad / Poliklinikker/løspakk** (D43): two functions, two competencies;
  employees may hold both. The still-combined source column maps to both
  until the file is re-issued (Q20).

**Preferences** (D32) are a per-employee allowlist maintained by managers in
the admin view: when present, the employee is assigned *only* functions on
the list, regardless of what else they're qualified for (the utpost-workers
case). This is sensitive-adjacent steering information: it is stored, applied,
and visible **only** in admin — no other view exposes it or its effects'
rationale. Restrictions (D11) remain the complementary denylist.

An in-app **competency editor** is planned for the admin view (D33): edit
qualified/uncertain per employee × competency, with `?` kept as a "assess
this next" reminder that never affects planning (D44). File import stays the
default pathway.

### 2.2 Time: operational day and blocks

The operational day runs 07:00 → 07:00 (internal plumbing only — every
screen speaks tidligvakt/senvakt/nattevakt/helgevakt, D23). Blocks are
derived from **configuration, not code** (D35, D47):

- `shift_codes.csv` assigns each vaktkode a category (explicitly — edge
  cases defy formulas): tidligvakt, senvakt, **mellomvakt** (ME/UME),
  nattevakt, helgevakt (H1/H2, D36).
- `rotation_rules.csv` gives each category its rotation time: 11:00 / 18:00
  (Fridays included, D34) / **16:00 for mellomvakt** / none for night and
  weekend.
- A shift's blocks = its span cut at its category's rotation time. A weekend
  day therefore *naturally* renders as one ad-hoc block — no "is weekend"
  flag anywhere (D47). Another department could add categories and rotation
  times without touching code.

### 2.3 Rotation and heavy work *(reshaped in R2 — D37)*

Two distinct mechanisms, formerly conflated:

1. **The zone swap**: once per shift, at the category's rotation time,
   employees switch between **uren sone and ren sone** (competence
   permitting) to relieve homogeneous, repetitive work. Exact scope — whole
   crews or subsets, which ren functions participate, steril's role — is the
   top open question (Q18).
2. **The heavy-exposure rule**: heavy functions at most once per employee per
   week. As literally stated this is infeasible (~150–175 heavy person-slots
   per week vs. 69 employees — arithmetic in Q19); until the department picks
   a relaxation, the planner treats it as a soft target (minimize occurrences,
   aim 1) with a hard cap of 3, tie-broken by the 28-day intensity-hours
   ledger (D9). Partial-shift heavy work counts fully (D38).

Intensity stays a continuous scalar per function/time window (D10) — the
ledger is ∑ intensity × hours, future graded intensity and preference
weights need no schema change, and the crisp rules bind to a configurable
threshold. UI shows labels, never numbers.

### 2.4 Utposter: parked, not deleted *(D39)*

Outpost staffing isn't settled in the department, so utposter are **out of
planning scope**: their functions carry `active = no`, their demand rows are
kept as dormant reference, and employees get `works_at ∈ {sf, utpost_fast}`
— fast utpost staff (list pending, Q21) are simply absent from SF planning.
Reactivation = flipping `active` and filling the clarified numbers; nothing
gets rebuilt.

## 3. Architecture

One Python process — FastAPI + Jinja2 + vendored htmx, SQLite — on a single
machine (D31). pip user-installs are confirmed working (D48), so the stack
is locked in. **Everything lives in one self-contained folder** (D49),
relative paths only, so the app can move machines or to a shared drive by
copying the folder:

```
SF-Planlegger/                 (deployed folder, outside this repo)
├── app/                       code (from this repo)
├── .venv/                     python -m venv .venv; pip install -r requirements.txt
├── data/
│   ├── sf_planlegger.db       SQLite
│   ├── import/                grunndata.xlsx · personal.xlsx · turnus_*.xlsx
│   └── backup/                dated copies, written on each start
└── start.bat                  activates venv, runs uvicorn, opens browser
```

| Mode | URL | Access (D25) | Does |
|---|---|---|---|
| Display | `/display` | none, read-only | Portrait, grouped by zones; assignments + next-rotation takeovers; ad-hoc badges fall out of the data (D47). **Never shows absences** — just the current plan (D46). No preference/restriction information visible. |
| Manager | `/plan` | shared PIN | Day/week board per block; generate, edit, lock, publish; absences (full/partial day, type list per Q26) |
| Admin | `/admin` | separate PIN | Master data; **competency editor** (D33); **preference lists** (D32, only visible here); restrictions; re-import; rotation/intensity settings; ledger reports |

## 4. Data flow

**Import folder** (D29): `grunndata.xlsx` (admin config: Funksjoner,
Bemanningsbehov, Intensitet, Vaktkoder, Rulleringsregler, Åpningstider) and
`personal.xlsx` (Ansatte, Kompetanse, Preferanser, Fritak), plus the roster
export dropped in as-is. Import validates, shows a diff summary, refuses to
break published plans, then upserts.

**Roster refresh** (D45): the 10-week base roster repeats ~6 months; changes
(forskyvning, vaktbytte) are made in the roster file by managers and
re-imported. On refresh the app re-validates published plans against the new
roster and flags conflicts ("Kari's assignment Wednesday no longer matches
her shift") instead of silently editing plans.

**Competency import today**: `Kompetanse_Anonymisert.xlsx` →
`scripts/import_competencies.py` → `employee_competencies.csv` (`x`/`X` →
qualified, `?` → uncertain, anything else warned and ignored, D44). Fictional
identities map 1:1 to the anonymized rows via `source_label`, so test data
carries the department's real competency structure.

## 5. The planning engine

Per day in the 2-week rolling horizon (D22):

1. **Resolve the day**: weekday/weekend/holiday; blocks from shift categories
   × rotation rules (§2.2).
2. **Determine supply**: rostered SF employees (works_at = sf) minus
   absences, mapped to blocks.
3. **Pin roster-decided roles**: DK/DKK-coded employees → DK/ansvarsvakt.
4. **Fill demand functions** hardest-first. Hard filters: the eligibility
   formula (§2.1), presence, the zone-swap structure (§2.3), the heavy cap.
   Soft scoring: heavy-occurrence minimization, intensity-hours balance,
   continuity across non-rotating boundaries, variety, saving scarce
   competencies (e.g. only 21 ansvarsvakt-qualified).
5. **Pour the remainder**: uren's leftover → Produksjon uren; everyone else →
   Arbeidsbord/brikkelegging (D13/D14). Shortfalls are loud warnings.
6. **Update the ledger.**

Explainability and determinism remain the two non-negotiables: every
suggestion shows its reasoning (without ever citing preferences outside
admin), and identical inputs give identical plans.

## 6. Best practices adopted

- **Decision log + stable Q-numbers**: every rule in data and code traces to
  a D/Q reference; superseded decisions stay visible, struck through.
- **Configuration over code** for everything another department would change:
  rotation times, shift categories, intensity, demand, competency mappings.
- **Ubiquitous language**, provenance (`data/source/` untouched), assumptions
  as data with notes, deterministic fictional test data, validation as a
  habit (`validate_seed.py`), suggestion ≠ decision, locked edits survive.
- **Privacy by placement**: preferences and restrictions live only in the
  admin surface; the display never shows absences; names as first name +
  initial.

## 7. Roadmap

| Milestone | Content | Exit criterion |
|---|---|---|
| **M0 — done** | Repo, decoded data, competency/eligibility architecture, rotation framework, decision log | Q18/Q19 (rotation scope & feasibility) answered |
| **M1 — data foundation** | SQLite schema, importer (+ generate the two Excel workbooks), read-only browsing, first `/display` with a hand-made plan | Display renders a real day, night shift included |
| **M2 — manual planning** | Manager board per block, absences, locking, publish; roster adapter against the real export (Q1) | Planning tomorrow by hand beats paper |
| **M3 — suggestions** | Engine v1: zone swap + heavy cap + ledger, 2-week horizon, regenerate-with-locks, shortfall warnings | A normal week accepted with < ~10 corrections |
| **M4 — hardening** | Admin CRUD incl. competency editor & preferences, holiday calendar, reports, backups | A live pilot week |
| **Later** | Wall display, utposter reactivation, GAT/API, SSO, preference weights in the objective, per-worktable planning | — |

## 8. Risks

- **Rotation semantics** (Q18/Q19) now carry the risk formerly held by the
  fairness rule: building the engine before they're answered means rework.
  M1/M2 don't depend on them; M3 does.
- **The roster sample** (Q1) is still the critical path for M2/M3.
- **Interim eligibility assumptions** (D42, Q24): surfaced in the UI as
  "antatt kvalifisert via produksjon-kompetanse" so wrong assumptions get
  caught by eyeballs.
- **Scope creep toward rostering**: unchanged — this app places rostered
  people, it does not generate turnus.

# Decision log

Decisions made so far, referenced from the seed data (`notes` columns), the
assessment and the open questions as **D-numbers**. Tentative decisions —
adopted so work can proceed, but explicitly open for revision — are marked
*(interim)* and have a corresponding entry in
[open-questions.md](open-questions.md).

All decisions below: 2026-08-31, project owner.

## Domain & terminology

| # | Decision |
|---|---|
| D1 | Canonical term is **funksjon** ("function"), not station/workstation. |
| D2 | Browser-based app: single-process Python (FastAPI + server-rendered templates + vendored htmx), SQLite storage. |
| D3 | All user-facing text in **professional, plain Norwegian (bokmål)** — including manager and admin views. Code and docs in English. |

## Rullering (rotation)

| # | Decision |
|---|---|
| D4 | Weekday rotation times: **11:00** (early shift) and **18:00** (late shift). |
| D5 | *(interim)* Everyone on a heavy function must leave it at the rotation point; replacements may come from anywhere competence allows. Keep configurable — not 100 % certain (Q8). |
| D6 | One rotation per shift. |
| D7 | A fresh person takes the heavy stretch: on `after-12` functions, work 07–11 does **not** count as heavy. |
| D8 | No rotation at night. No rotation on weekends/holidays (ad hoc, D21). |
| D30 | *(interim)* Friday evening: assume rotation at **17:00** (the period is helg-typed from 17:00) — confirm (Q6). |

## Heaviness, fairness & restrictions

| # | Decision |
|---|---|
| D9 | Fairness rules: **hard** — no back-to-back heavy days; **soft** — balance a 28-day rolling intensity-hours count. Any heavy block makes a heavy day; partial-shift heavy work counts *(interim, Q9)*. |
| D10 | Intensity is modeled as a **continuous scalar per (function, time window)** — `function_intensity.csv`. Values are 0/1 today ("normal"/"tungt"), but the scale admits future nuance and, later, per-employee preference weights in the same optimization machinery. UI shows labels ("tungt"), never numbers. |
| D11 | Per-employee **restrictions/exemptions**: an employee can be exempted from heavy work and/or from any combination of individual functions, with validity periods (`employee_restrictions.csv`). No reason/diagnosis is ever stored. |

## Data semantics

| # | Decision |
|---|---|
| D12 | The missing hour 00:00 in the demand matrix is filled by interpolation (equal to 23:00/01:00). Confirmed unproblematic. |
| D13 | **Ren sone is the remainder zone**: everyone not otherwise placed is at Arbeidsbord/brikkelegging. |
| D14 | This holds at night too: night-shift remainder staff go to Arbeidsbord/brikkelegging. |
| D15 | Shift codes may exceed 7.5 h — the "max 7.5 h" rule is disregarded (HR system's concern). |
| D16 | "Sterrad + poliklinikker/løspakk" is split into two functions: **Sterrad** and **Poliklinikker og løspakk** (demand/competency split pending, Q5). |
| D17 | Competency is **binary eligibility per function** for now. |
| D18 | Worktables are generic (any surgical field) and treated as one group; the type list is kept in the model for future per-department preferences. |
| D19 | Roster-pinned functions: `DK`/`DKK` codes pin Driftskoordinator (specific employees); `U*` codes pin utposter. Ansvarsvakt is competency-gated (senior staff) but planned normally. |
| D20 | **Fast utpost staff are displayed, not planned.** The model keeps them plannable for the future. |
| D21 | Weekends **and holidays**: everyone self-manages ad hoc (may change later). |

## Product & workflow

| # | Decision |
|---|---|
| D22 | Planning horizon: **2 weeks rolling**. Managers/admins publish plans; published plans stay editable and regenerateable; regeneration never overwrites locked (manually set) assignments. |
| D23 | Display: **single portrait screen**, grouped by the three zones + utposter, showing each person's assignment and who takes over what at the next rotation point. Staff think in tidlig/sen/natt/helg — the display speaks those terms; the 07:00→07:00 "operational day" is internal plumbing only. |
| D24 | Names shown as **first name + initial** ("Kari H."). |
| D27 | Absences affect **supply only**, never demand. Full-day is the main case; partial-day (time-range) absences should be supported. |
| D28 | Roster is per-date in **10-week periods**, exportable from the workforce system. Import must adapt to its pre-defined export format (sample pending, Q1). |
| D29 | Config and personnel data arrive as **files in an import folder** (Excel workbooks managers overwrite/edit), per the structure proposed in the assessment §4. |

## Technical & security

| # | Decision |
|---|---|
| D25 | PIN-level access control is acceptable (app runs only on the hospital's secure internal network). |
| D26 | SQLite file on a local/shared drive is approved, and may hold full personal data. |
| D31 | Deployment target for now: **one single machine** (prototype + possibly real planning); the wall display comes later. |

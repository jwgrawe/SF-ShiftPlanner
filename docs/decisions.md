# Decision log

Decisions referenced from seed data, docs and (later) code as **D-numbers**.
*(interim)* = adopted so work can proceed, still open for revision (has a
Q-number). ~~Struck~~ = superseded; kept for traceability.

Rounds: **R1** = 2026-08-31 (first briefing + answers), **R2** = 2026-09-02
(question round after the department meeting).

## Domain & terminology

| # | R | Decision |
|---|---|---|
| D1 | R1 | Canonical term is **funksjon** ("function"), not station/workstation. |
| D2 | R1 | Browser-based app: single-process Python (FastAPI + server-rendered templates + vendored htmx), SQLite storage. |
| D3 | R1 | All user-facing text in **professional, plain Norwegian (bokmål)**. Code and docs in English. |

## Rullering (rotation)

| # | R | Decision |
|---|---|---|
| D4 | R1 | Weekday rotation times: **11:00** (tidligvakt) and **18:00** (senvakt). |
| ~~D5~~ | R1 | ~~Everyone on a heavy function must leave it at the rotation point~~ — superseded by D37: rotation is a zone swap. |
| D6 | R1 | One rotation per shift. |
| D7 | R1 | A fresh person takes the heavy stretch: on functions heavy from 12:00, work 07–11 does **not** count as heavy. |
| D8 | R1 | No rotation at night; none on weekends/holidays (ad hoc, D21). |
| ~~D30~~ | R1 | ~~Friday evening rotates at 17:00~~ — superseded by D34. |
| D34 | R2 | **Friday evening rotates at 18:00**, exactly like other weekdays. |
| D35 | R2 | New shift category **mellomvakt** for shifts spanning both ordinary rotation points, with its own rotation time **16:00**. Rotation times are per-category *configuration* (`rotation_rules.csv`), not code — customizable for other departments. Current mellomvakt codes: `ME`, `UME`. |
| D37 | R2 | **The rotation is a zone swap between uren sone and ren sone** (all functions), once per shift, competence permitting — its purpose is relieving homogeneous/repetitive work. Heavy functions are governed by a *separate* exposure rule: at most one occurrence per employee per week *(interim — scope and feasibility open, Q18/Q19)*. |
| D38 | R2 | Partial-shift heavy work counts the same as a full shift in the exposure rule. |

## Heaviness, fairness & individual settings

| # | R | Decision |
|---|---|---|
| D9 | R1 | Soft fairness: balance a 28-day rolling intensity-hours count per employee. *(The R1 hard rule "no back-to-back heavy days" is replaced by D37's once-per-week exposure rule.)* |
| D10 | R1 | Intensity is a **continuous scalar per (function, time window)** (`function_intensity.csv`, 0–1). UI shows labels ("tungt"), never numbers. |
| D11 | R1 | Per-employee **restrictions**: exemptions from heavy work and/or specific functions, with validity periods; no reason stored. |
| D32 | R2 | Per-employee **preferred functions** (allowlist): when set, the employee is only assigned functions on their list. Eligibility = competency ∧ not-restricted ∧ (no preference list ∨ function on it). Maintained by managers in the admin view; **never shown anywhere else** (not on display, not on the plan board beyond its effect). |
| D33 | R2 | An in-app **competency editor** (admin view) is planned: managers edit competencies, including the `?` status. File import remains the default path for now. |
| D44 | R2 | Competency marks: `x`/`X` = qualified; `?` = "assess this" reminder for managers, **not eligible** for planning; any other mark = ignored with a warning. |

## Competency architecture

| # | R | Decision |
|---|---|---|
| D17 | R1 | Competency is binary eligibility (per competency type). |
| D18 | R1 | Worktables are generic, treated as one group; type list kept for future preferences. |
| ~~D19~~ | R1 | ~~DK/DKK pin Driftskoordinator; U-codes pin utposter; Ansvarsvakt competency-gated~~ — DK part folded into D41; utpost part suspended by D39. |
| D40 | R2 | **Competencies are first-class entities**, decoupled from functions: `competency_types.csv` (catalog) + `function_competencies.csv` (which competencies qualify for which function, with priority). Supports merged functions, split competencies, and derived coverage without special cases. |
| D41 | R2 | **Driftskoordinator and Ansvarsvakt merge into one function "DK/ansvarsvakt"** (demand: 1 around the clock) with competencies kept separate. Employees on `DK`/`DKK` shift codes are prioritized; otherwise an ansvarsvakt-qualified employee is chosen — there is always someone in charge on duty. |
| D42 | R2 | The empty uren competency columns (Daglige rutiner, Manuell rengjøring, Gangen) are **covered by "Produksjon, uren sone"** competency, via the function-competency mapping. |
| ~~D16~~ | R1 | ~~Split into "Sterrad" and "Poliklinikker og løspakk"~~ — superseded by D43 (name + competency split). |
| D43 | R2 | **Both the function and the competency split** into "Sterrad" and "Poliklinikker/løspakk"; employees may hold either or both. The still-combined source column maps to both until the file is re-issued (Q20). |

## Data semantics

| # | R | Decision |
|---|---|---|
| D12 | R1 | Missing hour 00:00 filled by interpolation — confirmed. |
| D13 | R1 | Ren sone is the remainder zone: everyone not otherwise placed → Arbeidsbord/brikkelegging. |
| D14 | R1 | Holds at night too. |
| D15 | R1 | Shift codes may exceed 7.5 h. |
| ~~D20~~ | R1 | ~~Fast utpost staff displayed, not planned~~ — superseded by D39. |
| D21 | R1 | Weekends and holidays: ad hoc self-management. |
| D36 | R2 | **`H1` and `H2` are weekend/holiday shift codes** (category helgevakt). |
| D39 | R2 | **Utposter are entirely out of planning scope for now** (their staffing is not yet settled in the department). The model keeps them ready for reactivation (`active = no` on the functions). For now it suffices to mark each employee as working in the CSSD (`sf`) or permanently at an outpost (`utpost_fast`, excluded from SF planning) — who is which is Q21. |
| D45 | R2 | Roster mechanics: a 10-week base roster repeats for ~6 months. Changes (forskyvning, vaktbytte) are made **in the underlying roster file** by managers and refreshed into the app by re-import; infrequent. |

## Product & workflow

| # | R | Decision |
|---|---|---|
| D22 | R1 | 2-week rolling horizon; publish; published plans editable and regenerateable; locked assignments survive regeneration. |
| D23 | R1 | Display: single portrait screen grouped by the three zones (+ utposter when reactivated); shows assignments and next-rotation takeovers; speaks tidlig/sen/natt/helg. |
| D24 | R1 | Names shown as first name + initial. |
| D27 | R1 | Absences affect supply only; full-day and partial-day supported. |
| D46 | R2 | **Absences are never surfaced on the display** — it simply shows the current (updated) plan. Absence details are manager/admin-only. |
| D47 | R2 | The weekend view is **data-driven**, not special-cased: views render from the day's blocks and rotation rules, so a weekend naturally produces one ad-hoc block. Same for holidays. |

## Technical & deployment

| # | R | Decision |
|---|---|---|
| D25 | R1 | PIN-level access control acceptable (secure internal network). |
| D26 | R1 | SQLite on local/shared drive approved; may hold full personal data. |
| D31 | R1 | One single machine for now; wall display later. |
| D48 | R2 | **User-level pip installs confirmed working** on the work PC — the FastAPI stack is locked in; no stdlib-only fallback needed. |
| D49 | R2 | The app is **self-contained in a single folder** (code, virtual environment, database, import folder, backups — all under one directory, relative paths only), since final paths/hosting won't be settled for a while. |

# Decision log

Decisions referenced from seed data, docs and (later) code as **D-numbers**.
*(interim)* = adopted so work can proceed, still open for revision (has a
Q-number). ~~Struck~~ = superseded; kept for traceability.

Rounds: **R1** = 2026-08-31 (first briefing + answers), **R2** = 2026-09-02
(question round after the department meeting), **R3** = 2026-09-02 (follow-up
answers on intensity, imports and product details), **R4** = 2026-09-04
(UI review of the running prototype), **R5** = 2026-10-13/15 (the real roster
sources: Plan and Ajourhold, and the first anonymised samples of both).

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
| D50 | R3 | **Two-tier intensity**: Kontrollsone (after 12:00) = full intensity **1.0**; all other heavy functions = moderate **0.5**. **Night hours (22–07) carry no intensity** — night work is not considered heavy. Baseline for normal work is 0. *(Window boundaries 07:00/22:00 for the all-day functions are inferred — Q27.)* |
| D51 | R3 | The weekly exposure rule applies to **full-intensity work only** (occurrence threshold: intensity ≥ 1.0): soft target 1 occurrence per employee per week, hard cap 3 — **all parameters admin-adjustable** (`planner_settings.csv`). With current data this makes the rule feasible: ~25 full-intensity slots/week vs. 33 Kontrollsone-qualified employees. Moderate work is governed by the zone swap + ledger balancing. |
| D52 | R3 | **Intensity is tracked per hour**: the ledger accrues intensity × hours from the actual hours spent in each function, using the per-window intensity data (any granularity). Baseline 0 is deliberate: the ledger measures heavy *exposure*; a total-workload metric, if ever wanted, is a separate sum — not a shifted baseline. |
| D53 | R3 | **Rule violations are never silent**: when a cap or rule must be broken (or is broken by a manual edit), the manager/admin gets an explicit warning and can override with an acknowledgement, which is audited. |

## Heaviness, fairness & individual settings

| # | R | Decision |
|---|---|---|
| D9 | R1 | Soft fairness: balance a 28-day rolling intensity-hours count per employee. *(The R1 hard rule "no back-to-back heavy days" is replaced by D37's once-per-week exposure rule.)* |
| D10 | R1 | Intensity is a **continuous scalar per (function, time window)** (`function_intensity.csv`, 0–1). UI shows labels ("tungt"), never numbers. |
| D11 | R1 | Per-employee **restrictions**: exemptions from heavy work and/or specific functions, with validity periods; no reason stored. |
| D32 | R2 | Per-employee **preferred functions** (allowlist): when set, the employee is only assigned functions on their list. Eligibility = competency ∧ not-restricted ∧ (no preference list ∨ function on it). Maintained by managers in the admin view; **never shown anywhere else** (not on display, not on the plan board beyond its effect). |
| D56 | R3 | Preference semantics confirmed: empty list = no constraint; admin-only visibility. **Tilrettelegging is handled via restrictions (fritak)**, not preferences: restrictions carry validity periods and express "should not do X", which matches accommodations; preferences express organizational steering ("works only here"). Confirmed by the owner 2026-09-02. |
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
| D45 | R2 | Roster mechanics: a 10-week base roster repeats for ~6 months. ~~Changes (forskyvning, vaktbytte) are made in the underlying roster file by managers and refreshed into the app by re-import; infrequent.~~ The change-handling half is superseded by D73: changes arrive through Ajourhold. |
| D54 | R3 | **Import drift detection**: the importer compares each file's structure against what the app has configured (columns, sheets) and warns the admin/manager on mismatch — merged, missing, renamed or new columns — before importing. Import file formats may evolve slightly over time; the competency file will be re-issued with the Sterrad/Poliklinikker split. |
| D55 | R3 | **Utpost days are derived from the roster**: shift codes starting with `U` are flagged `utpost_code = yes`, and a day with a U-code keeps that employee out of SF planning for that day (covers both fast staff and future "rullering fra SF"). The `works_at` column remains as a manual fallback/override until the roster import exists. |
| D58 | R3 | Steril sone confirmed: "Produksjon, steril sone" and "Gang/vognvaskere" are borderline indistinguishable and stay `adhoc_zone` — the crew organizes internally. Gang/vognvask competency covered by produksjon_steril. |
| D59 | R3 | Shift categories stay **explicitly assigned** per vaktkode; the app adds an *advisory* heuristic that suggests a category for new codes and flags suspicious assignments, but never classifies silently. (The literal rule "covers both 11:00 and 18:00" would misclassify `ME` 12–20, which does not cover 11:00 — evidence that a hard algorithm here breeds confusion.) Confirmed by the owner 2026-09-02. |

## Roster sources & personal data (R5)

| # | R | Decision |
|---|---|---|
| D73 | R5 | **Two roster sources, one effective roster.** **Plan** (the turnus; exported for a whole year, currently 2026) gives the planned shifts. **Ajourhold** (the ukeplan; the HR system exports one week at a time, so a manager exports it weekly) carries the freshest changes — above all absence and leave. For every date inside an imported Ajourhold week, Ajourhold wins; elsewhere Plan stands. *(interim, Q32: Ajourhold is treated as authoritative for the whole week it covers, pending whether it lists every person or only the changes.)* |
| D74 | R5 | **Terminology.** The HR system's module names are kept as proper names: **Plan** and **Ajourhold**; in the UI «Turnus (Plan)» and «Ukeplan (Ajourhold)». In English text: *planned roster* and *roster maintenance*; combined, the *effective roster*. In code: `source = 'plan' \| 'ajourhold'` — never a bare "plan" for the HR source, since the app already uses *plan* for placement plans (`plan_days`, `/plan`). |
| D75 | R5 | **Ajourhold coverage is visible.** The planning overview shows, per week, whether an ukeplan has been imported (and when); days that rest on Plan alone are flagged, so the weekly export routine is easy to keep. |
| D76 | R5 | **Absences carry no type.** The app only needs to know that someone is unavailable (and when) — not why. Ajourhold's absence codes are mapped by configuration to *available / unavailable*, and only that is stored. Resolves Q29: the manual absence form drops its type list when the Ajourhold import lands. Sick-leave detail never enters the app. |
| ~~D77~~ | R5 | ~~Identity: employee number … the next Plan export will add ansattnr~~ — superseded by D82: the Plan export will keep names only for now. |
| D78 | R5 | **Real exports never leave the PC; the repo is public.** Real files live in `data/import/` — the app's import folder (D29) — and the anonymiser's key and output in `data/private/`; both are git-ignored except their READMEs, and new files in `data/source/` are ignored too. `scripts/anonymise_export.py` runs locally and writes structure-preserving copies with invented names/numbers, person comments removed and a 20-person sample. Those copies are shared in the chat, **never committed** — a rotation pattern can identify a colleague even under an invented name. Test fixtures in the repo are synthetic, generated from the learned structure. |
| D79 | R5 | **Job titles (Stillingsbetegnelse) are data, not code.** Each turnus row carries one; titles are matched by exact text and novel ones must be handled without code changes (a renamed main title is just a new title to classify). Titles seen: Sterilforsyningstekniker, Prosjektmedarbeider, Spesialkonsulent, Renholdsoperatør, IKT-konsulent, Kvalitetskoordinator. **IKT-konsulent and Kvalitetskoordinator are never placed on the normal functions** — they have other tasks. *(Mechanism under review: position rules as their own eligibility layer, see D87.)* Titles may later steer competency tables too. |
| D80 | R5 | **One person never has two shifts on the same day across rows.** A person can have several turnus rows (concurrent positions, or a change of role during the year); if two rows for the same name both carry a code on one date, the import raises an alert. |
| D81 | R5 | **No skip rules.** Every row in the person range is imported on equal terms, even one whose name looks odd (e.g. "Ola50"): an aberrant row is an HR-system matter to fix at the source, and guessing which rows to drop adds risk. Such a row simply surfaces through the ordinary checks (no competencies, no match). |
| D82 | R5 | **Identity is the full name, exactly as exported**, until the Plan export adds its optional PersonID column (then PersonID becomes primary; the header-anchored parser absorbs the extra column). Names are compared after trimming and collapsing whitespace, never reordered — the exports write them reversed, and the competency file must use the identical form. Ajourhold's PersonID is stored alongside. PersonIDs are 3–5 digit integers without leading zeros. **Any ambiguity alerts**: one name with two PersonIDs, one PersonID with two names, or an exact duplicate that can't be told apart. |
| D83 | R5 | **One export covers the whole unit** («STS, Steril forsyning driftspersonell»); managers belong to another unit and are not in it. The unit name is checked on every import. |
| D84 | R5 | **File names and precedence.** Real files are named `Utskrift_fleksiplan_<ÅÅÅÅMMDDttmmss>.csv` (Plan) and `Ukeplan_<ÅÅÅÅMMDDttmmss>.csv` (Ajourhold, one week per file). A plan covers 10–12 weeks ahead and is exported a handful of times a year. For any date, the newest file covering it wins. |
| D85 | R5 | **Refuse rather than misread.** Each export has a structural fingerprint (title lines, unit, header row, day-column pattern, legend and summary blocks, encoding, delimiter). Any deviation — e.g. an export made with different settings — rejects the file with a message saying what was expected and what was found. Content issues that don't make the reading doubtful import with an alert. |
| D86 | R5 | **Combined codes are never guessed.** `DK/F3` (Plan) and `N, M` (Ajourhold) use different separators and their meaning is not yet confirmed (Q34–Q36). Until it is, the raw text is kept and the day is flagged for the manager; nothing is inferred from it. |
| D87 | R5 | *(proposed, under review)* **Position rules as an eligibility layer.** Per title: planned normally / never on any function / excluded from specific functions. Kept separate from the competency matrix, because the rule belongs to the role, not the person (someone changing role mid-year needs no edits); the existing per-person fritak (D56) stays the tool for individual exclusions. Shifts of a never-planned title stay in the roster but are left out of placement and supply, like utpost days (D55). |
| D88 | R5 | *(proposed, under review)* **Imports live in the SQLite database** the app already uses: one row per imported file (kind, export time, period, hash, status, alerts) plus its raw entries, so coverage, staleness and supersession are queries, re-importing the same file is a no-op, and a bad import can be withdrawn. Raw CSVs are archived after import and purged once superseded and past. |

## Product & workflow

| # | R | Decision |
|---|---|---|
| D22 | R1 | 2-week rolling horizon; publish; published plans editable and regenerateable; locked assignments survive regeneration. |
| D23 | R1 | Display: single portrait screen grouped by the three zones (+ utposter when reactivated); shows assignments and next-rotation takeovers; speaks tidlig/sen/natt/helg. |
| D24 | R1 | Names shown as first name + initial. |
| D27 | R1 | Absences affect supply only; full-day and partial-day supported. |
| D46 | R2 | **Absences are never surfaced on the display** — it simply shows the current (updated) plan. Absence details are manager/admin-only. |
| D57 | R3 | **Every shift has a DK/ansvarsvakt** — weekends and holidays included (1 person 08–18 on weekend days; the rest of the weekend crew stays ad hoc). The planner warns when no qualified person is available. |
| D60 | R3 | Absences are both **importable from file and definable in-app** (manager/admin). Default type list *(interim, Q29)*: Syk · Ferie · Kurs/opplæring · Permisjon · Annet. |
| D47 | R2 | The weekend view is **data-driven**, not special-cased: views render from the day's blocks and rotation rules, so a weekend naturally produces one ad-hoc block. Same for holidays. |
| D62 | R4 | **Display grouping is zone → funksjon → ansatt(e)**, with each person's post-rotation destination on their own row. Heading: «Fordeling, SF». |
| D63 | R4 | The day view has two shapes: **«Per sone» (swimlane timeline) is the default** — one row per employee under each function, time left→right on a half-hour grid, with rotation markers (11:00/18:00 solid, mellomvakt 16:00 dashed and subtler) — and «Tidsblokker», which groups by **shift category** (tidligvakt → mellomvakt → senvakt → nattevakt → helgevakt) before time block. Management views use the full window width; only the display stays portrait-constrained. |
| D69 | R4 | **The wall board has a light theme**, chosen in the admin view («Fargevisning på tavlen»), stored in a small `app_settings` key/value table. `?tema=lys`/`?tema=mork` overrides it for a one-off preview. The layout, zone colours and fit-to-screen behaviour are identical in both; default is dark. |
| D70 | R4 | **«Diverse info» is multi-line** (a textarea; line breaks are preserved on the board). The board's panel is the one that carries emphasis — bright amber, a thick left rule, bold 1.25em text — while the editor in the plan view stays a plain card. |
| D72 | R4 | **Board hierarchy reads across the room**: the function heading is set full-size, bold, uppercase and in the strong ink colour over a 2 px rule, so it separates its group as clearly as the zone header above it; employee names are bold and every row carries a hairline rule that carries the eye to the rotation chip. Dotted leaders between name and chip were tried and dropped — with the row rules already in place they made the board look cluttered (R4 feedback). |
| D71 | R4 | **Static assets are versioned** (`/static/app.css?v=<mtime>`): FastAPI's StaticFiles sends no `Cache-Control`, so browsers cache the stylesheet heuristically and a pulled restyle could stay invisible until a hard refresh. Stamping the URL makes every change a new URL. |
| D68 | R4 | **Publishing is reversible, deleting is gated.** «Avpubliser» returns a published day to *utkast* and removes it from the wall board — allowed for any day, including today, but behind a confirmation that says the board will be left without a plan. «Slett planen» removes a day's placements outright, locked rows included, and is offered **only on drafts**; a published plan must be unpublished first. The route enforces that too, not just the UI. Deleting a plan leaves «Diverse info» and registered absences untouched, since neither is part of the plan. Bulk delete/unpublish across a week is deliberately withheld until there is an edit history to undo from (UX backlog #7). |
| D67 | R4 | **The wall board fills its screen**: display sizes are `em`-based on a viewport-scaled root, so the same markup serves a laptop preview and a 1080×1920 portrait screen; a small fit-to-screen script then grows or shrinks the type (14–48 px) so a quiet day fills the height and a busy one never scrolls. Notices sit at the foot whatever the height. |
| D65 | R4 | **«Diverse info» per day**: a free-text notice bound to the date, edited near the top of the day's plan view and shown at the foot of the wall display — only when it has text. Kept in its own table so it never affects a day's plan status. |
| D66 | R4 | Timeline bars state what each end means: a **rounded cap** is the shift's own start/end, a **square cap with ›** is a rullering to or from another function, and abutting bars mean the same function continues. |
| D64 | R4 | **One stylesheet, one token set** (`app/static/app.css`): zone colours are defined once and softened/desaturated. Zone chips are solid with white text; status chips (publisert/utkast/endret) are soft tints with dark text — so a status can never be mistaken for a zone. Staffing modes are shown in Norwegian (Resterende / Påkrevd / Ad hoc); planner setting keys stay in English since the explanation column carries the meaning. |

## Technical & deployment

| # | R | Decision |
|---|---|---|
| D25 | R1 | PIN-level access control acceptable (secure internal network). |
| D26 | R1 | SQLite on local/shared drive approved; may hold full personal data. |
| D31 | R1 | One single machine for now; wall display later. |
| D48 | R2 | **User-level pip installs confirmed working** on the work PC — the FastAPI stack is locked in; no stdlib-only fallback needed. |
| D49 | R2 | The app is **self-contained in a single folder** (code, database, import folder, backups — all under one directory, relative paths only), since final paths/hosting won't be settled for a while. |
| D61 | R3 | **No virtual environment on the work PC** — org policy blocks venv creation there. Dependencies install per-user (`pip install --user`); `run.py`/`start.bat` assume no venv and work from any current directory. The single-folder principle (D49) stands, with packages living in the user profile. The app folder should sit **outside OneDrive** (or be marked "Always keep on this device") so sync never locks the SQLite file; **network drives (H:) are unsuitable** for the SQLite file. Addendum: group policy also blocks `.bat` execution on the work PC, so the canonical launch is **`python run.py`** (terminal, or a Windows shortcut targeting `python.exe run.py`); the .bat/.sh wrappers remain for unrestricted machines. |

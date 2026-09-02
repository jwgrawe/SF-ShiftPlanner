# Source data — findings and how it was restructured

This documents what was found in the four workbooks received 2026-08-31 (stored
unmodified in `data/source/`), how each was translated into the editable seed
tables in `data/seed/`, and every inconsistency or gap discovered on the way.
Items marked **⚠** were flagged for clarification; where an answer has since
arrived, the resolution is noted as a D-number ([decisions.md](decisions.md))
or remains as a Q-number ([open-questions.md](open-questions.md)).

## 1. `Grunnbemanning_funksjonsvis.xlsx`

### Sheet `Ark1` — hourly staffing demand

A matrix of functions × clock hours with required head-count. Structure decoded:

- Hour columns run **07 → 23, then 01 → 06**. **⚠ Hour 00 (midnight) is missing
  entirely.** Filled by interpolation in the seed — *confirmed unproblematic
  (D12)*.
- Asterisk conventions (from the legend rows at the bottom):
  - `*` = heavy work at all times → `heavy = always`
  - `**` = heavy work after 12:00 → `heavy = after_12`
  - `***` (on Arbeidsbord/brikkelegging) = *not* a heaviness marker; it points
    to the list of worktable types. **⚠ The legend says 10 worktables but only
    8 types are listed** (ORT, ORTA, KOP, KVOP, HLOP, NOP, ØNHO, ØYOP) —
    *defused by D18: tables are generic and treated as one group, so the exact
    count no longer affects planning.*
  - The asterisk heaviness markers are now modeled as continuous intensity
    windows in `function_intensity.csv` (D10).
- Empty demand rows have **three distinct meanings**, now made explicit via
  `staffing_mode` in `functions.csv`:
  | Meaning | Functions | Seed representation |
  |---|---|---|
  | "Everyone left over in this zone works here" | Produksjon uren sone; Arbeidsbord/brikkelegging | `staffing_mode = remainder`, no demand row |
  | "Zone staffed as a whole, distributed ad hoc internally" | Produksjon steril sone; Gang/vognvaskere | `staffing_mode = adhoc_zone`, demand carried by the `zone_total` row for steril |
  | "No demand" | (empty hour cells in otherwise filled rows) | `0` in the demand row |
- Zone totals: Uren and Steril have explicit hourly totals; **⚠ Ren sone's
  total row is empty** — *confirmed (D13): ren sone absorbs everyone not
  otherwise placed, via Arbeidsbord/brikkelegging, nights included (D14).*
- Row "Antall ansatte på jobb" (16–17 by day, 15 late evening, 7 at night) is
  itself an *assumption* about attendance. In the app this number must come
  from the actual roster (who is on shift that day), not from configuration.
  It is kept in the seed as `row_type = total_on_duty` for reference only.
- Utposter demand is inconsistent between sheets — see below.

### Sheet `Dagsvis` — per-weekday rules

Mostly empty; the filled cells are free-text rules for the utposter:

- Kir. Pol. (rullering fra SF): Thu 10:00–17:00 (1 person), Fri 10:00–15:00 (1 person)
- Gastrolab. (fast): Thu + Fri, two people, 09:00–16:00 and 10:00–17:00
- KOP barn (fast): activity Thursdays 08:00–15:00 only; otherwise "Ingen aktivitet"

These are structured in `weekday_rules.csv`.

**⚠ Inconsistencies between the two sheets:**

- `Ark1` gives the *rullering* utposter a total of 1 person at hours 10–11 only,
  while `Dagsvis` says Kir. Pol. alone needs 1 person 10:00–17:00 on Thursdays.
- `Ark1` gives Gastrolab (fast) up to **3** people at midday, while `Dagsvis`
  describes only **2** (09–16 and 10–17), and only on Thu/Fri.
- The `Dagsvis` sheet also splits "Sterrad" and "Poliklinikker" into separate
  rows, while `Ark1` combines them as one function — *now two functions per
  D16; the combined demand/competency split remains open (Q5).*

The utposter conflict is still under investigation (Q10); the seed keeps both
versions verbatim (in `staffing_demand.csv` and `weekday_rules.csv`) rather
than guessing which is right. Fast utpost staff are display-only, not planned
(D20).

## 2. `Vaktkoder_SF.xlsx` → `shift_codes.csv`

21 shift codes. Cleanups and findings:

- `A1` used `13.30`/`21.00` with dots and stray spaces → normalised to
  `13:30`/`21:00`. Several other cells had trailing spaces.
- The source's `Vakttype` column (Dag/Kveld/Natt) is **disregarded** per the
  project decision; instead a `category_proposed` column maps every code onto
  the four planning categories (tidligvakt/senvakt/nattevakt/helgevakt) using
  explicit per-code assignment. **⚠ The straddling codes** were resolved in
  round 2: `H2` turned out to be a weekend code (D36), and `ME`/`UME` became
  the new category **mellomvakt** with its own 16:00 rotation time (D35).
  Categories are assigned explicitly per code, not by formula (Q25 confirms).
- **⚠ Several codes exceed the stated 7.5 h maximum**: `N` 9 h, `NA` 9.5 h,
  `U8` 9 h, `U9` 9 h — *resolved (D15): longer shifts are allowed; the 7.5 h
  rule is the HR system's concern and is disregarded here.*
- **⚠ No code matches the helgevakt window 08:00–18:00** — *resolved (D36):
  `H1` (08–16) and `H2` (10–18) are the weekend/holiday codes.*
- `DK`/`DKK` are dedicated Driftskoordinator codes and `U*` codes are dedicated
  utpost codes — i.e. for these, the *function* is largely decided by the
  roster before daily planning starts.

## 3. `Åpningstider_og_vakter_i_SF.xlsx` → `opening_hours.csv`

Already tidy; copied through with normalised headers. One detail worth noting:

- Friday 15:00–17:00 is `Hverdag`, but **Friday 17:00–22:00 is typed `Helg`**
  while still being an open Senvakt period. **⚠ Does the Friday senvakt follow
  weekday rules or weekend rules?** — *resolved (D34): Friday evening rotates
  at 18:00 like every other weekday; the `Helg` typing is only about opening
  periods.*
- The week is closed Mon 00:00–07:00, Fri 22:00 → Sat 08:00, Sat 18:00 → Sun
  08:00, and Sun 18:00 → Mon 07:00 — matching the briefing.

## 4. `Kompetanse_Anonymisert.xlsx` → `competencies.csv`

Received 2026-08-31 (second delivery). A matrix of 69 anonymized employees
("Employee 1"–"Employee 69") × 14 competency columns grouped by zone,
marked with `x` (and occasionally `?`). Import pipeline:
`scripts/import_competencies.py` converts it to `competencies.csv`
(`x` → `qualified`, `?` → `uncertain`), and `scripts/generate_fake_employees.py`
gives each anonymized row a deterministic fictional identity via the
`source_label` column in `employees.csv` — so the test data carries the
department's **real competency structure** under fictional names.

Findings:

- **⚠ Five columns contain no marks at all** — *resolved for uren (D42: the
  three uren columns are covered by "Produksjon, uren sone" competency, via
  the function-competency mapping) and for DK (D41: DK is identified via
  shift codes; the function merged with Ansvarsvakt). Gang/vognvaskemaskiner
  remains an assumption (Q24: covered by produksjon_steril).*
- **⚠ Five `?` marks** (Employees 15, 18, 29, 36, 37) — *resolved (D44): a
  manager's "assess this" reminder; imported as `uncertain`, never eligible;
  any other unexpected mark is ignored with a warning.*
- The column *"Sterrad + poliklinikker/løspakk"* is combined, while both the
  function **and the competency** were split (D43) — the import credits both
  competencies from the one column until the file is re-issued (Q20).
- Coverage counts (qualified): Produksjon uren 59, Arbeidsbord 60,
  Produksjon steril 38, Kontrollsone 33, Sterrad+poliklinikker 27,
  Ansvarsvakt 21, Kir. Pol. 18, Gastrolab 14, KOP barn 10.
- Minor naming variants vs. the staffing sheet ("Daglige rutiner" vs "Ansvar
  daglige rutiner"; "Gang/vognvaskemaskiner" vs "Gang/vognvaskere"; "Kirurgisk
  poliklinikk" vs "Kir. Pol."; "Gastro lab." vs "Gastrolab.") — mapped
  explicitly in the import script, worth unifying at the source eventually.
- Ten employees have **no uren competency**, and Employee 55 has only
  *Produksjon, uren sone* — useful realism for testing shortfall warnings.

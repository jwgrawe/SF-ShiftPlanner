# Source data — findings and how it was restructured

This documents what was found in the three workbooks received 2026-08-31 (stored
unmodified in `data/source/`), how each was translated into the editable seed
tables in `data/seed/`, and every inconsistency or gap discovered on the way.
Anything marked **⚠** also appears in [open-questions.md](open-questions.md).

## 1. `Grunnbemanning_funksjonsvis.xlsx`

### Sheet `Ark1` — hourly staffing demand

A matrix of functions × clock hours with required head-count. Structure decoded:

- Hour columns run **07 → 23, then 01 → 06**. **⚠ Hour 00 (midnight) is missing
  entirely.** In the seed data it has been filled by interpolation (h23 and h01
  are equal everywhere it matters) and flagged in the `notes` column.
- Asterisk conventions (from the legend rows at the bottom):
  - `*` = heavy work at all times → `heavy = always`
  - `**` = heavy work after 12:00 → `heavy = after_12`
  - `***` (on Arbeidsbord/brikkelegging) = *not* a heaviness marker; it points
    to the list of worktable types. **⚠ The legend says 10 worktables but only
    8 types are listed** (ORT, ORTA, KOP, KVOP, HLOP, NOP, ØNHO, ØYOP).
- Empty demand rows have **three distinct meanings**, now made explicit via
  `staffing_mode` in `functions.csv`:
  | Meaning | Functions | Seed representation |
  |---|---|---|
  | "Everyone left over in this zone works here" | Produksjon uren sone; Arbeidsbord/brikkelegging | `staffing_mode = remainder`, no demand row |
  | "Zone staffed as a whole, distributed ad hoc internally" | Produksjon steril sone; Gang/vognvaskere | `staffing_mode = adhoc_zone`, demand carried by the `zone_total` row for steril |
  | "No demand" | (empty hour cells in otherwise filled rows) | `0` in the demand row |
- Zone totals: Uren and Steril have explicit hourly totals; **⚠ Ren sone's
  total row is empty** — presumably "everything left over in the whole
  department", but this must be confirmed.
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
  rows, while `Ark1` combines them as one function.

The seed keeps both versions verbatim (in `staffing_demand.csv` and
`weekday_rules.csv` respectively) rather than guessing which is right.

## 2. `Vaktkoder_SF.xlsx` → `shift_codes.csv`

21 shift codes. Cleanups and findings:

- `A1` used `13.30`/`21.00` with dots and stray spaces → normalised to
  `13:30`/`21:00`. Several other cells had trailing spaces.
- The source's `Vakttype` column (Dag/Kveld/Natt) is **disregarded** per the
  project decision; instead a `category_proposed` column maps every code onto
  the four planning categories (tidligvakt/senvakt/nattevakt/helgevakt) using
  the *midpoint rule*: a shift belongs to the category whose window contains
  the shift's midpoint. **⚠ The rule needs confirmation**, especially for the
  straddling codes `H2` (10–18), `ME`/`UME` (12–20).
- **⚠ Several codes exceed the stated 7.5 h maximum**: `N` 9 h, `NA` 9.5 h,
  `U8` 9 h, `U9` 9 h (A, D, H1, H2, ME are 8 h). Presumably unpaid breaks are
  included, but this contradicts the briefing and should be clarified.
- **⚠ No code matches the helgevakt window 08:00–18:00.** Which codes are
  actually worked on weekends/holidays?
- `DK`/`DKK` are dedicated Driftskoordinator codes and `U*` codes are dedicated
  utpost codes — i.e. for these, the *function* is largely decided by the
  roster before daily planning starts.

## 3. `Åpningstider_og_vakter_i_SF.xlsx` → `opening_hours.csv`

Already tidy; copied through with normalised headers. One detail worth noting:

- Friday 15:00–17:00 is `Hverdag`, but **Friday 17:00–22:00 is typed `Helg`**
  while still being an open Senvakt period. **⚠ Does the Friday senvakt follow
  weekday rules (rullering at 18:00) or weekend rules (ad hoc)?**
- The week is closed Mon 00:00–07:00, Fri 22:00 → Sat 08:00, Sat 18:00 → Sun
  08:00, and Sun 18:00 → Mon 07:00 — matching the briefing.

## 4. `Kompetanse - Anonymisert` — **not received**

The file was mentioned in the briefing but did not arrive with the upload.
As a stand-in, `scripts/generate_fake_employees.py` deterministically generates
69 fictional employees (`employees.csv`) and a placeholder eligibility matrix
(`competencies.csv`, employee × function). Both must be replaced by an import
of the real file once available — see open questions, section D.

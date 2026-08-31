# Open questions

Fresh list as of 2026-08-31, after the first round of answers (recorded in
[decisions.md](decisions.md)). Numbered **Q1–Q17** for reference from seed
data and code; bring this list to the clarification meeting.

Where an *interim rule* is stated, the project proceeds on that assumption —
the question is whether it's right, not whether work is blocked.

Priority: 🔴 gates the planning engine · 🟡 needed soon · 🟢 can wait.

## A. Roster & import

**Q1 🔴 The roster export.** *(Sample promised later this week.)* When it
arrives, we also need:
- the exact field layout (employee identifier, date, shift code — anything
  else, e.g. absence codes?);
- **how employee identity matches across sources** — does the roster export
  and the competency sheet share an employee number, so the app can join
  them? (The competency file is row-anonymized; the join key question remains.)
- whether absences appear in the export at all, or only get registered
  in-app (per D27 they only affect supply).

**Q2 🟡 Mid-period roster changes.** When the 10-week roster changes after
import (swaps, new hires, corrected shifts): is the mechanism a fresh
export/re-import, and how often should managers expect to do it?

## B. The competency file

**Q3 🔴 Five columns are completely empty**: *Daglige rutiner (uren)*,
*Manuell rengjøring*, *Gangen*, *Driftskoordinator*, *Gang/vognvaskemaskiner*.
Are these (a) covered implicitly by zone competency, (b) simply not yet
registered, or (c) genuinely zero qualified? Note the tension: D19 says
specific employees hold DK, yet the DK column is empty.
*Interim rule:* the planner fills the three uren functions from
`uren_produksjon`-qualified staff and vognvask from `steril_produksjon`-
qualified staff; Driftskoordinator comes from the DK/DKK shift codes only.

**Q4 🟡 What does "?" mean?** Five marks (Employee 15, 18, 29, 36, 37 —
mostly under *Produksjon, steril sone*). Under training? Needs refresh?
*Interim rule:* imported as status `uncertain` and treated as **not**
eligible.

**Q5 🟡 The Sterrad/Poliklinikker split (D16) needs two follow-ups:**
(a) the competency column is combined — is one competency really valid for
both functions? (b) the hourly demand exists only combined (2 people
mornings, 1 midday, 2 in the evening) — how does it split between the two?
*Interim rule:* competency applies to both; demand kept as a combined
"function group" row.

## C. Rullering

**Q6 🟡 Friday evening.** Rotation assumed at **17:00** (D30) since the
period is helg-typed from 17:00 — confirm the time, and that Friday evening
rotates at all rather than self-managing.

**Q7 🟡 Mid shifts.** `ME`/`UME` (12–20) and `H2` (10–18) span both rotation
points. Do they rotate at both, one, or neither? Related: confirm the
midpoint rule used to map every shift code to tidlig/sen/natt/helg
(`category_proposed` in `shift_codes.csv`).

**Q8 🟡 Confirm the rotation rule (D5):** everyone on a heavy function must
leave it at the rotation point, replacements from anywhere competence
allows. Flagged as "not 100 % certain" — the app keeps it configurable
either way.

**Q9 🟢 Partial-shift heavy work** currently counts as a full "heavy day"
in the back-to-back rule (D9). Keep, or refine (e.g. a minimum number of
heavy hours)?

## D. Demand data

**Q10 🔴 Utposter numbers conflict** between the hourly matrix (Gastrolab
up to 3 people daily; rullering total only hours 10–11) and the per-weekday
sheet (Gastrolab 2 people Thu/Fri only; Kir. Pol. Thu 10–17 / Fri 10–15).
*(Owner investigating.)* Also unstated: KOP barn's Thursday head-count
(assumed 1).

**Q11 🟡 Weekend/holiday shift codes** are missing from the vaktkode list —
no code matches the 08:00–18:00 helgevakt window. *(Owner adding.)*

**Q12 🟢 Are utpost functions heavy?** Currently intensity 0 (no marks in
the source).

**Q13 🟢 Weekend display.** With everyone ad hoc (D21), should the screen
show anything beyond the day's crew list per zone — e.g. who holds
ansvarsvakt-like responsibility, if anyone?

## E. Product details

**Q14 🟡 Absence types.** Which list should the app offer (syk, egenmelding,
ferie, kurs, permisjon, annet …)? Should the type be visible to everyone on
the display/plan, or shown simply as "fravær" with the type visible only to
managers?

**Q15 🟢 Driftskoordinator fallback.** If no DK/DKK-coded employee is
present (sickness): should the planner suggest a replacement (requires an
answer to Q3 — who is DK-qualified?), or leave the slot empty with a
warning for the manager?

## F. Technical

**Q16 🟡 Package installation on the work PC.** Test user-level installs
(no admin rights needed) — instructions in [assessment.md](assessment.md)
§6. The outcome decides FastAPI vs. a stdlib-only fallback.

**Q17 🟢 Concrete paths.** Where should the app folder, the SQLite file and
the import folder live — local disk or a shared drive (which one)?

---

### Resolved since last version

Former questions on terminology, stack, rotation time (18:00), ren sone as
remainder, night staffing, hour 00:00, shift-code lengths, competency
granularity, worktables, utpost fast staff, weekends/holidays, horizon,
display layout, naming, UI language, PINs, storage and absences are all
settled — see [decisions.md](decisions.md).

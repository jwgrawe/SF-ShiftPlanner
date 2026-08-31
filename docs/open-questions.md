# What must be known or defined before/while building

This is the master list of decisions, missing data and clarifications the
project needs. Each item says **why it matters** for development. Items are
grouped by theme and roughly ordered by how early they block progress.

Priority key: 🔴 blocks the planning engine · 🟡 needed before the app is
useful in production · 🟢 can be decided late / defaulted for the prototype.

## A. The roster — who is actually at work? 🔴

**This is the single biggest missing input.** The demand side (functions ×
hours) is now well covered by the seed data, but the *supply* side is not:

1. **How do we know which employee works which shift code on which date?**
   The briefing mentions "a table listing employees and their shift codes",
   but no such table was provided. Is it:
   - a fixed repeating pattern per employee (a "turnus" with e.g. a 6-week
     cycle), or
   - a per-date roster exported from the workforce system (GAT/MinGat or
     similar), or
   - something managers type in manually?
   The prototype can start with a hand-editable `roster.csv`
   (`date, employee_id, shift_code`), but the answer decides the whole import
   story and how many weeks ahead the app can plan.
2. **What does a realistic week of rosters look like?** Even a fictionalised
   two-week example (69 employees × dates × codes) would let us test the
   planner against reality — e.g. whether 16 people really are present on a
   weekday morning.
3. **Absence handling:** which absence types matter (sick, child-sick, leave,
   course, vacation)? Full-day only, or partial-day? Does an absence ever
   *change* demand (e.g. close a worktable) or only supply?

## B. Rullering (rotation) semantics 🔴

4. **The late-shift rotation time is stated as both 18:00 and 17:00** in the
   briefing (requirements say 18:00; the display description says "switch at
   either 11:00 or 17:00"). Which is correct — or does it vary?
5. **Who must rotate?** Is the rule (a) everyone on a heavy function must leave
   it at the rotation point, (b) they *may* rotate, or (c) whole pairs/groups
   swap between a heavy function and the default pool? Where do replacements
   come from — only the zone's default pool, or anywhere competence allows?
6. **"1 rotation per shift" — hard or soft?** Does it mean each employee
   changes function *at most* once per shift, *exactly* once, or that each
   heavy function swaps its crew once?
7. **Interaction between rotation at 11:00 and heaviness from 12:00:** a person
   put on `Gangen` or `Kontrollsone` (heavy *after 12:00*) at the 11:00
   rotation gets the heavy part of the day. Is that intended (fresh person
   takes the heavy stretch), and does the 07–11 stint on such functions count
   as heavy work in the fairness accounting?
8. **Night shift:** no rotation at night, correct? And which functions do the
   ~7 night workers cover (demand rows suggest uren 2, ansvarsvakt 1,
   kontrollsone 1, steril 1 — leaving 2 unaccounted)?
9. **Friday evening** is typed `Helg` from 17:00 in the opening-hours table.
   Does Friday's senvakt rotate as a weekday or self-manage as a weekend?
10. **Mid shifts (`ME`/`UME` 12–20, `H2` 10–18)** span both rotation points.
    How do they participate — rotate at both, one, or neither? And is the
    proposed "midpoint rule" for mapping shift codes to the four categories
    acceptable (see `shift_codes.csv`, column `category_proposed`)?

## C. Heavy-work fairness rules 🔴

11. **The exact constraint must be quantified.** "Not several days in a row,
    ideally not several weeks in a row" could mean, e.g.:
    - hard: no employee has heavy blocks two working days in a row;
    - soft: minimise a rolling heavy-load score per employee over 2–4 weeks.
    Proposal to confirm: *hard* rule against back-to-back heavy days +
    *soft* balancing of a 28-day rolling "heavy hours" count. What counts as
    a "heavy day" — any heavy block, or a minimum number of heavy hours?
12. **Does half a shift on a heavy function count the same as a full one?**
    (Relates to B7.)
13. **Are some employees exempt** (pregnancy, injury, age, "tilrettelegging")?
    That implies a per-employee flag with a validity period — sensitive data,
    so probably just "exempt from heavy work yes/no" with no reason stored.

## D. Competency data 🟡

14. **The real competency file** ("Kompetanse - Anonymisert", 69 employees) was
    not received. Needed: the file itself, plus its column semantics.
15. **Is competency binary or graded?** (qualified / under training / can do
    with support?). The seed models it as binary eligibility per function.
16. **Do worktable types (ORT, ORTA, …) have their own competencies?** If
    brikkelegging is planned per table type, planning granularity in ren sone
    changes significantly. Also: the legend says 10 tables, 8 types are
    listed — what are the last two?
17. **Special roles by shift code:** DK/DKK (Driftskoordinator) and U-codes
    (utposter) imply the function is decided by the roster, not by the daily
    planner. Confirm: the planner should treat these as pre-assigned and plan
    everyone else around them. Is Ansvarsvakt likewise tied to specific
    (senior) employees?

## E. Demand data gaps 🟡

18. **Hour 00:00 is missing** from the demand matrix (assumed equal to
    23:00/01:00 in the seed — confirm).
19. **Ren sone has no zone total.** Confirm the interpretation: ren sone
    absorbs everyone not needed elsewhere (via Arbeidsbord/brikkelegging).
20. **Utposter numbers conflict** between the hourly sheet and the per-weekday
    sheet (see source-data-findings.md). Which is authoritative? Are the
    "fast" utpost staff inside or outside the 69-person pool this app plans —
    i.e. should the app *plan* them or merely *display* them?
21. **Weekend demand is undefined** beyond "5–6 people self-manage". Are there
    minimums per zone on weekends (e.g. at least 1 in steril)? Is the
    weekend day demand matrix simply not applicable?
22. **Sterrad vs. poliklinikker:** one function or two?
23. **Do holidays follow the weekend pattern exactly** (08–18, ad hoc)? What
    about half-days such as Christmas Eve, New Year's Eve, Easter Wednesday —
    hospital-specific rules? (Norwegian national holidays themselves can be
    computed in code; no data needed.)

## F. Product / UX decisions 🟡

24. **Planning horizon and workflow:** how many weeks ahead should suggestions
    be generated (proposal: 2 weeks rolling)? Who "publishes" a plan, and may
    a published plan be regenerated? (Proposal: regeneration never overwrites
    manually locked assignments.)
25. **Display screen:** what should it show outside rotation windows vs. the
    30–60 min around 11:00/18:00 (proposal: current placement + "next change"
    panel)? Portrait or landscape? One screen or several (per zone)?
26. **Naming on the wall display:** full names, or first name + initial?
    The screen hangs in a semi-public area — worth a deliberate GDPR-friendly
    choice even though viewers are staff. (Seed data includes a
    `display_name` column: "Kari H.".)
27. **How do night shifts display?** A "planning day" runs 07:00 → 07:00 (the
    night shift belongs to the day it starts). Confirm this matches how staff
    think about it.
28. **Language of the UI:** Norwegian (bokmål) assumed for all end-user
    screens; code/docs in English.

## G. Technical / environment 🟢

29. **Can the work PC install Python packages** (pip against PyPI, possibly
    via a proxy)? If not, the stack must shrink to the standard library —
    doable, but worth knowing before choosing FastAPI/Flask. Which browser is
    available (Edge?), and can the wall display point at the work PC over the
    network, or is it the same machine?
30. **Where may data live?** Even with fictional data now, confirm SQLite
    file on a local/shared drive is acceptable, and whether real names may be
    stored there later without further approval (likely fine internally, but
    hospitals often require a DPIA — worth asking early because approval is
    slow).
31. **Backup/copy routine** for the SQLite file (proposal: the app writes a
    dated backup on start).

## Suggested resolution order

1. A1–A2 (roster source + example data) — everything else feeds off this.
2. B4–B10 (rullering semantics) and C11–C13 (fairness rules) — needed to
   design the planner correctly the first time.
3. D14–D17 (competency file) — swap fake data for realistic structure.
4. E18–E23 (demand gaps) — mostly confirmations; defaults already chosen in
   the seed and marked with notes.
5. F/G — can be answered while the data foundation is being built.

# Open questions

Current list as of 2026-09-02, after the department's question round.
Q-numbers are stable across rounds: **Q2–Q17 are resolved** (answers recorded
in [decisions.md](decisions.md)); Q1 remains open; new items continue from
Q18. Where an *interim rule* is stated, work proceeds on that assumption.

Priority: 🔴 gates the planning engine · 🟡 needed soon · 🟢 can wait.

## A. Roster & import

**Q1 🔴 The roster export.** *(Still pending — sample promised.)* Needed with
it: the field layout, and **the identity join key** — do the roster export
and the competency data share an employee number the app can join on?

## B. Rotation semantics *(new — the big ones)*

**Q18 🔴 Scope of the zone swap (D37).** "Rotation between uren sone and ren
sone (all functions)" needs pinning down, because the crews are different
sizes (uren needs 3–6 people; ren holds most of the department):

- Does the **entire uren crew** leave uren at the rotation point, replaced by
  an equal number from ren — or only part of the crew?
- Who in ren is in the swap pool: only the Arbeidsbord/brikkelegging
  remainder, or also people on demand functions (Kontrollsone, Sterrad,
  Poliklinikker/løspakk, DK/ansvarsvakt)?
- **Kontrollsone and Gangen are heavy from 12:00** but are not a uren↔ren
  swap in themselves. Does the person on Kontrollsone rotate within ren
  (e.g. to arbeidsbord), does the Gangen person swap like the rest of uren —
  or do these simply follow the zone swap?
- Does **steril sone** participate in any rotation? Its functions are marked
  heavy (`*`), but D37 defines rotation as uren↔ren only. If steril doesn't
  rotate, is that intentional (small crew, self-paced)?
- Night shift: confirmed no rotation — so the ~2 people in uren at night
  stand a full night of heavy work. Accepted?

**Q19 🔴 The "heavy at most once per week" rule (D37) looks mathematically
infeasible as stated — which relaxation is intended?** Rough arithmetic per
weekday, counting distinct people who touch heavy work (intensity > 0), with
the zone swap making each half-shift a different person:

| Heavy work | Distinct people per weekday |
|---|---|
| Uren sone (heavy all day, 3–6 on duty × 4 rotation halves + night) | ~20–22 |
| Kontrollsone (heavy 12:00–21:00) | ~5 |
| Gangen (heavy 12:00–21:00) | ~3 |
| Steril sone (heavy all day) | ~5 |
| **Total** | **~30–35 per day → ~150–175 per week** |

With 69 employees, a hard cap of one heavy occurrence per week allows at most
69 — the demand is ~2–2.5× that, so every employee would need **2–3 heavy
stints per week** no matter how cleverly we plan. Options (pick or combine):

1. **Narrow the rule's scope**: "once per week" applies only to the
   *especially* heavy functions (e.g. Gangen + Kontrollsone — ~8 slots/day
   ≈ 40/week, comfortably feasible), while general uren/steril work is
   governed by the zone swap + soft balancing only.
2. **Half-shifts don't count**: the zone swap already caps uren work at half
   a shift; only a *full* unrotated heavy shift counts as an "occurrence".
   (Then the rule mostly bites nights and steril.)
3. **Make it a soft target**: the planner minimizes heavy occurrences per
   person per week (aiming at 1) with a higher hard cap (2–3).

*Interim rule until answered:* option 3 with a hard cap of 3 and the 28-day
intensity-hours balancing (D9) as tiebreaker.

**Q25 🟢 Mellomvakt membership.** Confirm `ME` and `UME` are the only current
mellomvakt codes (D35), and that new codes get their category assigned
explicitly in the vaktkode table (rather than by a formula) — proposed, since
edge cases like `A` (14–22) defy any clean rule.

## C. Competencies, preferences & staffing data

**Q20 🟡 The Sterrad / Poliklinikker/løspakk split (D43), remaining halves:**
(a) the hourly demand still exists only combined — how does it split?
(b) will the competency file be re-issued with two separate columns (and
ideally values in the currently empty columns while at it)? Until then the
combined column credits employees with both competencies.

**Q21 🟡 Who works fast at the utposter?** D39 needs the actual list:
which employees should be marked `utpost_fast` (excluded from SF planning)?
Alternatively: can it be derived from the roster (everyone with only U-codes)?

**Q22 🟡 Preference semantics (D32), two defaults to confirm:**
(a) an employee with **no** preference list = *no constraint* (assignable to
any competent, non-restricted function) — correct?
(b) preferences are maintained by managers in the admin view and visible
only there — correct that regular planning views shouldn't even hint at why
someone is never placed somewhere?

**Q24 🟢 Gang/vognvaskere competency** (empty column, not covered by the Q3
answer which addressed uren + DK): still assumed covered by "Produksjon,
steril sone". Confirm — low stakes while steril is staffed as a zone.

## D. Product details

**Q23 🟡 Someone in charge on weekends?** DK/ansvarsvakt exists to guarantee
a responsible person on duty (D41) — weekdays it's staffed around the clock.
Should the weekend ad hoc crew also always include (at least) one
ansvarsvakt-qualified employee, and should the planner/warning system check
for it?

**Q26 🟢 Absence types.** Which list should managers get when registering
(syk, egenmelding, ferie, kurs, permisjon, annet …)? Display never shows
absences (D46); this is only for the manager view and any reports.

---

### Resolved since last version

Q2 (roster mechanics → D45), Q3 (empty columns → D41/D42), Q4 ("?" → D44),
Q5 (split → D43), Q6 (Friday 18:00 → D34), Q7 (mellomvakt 16:00 → D35),
Q8 (zone-swap rotation → D37, with follow-ups Q18/Q19), Q9 (partial counts →
D38), Q10 (utposter out of scope → D39), Q11 (H1/H2 helgevakt → D36),
Q12 (utpost intensity 0), Q13 (data-driven weekend view → D47),
Q14 (absences hidden on display → D46; type list lives on as Q26),
Q15 (DK/ansvarsvakt merge → D41), Q16 (pip works → D48),
Q17 (self-contained folder → D49).

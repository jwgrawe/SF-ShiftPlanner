# Measuring heavy work, and keeping the plan fair

Assessment, round 13 (2026-11-12). Covers two questions from the owner: is
the 0-baseline way of measuring heavy work right, and how fair and optimal is
the planner over the long run?

## 1. Is a baseline of 0 right?

**Short answer: yes, keep 0 in the calculation; call the number something
that can't be mistaken for working hours.**

### What the measure is

It measures **extra load beyond ordinary work**, not work done. An hour at
Arbeidsbord adds nothing; an hour on Kontrollsone after 12 adds 1; an hour in
Produksjon uren adds 0.5. Multiplying by 0 isn't an anomaly. It says "this
hour brought no extra load", which is the claim being made.

Occupational exposure measures work the same way. Noise dose (OSHA) adds up
*time ÷ allowed time* per noise level, so quiet periods add nothing. Ergonomic
job-rotation models weight each task's exposure by its duration and sum. The
ergonomics literature's warning about such sums is a different one: an average
flattens *peaks*. That is why the app has a separate peak rule, the weekly cap
on full-intensity days, alongside the sum. The literature recommends exactly
this pair (time-weighted sum + peak limit).

### Would a baseline of 1 be better?

A factor scale (normal work = 1.0, moderate = 1.5, heavy = 2.0) is the same
information. Factor *f* on the 1-scale = intensity *f − 1* on the 0-scale. The
difference shows up when the numbers are **added up per person**:

- 1-scale sum = hours worked + extra load.
- Hours worked are fixed by the turnus, not by the planner. Someone with more
  shifts gets a bigger number without any heavy work. The planner would then
  give heavy work to people with *fewer* hours, so part-timers would get more
  than their share.
- The 0-scale sum isolates the part the planner actually controls: who gets
  the heavy places.

So the arithmetic stays at 0. Two presentation changes are recommended:

- **Name:** «belastningstimer» (or «tung belastning, vektede timer»), never
  just «timer». 1 belastningstime = one hour of full-intensity work.
- **Optional display:** show the intensities as factors (×1 vanlig,
  ×1.5 moderat, ×2 tungt) if that reads more naturally. That's purely a
  display choice.

### The real weakness: absolute sums and part-time

Today the planner balances the **absolute** number of belastningstimer over
the last 28 days. Someone working half as many shifts collects half as much,
so they look "less loaded" and are chosen first for heavy work every time
they're on duty. Per hour worked, they end up carrying more than full-timers.
In the demo (4 weeks, 39 heavy-qualified people) the effect is small:
heavy share 0.16 of own hours for the quarter working least, vs 0.14 for the
quarter working most. With real part-time contracts it will be larger.

**Recommendation:** balance the **share**: belastningstimer ÷ hours worked in
the window. Scheduling practice handles part-time the same way, with load
targets in proportion to FTE (stillingsprosent). The weekly cap stays in
absolute days, since that protects the body regardless of contract. **Built in
round 14 (D118)**, with the owner's agreement.

**Risks of the change, and how they're handled:**

- *Few hours in the window* (newcomer, back from leave, mostly ad hoc weekends):
  a share computed from little data is noisy, and 0 ÷ few hours would look
  «fresh». The share is pulled towards the group average as if the person had
  worked two shifts at it, so they count as average, not as fresh.
- *Full-timers now carry more heavy hours in absolute terms*, in proportion to
  their hours. That's the intent; the weekly cap (whole days) still protects
  everyone's body.
- *What isn't planned isn't counted* (e.g. weekends left ad hoc): those hours
  are missing from both the heavy hours and the hours worked, so the share
  isn't skewed by it. Shift changes on the floor can now be recorded
  (Endringer i vaktlisten, D119), and placement swaps edited in the day plan,
  also afterwards.
- *Nothing to migrate*: the same stored plans, just a different ordering.

## 2. How optimal and how fair is the planner?

### How optimal

It is **greedy**: block by block, day by day, it takes the best candidate by a
fixed order of preference and never goes back. That makes it predictable,
explainable and fast. It isn't a global optimum. A full optimiser could
sometimes find a week with slightly fewer target breaks or a flatter spread.
On the demo data the gap left is small: no cap breaks, and the spread of heavy
hours fell from sd 32.8 to 21.0 when the balancing came in. An optimiser can
be added later behind the same rules if the statistics show a need.

### Risks of bias or recurring patterns

| Risk | Status |
|---|---|
| **Ties broken by employee number**: when people are equal (e.g. at go-live, or among people who never do heavy work), the same low numbers would always win the light places or Sterrad/DK. | **Fixed** (D116): ties are now broken by a value that changes every day but is reproducible. |
| **Part-time**: absolute sums push heavy work onto people with fewer shifts. | Recommendation above (Q51). |
| **Scarce competencies**: if few are qualified for Kontrollsone, they share all of it however fair the order is. The planner can only balance among those qualified. | Can't be fixed by the planner; the statistics page should show heavy load per person so it's visible, and training more people is the fix. |
| **Shift pattern**: evening shifts lie almost entirely in the heavy window (12–22). People who mostly work evenings collect more, and the window evens it out only within the evening crew. | Same: visible in statistics; the cap protects the individual. |
| **Memory of 28 days**: a heavy month is forgotten after the window. Long-run imbalance (over a year) isn't corrected. | Acceptable; statistics over months will show it. A longer second window is possible if it shows. |
| **Plan vs. reality**: the planner counts what was planned. Swaps on the floor that aren't edited in are invisible. | Process: edit the plan when people swap. The statistics page can count manual edits. |
| **Order of days**: each day is planned seeing earlier days; replanning one day in the middle of an already planned week doesn't revisit the days after it. | Minor; «Lag forslag på nytt» for the rest of the week evens it. |
| **The soft target gives way to structure** (P3): rotation and fixed places can push someone over the target. | By choice (Q48); now visible as a notice (P3N), and it can be switched round under Avvik og tiltak. |

### What to watch

The statistics page (planned) should show per person, for admins only:
belastningstimer per hour worked, heavy days per week, cap and target breaks.
Those are the figures that would reveal any of the patterns above in real
data.

## Sources

- OSHA 29 CFR 1910.95 Appendix A – noise dose as a sum of time fractions:
  <https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.95AppA>
- Frazer et al. (2003), job rotation and low-back risk – time-weighted sums
  and their limits:
  <https://www.torontomu.ca/content/dam/hfe/documents/frazer2003-job-rotation-low-back-risk.pdf>
- Cumulative Lifting Index for rotation – between time-weighted and peak
  approaches:
  <https://metatoc.com/papers/51691-the-cumulative-lifting-index-culi-for-the-revised-niosh-lifting-equation-quantifying-risk-for-workers-with-job-rotation>
- Fairness in shift scheduling (balance over a longer window; part-time):
  <https://docs.timefold.ai/employee-shift-scheduling/latest/employee-resource-constraints/fairness>
- FTE-based load targets for part-time staff:
  <https://intercom.help/mesh_ai/en/articles/12167810-what-are-workload-modifiers>

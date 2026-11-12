# How the planner makes a suggestion

Plain-language reference for the planner as of round 11 (`app/planner.py`,
`app/exposure.py`; D107, D110). All numbers named here are settings under
Administrasjon → Planregler.

## 1. Measuring heavy work

Each function can have **intensity windows**: a time range and a weight.

| Function | Window | Intensity |
|---|---|---|
| Kontrollsone | 12:00–22:00 | 1.0 (tungt) |
| Produksjon uren, Produksjon steril, Gang/vognvask | 07:00–22:00 | 0.5 (moderat) |
| Gangen | 12:00–22:00 | 0.5 |
| everything else, and all night hours | – | 0 |

**Weighted heavy hours** for a stretch of work = hours inside a window × its
intensity, added up. Examples:

- Produksjon uren 07–11: 4 h × 0.5 = **2.0**
- Kontrollsone 11–15: only 12–15 counts, 3 h × 1.0 = **3.0**
- Kontrollsone on an evening shift 14–22: 8 h × 1.0 = **8.0**
- Arbeidsbord all day: **0**

From this the app keeps two counts per person:

- **The ledger («utjevningsvindu»)**: the sum of weighted heavy hours over the
  last *N* days of plans (N = 28 by default), plus what the person has already
  been given earlier the same day.
- **Heavy days this week**: the number of days Monday–Sunday on which the
  person works inside a window of intensity ≥ 1.0 (today: Kontrollsone after
  12:00). Part of a shift counts as a whole day (D38). The day being planned is
  left out, and the other days of the week count, including days already
  planned ahead.

## 2. Building one day

1. **Who is on duty**: the roster for the day, minus absences, held days and
   U-codes.
2. **Blocks**: each shift is cut at its category's rotation time (tidligvakt
   11:00, mellomvakt 16:00, senvakt 18:00, none at night or weekends). A D shift
   becomes 07–11 and 11–15.
3. **Block by block, in time order**, the places are filled:
   1. People who can't go across in the swap stay where they were.
   2. **Demand functions in fill order** (DK/ansvarsvakt, Kontrollsone,
      Sterrad, …). For each function: first whoever is already on it and
      simply continues (if still needed), then the best of the rest, up to
      the number needed in the busiest hour of the block.
   3. **Zone totals**: uren and steril are topped up to their head-count
      with Produksjon uren/steril, the same way.
   4. **Everyone left** goes to Arbeidsbord (weekdays).
   5. Anyone still free who can't take Arbeidsbord helps in a zone they're
      qualified for.
4. Days are planned **in date order**, so each day sees the plans before it.

## 3. Choosing «the best of the rest»

Candidates are sorted by a list of questions, asked in order. The second
question only matters between people tied on the first, and so on:

| # | Question | Better |
|---|---|---|
| 1 | Does their shift code lead to this function (DK/DKK → DK/ansvarsvakt)? | yes |
| 2 | Would this put them **over the weekly cap** (3 heavy days)? | no |
| 3 | Their place in the **swap and continuity** (see below) | lower |
| 4 | Would this put them **over the weekly target** (1 heavy day)? | no |
| 5 | **Ledger**: heavy work → fewest weighted hours first; light work → most first | as said |
| 6 | Employee number (only so the result is always the same) | lower |

Place in the swap, question 3 (with uren ↔ Arbeidsbord):

| Value | Who |
|---|---|
| 0 | drawn here by the swap (was at Arbeidsbord, now uren – or the other way) |
| 1 | just came on duty |
| 2 | free after the rotation point |
| 3 | wanted by the swap somewhere else (an Arbeidsbord person, when uren needs them) |
| 4 | should go across, but would stay on this side |
| 5 | is keeping a function outside the swap (steril, Kontrollsone) – taken last |

**Looking ahead:** a function that continues past the rotation point is judged
over the rest of the shift. Choosing someone for Kontrollsone at 07:00 counts
the heavy 12–15 that follows, so the morning pick is already someone under
the target.

**Why light work goes to the most exposed:** it keeps the least exposed free
for the heavy places that come later in the day.

## 4. What this means in practice

- The cap is never broken while someone else can do the work. When it must
  be broken, the day plan says so.
- The target is soft: rotation, and people keeping their function, come
  first. Over four demo weeks: 15 → 0 person-weeks over the cap, 15 → 8
  over the target, top heavy hours per person 120 → 64.
- Over time the ledger evens out who gets the heavy places. A person with a
  heavy week gets lighter places the following weeks, until the window has
  moved past it.

## 5. Limits worth knowing

- **Greedy, not a global optimum**: it decides block by block and day by day,
  never going back to change an earlier day for a better week overall. That
  makes it predictable and explainable. A full optimiser is possible later if
  the results call for it.
- **It counts the app's plans.** The ledger is empty at go-live and fills up
  over the first weeks. A swap on the floor that isn't edited into the plan
  isn't counted.
- **Ties in the first days** are broken by employee number, until the ledger
  separates people (a day or two).
- Plans must be kept longer than the window. The app enforces this.

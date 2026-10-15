# Open questions

Current list as of 2026-10-15 (round 5: the first anonymised Plan and Ajourhold samples). Q-numbers are stable across
rounds — resolved ones are recorded in [decisions.md](decisions.md) and
listed at the bottom. Where an *interim rule* is stated, work proceeds on
that assumption; the question is whether it's right.

Priority: 🔴 gates the planning engine · 🟡 needed soon · 🟢 can wait.

## Open

**Q1 ✔ The roster export** — layout now known from the anonymised samples
(spec in [source-data-findings.md](source-data-findings.md) §5, and
D79–D86). Identity: full name (D82). What remains are the semantic questions
below.

**Q32 🔴 What does an Ajourhold week contain?** In the sample week, 10 of 20
people differ from Plan: shifts vanish (no absence code is shown), move
between people (swaps) or appear. To confirm: (a) is a blank cell always
"not working", whatever the reason? (b) does the ukeplan list every person
in the unit even with no shifts that week? (c) what can the always-empty
`Gruppe` column contain — can the export be filtered by group?

**Q33 🔴 Which date carries a night shift?** N/NA appear Tue–Fri, never
Monday, in both files and in their count rows, while the opening hours put
nights Mon–Thu evenings. Reading: a night is dated by the morning it *ends*,
so the import moves it back one day (the app files nights under the day they
start).

**Q34 🟡 What is `M`?** Seen only in Ajourhold, alongside a shift: `N, M`,
`M, A1`. A shift, or a note (e.g. a meeting)? Should it affect planning?

**Q35 🟡 What is `DX`?** Seen once in Ajourhold; not in the Plan legend. Times?

**Q36 🟡 What is `F3`, and what do `/` and `,` mean?** `DK/F3`, `U8/F3` in Plan
only on 01.04 (Wednesday before Maundy Thursday), 24.12 and 31.12 — perhaps
"off from 12:00 on holiday eves". Ajourhold separates codes with `, `.

**Q37 🟡 New codes `D3` (09:00–13:30), `A3` (17:30–22:00), `D2*` (08:00–15:30).**
Categories? What does the `*` mean? (All other legend times match
`shift_codes.csv` exactly.)

**Q38 🟢 Which codes do the count rows count?** Plan's D/A/N and Ajourhold's
Dag/Kveld/Natt count the whole unit per day; knowing which codes go where
lets the import use them as checksums.

**Q39 🟡 Export routine.** Which week will a normal ukeplan export cover (the
coming one)? Does each Plan export always span a whole plan year (this one:
12.01.2026–10.01.2027), or only the weeks it was made for?

**Q40 🟡 Competency file in export name form.** It must carry each employee's
name exactly as the exports write it (reversed), later PersonID too (D82).

**Q41 🟡 Titles outside the turnus, and unknown titles.** Ajourhold has no title
column, so an Ajourhold shift takes its title from the Plan row active on that
date — ambiguous if a person has two rows with different titles that week.
And until an admin classifies a newly seen title: plan it normally (and
alert), or hold it out (and alert)?

**Q18 🔴 Scope of the zone swap.** *(Noted for follow-up by the owner.)*
Does the entire uren crew swap at the rotation point, or a subset? Is the
ren-side swap pool only Arbeidsbord, or also Kontrollsone/Sterrad/
Poliklinikker? Do Kontrollsone and Gangen rotate within their zones? Does
steril participate at all? *(Night is settled: night hours are not heavy
(D50), so no night rotation and no night exposure accrual.)*

**Q19 🟡 Exposure-rule follow-up.** *(Booked by the owner.)* The two-tier
scheme (D50/D51) is adopted and feasible — this item is for the department
to confirm the concrete numbers at the follow-up: Kontrollsone as the only
full-intensity function, target 1/week, hard cap 3/week, 0.5 for the other
heavy functions.

**Q20 🟡 Sterrad / Poliklinikker demand split.** The competency side is
settled (re-issued file coming, D54) — but the **hourly demand** still
exists only combined (2 people mornings, 1 midday, 2 evenings). How does it
split between the two functions? *Interim: kept as one combined
function-group row.*

**Q27 🟡 Intensity window boundaries.** Night (22–07) is not heavy (D50) —
so the seed gives the all-day heavy functions (Produksjon uren, both steril
functions) intensity 0.5 in the window **07:00–22:00**. Confirm those edges
(and that weekend daytime work accrues the same). Gangen/Kontrollsone remain
12:00–22:00. Longer term the department can tune intensity per function and
hour freely — the model already supports it (D52).

## Resolved (all rounds)

Q2–Q17: see the round-2 log in [decisions.md](decisions.md).
Round 3: Q21 (utpost staff derived from roster U-codes → D55),
Q22 (preference semantics → D56), Q23 (DK/ansvarsvakt on all shifts,
weekends included → D57), Q24 (steril ad hoc, vognvask via produksjon_steril
→ D58), Q25 (explicit categories + advisory heuristic → D59),
Q26 (absence visibility and import → D46/D60, type list lives on as Q29),
Q28 (tilrettelegging belongs in fritak, preferences stay steering → D56,
confirmed by the owner).
Round 5: Q29 (absence types — not needed at all → D76), Q1 (export layout
and identity → D79–D86).
The Q19 infeasibility itself is resolved by the two-tier scheme (D50/D51);
what remains is the booked confirmation above.

# Open questions

Current list as of 2026-10-13 (round 5: the real roster sources). Q-numbers are stable across
rounds — resolved ones are recorded in [decisions.md](decisions.md) and
listed at the bottom. Where an *interim rule* is stated, work proceeds on
that assumption; the question is whether it's right.

Priority: 🔴 gates the planning engine · 🟡 needed soon · 🟢 can wait.

## Open

**Q1 🔴 The roster export.** *(Partly answered in R5.)* The roster comes from
two sources, Plan and Ajourhold (D73), both CSV. Join key: employee number
(D77) — present in Ajourhold, and coming to Plan with its next export.
**Still pending:** the field layout, via the anonymised copies
(`scripts/anonymise_export.py`, D78), and the check of Plan's own shift-code
explanations against `shift_codes.csv`.

**Q32 🔴 What does an Ajourhold week contain?** Every person and day of the
week, or only what changed against Plan? The owner's reading: "the freshest
information" — some long-known absences are already in Plan too. *Interim
(D73): Ajourhold is authoritative for the whole week it covers.* The
anonymised sample should settle it by comparing the two files.

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
Round 5: Q29 (absence types — not needed at all → D76).
The Q19 infeasibility itself is resolved by the two-tier scheme (D50/D51);
what remains is the booked confirmation above.

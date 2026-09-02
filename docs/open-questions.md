# Open questions

Current list as of 2026-09-02 (after round 3). Q-numbers are stable across
rounds — resolved ones are recorded in [decisions.md](decisions.md) and
listed at the bottom. Where an *interim rule* is stated, work proceeds on
that assumption; the question is whether it's right.

Priority: 🔴 gates the planning engine · 🟡 needed soon · 🟢 can wait.

## Open

**Q1 🔴 The roster export.** *(Sample pending.)* Needed with it: the field
layout, and the **identity join key** — do the roster export and the
competency data share an employee number the app can join on? *(New since
D55: the roster is now also the source for utpost days via U-codes, so the
sample matters even more.)*

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

**Q28 🟢 Tilrettelegging placement.** Recommendation adopted pending your
confirmation (D56): accommodations go in **restrictions (fritak)** — "should
not do X", with validity periods, no reason stored — while **preferences**
express organizational steering ("works only here"). Both admin-only. OK?

**Q29 🟢 Absence type list.** Restated: when a manager registers an absence,
which categories should the dropdown offer? *Interim default (D60): Syk ·
Ferie · Kurs/opplæring · Permisjon · Annet.* Types are visible only to
managers/admins (D46); the display never shows absences. Confirm or edit
the list — also relevant for the absence *import file*, whose format we can
define ourselves.

## Resolved (all rounds)

Q2–Q17: see the round-2 log in [decisions.md](decisions.md).
Round 3: Q21 (utpost staff derived from roster U-codes → D55),
Q22 (preference semantics → D56), Q23 (DK/ansvarsvakt on all shifts,
weekends included → D57), Q24 (steril ad hoc, vognvask via produksjon_steril
→ D58), Q25 (explicit categories + advisory heuristic → D59),
Q26 (absence visibility and import → D46/D60, type list lives on as Q29).
The Q19 infeasibility itself is resolved by the two-tier scheme (D50/D51);
what remains is the booked confirmation above.

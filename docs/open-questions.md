# Open questions

Current list as of 2026-11-12 (round 11: heavy-work balancing, contingency rules planned). Q-numbers are stable across
rounds — resolved ones are recorded in [decisions.md](decisions.md) and
listed at the bottom. Where an *interim rule* is stated, work proceeds on
that assumption; the question is whether it's right.

Priority: 🔴 gates the planning engine · 🟡 needed soon · 🟢 can wait.

## Open

**Q1 ✔ The roster export** — layout now known from the anonymised samples
(spec in [source-data-findings.md](source-data-findings.md) §5, and
D79–D86). Identity: full name (D82). What remains are the semantic questions
below.

**Q40 🟡 Competency data for the real staff.** The owner is preparing the existing,
already-filled competency list (names abbreviated) — it no longer needs hand-editing to
match the exports: the import's link step suggests the right person per name (D98).
After that, the managers fill the gaps via the generated form or directly in the app.

**Q48 🟡 Contingency rules.** Review the inventory in
[contingency-rules.md](contingency-rules.md): is any of today's behaviour wrong for you,
and which situations from the floor are missing?

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
Round 6: Q32 (ukeplan contents → D93), Q33 (nights dated by their end → D92),
Q34 (`M` = overtime), Q36 (`F3` = ends 12:00), Q37 (categories don't matter beyond
rotation; `*` = paid lunch) → D92; Q35 (`DX`) → D95/Q43; Q38 (count rows not used);
Q39 (export routines open-ended — the app handles any cadence → D91/D93);
Q41 (titles: hold out until classified, once → D87).
Round 7: Q42 (surname first; the first word is the full surname, hyphens included —
as implemented), Q43 (`DX`: manual times per occurrence → D95), Q44 (temps get a
manager-defined standard set; new staff are assessed → D97).
Round 11: Q46 (Kontrollsone rotation, if app-managed, is with another function – most
likely Arbeidsbord: the ready «Kontrollsone ↔ Arbeidsbord» rule, switched on under
Planregler when decided; no split needed), Q47 (other departments export from the same
HR system; their rules, functions and codes are their own, the rest is shared →
[generic.md](generic.md)).
Round 10: Q18 (the zone swap: all of uren sone ↔ Arbeidsbord; Kontrollsone takes turns
by itself; steril doesn't rotate; who can't work at Arbeidsbord stays → D107).
Round 9: Q19 (exposure numbers confirmed, tunable → D106), Q22 (reconfirmed),
the turnus PersonID standard (D102), shift codes `DMT`/`DMK` ignored, `D4`, `M`, `D, A`
(D103), Q40 partly (competency lists can be CSV and carry PersonID → D105).

# Open questions

Current list as of 2026-10-19 (round 6: sample semantics answered, import built). Q-numbers are stable across
rounds — resolved ones are recorded in [decisions.md](decisions.md) and
listed at the bottom. Where an *interim rule* is stated, work proceeds on
that assumption; the question is whether it's right.

Priority: 🔴 gates the planning engine · 🟡 needed soon · 🟢 can wait.

## Open

**Q1 ✔ The roster export** — layout now known from the anonymised samples
(spec in [source-data-findings.md](source-data-findings.md) §5, and
D79–D86). Identity: full name (D82). What remains are the semantic questions
below.

**Q40 🟡 Competency file in export name form.** It must carry each employee's
name exactly as the exports write it (surname first), later PersonID too (D82).
The import reads it as soon as it lands in `data/import/` (.xlsx, same layout as
today's workbook); until then nobody can be placed automatically.

**Q42 🟡 Name order for board names.** The exports write names surname first.
The board shows «Fornavn E.», taking the *first* word as the surname and the
second as the first name (`Hansen Kari Marie` → «Kari H.»). Is that always the
order — and how are double surnames written (`Berg Hansen Kari`)? Wrong
guesses only affect the short display name, never matching.

**Q43 🟡 Temps' unknown codes (`DX`).** See the assessment in the R6 notes:
until decided, such days are held out with an alert (D95). Options: per-occurrence
time entry by a manager, and/or defining a code once when it turns out stable.

**Q44 🟢 Temps' competencies.** Temps in the ukeplan but not in the turnus are
planned like regular staff (D93) — but can only be placed if they are in the
competency file. Should they be added there, or handled by hand?

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
The Q19 infeasibility itself is resolved by the two-tier scheme (D50/D51);
what remains is the booked confirmation above.

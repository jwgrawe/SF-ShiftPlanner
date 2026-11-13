# Open questions

Current list as of 2026-11-13 (round 15: login through Windows, root mode). Q-numbers are stable across
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

**Q49 🔴 Real fritak and preferences.** In real mode there is no way yet to enter
fritak (incl. tilrettelegging) or preferences for real staff: the rows in
`data/seed/employee_restrictions.csv` / `employee_preferences.csv` are fictional demo
data, ignored in real mode — and real ones must never go there (public repository;
tilrettelegging can be health information). Proposal: an admin-only editor under
Administrasjon (per person: fritak from heavy work or from given functions, from/to
dates, note), stored only in the database and logged.

**Q54 🔴 Who keeps the app (and the board) running?** The app runs as the Windows user who
started it; when that person logs off, the app and the board stop. With everyone logging in
personally, the PC by the big screen probably needs a session that stays logged in for the
board (e.g. a dedicated account from IT), with managers using the app from their own login
on the same PC (Windows sign-on tells them apart). Ask IT what is possible there.

**Q55 🟡 Check Windows sign-on on the PC.** Run `python run.py --test-innlogging` and send the
output; then open `http://localhost:8000` and see that you're logged in without typing anything
(details in [login.md](login.md)).

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
Round 15: Q53 (login: use the Windows login, owner = the department owner, root mode for
managing administrators → D121).
Round 14: Q51 (balance per hour worked → D118), Q52 (board window built → D120; one
account per manager, via the ID card → Q53).
Round 13: Q48 (contingency rules reviewed; choices built → D114/D115), Q50 (statistics:
admin-only, serious findings and short-staffing first, anonymous totals three years → D117).
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

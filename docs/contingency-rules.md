# «Avvik og tiltak»: contingency rules as settings

**Built in round 13** (D114) under Planregler → Avvik og tiltak, with the owner's
choices from the Q48 review: P5 → «Ad hoc» (D115), S2 → the ukeplan is the truth,
S5 → flagged whenever found (red within the set days, yellow later), P3 → a
notice when the weekly target gives way (P3N). P7 (level per function) is left
for later. The inventory below is kept as the background.

Plan, round 11 (2026-11-12). The aim: every
«when X happens, the app does Y» that is a judgement call becomes a visible
setting under Administrasjon → Planregler. The rules that guard safety or data
integrity stay fixed, but are listed on the page too, so nothing is hidden.

## What the app decides today

### Planning (the suggestion)

| # | Situation | What the app does today | Possible choices | Expose? |
|---|---|---|---|---|
| P1 | Too few at Arbeidsbord to swap with everyone in uren | Covers uren first; the rest stay in uren; light notice | (a) cover first, stay (today) · (b) rotate anyway, leave uren short + warning | **Yes** |
| P2 | Weekly cap on full-intensity days can't be kept (nobody else qualified) | Goes over the cap as a last resort + warning (D53) | (a) go over + warn (today) · (b) leave the function short + alert | **Yes** |
| P3 | Weekly target vs. the swap and «steril doesn't rotate» | Structure first, target second (D110) | (a) structure first (today) · (b) target first: may move people out of continuing functions | **Yes** |
| P4 | Someone can't work at the swap's other side (competency, fritak) | Stays where they were; light notice (D107) | notice level only: merknad / av | Notice level |
| P5 | Someone on duty can't take Arbeidsbord and nothing else is short | Helps out in a zone they're qualified for | (a) zone (today) · (b) leave unplaced + notice | Yes |
| P6 | Weekend or holiday | Only the lead function (DK/ansvarsvakt) is planned (D21) | (a) lead only (today) · (b) plan the whole day like a weekday | **Yes** |
| P7 | A demand function can't be covered | Left short + warning (alert if it is the lead function) | warning level per function | Levels |
| P8 | Roster changes after a day is planned (new ukeplan) | Warns «lag forslag på nytt» | (a) warn (today) · (b) remake unpublished drafts automatically, warn on published days | **Yes** |

### Source data (imports)

| # | Situation | What the app does today | Possible choices | Expose? |
|---|---|---|---|---|
| S1 | New job title in the turnus | Held out of planning until classified (D87) | (a) hold (today) · (b) plan as «vanlig» meanwhile + alert | Yes |
| S2 | Someone has shifts in the turnus but isn't in that week's ukeplan | Turnus used for them + warning | (a) use turnus (today) · (b) treat as not working that week + warning | Yes |
| S3 | Temp (only in the ukeplan) without own competencies | Gets the standard set (D97) | – (the set itself is already editable) | No |
| S4 | Turnus doesn't reach far enough ahead | Alert when days within **28** days are missing | the number of days | Number |
| S5 | Shifts that can't be planned (unknown code, conflicts) | Alert for those within **28** days | the number of days | Number |
| S6 | New turnus has a very different number of people | Warning above a **15 %** change | the percentage | Number |
| S7 | Competency file waiting for review | Warning | level | Level |
| S8 | How often the inbox is checked | Every 30 s on page loads | – | No |

### Notices (levels only)

Draft not published, on duty without placement, «Rullerer ikke», shift times
changed, two people with the same name: each could be set to **varsel**,
**merknad** or **av**, where switching it off can't hide a problem.

## Fixed on purpose (shown, not changeable)

| Rule | Why fixed |
|---|---|
| A file with the wrong structure, wrong unit or no PersonID is refused | Reading a wrong export is how people get mixed up |
| A shift that can't be tied to one person (identity) is held | The app never guesses who someone is |
| An unknown shift code is held until defined (D103) | Never guesses times; defining the code is the fix |
| Two rows / two shifts the same day are held (D80) | Ambiguous at the source |
| Someone absent but still in the plan → alert | Must never reach the board |
| Breaking a rule is never silent (D53) | Every exception is visible |

## Design (generic)

- One registry in code: each situation gets an id, area, a Norwegian text, its
  allowed choices (with the safe default first), whether its notice can be
  switched off, and optional numbers. The page is generated from it, so a new
  situation needs no new page.
- Stored like the other rules (D108): seeded defaults, edited values survive a
  pull, «Tilbake til standard», every change logged.
- Each notice in the app links to «Hvorfor?» → its rule, so the managers see
  why something happened and where to change it.
- Nothing names SF functions: rules refer to roles in the data (the lead
  function, swap sides, zone remainders), so another department gets the same
  page with its own functions.

## Suggested order

1. Registry + page section with P1, P2, P3, P6, P8, S1, S2 and the numbers
   S4–S6 (the decisions that change outcomes).
2. Notice levels and «Hvorfor?» links.
3. Anything the managers find missing after using it.

## For the owner

- Are any of the «today» behaviours above wrong for you already?
- Any situations from the floor that are missing? The list is what the app
  knows about; the floor knows more.

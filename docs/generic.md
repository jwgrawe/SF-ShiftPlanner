# Can the app serve other departments?

Assessment as of round 10 (2026-11-12). Short answer: **mostly yes, and
cheaply, if each department runs its own copy** (its own folder, database
and import folder). A few things are still written for Sterilforsyningen and
need to move into data first.

## Already department-neutral

| Area | Why it carries over |
|---|---|
| Zones, functions, competencies, demand per hour, intensity | All data (`data/seed/*.csv`), none in code |
| Fill order, lead codes, zone remainders | Data since D109: `functions.csv` columns `fill_priority`, `lead_codes`, `staffing_mode` |
| Rotation: when, and who swaps with whom | Data, edited in the app (Planregler, D107/D108) |
| Shift codes | The app's own list, edited in the app (Vaktkoder, D103) |
| Job-title rules | Classified once in the app (Stillinger, D87) |
| HR imports (turnus, ukeplan) | Read by structure, not position (D85). Any unit exporting from the same HR system works; the unit name is a setting (`expected_unit`) |
| Competency matrix, fill-in form, CSV/Excel import | Columns come from the competency list in the data |
| Log, retention, demo/real split | General |

## Still written for SF

| What | Where | Fix | Size |
|---|---|---|---|
| The name «SF-Planlegger», «Fordeling, SF» on the board, «Sterilforsyningen» in the form guide | templates, `competency.py` | A department name setting | Small |
| Zone colours keyed by zone id (uren/ren/steril/utpost) | `app.css`, `competency.py` | A colour column in `zones.csv` | Small |
| Weekends planned for the lead function only (D21) | `planner.py` | A setting: plan the remainder on weekends or not | Small |
| «Utpost» as the name for days kept out of planning (U-codes) | shift codes, texts | Rename to «utenfor avdelingen» in texts; the mechanism is general | Small |
| Functions, zones, demand and intensity can only be changed in the CSV files | `data/seed/` | In-app editors like Vaktkoder/Planregler | Medium |
| One set of seed files | `data/seed/` | A template set for a new department + a short setup guide | Small |
| Shift categories (tidlig/mellom/sen/natt/helg) | `service.py`, validator | Fine for hospital shift work; make the list data only if a department needs other categories | – |

## Recommended shape

**One copy per department.** Each department gets its own app folder (code
from the same repository, its own `data/seed/`, database and import folder).
That keeps personal data apart, needs no login per department, and fits the
single-folder setup (D49). Updates are a `git pull` in each folder; each
department's own settings live in its database and survive the pull, as the
Vaktkoder and Planregler pages already do.

A single shared installation serving several departments is possible later,
but it needs real logins and per-department access first (today: PIN-level
access, D25). Not worth it until there is more than one department using it.

## Suggested order

1. Department name setting + zone colours in data + weekend setting (small, low risk).
2. In-app editors for functions, demand per hour and intensity (medium; the
   pattern exists).
3. A template seed and a one-page «ny avdeling» guide, tried on a second unit.

## Open question for the owner

Which departments are realistic candidates, and do they export from the same
HR system (Ressursstyring)? If so, the import side carries over unchanged.

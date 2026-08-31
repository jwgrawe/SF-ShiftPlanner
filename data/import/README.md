# The import folder (spec — not yet implemented)

At runtime the app reads its master data from a folder like this one, per
decision D29. Managers and admins maintain a small number of Excel files and
press "Importer på nytt" in the admin view (or run a CLI command). See
[docs/assessment.md](../../docs/assessment.md) §4 for the full design.

Planned contents:

| File | Owner | Sheets |
|---|---|---|
| `grunndata.xlsx` | admin | Funksjoner · Bemanningsbehov · Intensitet · Vaktkoder · Åpningstider · Ukedagsregler |
| `personal.xlsx` | managers | Ansatte · Kompetanse · Fritak · (Fravær, as fallback — normally entered in-app) |
| `turnus_*.xlsx` | roster system export | dropped in as-is; parsed by a dedicated adapter once the real export format is known (Q1) |

Import rules: validate first, show a diff summary, refuse to delete master
data referenced by published plans, then upsert. Idempotent — re-importing an
unchanged file changes nothing.

The two workbooks will be generated from `data/seed/` when milestone M1
starts, so the department edits familiar, pre-filled files from day one.

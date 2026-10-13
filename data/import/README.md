# The import folder (spec — not yet implemented)

> **Real data lives here — and never reaches git.** Everything in this folder
> except this README is git-ignored, because the repository is public (D78).
> Put the Plan (turnus) and Ajourhold (ukeplan) CSV exports here. To share
> their *structure* with a developer, run `python scripts/anonymise_export.py`
> — see [data/private/README.md](../private/README.md).

At runtime the app reads its master data from a folder like this one, per
decision D29. Managers and admins maintain a small number of Excel files and
press "Importer på nytt" in the admin view (or run a CLI command). See
[docs/assessment.md](../../docs/assessment.md) §4 for the full design.

Planned contents:

| File | Owner | Sheets |
|---|---|---|
| `grunndata.xlsx` | admin | Funksjoner · Funksjonskompetanser · Bemanningsbehov · Intensitet · Vaktkoder · Rulleringsregler · Planleggingsinnstillinger · Åpningstider · Ukedagsregler |
| `personal.xlsx` | managers | Ansatte · Kompetanse · Preferanser · Fritak · Fravær (importable and definable in-app, D60) |
| Plan export (turnus, CSV) | roster system, yearly | dropped in as-is; parsed by a dedicated adapter once the layout is known from the anonymised copy (Q1, D73) |
| Ajourhold export (ukeplan, CSV) | a manager, weekly | dropped in as-is; wins over Plan for the week it covers (D73). On refresh, published plans are re-validated and conflicts flagged |

Note on sensitivity: the Preferanser sheet (and Fritak) carries information
that is only ever surfaced in the admin view (D32/D11) — the import folder
should live with the app in its access-controlled location.

Import rules: validate first, show a diff summary, refuse to delete master
data referenced by published plans, then upsert. Idempotent — re-importing an
unchanged file changes nothing. **Structure-drift detection** (D54): before
importing, the file's sheets and columns are compared against what the app
expects, and any mismatch (merged, missing, renamed or new columns) is
reported to the admin/manager as a warning instead of a silent misread.

The two workbooks will be generated from `data/seed/` when milestone M1
starts, so the department edits familiar, pre-filled files from day one.

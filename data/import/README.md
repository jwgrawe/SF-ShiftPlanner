# data/import — the inbox for real data

> **Real data lives here — and never reaches git.** Everything in this folder
> except this README is git-ignored, because the repository is public (D78).

Drop the exports from the HR system here (or upload them under
«Datagrunnlag» in the app). While the app is open it looks for new files every
30 seconds (D91):

| File | From | How often |
|---|---|---|
| `Utskrift_fleksiplan_<ÅÅÅÅMMDDttmmss>.csv` | Plan («Utskrift fleksiplan», the turnus) | whenever a turnus is made or revised |
| `Ukeplan_<ÅÅÅÅMMDDttmmss>.csv` | Ajourhold (the week plan) | one file per week — re-exports are fine, the newest wins |
| `*.xlsx` | the competency matrix, names written exactly as in the turnus | when it changes |

What happens to a file:

- **read** → moved to `arkiv/`; its data goes into the database. Raw files are
  deleted once a newer file replaces them, and everything older than the
  retention period (92 days by default, D94).
- **refused** → moved to `avvist/` together with a `.txt` explaining exactly
  what was expected and what was found (D85/D90). It stays on the app's
  attention list until you remove it from `avvist/`. Fix the export and drop
  the new file here.
- **the same file again** → recognised and ignored.

The formats are specified in [docs/source-data-findings.md §5](../../docs/source-data-findings.md).
How the roster is built from them: D73, D82, D86–D95 in
[docs/decisions.md](../../docs/decisions.md). To share a file's *structure*
with a developer, anonymise it first: [data/private/README.md](../private/README.md).

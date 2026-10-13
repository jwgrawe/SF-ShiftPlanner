# data/private — ekte personopplysninger, kun lokalt

Alt i denne mappa unntatt denne filen er utelatt fra git (`.gitignore`).
Repoet er **offentlig**, så ekte eksportfiler skal aldri ligge noe annet sted
i prosjektet.

| Hva | Hvor |
|---|---|
| Eksport fra **Plan** (turnus) og **Ajourhold** (ukeplan), CSV | rett i denne mappa |
| Anonymiserte kopier + rapport + gjennomgangsliste | `anonymisert/` (lages av skriptet) |
| Nøkkelen ekte → oppdiktet navn/nummer | `anonymiser_nokkel.json` — **del aldri** |
| Ekstra ord som skal sladdes (ett per linje) | `ekstra_sladding.txt` (valgfri) |

## Anonymisere

```bat
python scripts\anonymise_export.py
```

Skriptet leser alle `*.csv` her, og skriver til `anonymisert/`:

- én kopi per fil med samme oppsett, tegnsett og skilletegn — men oppdiktede
  navn og ansattnummer, kommentarer på personrader byttet ut med `[tekst]`,
  telefon/e-post fjernet, og bare et utvalg på 20 ansatte (`--alle` for alle).
  Samme person får samme oppdiktede navn i alle filene, så turnus og ukeplan
  kan fortsatt kobles.
- `_rapport.txt` — bare struktur: tegnsett, kolonner, vaktkoder funnet.
- `_gjennomgang.txt` — **alle** tekstverdier som står igjen. Les den før du
  deler noe. Står det et ekte navn der, skriv det i `ekstra_sladding.txt` og
  kjør på nytt.

Finner skriptet verken navn eller ansattnummer i en fil, hopper det over
filen i stedet for å gjette. Oppgi da overskriften:
`python scripts\anonymise_export.py --navn-kolonne "Navn" --id-kolonne "Ansattnr"`.

De anonymiserte kopiene deles i chatten med Claude — **ikke** i repoet: selv
med oppdiktede navn kan en kollega kjenne igjen en person på vaktmønsteret.
Testdata i repoet lages syntetisk ut fra strukturen.

"""«Avvik og tiltak»: what the app does when something doesn't fit (D114).

One registry of every judgement call the app makes, each with its allowed
choices and a default (the owner's choices from the Q48 review). The page
under Administrasjon → Planregler is generated from it, and the code asks it
instead of hard-coding the behaviour. Rules that guard safety or data
integrity are not settings, but are listed (FIXED) so nothing is hidden.

Generic by design: rules talk about roles in the data (the swap, the
remainder function, the lead function), never about one department's
functions.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass, field

from app import applog

LEVELS = [("varsel", "Varsel (gult)"), ("merknad", "Merknad (diskret)"), ("av", "Av – vises ikke")]
LEVEL_TO_FINDING = {"varsel": "warn", "merknad": "info", "av": None}


@dataclass(frozen=True)
class Rule:
    id: str
    area: str                      # «planlegging» | «grunnlag» | «merknader»
    title: str
    help: str = ""
    kind: str = "choice"           # choice | level | number
    choices: tuple = ()
    default: str = ""
    unit: str = ""
    low: int = 0
    high: int = 0
    levels: tuple = field(default=("varsel", "merknad", "av"))


RULES: list[Rule] = [
    # -- planning ----------------------------------------------------------
    Rule("P1", "planlegging", "For få på den andre siden til at alle kan rullere",
         "F.eks. flere i uren sone enn på Arbeidsbord ved rulleringspunktet.",
         choices=(("dekk", "Dekk behovet først – de som ikke får byttet, blir stående (merknad «Rullerer ikke»)"),
                  ("roter", "Rullér alle likevel – funksjonen står underbemannet (varsel)")),
         default="dekk"),
    Rule("P2", "planlegging", "Ukegrensen for tunge dager kan ikke holdes",
         "Ingen andre kvalifiserte er ledige.",
         choices=(("over", "Gå over grensen for den som må – med varsel"),
                  ("kort", "La funksjonen stå underbemannet – med varsel")),
         default="over"),
    Rule("P3", "planlegging", "Ukemålet for tunge dager kommer i konflikt med rulleringen eller faste plasser",
         "«Faste plasser»: den som står på en funksjon utenfor rulleringen (steril, Kontrollsone) "
         "beholder den etter rulleringspunktet.",
         choices=(("struktur", "Rullering og faste plasser først, ukemålet etterpå"),
                  ("maal", "Ukemålet først – kan flytte folk ut av en fast plass midt i vakten")),
         default="struktur"),
    Rule("P3N", "planlegging", "Noen går over ukemålet for tunge dager",
         "Viser når rullering eller faste plasser gikk foran ukemålet.",
         kind="level", default="merknad"),
    Rule("P4", "planlegging", "Noen rullerer ikke (mangler kompetanse, fritak eller for få å bytte med)",
         kind="level", default="merknad"),
    Rule("P5", "planlegging", "Noen på vakt kan ikke stå på restfunksjonen, og ingenting annet mangler folk",
         "Restfunksjonen er den alle andre går til (i SF: Arbeidsbord).",
         choices=(("adhoc", "Sett på «Ad hoc» – fordeler seg selv eller avklarer med leder"),
                  ("sone", "Sett i en sone de er kvalifisert for"),
                  ("ingen", "La være uten plassering (merknad)")),
         default="adhoc"),
    Rule("P6", "planlegging", "Helg og helligdag",
         choices=(("behov", "Planlegg bare funksjoner med helgebehov (DK/ansvarsvakt); resten vises "
                            "som «På jobb i dag – fordeles ad hoc»"),
                  ("full", "Planlegg hele dagen som en hverdag")),
         default="behov"),
    Rule("P8", "planlegging", "Vaktlisten endres etter at en dag er planlagt",
         "F.eks. når en ny ukeplan kommer.",
         choices=(("varsle", "Varsle – «lag forslag på nytt»"),
                  ("utkast", "Lag utkast på nytt automatisk; varsle for publiserte dager")),
         default="varsle"),
    # -- source data -------------------------------------------------------
    Rule("S1", "grunnlag", "Ny stillingsbetegnelse i turnusen",
         choices=(("hold", "Hold vaktene utenfor planen til stillingen er klassifisert"),
                  ("planlegg", "Planlegg som «vanlig» i mellomtiden – med varsel")),
         default="hold"),
    Rule("S2", "grunnlag", "Har vakter i turnusen, men står ikke i ukens ukeplan",
         choices=(("ukeplan", "Ukeplanen gjelder – regnes som ikke på jobb den uken (merknad; "
                              "varsel hvis ukeplanen ser ufullstendig ut)"),
                  ("turnus", "Bruk turnusen for dem – med varsel")),
         default="ukeplan"),
    Rule("S4", "grunnlag", "Varsle når turnusen ikke rekker frem", kind="number",
         default="28", unit="dager frem", low=7, high=120),
    Rule("S5", "grunnlag", "Vakter som ikke kan planlegges (ukjent kode, konflikt)",
         "Varsles alltid når de oppdages. Rødt varsel for de nærmeste dagene, gult for senere.",
         kind="number", default="28", unit="dager med rødt varsel", low=1, high=120),
    Rule("S6", "grunnlag", "Ny turnus har et helt annet antall personer enn forrige", kind="number",
         default="15", unit="% endring før varsel", low=1, high=90),
    Rule("S7", "grunnlag", "Kompetanse venter på gjennomgang eller mangler",
         kind="level", default="varsel", levels=("varsel", "merknad")),
    # -- notices -----------------------------------------------------------
    Rule("N1", "merknader", "Planen er et utkast (ikke publisert)", kind="level", default="merknad",
         levels=("merknad", "av")),
    Rule("N2", "merknader", "På vakt uten plassering", kind="level", default="merknad"),
    Rule("N3", "merknader", "To ansatte med samme navn (skilles på PersonID)", kind="level",
         default="merknad", levels=("merknad", "av")),
]
BY_ID = {r.id: r for r in RULES}
AREAS = [("planlegging", "Planlegging"), ("grunnlag", "Grunnlag fra turnus og ukeplan"),
         ("merknader", "Merknader")]

FIXED = [
    ("Feil filstruktur, feil enhet eller turnus uten PersonID", "Filen avvises og legges i avvist\\ med begrunnelse."),
    ("En vakt som ikke kan knyttes til nøyaktig én person", "Holdes utenfor planen med varsel – appen gjetter aldri hvem det er."),
    ("Ukjent vaktkode (også «D, A»)", "Holdes utenfor til koden er definert under Vaktkoder."),
    ("To rader eller to vakter for samme person samme dag", "Holdes utenfor med varsel."),
    ("Noen er meldt fraværende, men står i planen", "Alltid rødt varsel – skal aldri nå tavlen."),
    ("En regel brytes (ukegrense, underbemanning, rullering)", "Vises alltid – aldri i det stille."),
    ("Tom celle i ukeplanen", "Ikke på jobb den dagen."),
    ("Nattevakter", "Dateres etter morgenen de slutter (som i turnussystemet), planlegges under kvelden de starter."),
    ("M (overtid), * (betalt lunsj), /F3", "M alene er ingen vakt; D2* = D2; /F3 slutter kl. 12."),
    ("Flere filer for samme uke", "Nyeste eksport gjelder; ukeplanen går foran turnusen."),
    ("I ukeplanen, men ikke i turnusen", "Regnes som vikar med standardkompetanse."),
]


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS contingency_settings (rule_id TEXT PRIMARY KEY, "
                 "value TEXT NOT NULL, updated_at TEXT)")


def values(conn: sqlite3.Connection) -> dict[str, str]:
    """Every rule's current value (the default unless changed)."""
    _ensure_table(conn)
    stored = {r[0]: r[1] for r in conn.execute("SELECT rule_id, value FROM contingency_settings")}
    return {r.id: stored.get(r.id, r.default) for r in RULES}


def value(conn: sqlite3.Connection, rule_id: str) -> str:
    return values(conn)[rule_id]


def number(conn: sqlite3.Connection, rule_id: str) -> int:
    return int(value(conn, rule_id))


def finding_level(conn: sqlite3.Connection, rule_id: str, current: dict | None = None) -> str | None:
    """'warn' / 'info' / None (switched off) for a notice rule."""
    return LEVEL_TO_FINDING[(current or values(conn))[rule_id]]


def overview(conn: sqlite3.Connection) -> dict:
    current = values(conn)
    labels = dict(LEVELS)
    groups = []
    for area, area_label in AREAS:
        items = []
        for r in RULES:
            if r.area != area:
                continue
            choices = list(r.choices) if r.kind == "choice" else [(k, labels[k]) for k in r.levels]
            items.append({"rule": r, "value": current[r.id], "choices": choices,
                          "changed": current[r.id] != r.default})
        groups.append({"area": area, "label": area_label, "items": items})
    return {"groups": groups, "fixed": FIXED}


class Invalid(ValueError):
    pass


def save(conn: sqlite3.Connection, form) -> str:
    _ensure_table(conn)
    current = values(conn)
    changes = []
    for r in RULES:
        raw = (form.get(r.id) or "").strip()
        if not raw:
            continue
        if r.kind == "number":
            if not raw.isdigit() or not r.low <= int(raw) <= r.high:
                raise Invalid(f"«{r.title}»: må være et tall mellom {r.low} og {r.high}.")
            raw = str(int(raw))
        else:
            allowed = [k for k, _ in r.choices] if r.kind == "choice" else list(r.levels)
            if raw not in allowed:
                raise Invalid(f"«{r.title}»: ukjent valg.")
        if raw != current[r.id]:
            changes.append((r, current[r.id], raw))
    with conn:
        for r, old, new in changes:
            if new == r.default:
                conn.execute("DELETE FROM contingency_settings WHERE rule_id = ?", (r.id,))
            else:
                conn.execute("INSERT INTO contingency_settings (rule_id, value, updated_at) VALUES (?, ?, ?) "
                             "ON CONFLICT(rule_id) DO UPDATE SET value = excluded.value, "
                             "updated_at = excluded.updated_at",
                             (r.id, new, dt.datetime.now().isoformat(timespec="seconds")))
            applog.log(conn, "regler", f"Avvik og tiltak – {r.id} «{r.title}»: {_label(r, old)} → {_label(r, new)}.")
    if not changes:
        return "Ingen endringer."
    return f"Lagret {len(changes)} endring{'er' if len(changes) != 1 else ''} under Avvik og tiltak."


def _label(r: Rule, value: str) -> str:
    if r.kind == "number":
        return f"{value} {r.unit}"
    options = dict(r.choices) if r.kind == "choice" else dict(LEVELS)
    return options.get(value, value).split(" – ")[0]


def reset(conn: sqlite3.Connection) -> None:
    _ensure_table(conn)
    conn.execute("DELETE FROM contingency_settings")

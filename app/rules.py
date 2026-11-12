"""Planning rules managed in the app (D108): Administrasjon → Planregler.

Three kinds, all seeded from data/seed/ and then owned by the app (an edited
row keeps its value when the seed changes):
  rotation_swaps    who swaps with whom at the rotation point (D107)
  rotation_rules    the rotation point per shift category (D35)
  planner_settings  the weekly heavy-work numbers (D51/D106)
Every change is logged under «Planregler».
"""
from __future__ import annotations

import re
import sqlite3

from . import applog, domain, importer, service

SETTINGS = {
    # key: (label, help, kind, min, max)
    "heavy_occurrence_hard_cap_per_week": (
        "Grense for tunge økter per uke",
        "Hard grense per ansatt. Planleggeren går bare over når ingen andre kan ta "
        "arbeidet – og da varsles det i dagens kontroller (D51/D53).",
        int, 0, 7),
    "heavy_occurrence_target_per_week": (
        "Mål for tunge økter per uke",
        "Mykt mål per ansatt: planleggeren velger helst noen under målet, men rullering og "
        "faste plasser går foran.", int, 0, 7),
    "heavy_occurrence_intensity_threshold": (
        "Hva som teller som en tung økt",
        "Intensitet fra og med denne verdien. 1,0 = bare full intensitet (i dag Kontrollsone "
        "etter kl. 12); 0,5 tar med de moderat tunge funksjonene.", float, 0.1, 1.0),
    "intensity_ledger_window_days": (
        "Utjevningsvindu (dager)",
        "Hvor mange dager bakover tunge timer telles. Tungt arbeid går til den med færrest "
        "tunge timer i vinduet, lett arbeid til den med flest.", int, 7, 90),
}
CATEGORY_LABELS = service.SHIFT_CATEGORY_LABELS


class Invalid(ValueError):
    pass


def _side_label(conn: sqlite3.Connection, side: str) -> str:
    zones = {r["zone_id"]: r["name"] for r in conn.execute("SELECT zone_id, name FROM zones")}
    names = {r["function_id"]: r["name"] for r in conn.execute("SELECT function_id, name FROM functions")}
    parts = []
    for token in (t.strip() for t in side.split(";")):
        if token.startswith("zone:"):
            parts.append(f"hele {zones.get(token[5:], token[5:]).lower()}")
        elif token:
            parts.append(names.get(token, token))
    return ", ".join(parts) or "–"


def overview(conn: sqlite3.Connection) -> dict:
    seed_ids = {r["swap_id"] for r in importer.read_csv("rotation_swaps.csv")}
    swaps = []
    for swap in service.rotation_swaps(conn, active_only=False):
        tokens = {t.strip() for t in (swap["side_a"] + ";" + swap["side_b"]).split(";")}
        swaps.append({**swap, "a_label": _side_label(conn, swap["side_a"]),
                      "b_label": _side_label(conn, swap["side_b"]),
                      "a_tokens": {t.strip() for t in swap["side_a"].split(";")},
                      "b_tokens": {t.strip() for t in swap["side_b"].split(";")},
                      "standard": swap["swap_id"] in seed_ids, "tokens": tokens})
    zones = list(conn.execute(
        """SELECT z.zone_id, z.name FROM zones z WHERE EXISTS (SELECT 1 FROM functions f
           WHERE f.zone_id = z.zone_id AND f.active = 'yes' AND f.staffing_mode <> 'adhoc')
           ORDER BY z.sort_order"""))
    functions = list(conn.execute(
        "SELECT function_id, name, zone_id FROM functions WHERE active = 'yes' "
        "AND staffing_mode <> 'adhoc' ORDER BY sort_order"))
    settings = []
    values = {r["key"]: r for r in conn.execute("SELECT * FROM planner_settings")}
    for key, (label, help_text, kind, low, high) in SETTINGS.items():
        row = values.get(key)
        if row is None:
            continue
        value = row["value"]
        settings.append({"key": key, "label": label, "help": help_text,
                         "value": int(value) if kind is int else value,
                         "step": "1" if kind is int else "0.1", "min": low, "max": high,
                         "edited": row["edited"]})
    rotation = [dict(r) for r in conn.execute(
        "SELECT * FROM rotation_rules ORDER BY CASE category WHEN 'tidligvakt' THEN 0 "
        "WHEN 'mellomvakt' THEN 1 WHEN 'senvakt' THEN 2 WHEN 'nattevakt' THEN 3 ELSE 4 END")]
    for r in rotation:
        r["label"] = CATEGORY_LABELS.get(r["category"], r["category"])
    intensity = list(conn.execute(
        """SELECT i.*, f.name AS function_name FROM function_intensity i
           JOIN functions f ON f.function_id = i.function_id ORDER BY f.sort_order, i.start"""))
    return {"swaps": swaps, "zones": zones, "functions": functions, "settings": settings,
            "rotation": rotation, "intensity": intensity}


def _side(conn: sqlite3.Connection, tokens: list[str], label: str) -> str:
    valid = {f"zone:{r[0]}" for r in conn.execute("SELECT zone_id FROM zones")}
    valid |= {r[0] for r in conn.execute("SELECT function_id FROM functions WHERE active = 'yes'")}
    chosen = [t for t in dict.fromkeys(tokens) if t in valid]
    # A whole zone already covers its functions.
    zones = {t[5:] for t in chosen if t.startswith("zone:")}
    zone_of = {r[0]: r[1] for r in conn.execute("SELECT function_id, zone_id FROM functions")}
    chosen = [t for t in chosen if t.startswith("zone:") or zone_of.get(t) not in zones]
    if not chosen:
        raise Invalid(f"Velg minst én funksjon eller sone på {label}.")
    return ";".join(chosen)


def save_swap(conn: sqlite3.Connection, form) -> str:
    name = (form.get("name") or "").strip()[:80]
    if not name:
        raise Invalid("Regelen må ha et navn.")
    side_a = _side(conn, form.getlist("side_a"), "side A")
    side_b = _side(conn, form.getlist("side_b"), "side B")
    if service.expand_side(conn, side_a) & service.expand_side(conn, side_b):
        raise Invalid("Samme funksjon kan ikke stå på begge sider.")
    active = 1 if form.get("active") else 0
    notes = (form.get("notes") or "").strip()[:300]
    swap_id = (form.get("swap_id") or "").strip()
    with conn:
        if swap_id:
            before = conn.execute("SELECT * FROM rotation_swaps WHERE swap_id = ?", (swap_id,)).fetchone()
            if before is None:
                raise Invalid("Fant ikke regelen.")
            conn.execute("UPDATE rotation_swaps SET name = ?, side_a = ?, side_b = ?, active = ?, "
                         "notes = ?, edited = 1 WHERE swap_id = ?",
                         (name, side_a, side_b, active, notes, swap_id))
            changes = []
            if (before["side_a"], before["side_b"]) != (side_a, side_b):
                changes.append(f"{_side_label(conn, side_a)} → {_side_label(conn, side_b)}")
            if before["active"] != active:
                changes.append("slått på" if active else "slått av")
            text = f"Bytteregel «{name}» endret" + (f": {', '.join(changes)}." if changes else ".")
        else:
            base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "regel"
            swap_id, n = base, 2
            while conn.execute("SELECT 1 FROM rotation_swaps WHERE swap_id = ?", (swap_id,)).fetchone():
                swap_id, n = f"{base}_{n}", n + 1
            conn.execute("INSERT INTO rotation_swaps (swap_id, name, side_a, side_b, active, notes, "
                         "edited) VALUES (?, ?, ?, ?, ?, ?, 1)",
                         (swap_id, name, side_a, side_b, active, notes))
            text = (f"Bytteregel «{name}» lagt til: {_side_label(conn, side_a)} → "
                    f"{_side_label(conn, side_b)}{'' if active else ' (av)'}.")
        applog.log(conn, "regler", text)
    return text


def delete_swap(conn: sqlite3.Connection, swap_id: str) -> str:
    if swap_id in {r["swap_id"] for r in importer.read_csv("rotation_swaps.csv")}:
        raise Invalid("Standardregler kan ikke fjernes – slå dem av i stedet.")
    with conn:
        row = conn.execute("SELECT name FROM rotation_swaps WHERE swap_id = ?", (swap_id,)).fetchone()
        if row is None:
            raise Invalid("Fant ikke regelen.")
        conn.execute("DELETE FROM rotation_swaps WHERE swap_id = ?", (swap_id,))
        text = f"Bytteregel «{row['name']}» fjernet."
        applog.log(conn, "regler", text)
    return text


def save_rotation(conn: sqlite3.Connection, form) -> str:
    changed = []
    with conn:
        for row in conn.execute("SELECT * FROM rotation_rules").fetchall():
            raw = (form.get(f"time_{row['category']}") or "").strip()
            try:
                value = domain.parse_clock(raw).strftime("%H:%M") if raw else None
            except ValueError:
                raise Invalid(f"«{raw}» er ikke et klokkeslett ({row['category']}).") from None
            if value != row["rotation_time"]:
                conn.execute("UPDATE rotation_rules SET rotation_time = ?, edited = 1 "
                             "WHERE category = ?", (value, row["category"]))
                changed.append(f"{CATEGORY_LABELS.get(row['category'], row['category'])} "
                               f"{row['rotation_time'] or 'ingen'} → {value or 'ingen'}")
        if changed:
            applog.log(conn, "regler", "Rulleringstidspunkt endret: " + "; ".join(changed) + ".")
    return ("Rulleringstidspunktene er lagret: " + "; ".join(changed) + "."
            if changed else "Ingen endringer.")


def save_settings(conn: sqlite3.Connection, form) -> str:
    changed = []
    with conn:
        for key, (label, _, kind, low, high) in SETTINGS.items():
            raw = (form.get(key) or "").strip().replace(",", ".")
            if not raw:
                continue
            try:
                value = kind(float(raw))
            except ValueError:
                raise Invalid(f"{label}: «{raw}» er ikke et tall.") from None
            if not low <= value <= high:
                raise Invalid(f"{label}: må være mellom {low} og {high}.")
            if key == "intensity_ledger_window_days":
                from .hr_import import retention_days
                if value >= retention_days(conn):
                    raise Invalid(f"{label}: må være kortere enn hvor lenge data beholdes "
                                  f"({retention_days(conn)} dager, under Innstillinger).")
            row = conn.execute("SELECT value FROM planner_settings WHERE key = ?", (key,)).fetchone()
            if row is not None and float(row["value"]) != float(value):
                conn.execute("UPDATE planner_settings SET value = ?, edited = 1 WHERE key = ?",
                             (value, key))
                old = kind(row["value"])
                changed.append(f"{label} {old} → {value}")
        if changed:
            applog.log(conn, "regler", "Innstilling endret: " + "; ".join(changed) + ".")
    return ("Lagret: " + "; ".join(changed) + "." if changed else "Ingen endringer.")


def reset(conn: sqlite3.Connection) -> str:
    """Back to the seed's values for everything on this page."""
    with conn:
        conn.execute("UPDATE rotation_rules SET edited = 0")
        conn.execute("UPDATE planner_settings SET edited = 0")
        seed_ids = {r["swap_id"] for r in importer.read_csv("rotation_swaps.csv")}
        conn.execute("UPDATE rotation_swaps SET edited = 0")
        for (swap_id,) in conn.execute("SELECT swap_id FROM rotation_swaps").fetchall():
            if swap_id not in seed_ids:
                conn.execute("DELETE FROM rotation_swaps WHERE swap_id = ?", (swap_id,))
        importer.seed_rules(conn)
        from .contingency import reset as reset_contingency
        reset_contingency(conn)
        applog.log(conn, "regler", "Alle planregler satt tilbake til standard.")
    return "Alle planregler er satt tilbake til standard."

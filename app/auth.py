"""Who may use the admin side (D121).

- The board (/display) stays public. Everything else needs a logged-in
  administrator once at least one administrator exists. Before that the app
  is open as before, with a banner saying so, so pulling this change can't
  lock anyone out.
- Identity comes from the Windows login (everyone is logged into Windows
  with their ID card): the browser proves it with Windows' own single
  sign-on (Negotiate, app/winauth.py). Fallback method «prosess»: the Windows
  user running the app.
- Administrators are Windows accounts, added in **root mode** only:
  `python run.py --rotadmin` opens the browser with a one-time key that makes
  that browser root for this run. Anyone who can start the app can already
  reach its files, so this grants nothing new — but nobody else can use it.
- Sessions live in memory: restarting the app logs everyone out, and a new
  login is automatic (single sign-on).
"""
from __future__ import annotations

import datetime as dt
import getpass
import os
import secrets
import sqlite3
import threading
import time

from app import applog

SESSION_COOKIE = "sf_okt"
IDLE_SECONDS = 60 * 60
PUBLIC_PREFIXES = ("/display", "/static/", "/tavle", "/logginn", "/loggut", "/rot")
DEMO_USER = {"account": "demo", "name": "Demo", "role": "admin"}
ROOT_USER = {"account": "rot", "name": "Rotadministrator", "role": "root"}
METHODS = {"windows": "Windows-innlogging (enkel pålogging i nettleseren)",
           "prosess": "Windows-brukeren som startet appen"}

_sessions: dict[str, dict] = {}
_lock = threading.Lock()
# Set by run.py --rotadmin: the one-time key that makes a browser root.
ROOT_KEY: str | None = None


# -------------------------------------------------------------- accounts
def normalise(account: str) -> str:
    return (account or "").strip().replace("/", "\\").lower()


def admins(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM admins ORDER BY name")]


def is_set_up(conn: sqlite3.Connection) -> bool:
    return bool(conn.execute("SELECT 1 FROM admins WHERE active = 1 LIMIT 1").fetchone())


def find_admin(conn: sqlite3.Connection, account: str) -> dict | None:
    """An entry «DOMENE\\bruker» matches exactly; an entry without a domain
    matches that user name in any domain."""
    account = normalise(account)
    user = account.split("\\")[-1]
    for row in conn.execute("SELECT * FROM admins WHERE active = 1"):
        entry = row["account"]
        if entry == account or ("\\" not in entry and entry == user):
            return dict(row)
    return None


def method(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key = 'login_method'").fetchone()
    return row[0] if row and row[0] in METHODS else "windows"


def process_account() -> str:
    """The Windows account running the app («DOMENE\\bruker»)."""
    user = getpass.getuser()
    domain = os.environ.get("USERDOMAIN", "")
    return normalise(f"{domain}\\{user}" if domain else user)


class Invalid(ValueError):
    pass


def add_admin(conn: sqlite3.Connection, account: str, name: str, by: dict) -> str:
    account, name = normalise(account), (name or "").strip()[:80]
    if not account or not all(part for part in account.split("\\")) or account.count("\\") > 1 \
            or any(c.isspace() for c in account):
        raise Invalid("Skriv Windows-kontoen som DOMENE\\brukernavn (eller bare brukernavn).")
    if not name:
        raise Invalid("Skriv navnet til personen.")
    with conn:
        conn.execute(
            """INSERT INTO admins (account, name, active, added_at, added_by) VALUES (?, ?, 1, ?, ?)
               ON CONFLICT(account) DO UPDATE SET name = excluded.name, active = 1""",
            (account, name, dt.datetime.now().isoformat(timespec="seconds"), by["name"]))
        applog.log(conn, "tilgang", f"Administrator lagt til: {name} ({account}).")
    return f"{name} ({account}) er administrator."


def remove_admin(conn: sqlite3.Connection, account: str) -> str:
    with conn:
        row = conn.execute("SELECT name FROM admins WHERE account = ?", (normalise(account),)).fetchone()
        if row is None:
            raise Invalid("Fant ikke kontoen.")
        conn.execute("UPDATE admins SET active = 0 WHERE account = ?", (normalise(account),))
        applog.log(conn, "tilgang", f"Administrator fjernet: {row['name']} ({normalise(account)}).")
    end_sessions(normalise(account))
    return f"{row['name']} har ikke lenger tilgang."


def set_method(conn: sqlite3.Connection, value: str) -> str:
    if value not in METHODS:
        raise Invalid("Ukjent innloggingsmåte.")
    with conn:
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('login_method', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (value,))
        applog.log(conn, "tilgang", f"Innloggingsmåte: {METHODS[value]}.")
    return f"Innlogging: {METHODS[value]}."


# -------------------------------------------------------------- sessions
def start_session(user: dict) -> str:
    token = secrets.token_urlsafe(32)
    with _lock:
        _sessions[token] = {**user, "last": time.monotonic()}
    return token


def session_user(token: str | None) -> dict | None:
    if not token:
        return None
    with _lock:
        user = _sessions.get(token)
        if user is None:
            return None
        if time.monotonic() - user["last"] > IDLE_SECONDS:
            _sessions.pop(token, None)
            return None
        user["last"] = time.monotonic()
        return dict(user)


def end_session(token: str | None) -> None:
    with _lock:
        _sessions.pop(token or "", None)


def end_sessions(account: str) -> None:
    with _lock:
        for token in [t for t, u in _sessions.items() if u["account"] == account]:
            _sessions.pop(token)


def login(conn: sqlite3.Connection, account: str) -> tuple[str | None, str]:
    """(session token or None, message) for a proven Windows account."""
    admin = find_admin(conn, account)
    if admin is None:
        return None, (f"Kontoen {normalise(account)} har ikke tilgang til administrasjonen. Be eieren "
                      "legge den til (rotmodus: python run.py --rotadmin).")
    with conn:
        conn.execute("UPDATE admins SET last_login = ? WHERE account = ?",
                     (dt.datetime.now().isoformat(timespec="seconds"), admin["account"]))
    token = start_session({"account": admin["account"], "name": admin["name"], "role": "admin"})
    applog.CURRENT_USER.set(admin["name"])
    applog.write(conn, "tilgang", f"{admin['name']} logget inn.")
    return token, f"Logget inn som {admin['name']}."


def use_root_key(key: str | None) -> str | None:
    """The one-time key from run.py --rotadmin → a root session."""
    global ROOT_KEY
    if not ROOT_KEY or not key or not secrets.compare_digest(key, ROOT_KEY):
        return None
    ROOT_KEY = None                                 # one use only
    return start_session(ROOT_USER)


def is_public(path: str) -> bool:
    return path == "/favicon.ico" or any(path == p or path.startswith(p) for p in PUBLIC_PREFIXES)

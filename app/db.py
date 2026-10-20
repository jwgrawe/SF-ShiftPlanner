"""SQLite connection and schema.

The database lives inside the repo/app folder (self-contained deployment,
D49). Master-data tables mirror the seed CSVs; runtime tables (roster,
absences, plans, imports) are owned by the app.

Two modes, two files (D89): the real database holds the imported HR exports
and real people; the demo database holds the fictional seed staff and a
generated roster. They never mix. `python run.py --demo` selects the demo.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
REAL_DB_PATH = DATA_DIR / "sf_planlegger.db"
DEMO_DB_PATH = DATA_DIR / "sf_planlegger_demo.db"

# "real" or "demo". Set once at start-up (run.py); SF_MODE lets a bare
# `uvicorn app.main:app` pick the demo too.
MODE = "demo" if os.environ.get("SF_MODE") == "demo" else "real"


def set_mode(mode: str) -> None:
    global MODE
    MODE = "demo" if mode == "demo" else "real"
    os.environ["SF_MODE"] = MODE


def is_demo() -> bool:
    return MODE == "demo"


def current_db_path() -> Path:
    return DEMO_DB_PATH if is_demo() else REAL_DB_PATH


# Kept for scripts that predate the two modes.
DEFAULT_DB_PATH = REAL_DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS zones (
    zone_id TEXT PRIMARY KEY, name TEXT NOT NULL, sort_order INTEGER, notes TEXT);
CREATE TABLE IF NOT EXISTS functions (
    function_id TEXT PRIMARY KEY, zone_id TEXT NOT NULL REFERENCES zones(zone_id),
    name TEXT NOT NULL, short_name TEXT NOT NULL, staffing_mode TEXT NOT NULL,
    active TEXT NOT NULL, sort_order INTEGER, notes TEXT);
CREATE TABLE IF NOT EXISTS competency_types (
    competency_id TEXT PRIMARY KEY, name TEXT NOT NULL, source_column TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS function_competencies (
    function_id TEXT NOT NULL REFERENCES functions(function_id),
    competency_id TEXT NOT NULL REFERENCES competency_types(competency_id),
    priority INTEGER NOT NULL, notes TEXT,
    PRIMARY KEY (function_id, competency_id));
CREATE TABLE IF NOT EXISTS function_intensity (
    function_id TEXT NOT NULL REFERENCES functions(function_id),
    start TEXT NOT NULL, end TEXT NOT NULL, intensity REAL NOT NULL, notes TEXT);
-- Long format: one row per hour. function_ids may hold several ids separated
-- by ";" when row_type = 'function_group' (shared demand, Q20).
CREATE TABLE IF NOT EXISTS staffing_demand (
    row_type TEXT NOT NULL, zone_id TEXT, function_ids TEXT, category TEXT NOT NULL,
    day_type TEXT NOT NULL, hour INTEGER NOT NULL, required INTEGER NOT NULL, notes TEXT);
CREATE TABLE IF NOT EXISTS shift_codes (
    code TEXT PRIMARY KEY, start TEXT NOT NULL, end TEXT NOT NULL,
    crosses_midnight TEXT NOT NULL, category TEXT NOT NULL, utpost_code TEXT NOT NULL,
    duration_hours REAL, comment TEXT);
CREATE TABLE IF NOT EXISTS rotation_rules (
    category TEXT PRIMARY KEY, rotation_time TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS planner_settings (
    key TEXT PRIMARY KEY, value REAL NOT NULL, notes TEXT);
CREATE TABLE IF NOT EXISTS opening_hours (
    period_type TEXT, shift_type TEXT, sort_order INTEGER, weekday TEXT,
    weekday_num INTEGER, start TEXT, end TEXT);
CREATE TABLE IF NOT EXISTS worktable_types (
    worktable_type TEXT PRIMARY KEY, notes TEXT);
CREATE TABLE IF NOT EXISTS weekday_rules (
    function_id TEXT NOT NULL, category TEXT, weekday TEXT NOT NULL, rule TEXT,
    start TEXT, end TEXT, count INTEGER, source_text TEXT);
CREATE TABLE IF NOT EXISTS employees (
    employee_id TEXT PRIMARY KEY, source_label TEXT, first_name TEXT, last_name TEXT,
    display_name TEXT NOT NULL, works_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS employee_competencies (
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    competency_id TEXT NOT NULL REFERENCES competency_types(competency_id),
    status TEXT NOT NULL,
    PRIMARY KEY (employee_id, competency_id));
CREATE TABLE IF NOT EXISTS employee_preferences (
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    function_id TEXT NOT NULL REFERENCES functions(function_id),
    note TEXT,
    PRIMARY KEY (employee_id, function_id));
CREATE TABLE IF NOT EXISTS employee_restrictions (
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    restriction_type TEXT NOT NULL, function_id TEXT,
    valid_from TEXT, valid_to TEXT, note TEXT);

-- Runtime tables (owned by the app, not wiped on re-import)
CREATE TABLE IF NOT EXISTS roster (
    date TEXT NOT NULL, employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    shift_code TEXT NOT NULL REFERENCES shift_codes(code),
    PRIMARY KEY (date, employee_id));
CREATE TABLE IF NOT EXISTS absences (
    absence_id INTEGER PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    date TEXT NOT NULL, start TEXT, end TEXT, type TEXT, note TEXT);
-- status: 'draft' (utkast) or 'published' (publisert). The display shows
-- published plans only (D22). manually_edited marks plans a manager changed.
CREATE TABLE IF NOT EXISTS plan_days (
    plan_date TEXT PRIMARY KEY, status TEXT NOT NULL, generated_at TEXT,
    manually_edited INTEGER NOT NULL DEFAULT 0, note TEXT);
CREATE TABLE IF NOT EXISTS assignments (
    assignment_id INTEGER PRIMARY KEY,
    plan_date TEXT NOT NULL REFERENCES plan_days(plan_date),
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    function_id TEXT NOT NULL REFERENCES functions(function_id),
    start TEXT NOT NULL, end TEXT NOT NULL,
    locked INTEGER NOT NULL DEFAULT 0, source TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS idx_assignments_date ON assignments(plan_date);
-- Small key/value store for app preferences set in the admin view.
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- Free-text notice per day ("diverse info"), shown on the wall display.
CREATE TABLE IF NOT EXISTS day_info (
    plan_date TEXT PRIMARY KEY, info TEXT NOT NULL DEFAULT '', updated_at TEXT);

-- HR exports (D88): one row per file seen, its person rows and its non-empty
-- day cells exactly as exported (export_date = the date column it sat in).
-- kind: 'plan' | 'ajourhold' | 'kompetanse'
-- status: 'active' | 'superseded' | 'rejected'
CREATE TABLE IF NOT EXISTS import_files (
    file_id INTEGER PRIMARY KEY, kind TEXT NOT NULL, filename TEXT NOT NULL,
    sha256 TEXT NOT NULL, exported_at TEXT, first_date TEXT, last_date TEXT,
    imported_at TEXT NOT NULL, status TEXT NOT NULL, reason TEXT,
    person_count INTEGER, fingerprint TEXT, stored_path TEXT);
CREATE INDEX IF NOT EXISTS idx_import_files_sha ON import_files(sha256);
CREATE TABLE IF NOT EXISTS import_rows (
    file_id INTEGER NOT NULL, row_no INTEGER NOT NULL, full_name TEXT NOT NULL,
    person_id TEXT, title TEXT, first_date TEXT, last_date TEXT,
    PRIMARY KEY (file_id, row_no));
CREATE TABLE IF NOT EXISTS import_cells (
    file_id INTEGER NOT NULL, row_no INTEGER NOT NULL, export_date TEXT NOT NULL,
    raw TEXT NOT NULL, PRIMARY KEY (file_id, row_no, export_date));
CREATE INDEX IF NOT EXISTS idx_import_cells_date ON import_cells(export_date);
CREATE TABLE IF NOT EXISTS import_legend (
    file_id INTEGER NOT NULL, code TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
    PRIMARY KEY (file_id, code));
-- Findings of the latest refresh (rebuilt every time) and a lasting log of
-- what imports did, e.g. assignments removed because a shift disappeared.
CREATE TABLE IF NOT EXISTS import_findings (
    finding_id INTEGER PRIMARY KEY, level TEXT NOT NULL, kind TEXT NOT NULL,
    text TEXT NOT NULL, date TEXT);
CREATE TABLE IF NOT EXISTS import_log (
    log_id INTEGER PRIMARY KEY, at TEXT NOT NULL, text TEXT NOT NULL);
-- Competency matrix rows by name (the workbook names people exactly as the
-- exports do, D82); linked to employees at every refresh.
CREATE TABLE IF NOT EXISTS competency_rows (
    full_name TEXT NOT NULL, competency_id TEXT NOT NULL, status TEXT NOT NULL,
    PRIMARY KEY (full_name, competency_id));
-- Job titles (D79/D87): one rule per title, set once by an admin.
-- rule: 'vanlig' | 'aldri' | 'begrenset' | 'uavklart'
CREATE TABLE IF NOT EXISTS positions (
    title TEXT PRIMARY KEY, rule TEXT NOT NULL, first_seen TEXT, classified_at TEXT,
    notes TEXT);
CREATE TABLE IF NOT EXISTS position_exclusions (
    title TEXT NOT NULL, function_id TEXT NOT NULL, PRIMARY KEY (title, function_id));
-- Shift codes learned from a Plan legend (not in data/seed/shift_codes.csv).
-- Survive the seed reload on start-up; merged into shift_codes after it.
CREATE TABLE IF NOT EXISTS learned_shift_codes (
    code TEXT PRIMARY KEY, start TEXT NOT NULL, end TEXT NOT NULL,
    crosses_midnight TEXT NOT NULL, category TEXT NOT NULL, utpost_code TEXT NOT NULL,
    duration_hours REAL, confirmed INTEGER NOT NULL DEFAULT 0, learned_at TEXT);
-- Competency data (D96–D99). The app's own copy is competency_rows (by the
-- export name, D82); Excel files are staged for review before they touch it.
CREATE TABLE IF NOT EXISTS standard_competencies (
    competency_id TEXT PRIMARY KEY, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS competency_aliases (
    alias TEXT PRIMARY KEY, full_name TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS competency_imports (
    import_id INTEGER PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL,
    uploaded_at TEXT NOT NULL, status TEXT NOT NULL, decided_at TEXT, payload TEXT NOT NULL);
-- Times a manager entered for a shift whose code the app doesn't know
-- (temps' codes such as DX, D95). Tied to the exact cell: person, export date
-- and the raw text — a changed cell drops the entry.
CREATE TABLE IF NOT EXISTS manual_shift_times (
    employee_id TEXT NOT NULL, export_date TEXT NOT NULL, raw TEXT NOT NULL,
    start TEXT NOT NULL, end TEXT NOT NULL, entered_at TEXT NOT NULL,
    PRIMARY KEY (employee_id, export_date));
-- Roster days that can't be planned yet: an unknown code, an ambiguous cell.
CREATE TABLE IF NOT EXISTS roster_pending (
    date TEXT NOT NULL, employee_id TEXT NOT NULL, raw TEXT NOT NULL,
    reason TEXT NOT NULL, source TEXT, PRIMARY KEY (date, employee_id));
"""

MASTER_TABLES = [
    "function_competencies", "function_intensity", "staffing_demand",
    "employee_competencies", "employee_preferences", "employee_restrictions",
    "weekday_rules", "worktable_types", "opening_hours", "rotation_rules",
    "planner_settings", "shift_codes", "functions", "competency_types",
    "employees", "zones",
]
# In real mode people come from the imports, not from the seed: these are
# never wiped or reloaded there.
PEOPLE_TABLES = {"employees", "employee_competencies", "employee_preferences",
                 "employee_restrictions"}


def get_conn(db_path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or current_db_path()), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Lightweight migrations for databases created by earlier versions.
    _ensure_column(conn, "functions", "short_name", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "plan_days", "manually_edited", "INTEGER NOT NULL DEFAULT 0")
    # Real roster (D73/D87): who/what decided a day, a shortened end (F3), and
    # why a rostered person is held out of placement (title rules).
    for column, decl in (("hold", "TEXT"), ("end_override", "TEXT"), ("title", "TEXT"),
                         ("source", "TEXT"), ("raw", "TEXT"), ("start_override", "TEXT"),
                         ("category_override", "TEXT")):
        _ensure_column(conn, "roster", column, decl)
    for column, decl in (("full_name", "TEXT"), ("person_id", "TEXT"), ("origin", "TEXT"),
                         ("is_temp", "INTEGER NOT NULL DEFAULT 0")):
        _ensure_column(conn, "employees", column, decl)
    # 'standard' marks competencies assumed for a temp (D97), not assessed.
    _ensure_column(conn, "employee_competencies", "source", "TEXT")
    # Every log line belongs to an area, so each page can show its own (D100).
    _ensure_column(conn, "import_log", "area", "TEXT NOT NULL DEFAULT 'import'")
    _ensure_column(conn, "roster_pending", "fixable", "INTEGER NOT NULL DEFAULT 0")


def merge_learned_codes(conn: sqlite3.Connection) -> None:
    """Shift codes learned from Plan legends join the seed codes (seed wins).
    Also the reserved code MAN: a shift whose times a manager entered by hand
    (its real times live on the roster row, D95)."""
    conn.execute(
        """INSERT OR IGNORE INTO shift_codes
           (code, start, end, crosses_midnight, category, utpost_code, duration_hours, comment)
           VALUES ('MAN', '00:00', '00:00', 'no', 'tidligvakt', 'no', 0,
                   'Reservert: vakt med manuelt angitt tid (D95)')""")
    conn.execute(
        """INSERT OR IGNORE INTO shift_codes
           (code, start, end, crosses_midnight, category, utpost_code, duration_hours, comment)
           SELECT code, start, end, crosses_midnight, category, utpost_code, duration_hours,
                  'Lært fra turnusens forklaring' FROM learned_shift_codes""")


def migrate_legacy_demo_db() -> str | None:
    """Before D89 the demo lived in sf_planlegger.db. If that file holds demo
    data and no imports, it becomes the demo database, so real mode starts
    clean. Returns a message when something was moved."""
    if not REAL_DB_PATH.exists() or DEMO_DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(REAL_DB_PATH))
    try:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "import_files" in tables and conn.execute(
                "SELECT COUNT(*) FROM import_files").fetchone()[0]:
            return None
        demo_rows = 0
        if "employees" in tables:
            demo_rows = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE source_label LIKE 'Employee %'").fetchone()[0]
    finally:
        conn.close()
    if not demo_rows:
        return None
    shutil.move(str(REAL_DB_PATH), str(DEMO_DB_PATH))
    return (f"Den gamle demodatabasen ble flyttet til {DEMO_DB_PATH.name} "
            "(start demo med: python run.py --demo).")

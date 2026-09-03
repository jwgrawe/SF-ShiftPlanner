"""SQLite connection and schema.

The database lives inside the repo/app folder (self-contained deployment,
D49) and is rebuilt from data/seed/ by app/importer.py. Master-data tables
mirror the seed CSVs; runtime tables (roster, absences, plans) are owned by
the app.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "sf_planlegger.db"

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
"""

MASTER_TABLES = [
    "function_competencies", "function_intensity", "staffing_demand",
    "employee_competencies", "employee_preferences", "employee_restrictions",
    "weekday_rules", "worktable_types", "opening_hours", "rotation_rules",
    "planner_settings", "shift_codes", "functions", "competency_types",
    "employees", "zones",
]


def get_conn(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
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

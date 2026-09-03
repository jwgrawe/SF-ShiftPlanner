"""SF-Planlegger web app (M1: read-only).

Run:  python -m uvicorn app.main:app --reload
Then open http://127.0.0.1:8000/

Views (D2/D3/D23): /display (wall screen, portrait), /plan (manager, read-only
for now), /admin (master data browser). Editing, PINs and the suggestion
engine arrive in M2/M3. Preview any moment with ?date=YYYY-MM-DD&time=HH:MM.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import db, domain, service

try:
    TZ = ZoneInfo("Europe/Oslo")
except ZoneInfoNotFoundError:
    # Windows has no system tz database; without the `tzdata` package fall
    # back to the machine's local clock (which on-site is Oslo time anyway).
    TZ = None
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

app = FastAPI(title="SF-Planlegger", docs_url=None, redoc_url=None)


def get_conn():
    conn = db.get_conn()
    db.init_schema(conn)
    return conn


def resolve_now(date: str | None, time: str | None) -> dt.datetime:
    now = dt.datetime.now(TZ).replace(tzinfo=None)
    if date:
        parsed_time = domain.parse_time(time) if time else now.time()
        return dt.datetime.combine(dt.date.fromisoformat(date), parsed_time)
    if time:
        return dt.datetime.combine(now.date(), domain.parse_time(time))
    return now


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return TEMPLATES.TemplateResponse(request, "index.html", {})


@app.get("/display", response_class=HTMLResponse)
def display(request: Request, date: str | None = None, time: str | None = None):
    now = resolve_now(date, time)
    conn = get_conn()
    try:
        model = service.build_display_model(conn, now)
    finally:
        conn.close()
    model["preview"] = bool(date or time)
    return TEMPLATES.TemplateResponse(request, "display.html", model)


@app.get("/plan", response_class=HTMLResponse)
def plan(request: Request, date: str | None = None):
    plan_date = (
        dt.date.fromisoformat(date)
        if date
        else domain.operational_day(dt.datetime.now(TZ).replace(tzinfo=None))
    )
    conn = get_conn()
    try:
        model = service.build_plan_model(conn, plan_date)
    finally:
        conn.close()
    model["prev_date"] = (plan_date - dt.timedelta(days=1)).isoformat()
    model["next_date"] = (plan_date + dt.timedelta(days=1)).isoformat()
    return TEMPLATES.TemplateResponse(request, "plan.html", model)


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    conn = get_conn()
    try:
        functions = list(conn.execute(
            """SELECT f.*, z.name AS zone_name FROM functions f
               JOIN zones z ON z.zone_id = f.zone_id ORDER BY f.sort_order"""))
        intensity = list(conn.execute(
            """SELECT i.*, f.name AS function_name FROM function_intensity i
               JOIN functions f ON f.function_id = i.function_id ORDER BY f.sort_order"""))
        shift_codes = list(conn.execute("SELECT * FROM shift_codes ORDER BY code"))
        rotation_rules = list(conn.execute("SELECT * FROM rotation_rules"))
        settings = list(conn.execute("SELECT * FROM planner_settings ORDER BY key"))
        employees = list(conn.execute("SELECT * FROM employees ORDER BY employee_id"))
        competencies: dict[str, list[dict]] = {}
        for row in conn.execute(
            """SELECT ec.employee_id, ct.name, ec.status FROM employee_competencies ec
               JOIN competency_types ct ON ct.competency_id = ec.competency_id
               ORDER BY ct.name"""):
            competencies.setdefault(row["employee_id"], []).append(
                {"name": row["name"], "status": row["status"]})
        preferences = list(conn.execute(
            """SELECT p.employee_id, e.display_name, f.name AS function_name, p.note
               FROM employee_preferences p
               JOIN employees e ON e.employee_id = p.employee_id
               JOIN functions f ON f.function_id = p.function_id
               ORDER BY p.employee_id"""))
        restrictions = list(conn.execute(
            """SELECT r.*, e.display_name, f.name AS function_name
               FROM employee_restrictions r
               JOIN employees e ON e.employee_id = r.employee_id
               LEFT JOIN functions f ON f.function_id = r.function_id
               ORDER BY r.employee_id"""))
    finally:
        conn.close()
    return TEMPLATES.TemplateResponse(request, "admin.html", {
        "functions": functions, "intensity": intensity, "shift_codes": shift_codes,
        "rotation_rules": rotation_rules, "settings": settings, "employees": employees,
        "competencies": competencies, "preferences": preferences,
        "restrictions": restrictions,
    })

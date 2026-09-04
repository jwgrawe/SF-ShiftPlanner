"""SF-Planlegger web app (M2 in progress).

Run:  python run.py   (or python -m uvicorn app.main:app --reload)

Views (D2/D3/D23): /display (wall screen, portrait, published plans only),
/plan (manager: overview -> week -> day -> edit, generate/publish),
/admin (master data browser). PINs and absence registration come next;
until then the editing endpoints are open on the trusted machine (D25/D31).
Preview any moment with ?date=YYYY-MM-DD&time=HH:MM on /display.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import db, domain, planner, service

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


def local_now() -> dt.datetime:
    return dt.datetime.now(TZ).replace(tzinfo=None)


def resolve_now(date: str | None, time: str | None) -> dt.datetime:
    now = local_now()
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


# ---------------------------------------------------------------------------
# Planning (manager)

@app.get("/plan", response_class=HTMLResponse)
def plan_overview(request: Request):
    conn = get_conn()
    try:
        model = service.build_overview_model(conn, local_now().date())
    finally:
        conn.close()
    return TEMPLATES.TemplateResponse(request, "plan_overview.html", model)


@app.get("/plan/uke", response_class=HTMLResponse)
def plan_week(request: Request, start: str):
    monday = service.monday_of(dt.date.fromisoformat(start))
    conn = get_conn()
    try:
        model = service.build_week_model(conn, monday)
    finally:
        conn.close()
    return TEMPLATES.TemplateResponse(request, "plan_week.html", model)


@app.get("/plan/dag", response_class=HTMLResponse)
def plan_day(request: Request, date: str, visning: str | None = None):
    plan_date = dt.date.fromisoformat(date)
    conn = get_conn()
    try:
        model = service.build_day_model(conn, plan_date)
    finally:
        conn.close()
    model["prev_date"] = (plan_date - dt.timedelta(days=1)).isoformat()
    model["next_date"] = (plan_date + dt.timedelta(days=1)).isoformat()
    model["visning"] = visning
    return TEMPLATES.TemplateResponse(request, "plan_day.html", model)


@app.get("/plan/dag/rediger", response_class=HTMLResponse)
def plan_edit(request: Request, date: str):
    plan_date = dt.date.fromisoformat(date)
    conn = get_conn()
    try:
        model = service.build_edit_model(conn, plan_date)
    finally:
        conn.close()
    return TEMPLATES.TemplateResponse(request, "plan_edit.html", model)


@app.post("/plan/generer")
async def plan_generate(request: Request):
    form = await request.form()
    start = dt.date.fromisoformat(str(form["start"]))
    days = int(str(form.get("days", "7")))
    conn = get_conn()
    try:
        for offset in range(days):
            date = start + dt.timedelta(days=offset)
            if planner.day_roster(conn, date):
                planner.suggest_day(conn, date)
    finally:
        conn.close()
    return RedirectResponse(f"/plan/uke?start={service.monday_of(start)}", status_code=303)


@app.post("/plan/publiser")
async def plan_publish(request: Request):
    form = await request.form()
    start = dt.date.fromisoformat(str(form["start"]))
    days = int(str(form.get("days", "1")))
    conn = get_conn()
    try:
        with conn:
            for offset in range(days):
                conn.execute(
                    "UPDATE plan_days SET status = 'published' WHERE plan_date = ?",
                    ((start + dt.timedelta(days=offset)).isoformat(),),
                )
    finally:
        conn.close()
    target = str(form.get("back", f"/plan/dag?date={start}"))
    return RedirectResponse(target, status_code=303)


@app.post("/plan/dag/lagre")
async def plan_save(request: Request):
    form = await request.form()
    plan_date = dt.date.fromisoformat(str(form["date"]))
    conn = get_conn()
    try:
        current = {
            row["assignment_id"]: row
            for row in conn.execute(
                "SELECT * FROM assignments WHERE plan_date = ?", (plan_date.isoformat(),)
            )
        }
        changed = False
        with conn:
            for key, value in form.items():
                if not key.startswith("a"):
                    continue
                try:
                    assignment_id = int(key[1:])
                except ValueError:
                    continue
                row = current.get(assignment_id)
                if row is None:
                    continue
                new_function = str(value)
                if new_function == "__remove__":
                    conn.execute(
                        "DELETE FROM assignments WHERE assignment_id = ?", (assignment_id,)
                    )
                    changed = True
                elif new_function != row["function_id"]:
                    conn.execute(
                        """UPDATE assignments SET function_id = ?, locked = 1,
                           source = 'manuell' WHERE assignment_id = ?""",
                        (new_function, assignment_id),
                    )
                    changed = True
            if changed:
                conn.execute(
                    "UPDATE plan_days SET manually_edited = 1 WHERE plan_date = ?",
                    (plan_date.isoformat(),),
                )
    finally:
        conn.close()
    return RedirectResponse(f"/plan/dag?date={plan_date}", status_code=303)


@app.post("/plan/dag/laas-opp")
async def plan_unlock(request: Request):
    form = await request.form()
    plan_date = dt.date.fromisoformat(str(form["date"]))
    conn = get_conn()
    try:
        with conn:
            conn.execute(
                "UPDATE assignments SET locked = 0 WHERE plan_date = ?",
                (plan_date.isoformat(),),
            )
    finally:
        conn.close()
    return RedirectResponse(f"/plan/dag?date={plan_date}", status_code=303)


# ---------------------------------------------------------------------------
# Admin

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

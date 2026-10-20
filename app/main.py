"""SF-Planlegger web app (M2 in progress).

Run:  python run.py   (or python -m uvicorn app.main:app --reload)

Views (D2/D3/D23): /display (wall screen, portrait, published plans only),
/plan (manager: overview -> week -> day -> edit, generate/publish),
/import (the data the roster rests on: files, coverage, findings),
/admin (settings, job titles, learned codes, master data browser). PINs and absence registration come next;
until then the editing endpoints are open on the trusted machine (D25/D31).
Preview any moment with ?date=YYYY-MM-DD&time=HH:MM on /display.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time as time_module
from urllib.parse import quote
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import absences as absences_mod
from app import applog, checks, competency, db, domain, hr_import, planner, service
from app.hr_export import Rejected

try:
    TZ = ZoneInfo("Europe/Oslo")
except ZoneInfoNotFoundError:
    # Windows has no system tz database; without the `tzdata` package fall
    # back to the machine's local clock (which on-site is Oslo time anyway).
    TZ = None

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# Browsers cache /static/app.css heuristically (it is served without a
# Cache-Control header), which would leave a pulled restyle invisible until a
# hard refresh. Stamping the URL with the file's mtime makes every change a
# new URL, so the browser fetches it.
_CSS = Path(__file__).parent / "static" / "app.css"
TEMPLATES.env.globals["static_version"] = int(_CSS.stat().st_mtime) if _CSS.exists() else 0
TEMPLATES.env.globals["is_demo"] = db.is_demo
TEMPLATES.env.globals["kind_label"] = hr_import.kind_label

app = FastAPI(title="SF-Planlegger", docs_url=None, redoc_url=None)
app.mount(
    "/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static"
)


def get_conn(refresh: bool = False):
    """A connection; with refresh=True, new files in data/import/ are picked
    up first (at most every 30 s, D91) — so pages stay current by themselves."""
    conn = db.get_conn()
    db.init_schema(conn)
    if refresh:
        hr_import.refresh(conn)
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
def today_page(request: Request):
    """The manager's morning page: today's state, what needs attention, and
    the way into the coming weeks."""
    now = local_now()
    conn = get_conn(refresh=True)
    try:
        today = domain.operational_day(now)
        horizon = []
        for offset in range(3):
            date = today + dt.timedelta(days=offset)
            status = service.day_status(conn, date)
            status["checks"] = checks.day_checks(conn, date)
            horizon.append(status)
        model = {
            "now": now,
            "today": today,
            "horizon": horizon,
            "weeks": service.build_overview_model(conn, today, n_weeks=3)["weeks"],
            "display": service.build_display_model(conn, now),
            "absences": absences_mod.day_absences(conn, today),
            "import_findings": [] if db.is_demo() else service.import_findings(conn),
        }
    finally:
        conn.close()
    return TEMPLATES.TemplateResponse(request, "today.html", model)


@app.get("/display", response_class=HTMLResponse)
def display(request: Request, date: str | None = None, time: str | None = None,
            tema: str | None = None):
    """The wall board. The palette comes from the admin setting; `tema=lys`
    or `tema=mork` overrides it for a one-off preview (D69)."""
    now = resolve_now(date, time)
    conn = get_conn(refresh=True)
    try:
        model = service.build_display_model(conn, now)
        stored = service.get_setting(conn, "display_theme", "mork")
    finally:
        conn.close()
    model["preview"] = bool(date or time)
    model["theme"] = tema if tema in ("lys", "mork") else stored
    return TEMPLATES.TemplateResponse(request, "display.html", model)


# ---------------------------------------------------------------------------
# Planning (manager)

@app.get("/plan", response_class=HTMLResponse)
def plan_overview(request: Request):
    conn = get_conn(refresh=True)
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
def plan_day(request: Request, date: str, visning: str | None = None,
             feil: str | None = None):
    plan_date = dt.date.fromisoformat(date)
    conn = get_conn()
    try:
        model = service.build_day_model(conn, plan_date)
        model["checks"] = checks.day_checks(conn, plan_date)
        model["absences"] = absences_mod.day_absences(conn, plan_date)
        model["employee_options"] = service.employee_options(conn, plan_date)
    finally:
        conn.close()
    model["prev_date"] = (plan_date - dt.timedelta(days=1)).isoformat()
    model["next_date"] = (plan_date + dt.timedelta(days=1)).isoformat()
    model["visning"] = visning
    model["is_today"] = plan_date == domain.operational_day(local_now())
    model["feil"] = feil
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
        made = []
        for offset in range(days):
            date = start + dt.timedelta(days=offset)
            if planner.day_roster(conn, date):
                planner.suggest_day(conn, date)
                made.append(date)
        if made:
            applog.write(conn, "plan", f"Forslag laget for {made[0]:%d.%m.%Y}"
                                       f"{f'–{made[-1]:%d.%m.%Y}' if len(made) > 1 else ''}.")
    finally:
        conn.close()
    target = str(form.get("back", f"/plan/uke?start={service.monday_of(start)}"))
    return RedirectResponse(target, status_code=303)


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
            applog.log(conn, "plan", f"Publisert: {start:%d.%m.%Y}"
                                     f"{f' + {days - 1} dager' if days > 1 else ''}.")
    finally:
        conn.close()
    target = str(form.get("back", f"/plan/dag?date={start}"))
    return RedirectResponse(target, status_code=303)


@app.post("/plan/avpubliser")
async def plan_unpublish(request: Request):
    """Take a day off the wall display again, back to draft (D68)."""
    form = await request.form()
    plan_date = dt.date.fromisoformat(str(form["date"]))
    conn = get_conn()
    try:
        with conn:
            conn.execute(
                "UPDATE plan_days SET status = 'draft' WHERE plan_date = ? AND status = 'published'",
                (plan_date.isoformat(),),
            )
            applog.log(conn, "plan", f"Avpublisert: {plan_date:%d.%m.%Y}.")
    finally:
        conn.close()
    return RedirectResponse(str(form.get("back", f"/plan/dag?date={plan_date}")), status_code=303)


@app.post("/plan/dag/slett")
async def plan_delete(request: Request):
    """Delete a draft day outright, locked rows included (D68). A published
    plan must be unpublished first — checked here, not just hidden in the UI."""
    form = await request.form()
    plan_date = dt.date.fromisoformat(str(form["date"]))
    conn = get_conn()
    try:
        plan = conn.execute(
            "SELECT status FROM plan_days WHERE plan_date = ?", (plan_date.isoformat(),)
        ).fetchone()
        if plan is not None and plan["status"] == "published":
            return RedirectResponse(
                f"/plan/dag?date={plan_date}&feil=publisert", status_code=303)
        with conn:
            conn.execute("DELETE FROM assignments WHERE plan_date = ?", (plan_date.isoformat(),))
            conn.execute("DELETE FROM plan_days WHERE plan_date = ?", (plan_date.isoformat(),))
            applog.log(conn, "plan", f"Utkast slettet: {plan_date:%d.%m.%Y}.")
    finally:
        conn.close()
    return RedirectResponse(f"/plan/dag?date={plan_date}", status_code=303)


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
                applog.log(conn, "plan", f"Plan {plan_date:%d.%m.%Y} endret manuelt.")
    finally:
        conn.close()
    return RedirectResponse(f"/plan/dag?date={plan_date}", status_code=303)


@app.post("/plan/dag/info")
async def plan_day_info(request: Request):
    form = await request.form()
    plan_date = dt.date.fromisoformat(str(form["date"]))
    conn = get_conn()
    try:
        service.set_day_info(conn, plan_date, str(form.get("info", "")))
        applog.write(conn, "plan", f"«Diverse info» for {plan_date:%d.%m.%Y} oppdatert.")
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
            applog.log(conn, "plan", f"Alle rader låst opp: {plan_date:%d.%m.%Y}.")
    finally:
        conn.close()
    return RedirectResponse(f"/plan/dag?date={plan_date}", status_code=303)


@app.get("/plan/ansatt", response_class=HTMLResponse)
def plan_person(request: Request, id: str, fra: str | None = None):
    """One employee's period. Shows placements and heavy-work exposure —
    never preferences or fritak, which are admin-only (D32/D11)."""
    anchor = dt.date.fromisoformat(fra) if fra else local_now().date()
    first = service.monday_of(anchor) - dt.timedelta(days=7)
    last = first + dt.timedelta(days=27)
    conn = get_conn()
    try:
        model = service.build_person_model(conn, id, first, last)
        if model is None:
            return HTMLResponse("Ukjent ansatt", status_code=404)
        model["heavy_hours"] = checks.intensity_hours(conn, id, first, last)
        model["heavy_week"] = checks.week_heavy_counts(
            conn, service.monday_of(anchor)).get(id, 0)
        settings = {row["key"]: row["value"] for row in conn.execute(
            "SELECT key, value FROM planner_settings")}
    finally:
        conn.close()
    model["heavy_cap"] = int(settings.get("heavy_occurrence_hard_cap_per_week", 3))
    model["heavy_target"] = int(settings.get("heavy_occurrence_target_per_week", 1))
    model["anchor"] = anchor
    return TEMPLATES.TemplateResponse(request, "person.html", model)


@app.post("/fravaer/ny")
async def absence_add(request: Request):
    form = await request.form()
    plan_date = dt.date.fromisoformat(str(form["date"]))
    conn = get_conn()
    try:
        absences_mod.register(
            conn,
            employee_id=str(form["employee_id"]),
            date=plan_date,
            absence_type="Fravær",  # no reasons are kept (D76)
            start=str(form.get("start", "")) or None,
            end=str(form.get("end", "")) or None,
            note=str(form.get("note", "")),
        )
        who = conn.execute("SELECT display_name FROM employees WHERE employee_id = ?",
                           (str(form["employee_id"]),)).fetchone()
        applog.write(conn, "fravaer", f"Fravær registrert: {who[0] if who else form['employee_id']} "
                                      f"{plan_date:%d.%m.%Y}.")
    finally:
        conn.close()
    return RedirectResponse(str(form.get("back", f"/plan/dag?date={plan_date}")), status_code=303)


@app.post("/fravaer/slett")
async def absence_delete(request: Request):
    form = await request.form()
    conn = get_conn()
    try:
        absences_mod.remove(conn, int(str(form["absence_id"])))
        applog.write(conn, "fravaer", f"Fravær fjernet (nr. {form['absence_id']}).")
    finally:
        conn.close()
    return RedirectResponse(str(form.get("back", "/")), status_code=303)


# ---------------------------------------------------------------------------
# Admin

def admin_page(request: Request, conn, tab: str, template: str, model: dict):
    """Shared frame for the Administrasjon tabs (D96)."""
    model.update({
        "tab": tab,
        "melding": request.query_params.get("melding"),
        "badge_positions": conn.execute(
            "SELECT COUNT(*) FROM positions WHERE rule = 'uavklart'").fetchone()[0],
        "badge_competency": len(competency.pending_imports(conn)),
    })
    return TEMPLATES.TemplateResponse(request, template, model)


def back(url: str, message: str | None = None) -> RedirectResponse:
    if message:
        anchor = ""
        if "#" in url:
            url, anchor = url.split("#", 1)
            anchor = "#" + anchor
        url = f"{url}{'&' if '?' in url else '?'}melding={quote(message)}{anchor}"
    return RedirectResponse(url, status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    conn = get_conn()
    try:
        return admin_page(request, conn, "innstillinger", "admin_settings.html", {
            "display_theme": service.get_setting(conn, "display_theme", "mork"),
            "retention": hr_import.retention_days(conn),
            "log": applog.entries(conn, limit=300),
        })
    finally:
        conn.close()


@app.get("/admin/stillinger", response_class=HTMLResponse)
def admin_positions_page(request: Request):
    conn = get_conn(refresh=True)
    try:
        functions = list(conn.execute(
            "SELECT * FROM functions WHERE active = 'yes' ORDER BY sort_order"))
        return admin_page(request, conn, "stillinger", "admin_positions.html", {
            "positions": service.positions_model(conn), "all_functions": functions,
            "log": applog.entries(conn, "stilling"),
        })
    finally:
        conn.close()


@app.get("/admin/kompetanse", response_class=HTMLResponse)
def admin_competency(request: Request):
    conn = get_conn(refresh=True)
    try:
        model = competency.matrix(conn)
        model["pending_imports"] = competency.pending_imports(conn)
        model["log"] = applog.entries(conn, "kompetanse")
        return admin_page(request, conn, "kompetanse", "admin_competency.html", model)
    finally:
        conn.close()


@app.post("/admin/kompetanse/lagre")
async def admin_competency_save(request: Request):
    form = await request.form()
    try:
        changes = json.loads(str(form.get("changes", "[]")))
    except json.JSONDecodeError:
        changes = []
    conn = get_conn()
    try:
        applied, conflicts = competency.apply_changes(conn, changes if isinstance(changes, list) else [])
        if applied and not db.is_demo():
            hr_import.rebuild(conn)
    finally:
        conn.close()
    message = f"{applied} endring{'er' if applied != 1 else ''} lagret."
    if conflicts:
        message += " " + " ".join(conflicts[:3]) + (" …" if len(conflicts) > 3 else "")
    return back("/admin/kompetanse", message)


@app.post("/admin/kompetanse/fjern")
async def admin_competency_remove(request: Request):
    form = await request.form()
    conn = get_conn()
    try:
        competency.remove_person(conn, str(form["key"]))
        if not db.is_demo():
            hr_import.rebuild(conn)
    finally:
        conn.close()
    return back("/admin/kompetanse", "Kompetansen er fjernet.")


@app.post("/admin/kompetanse/last-opp")
async def admin_competency_upload(request: Request):
    form = await request.form()
    upload = form.get("fil")
    name = Path(getattr(upload, "filename", "") or "").name
    if not name.lower().endswith(".xlsx"):
        return back("/admin/kompetanse", "Velg en Excel-fil (.xlsx).")
    raw = await upload.read()
    conn = get_conn()
    try:
        with conn:
            import_id = competency.stage(conn, name, raw)
    except Rejected as exc:
        return back("/admin/kompetanse", "Filen kan ikke leses: " + " ".join(exc.reasons))
    finally:
        conn.close()
    return RedirectResponse(f"/admin/kompetanse/import/{import_id}", status_code=303)


@app.get("/admin/kompetanse/import/{import_id}", response_class=HTMLResponse)
def admin_competency_review(request: Request, import_id: int):
    conn = get_conn()
    try:
        try:
            model = competency.review(conn, import_id)
        except KeyError:
            return back("/admin/kompetanse", "Fant ikke importen.")
        model["words"] = competency.WORDS
        model["feil"] = request.query_params.getlist("feil")
        return admin_page(request, conn, "kompetanse", "competency_review.html", model)
    finally:
        conn.close()


@app.post("/admin/kompetanse/import/{import_id}/koble")
async def admin_competency_link(request: Request, import_id: int):
    form = await request.form()
    choices = {}
    for key in [k for k in form.keys() if k.startswith("alias_")]:
        index = key.split("_", 1)[1]
        choices[str(form[key])] = str(form.get(f"target_{index}", ""))
    conn = get_conn()
    try:
        problems = competency.save_links(conn, choices)
    finally:
        conn.close()
    url = f"/admin/kompetanse/import/{import_id}"
    if problems:
        url += "?" + "&".join(f"feil={quote(p)}" for p in problems)
    return RedirectResponse(url, status_code=303)


@app.post("/admin/kompetanse/import/{import_id}/bruk")
async def admin_competency_apply(request: Request, import_id: int):
    form = await request.form()
    conn = get_conn()
    try:
        written = competency.apply_import(conn, import_id, bool(form.get("overskriv_konflikter")))
        if not db.is_demo():
            hr_import.rebuild(conn)
    finally:
        conn.close()
    return back("/admin/kompetanse", f"Importen er tatt i bruk – {written} celler oppdatert.")


@app.post("/admin/kompetanse/import/{import_id}/forkast")
async def admin_competency_discard(request: Request, import_id: int):
    conn = get_conn()
    try:
        competency.discard_import(conn, import_id)
        if not db.is_demo():
            hr_import.rebuild(conn)
    finally:
        conn.close()
    return back("/admin/kompetanse", "Filen er forkastet – ingenting ble endret.")


@app.get("/admin/kompetanse/skjema.xlsx")
def admin_competency_form():
    conn = get_conn()
    try:
        data = competency.build_form(conn)
    finally:
        conn.close()
    stamp = local_now().strftime("%Y%m%d")
    return Response(
        data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="Kompetanse_utfylling_{stamp}.xlsx"'})


@app.get("/admin/vaktkoder", response_class=HTMLResponse)
def admin_codes(request: Request):
    conn = get_conn(refresh=True)
    try:
        return admin_page(request, conn, "vaktkoder", "admin_codes.html", {
            "learned": list(conn.execute("SELECT * FROM learned_shift_codes ORDER BY code")),
            "shift_codes": list(conn.execute("SELECT * FROM shift_codes WHERE code <> 'MAN' ORDER BY code")),
            "rotation_rules": list(conn.execute("SELECT * FROM rotation_rules")),
            "categories": service.SHIFT_CATEGORY_ORDER,
            "log": applog.entries(conn, "vaktkode"),
        })
    finally:
        conn.close()


@app.get("/admin/grunndata", response_class=HTMLResponse)
def admin_master(request: Request):
    conn = get_conn()
    try:
        return admin_page(request, conn, "grunndata", "admin_master.html", {
            "functions": list(conn.execute(
                """SELECT f.*, z.name AS zone_name FROM functions f
                   JOIN zones z ON z.zone_id = f.zone_id ORDER BY f.sort_order""")),
            "intensity": list(conn.execute(
                """SELECT i.*, f.name AS function_name FROM function_intensity i
                   JOIN functions f ON f.function_id = i.function_id ORDER BY f.sort_order""")),
            "settings": list(conn.execute("SELECT * FROM planner_settings ORDER BY key")),
            "preferences": list(conn.execute(
                """SELECT p.employee_id, e.display_name, f.name AS function_name, p.note
                   FROM employee_preferences p
                   JOIN employees e ON e.employee_id = p.employee_id
                   JOIN functions f ON f.function_id = p.function_id ORDER BY p.employee_id""")),
            "restrictions": list(conn.execute(
                """SELECT r.*, e.display_name, f.name AS function_name
                   FROM employee_restrictions r
                   JOIN employees e ON e.employee_id = r.employee_id
                   LEFT JOIN functions f ON f.function_id = r.function_id
                   ORDER BY r.employee_id""")),
        })
    finally:
        conn.close()


@app.post("/admin/innstillinger")
async def admin_settings(request: Request):
    """Admin-set app preferences: the wall board's palette and how long past
    data is kept (D94)."""
    form = await request.form()
    theme = str(form.get("display_theme", "mork"))
    conn = get_conn()
    try:
        theme = theme if theme in ("lys", "mork") else "mork"
        if theme != service.get_setting(conn, "display_theme", "mork"):
            service.set_setting(conn, "display_theme", theme)
            applog.write(conn, "innstilling", f"Tavlens fargevisning satt til «{theme}».")
        retention = str(form.get("retention_days", "")).strip()
        if (retention.isdigit() and 14 <= int(retention) <= 730
                and int(retention) != hr_import.retention_days(conn)):
            service.set_setting(conn, "retention_days", retention)
            applog.write(conn, "innstilling", f"Data beholdes i {retention} dager.")
    finally:
        conn.close()
    return back("/admin", "Innstillingene er lagret.")


@app.post("/admin/stillinger")
async def admin_positions(request: Request):
    """Classify job titles once (D87): planned normally, never, or not on
    some functions. Rebuilds the roster so held days are released at once."""
    form = await request.form()
    conn = get_conn()
    try:
        with conn:
            for key in [k for k in form.keys() if k.startswith("title_")]:
                index = key.split("_", 1)[1]
                title = str(form[key])
                rule = str(form.get(f"rule_{index}", "uavklart"))
                if rule not in ("vanlig", "aldri", "begrenset", "uavklart"):
                    continue
                current = conn.execute("SELECT rule FROM positions WHERE title = ?",
                                       (title,)).fetchone()
                if current is None:
                    continue
                if current["rule"] != rule:
                    conn.execute("UPDATE positions SET rule = ?, classified_at = ? WHERE title = ?",
                                 (rule, local_now().isoformat(timespec="seconds"), title))
                    hr_import.log(conn, f"Stillingen «{title}» satt til «{rule}».", "stilling")
                conn.execute("DELETE FROM position_exclusions WHERE title = ?", (title,))
                if rule == "begrenset":
                    conn.executemany(
                        "INSERT INTO position_exclusions (title, function_id) VALUES (?, ?)",
                        [(title, str(f)) for f in form.getlist(f"excl_{index}")])
        if not db.is_demo():
            hr_import.rebuild(conn)
    finally:
        conn.close()
    return back("/admin/stillinger", "Stillingene er lagret.")


@app.post("/admin/vaktkoder")
async def admin_learned_codes(request: Request):
    """Confirm (or correct) the category of codes learned from a turnus."""
    form = await request.form()
    allowed = set(service.SHIFT_CATEGORY_ORDER)
    conn = get_conn()
    try:
        with conn:
            for key in [k for k in form.keys() if k.startswith("code_")]:
                index = key.split("_", 1)[1]
                code = str(form[key])
                category = str(form.get(f"category_{index}", ""))
                if category not in allowed:
                    continue
                conn.execute("UPDATE learned_shift_codes SET category = ?, confirmed = 1 "
                             "WHERE code = ?", (category, code))
                applog.log(conn, "vaktkode", f"Vaktkoden {code} bekreftet som {category}.")
                conn.execute("UPDATE shift_codes SET category = ? WHERE code = ? AND code IN "
                             "(SELECT code FROM learned_shift_codes)", (category, code))
        if not db.is_demo():
            hr_import.rebuild(conn)
    finally:
        conn.close()
    return back("/admin/vaktkoder", "Kategoriene er bekreftet.")


# ---------------------------------------------------------------------------
# Data sources: imported turnus and ukeplan files (real mode)

@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request, melding: str | None = None):
    conn = get_conn(refresh=True)
    try:
        model = service.build_import_model(conn, domain.operational_day(local_now()))
        model["retention"] = hr_import.retention_days(conn)
    finally:
        conn.close()
    model["last_refresh"] = hr_import.last_refresh()
    model["last_error"] = hr_import.last_error
    model["inbox"] = hr_import.INBOX
    model["melding"] = melding
    return TEMPLATES.TemplateResponse(request, "import.html", model)


@app.post("/import/manuell-tid")
async def import_manual_time(request: Request):
    """A manager gives a held day (unknown code such as DX) its times."""
    form = await request.form()
    start, end = str(form.get("start", "")), str(form.get("end", ""))
    ok = True
    try:
        domain.parse_time(start)
        domain.parse_time(end)
    except ValueError:
        ok = False
    if not ok or start == end:
        return back("/import#ventende", "Oppgi gyldig start- og sluttid.")
    conn = get_conn()
    try:
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO manual_shift_times
                   (employee_id, export_date, raw, start, end, entered_at) VALUES (?, ?, ?, ?, ?, ?)""",
                (str(form["employee_id"]), str(form["date"]), str(form["raw"]), start, end,
                 local_now().isoformat(timespec="seconds")))
            name = conn.execute("SELECT display_name FROM employees WHERE employee_id = ?",
                                (str(form["employee_id"]),)).fetchone()
            applog.log(conn, "import", f"Tid angitt for {name[0] if name else form['employee_id']} "
                                       f"{form['date']} («{form['raw']}»): {start}–{end}.")
        hr_import.rebuild(conn)
    finally:
        conn.close()
    return back("/import#ventende", "Tiden er lagret – vakten tas med i planleggingen.")


@app.post("/import/manuell-tid/slett")
async def import_manual_time_delete(request: Request):
    form = await request.form()
    conn = get_conn()
    try:
        with conn:
            conn.execute("DELETE FROM manual_shift_times WHERE employee_id = ? AND export_date = ?",
                         (str(form["employee_id"]), str(form["date"])))
            applog.log(conn, "import", f"Angitt tid fjernet ({form['employee_id']} {form['date']}).")
        hr_import.rebuild(conn)
    finally:
        conn.close()
    return back("/import#ventende", "Den angitte tiden er fjernet.")


@app.post("/import/sjekk")
async def import_check(request: Request):
    conn = get_conn()
    try:
        messages = hr_import.refresh(conn, force=True)
    finally:
        conn.close()
    note = "ingen nye filer" if not messages else f"{len(messages)} fil(er) behandlet"
    return RedirectResponse(f"/import?melding={note}", status_code=303)


@app.post("/import/last-opp")
async def import_upload(request: Request):
    """Put uploaded files in data/import/ — exactly as if copied there — and
    process them right away."""
    form = await request.form()
    saved = 0
    if not db.is_demo():
        hr_import.INBOX.mkdir(parents=True, exist_ok=True)
        for upload in form.getlist("filer"):
            name = Path(getattr(upload, "filename", "") or "").name
            if not name or Path(name).suffix.lower() not in (".csv", ".xlsx"):
                continue
            target = hr_import.INBOX / name
            target.write_bytes(await upload.read())
            past = time_module.time() - 10   # so the inbox doesn't take it as still copying
            os.utime(target, (past, past))
            saved += 1
    conn = get_conn()
    try:
        hr_import.refresh(conn, force=True)
    finally:
        conn.close()
    return RedirectResponse(f"/import?melding={saved} fil(er) lastet opp", status_code=303)

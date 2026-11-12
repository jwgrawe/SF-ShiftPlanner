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
from app import applog, checks, competency, contingency, db, domain, exposure, hr_import, planner, roster_changes, rules, service, shift_codes
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
_STATIC = Path(__file__).parent / "static"
TEMPLATES.env.globals["static_version"] = max(
    (int(p.stat().st_mtime) for p in _STATIC.glob("*.*")), default=0)
TEMPLATES.env.globals["is_demo"] = db.is_demo
TEMPLATES.env.globals["kind_label"] = hr_import.kind_label


def _unknown_shift_count() -> int:
    """Open unknown-code days (D101), for the badge in the menu."""
    if db.is_demo():
        return 0
    try:
        conn = db.get_conn()
        try:
            db.init_schema(conn)
            return service.unknown_shift_count(conn, domain.operational_day(local_now()))
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - a badge must never break a page
        return 0


TEMPLATES.env.globals["unknown_shift_count"] = _unknown_shift_count

app = FastAPI(title="SF-Planlegger", docs_url=None, redoc_url=None)
app.mount(
    "/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static"
)


# --------------------------------------------------------------------------
# The board window (D120): a browser that opened /tavle is «the board» and is
# only ever shown the board – whatever is clicked or typed there. The admin
# browser never has this cookie (the kiosk window has its own profile).
BOARD_COOKIE = "sf_tavle"


def _board_path(path: str) -> bool:
    return path == "/display" or path.startswith("/static/") or path.startswith("/tavle")


@app.middleware("http")
async def board_lock(request: Request, call_next):
    if request.cookies.get(BOARD_COOKIE) == "1" and not _board_path(request.url.path):
        return RedirectResponse("/display", status_code=303)
    return await call_next(request)


@app.get("/tavle")
def board_mode():
    """Make this browser the board (the kiosk window opens this)."""
    response = RedirectResponse("/display", status_code=303)
    response.set_cookie(BOARD_COOKIE, "1", max_age=10 * 365 * 24 * 3600, httponly=True, samesite="strict")
    return response


@app.get("/tavle/av")
def board_mode_off():
    """Undo /tavle in a browser that got it by mistake."""
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(BOARD_COOKIE)
    return response


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
        model["worked_hours"] = exposure.worked(conn, first, last).get(id, 0.0)
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
        "badge_codes": shift_codes.attention(conn, local_now().date()),
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
    if not name.lower().endswith((".xlsx", ".csv")):
        return back("/admin/kompetanse", "Velg en Excel-fil (.xlsx) eller en CSV-fil (.csv).")
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
        model = shift_codes.overview(conn, local_now().date())
        model.update({
            "kinds": shift_codes.KINDS,
            "kind_help": shift_codes.KIND_HELP,
            "categories": service.SHIFT_CATEGORY_ORDER,
            "category_labels": service.SHIFT_CATEGORY_LABELS,
            "log": applog.entries(conn, "vaktkode"),
        })
        return admin_page(request, conn, "vaktkoder", "admin_codes.html", model)
    finally:
        conn.close()


def _codes_action(action) -> RedirectResponse:
    """Run one change to the shift-code list, rebuild the roster (real mode)
    and go back with the outcome."""
    conn = get_conn()
    try:
        try:
            message = action(conn)
        except shift_codes.Invalid as error:
            return back("/admin/vaktkoder", f"Ikke lagret: {error}")
        if not db.is_demo():
            hr_import.rebuild(conn)
    finally:
        conn.close()
    return back("/admin/vaktkoder", message)


@app.post("/admin/vaktkoder/lagre")
async def admin_codes_save(request: Request):
    form = {k: str(v) for k, v in (await request.form()).items()}
    return _codes_action(lambda conn: shift_codes.save(conn, form))


@app.post("/admin/vaktkoder/bekreft")
async def admin_codes_confirm(request: Request):
    codes = [str(c) for c in (await request.form()).getlist("code")]
    return _codes_action(lambda conn: f"{shift_codes.confirm(conn, codes)} vaktkode(r) bekreftet.")


@app.post("/admin/vaktkoder/bruk-turnus")
async def admin_codes_use_turnus(request: Request):
    code = str((await request.form()).get("code", ""))
    return _codes_action(lambda conn: shift_codes.use_turnus_time(conn, code))


@app.post("/admin/vaktkoder/behold")
async def admin_codes_keep(request: Request):
    code = str((await request.form()).get("code", ""))
    return _codes_action(lambda conn: shift_codes.keep_app_time(conn, code))


@app.post("/admin/vaktkoder/fjern")
async def admin_codes_delete(request: Request):
    code = str((await request.form()).get("code", ""))
    return _codes_action(lambda conn: shift_codes.delete(conn, code))


@app.post("/admin/vaktkoder/gjenopprett")
async def admin_codes_restore(request: Request):
    code = str((await request.form()).get("code", ""))
    return _codes_action(lambda conn: shift_codes.restore(conn, code))


@app.get("/admin/vaktkoder.csv")
def admin_codes_csv():
    conn = get_conn()
    try:
        data = shift_codes.export_csv(conn)
    finally:
        conn.close()
    stamp = local_now().strftime("%Y%m%d")
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="Vaktkoder_{stamp}.csv"'})


@app.get("/admin/regler", response_class=HTMLResponse)
def admin_rules(request: Request):
    conn = get_conn()
    try:
        model = rules.overview(conn)
        model["avvik"] = contingency.overview(conn)
        model["log"] = applog.entries(conn, "regler")
        return admin_page(request, conn, "regler", "admin_rules.html", model)
    finally:
        conn.close()


def _rules_action(action, anchor: str = "") -> RedirectResponse:
    conn = get_conn()
    try:
        try:
            message = action(conn)
        except (rules.Invalid, contingency.Invalid) as error:
            return back(f"/admin/regler{anchor}", f"Ikke lagret: {error}")
    finally:
        conn.close()
    if message != "Ingen endringer.":
        message += " Gjelder nye forslag – lag forslag på nytt for dager som alt er planlagt."
    return back(f"/admin/regler{anchor}", message)


@app.post("/admin/regler/bytte")
async def admin_rules_swap(request: Request):
    form = await request.form()
    return _rules_action(lambda conn: rules.save_swap(conn, form), "#bytte")


@app.post("/admin/regler/bytte/fjern")
async def admin_rules_swap_delete(request: Request):
    swap_id = str((await request.form()).get("swap_id", ""))
    return _rules_action(lambda conn: rules.delete_swap(conn, swap_id), "#bytte")


@app.post("/admin/regler/rullering")
async def admin_rules_rotation(request: Request):
    form = await request.form()
    return _rules_action(lambda conn: rules.save_rotation(conn, form), "#tidspunkt")


@app.post("/admin/regler/innstillinger")
async def admin_rules_settings(request: Request):
    form = await request.form()
    return _rules_action(lambda conn: rules.save_settings(conn, form), "#tungt")


@app.post("/admin/regler/avvik")
async def admin_rules_contingency(request: Request):
    form = await request.form()
    return _rules_action(lambda conn: contingency.save(conn, form), "#avvik")


@app.post("/admin/regler/standard")
async def admin_rules_reset(request: Request):
    return _rules_action(rules.reset)


@app.get("/admin/grunndata", response_class=HTMLResponse)
def admin_master(request: Request):
    conn = get_conn()
    try:
        return admin_page(request, conn, "grunndata", "admin_master.html", {
            "functions": list(conn.execute(
                """SELECT f.*, z.name AS zone_name FROM functions f
                   JOIN zones z ON z.zone_id = f.zone_id ORDER BY f.sort_order""")),
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
        window = exposure.settings(conn)["window_days"]
        if retention.isdigit() and 14 <= int(retention) <= 730 and int(retention) <= window:
            # The «utjevningsvindu» counts past plans, so they must still exist (D110).
            return back("/admin", f"Ikke lagret: data må beholdes lenger enn utjevningsvinduet "
                                  f"({window} dager, under Planregler).")
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


# ---------------------------------------------------------------------------
# Data sources: imported turnus and ukeplan files (real mode)

@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request, melding: str | None = None):
    conn = get_conn(refresh=True)
    try:
        model = service.build_import_model(conn, domain.operational_day(local_now()))
        model["retention"] = hr_import.retention_days(conn)
        model["roster_changes"] = roster_changes.active_count(conn, domain.operational_day(local_now()))
    finally:
        conn.close()
    model["last_refresh"] = hr_import.last_refresh()
    model["last_error"] = hr_import.last_error
    model["inbox"] = hr_import.INBOX
    model["melding"] = melding
    return TEMPLATES.TemplateResponse(request, "import.html", model)


def _shift_time(start: str, end: str) -> tuple[str, str]:
    """Typed times for a per-shift code: forgiving format, whole or half
    hours (R9). Raises ValueError with the reason."""
    try:
        s, e = domain.parse_clock(start), domain.parse_clock(end)
    except ValueError:
        raise ValueError("start og slutt må være klokkeslett") from None
    if s.minute % 30 or e.minute % 30:
        raise ValueError("bruk hele eller halve timer")
    if s == e:
        raise ValueError("start og slutt kan ikke være like")
    return s.strftime("%H:%M"), e.strftime("%H:%M")


@app.post("/import/manuell-tid")
async def import_manual_time(request: Request):
    """A manager gives a held day (unknown code such as DX) its times."""
    form = await request.form()
    try:
        start, end = _shift_time(str(form.get("start", "")), str(form.get("end", "")))
    except ValueError as error:
        return back("/import#ventende", f"Ikke lagret: {error}.")
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
            name = conn.execute("SELECT display_name FROM employees WHERE employee_id = ?",
                                (str(form["employee_id"]),)).fetchone()
            applog.log(conn, "import", f"Angitt tid fjernet for {name[0] if name else form['employee_id']} "
                                       f"{form['date']} – vakten må få tid på nytt.")
        hr_import.rebuild(conn)
    finally:
        conn.close()
    return back(str(form.get("back", "/import/ukjente")), "Den angitte tiden er fjernet.")


@app.get("/import/endringer", response_class=HTMLResponse)
def roster_changes_page(request: Request, tidligere: str | None = None):
    """Changes on the floor (D119): win over turnus and ukeplan."""
    conn = get_conn(refresh=True)
    try:
        model = roster_changes.model(conn, domain.operational_day(local_now()), show_past=bool(tidligere))
        model["log"] = applog.entries(conn, "vaktliste")
    finally:
        conn.close()
    model["melding"] = request.query_params.get("melding")
    return TEMPLATES.TemplateResponse(request, "roster_changes.html", model)


def _roster_change(action, back_url: str) -> RedirectResponse:
    if db.is_demo():
        return back(back_url, "I demoen er vaktlisten fast – endringer gjøres i den ekte planleggeren.")
    conn = get_conn()
    try:
        try:
            message = action(conn)
        except roster_changes.Invalid as error:
            return back(back_url, f"Ikke lagret: {error}")
        hr_import.rebuild(conn)
    finally:
        conn.close()
    return back(back_url, message)


@app.post("/import/endringer/lagre")
async def roster_changes_save(request: Request):
    form = await request.form()
    return _roster_change(lambda conn: roster_changes.save(conn, form), str(form.get("back") or "/import/endringer"))


@app.post("/import/endringer/fjern")
async def roster_changes_remove(request: Request):
    form = await request.form()
    return _roster_change(lambda conn: roster_changes.remove(conn, str(form.get("employee_id", "")),
                                                             str(form.get("date", ""))),
                          str(form.get("back") or "/import/endringer"))


@app.get("/import/ukjente", response_class=HTMLResponse)
def unknown_shifts_page(request: Request, tidligere: str | None = None):
    """Days with a code the app doesn't know (temps' DX/AX): one card per
    person, each day with the person's week for context (D101)."""
    conn = get_conn(refresh=True)
    try:
        model = service.unknown_shifts_model(conn, domain.operational_day(local_now()),
                                             show_past=bool(tidligere))
    finally:
        conn.close()
    model["melding"] = request.query_params.get("melding")
    return TEMPLATES.TemplateResponse(request, "unknown_shifts.html", model)


@app.post("/import/ukjente/lagre")
async def unknown_shifts_save(request: Request):
    """Save the times entered on one person's card: only rows with both
    times, and only those that changed."""
    form = await request.form()
    employee_id = str(form["employee_id"])
    rows, problems = [], []
    for key in [k for k in form.keys() if k.startswith("date_")]:
        i = key.split("_", 1)[1]
        start, end = str(form.get(f"start_{i}", "")).strip(), str(form.get(f"end_{i}", "")).strip()
        if not start and not end:
            continue
        day = str(form[key])
        try:
            start, end = _shift_time(start, end)
        except ValueError as error:
            problems.append(f"{dt.date.fromisoformat(day):%d.%m} ({error})")
            continue
        if (start, end) == (str(form.get(f"old_start_{i}", "")), str(form.get(f"old_end_{i}", ""))):
            continue
        rows.append((employee_id, day, str(form.get(f"raw_{i}", "")), start, end))
    conn = get_conn()
    try:
        if rows:
            name = conn.execute("SELECT display_name FROM employees WHERE employee_id = ?",
                                (employee_id,)).fetchone()
            label = name[0] if name else employee_id
            with conn:
                for eid, day, raw, start, end in rows:
                    conn.execute(
                        """INSERT OR REPLACE INTO manual_shift_times
                           (employee_id, export_date, raw, start, end, entered_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (eid, day, raw, start, end, local_now().isoformat(timespec="seconds")))
                    applog.log(conn, "import", f"Tid angitt for {label} {day} («{raw}»): {start}–{end}.")
            hr_import.rebuild(conn)
    finally:
        conn.close()
    if problems:
        message = f"{len(rows)} lagret. Sjekk {', '.join(problems)}."
    elif rows:
        message = f"{len(rows)} vakt{'er' if len(rows) != 1 else ''} fikk tid og tas med i planleggingen."
    else:
        message = "Ingen endringer å lagre."
    return back("/import/ukjente", message)


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

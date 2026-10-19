#!/usr/bin/env python3
"""Start SF-Planlegger — no virtual environment and no admin rights required.

Usage:  python run.py           the real planner (imports from data/import/)
        python run.py --demo    the demo with fictional staff (for presentations)
        options: [--port 8000] [--no-browser]

Works from any current directory (it anchors itself to the folder this file
lives in). Each mode has its own database (D89), so demo people never mix
with real ones. Opens the browser and starts the server. Stop with Ctrl+C.
"""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--demo", action="store_true",
                        help="start the demo (fictional staff, own database)")
    parser.add_argument("--check-deps", action="store_true",
                        help="exit 0 if all dependencies are installed, 1 otherwise")
    args = parser.parse_args()

    import importlib.util

    required = {
        "fastapi": ("fastapi",), "uvicorn": ("uvicorn",), "jinja2": ("jinja2",),
        "openpyxl": ("openpyxl",),
        "python-multipart": ("multipart", "python_multipart"),
    }
    missing = [
        package
        for package, modules in required.items()
        if all(importlib.util.find_spec(module) is None for module in modules)
    ]
    # tzdata is only needed where the OS has no tz database (i.e. Windows).
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Europe/Oslo")
    except Exception:
        if importlib.util.find_spec("tzdata") is None:
            missing.append("tzdata")
    if missing:
        raise SystemExit(
            f"Avhengigheter mangler ({', '.join(missing)}). Kjør først:\n"
            "  python -m pip install --user -r requirements.txt"
        )
    if args.check_deps:
        return
    import uvicorn

    from app import db, demo, hr_import
    from app.importer import import_seed

    moved = db.migrate_legacy_demo_db()
    if moved:
        print(moved)
    db.set_mode("demo" if args.demo else "real")

    # Master data is re-imported from data/seed/ on every start, so a
    # `git pull` that changes the seed tables takes effect immediately.
    # Runtime data (roster, plans, absences, imports) is never touched by
    # this; in real mode neither are the people tables (D89).
    conn = db.get_conn()
    db.init_schema(conn)
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with conn:
            import_seed(conn, people=db.is_demo())
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    if db.is_demo():
        demo.ensure(conn)
    else:
        hr_import.INBOX.mkdir(parents=True, exist_ok=True)
        for message in hr_import.refresh(conn, force=True):
            print(message)
    conn.close()

    from app.main import app as fastapi_app

    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    mode = "DEMO (fiktive ansatte)" if db.is_demo() else "ekte data fra data/import/"
    print(f"SF-Planlegger kjører på {url} – {mode}  (stopp med Ctrl+C)")
    uvicorn.run(fastapi_app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

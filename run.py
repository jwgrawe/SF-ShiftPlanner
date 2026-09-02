#!/usr/bin/env python3
"""Start SF-Planlegger — no virtual environment and no admin rights required.

Usage:  python run.py  [--port 8000] [--no-browser]

Works from any current directory (it anchors itself to the folder this file
lives in). On first run it prepares the database (seed import + demo week),
then opens the browser and starts the server. Stop with Ctrl+C.
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
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        raise SystemExit(
            "Avhengigheter mangler. Kjør først:\n"
            "  python -m pip install --user -r requirements.txt"
        )

    from app import db

    if not db.DEFAULT_DB_PATH.exists():
        print("Første oppstart: importerer grunndata og lager demo-uke ...")
        conn = db.get_conn()
        db.init_schema(conn)
        from app.importer import import_seed

        with conn:
            import_seed(conn)
        conn.close()
        from scripts.make_demo_data import main as make_demo_data

        make_demo_data()

    from app.main import app as fastapi_app

    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    print(f"SF-Planlegger kjører på {url}  (stopp med Ctrl+C)")
    uvicorn.run(fastapi_app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

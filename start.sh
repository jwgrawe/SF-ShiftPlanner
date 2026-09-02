#!/usr/bin/env bash
# SF-Planlegger — start the prototype on Linux/macOS.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
    echo "Forbereder første gangs oppstart..."
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
    .venv/bin/python -m app.importer
    .venv/bin/python scripts/make_demo_data.py
fi
echo "Åpne http://127.0.0.1:8000/ i nettleseren."
exec .venv/bin/python -m uvicorn app.main:app --port 8000

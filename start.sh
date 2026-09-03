#!/usr/bin/env bash
# SF-Planlegger — start the prototype (no venv, no admin rights required).
set -e
cd "$(dirname "$0")"
python3 -c "import fastapi, uvicorn, jinja2, openpyxl, tzdata" 2>/dev/null || {
    echo "Installerer avhengigheter til brukerprofilen..."
    python3 -m pip install --user -r requirements.txt
}
exec python3 run.py

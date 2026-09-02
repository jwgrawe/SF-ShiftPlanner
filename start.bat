@echo off
rem SF-Planlegger - start the prototype on Windows (no admin rights needed).
rem First time: creates a virtual environment and installs dependencies.
cd /d "%~dp0"
if not exist .venv (
    echo Forbereder foerste gangs oppstart...
    python -m venv .venv
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\python -m pip install -r requirements.txt
    .venv\Scripts\python -m app.importer
    .venv\Scripts\python scripts\make_demo_data.py
)
start "" http://127.0.0.1:8000/
.venv\Scripts\python -m uvicorn app.main:app --port 8000

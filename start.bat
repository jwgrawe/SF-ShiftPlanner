@echo off
rem SF-Planlegger - start prototypen. Krever verken administratorrettigheter
rem eller virtuelle miljoer: pakker installeres til brukerprofilen (pip --user).
cd /d "%~dp0"
python run.py --check-deps 2>nul
if errorlevel 1 (
    echo Installerer avhengigheter til brukerprofilen...
    python -m pip install --user -r requirements.txt
)
python run.py
pause

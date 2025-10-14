@echo off
setlocal enabledelayedexpansion

REM === Go to repo root ===
cd /d "%~dp0"

REM === Use UTF-8 in console (Windows) ===
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

REM === Create venv if missing ===
if not exist ".venv\Scripts\python.exe" (
    echo [*] Creating virtual environment...
    py -3 -m venv .venv
)

REM === Activate venv ===
call ".venv\Scripts\activate.bat"

REM === Upgrade pip and install deps ===
python -m pip install --upgrade pip
pip install -r requirements.txt

REM === Run bot ===
echo [*] Starting Say QUIZ Bot...
python bot.py

REM === Keep window open if something failed ===
if errorlevel 1 (
    echo.
    echo [!] Bot exited with errors. Press any key to close.
    pause >nul
)

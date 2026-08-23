@echo off
REM ================================================================
REM   LLM Local Setup Launcher (GUI)
REM
REM   Default mode: Tkinter GUI.
REM   If tkinter is unavailable or GUI init fails, falls back to TUI.
REM   Terminal mode: python -m launcher --tui
REM ================================================================
chcp 65001 >nul
cd /d "%~dp0"

REM -- Prefer the program's managed Python when available --
set "PYW=%~dp0llm_environment\venv\Scripts\pythonw.exe"
set "PY=%~dp0llm_environment\venv\Scripts\python.exe"
if exist "%PYW%" (
    start "" "%PYW%" -m launcher
    exit /b 0
)
if exist "%PY%" (
    "%PY%" -m launcher
    if errorlevel 1 pause
    exit /b %errorlevel%
)

REM -- Fallback for first-run diagnostics --
where pythonw.exe >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw.exe -m launcher
    exit /b 0
)
python -m launcher
if errorlevel 1 pause

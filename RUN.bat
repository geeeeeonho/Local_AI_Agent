@echo off
REM ================================================================
REM   LLM Local Setup Launcher (GUI)
REM
REM   Default mode: Tkinter GUI.
REM   If tkinter is unavailable or GUI init fails, falls back to TUI.
REM
REM   To force terminal mode, run RUN_TUI.bat instead.
REM ================================================================
chcp 65001 >nul
cd /d "%~dp0"

REM -- Use pythonw.exe (no console window) if available --
where pythonw.exe >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw.exe -m launcher
    exit /b 0
)

REM -- Fallback: regular python (console stays visible) --
python -m launcher
if errorlevel 1 pause

@echo off
REM LLM Local Setup Launcher (terminal mode)
chcp 65001 >nul
cd /d "%~dp0"

set "PY=%~dp0llm_environment\venv\Scripts\python.exe"
if exist "%PY%" (
    "%PY%" -m launcher --tui %*
    if errorlevel 1 pause
    exit /b %errorlevel%
)

python -m launcher --tui %*
if errorlevel 1 pause

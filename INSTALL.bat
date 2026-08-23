@echo off
REM LLM Local Setup Installer
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python 3 is required to run the installer.
    pause
    exit /b 1
)

python -m installer %*
if errorlevel 1 pause

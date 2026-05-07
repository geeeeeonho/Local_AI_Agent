@echo off
REM ============================================================
REM   LLM Local Setup - Installer
REM
REM   This file uses ASCII-only text and chcp 65001 to be safe
REM   against any zip extraction codepage mismatches.
REM   Do NOT save with BOM. Save as plain ANSI/UTF-8.
REM ============================================================
chcp 65001 >nul 2>&1

setlocal EnableDelayedExpansion

title LLM Environment - Install
cd /d "%~dp0"

echo.
echo Starting LLM Environment Installer...
echo Working directory: %CD%
echo.

REM ----- Read saved language (best effort) -----
set "UI_LANG=en"
set "CONFIG_FILE=launcher\settings\user_config.json"
if exist "%CONFIG_FILE%" (
    findstr /C:"\"language\": \"ko\"" "%CONFIG_FILE%" >nul 2>&1 && set "UI_LANG=ko"
)

REM ----- Docker detect -----
set "DOCKER_OK=0"
call :detect_docker

echo ============================================
echo   LLM Local Setup - Installer
echo ============================================
echo.

REM ----- Python -----
echo [1/3] Checking Python...
where python >nul 2>&1
if errorlevel 1 goto python_missing

python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 goto python_old

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
echo [OK] Python !PY_VER!
echo.

REM ----- Docker -----
echo [2/3] Checking Docker...
if "%DOCKER_OK%"=="1" (
    echo [OK] Docker running
) else (
    echo [WARN] Docker not available - continuing without it
    echo        Sandbox agent and SearXNG will be skipped.
)
echo.

REM ----- Sanity: required folders -----
if not exist "installer\__main__.py" (
    echo [ERROR] Cannot find installer package next to this BAT file.
    echo         Make sure you extracted the entire archive without renaming folders.
    echo         Current dir: %CD%
    pause
    exit /b 1
)

REM ----- Install -----
echo [3/3] Running installer...
echo.

if "%DOCKER_OK%"=="1" (
    python -m installer --lang %UI_LANG%
) else (
    python -m installer --skip-sandbox --skip-search --lang %UI_LANG%
)
set "PY_RC=%ERRORLEVEL%"

if not "%PY_RC%"=="0" (
    echo.
    echo [ERROR] Installation failed (rc=%PY_RC%)
    echo         See messages above for details.
    pause
    exit /b 1
)

echo.
echo Installation complete.
echo Run RUN.bat next.
pause
exit /b 0


REM ============================================================
REM   Subroutine: Docker detection
REM   Sets DOCKER_OK=1 on success, =0 on failure.
REM ============================================================

:detect_docker
set "DOCKER_OK=0"

REM 1) docker on PATH
docker --version >nul 2>&1
if not errorlevel 1 (
    docker info >nul 2>&1
    if not errorlevel 1 (
        set "DOCKER_OK=1"
        goto :eof
    )
)

REM 2) Default Docker Desktop install path
set "DOCKER_EXE=C:\Program Files\Docker\Docker\resources\bin\docker.exe"
if exist "%DOCKER_EXE%" (
    "%DOCKER_EXE%" --version >nul 2>&1
    if not errorlevel 1 (
        "%DOCKER_EXE%" info >nul 2>&1
        if not errorlevel 1 (
            set "DOCKER_OK=1"
            goto :eof
        )
    )
)

REM 3) Try to start Docker Desktop and wait up to ~60 seconds
if exist "C:\Program Files\Docker\Docker\Docker Desktop.exe" (
    echo [INFO] Starting Docker Desktop...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"

    set /a WAIT_COUNT=0

    :wait_loop
    timeout /t 3 /nobreak >nul
    docker info >nul 2>&1
    if not errorlevel 1 (
        set "DOCKER_OK=1"
        echo [OK] Docker is running
        goto :eof
    )

    set /a WAIT_COUNT+=1
    if !WAIT_COUNT! LSS 20 goto wait_loop
)

echo [WARN] Docker not available
goto :eof


:python_missing
echo [ERROR] Python not found in PATH.
echo         Install Python 3.11+ from https://www.python.org/downloads/
echo         IMPORTANT: Tick "Add Python to PATH" during installation.
pause
exit /b 1

:python_old
echo [ERROR] Python is too old. Need 3.11 or newer.
echo         Reinstall Python from https://www.python.org/downloads/
pause
exit /b 1

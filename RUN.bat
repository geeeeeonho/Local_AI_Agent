@echo off
REM ============================================================
REM   LLM Local Setup - Run
REM
REM   ASCII-only + chcp 65001 = safe across zip extractions
REM   on any Korean / Japanese / Western Windows.
REM ============================================================
chcp 65001 >nul 2>&1

setlocal EnableDelayedExpansion

title LLM Environment - Run
cd /d "%~dp0"

echo.
echo Starting LLM Environment...
echo Working directory: %CD%
echo.

REM ----- Sanity: required folders -----
if not exist "launcher\__main__.py" (
    echo [ERROR] Cannot find launcher package next to this BAT file.
    echo         Make sure you extracted the entire archive without renaming folders.
    echo         Current dir: %CD%
    pause
    exit /b 1
)

REM ----- Docker detect -----
set "DOCKER_OK=0"
call :detect_docker

if "%DOCKER_OK%"=="1" (
    echo [INFO] Docker available
) else (
    echo [INFO] Docker not available - sandbox/search will be limited
)

REM ----- Check install -----
if not exist "llm_environment" (
    echo [ERROR] Installation folder not found: llm_environment
    echo         Run INSTALL.bat first.
    pause
    exit /b 1
)

REM ----- Check Python -----
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo         Install Python 3.11+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM ----- Run launcher -----
python -m launcher
set "PY_RC=%ERRORLEVEL%"

echo.
if not "%PY_RC%"=="0" (
    echo [WARN] Launcher exited with code %PY_RC%
)
pause
exit /b %PY_RC%


REM ============================================================
REM   Subroutine: Docker detection (same logic as INSTALL.bat)
REM ============================================================

:detect_docker
set "DOCKER_OK=0"

docker --version >nul 2>&1
if not errorlevel 1 (
    docker info >nul 2>&1
    if not errorlevel 1 (
        set "DOCKER_OK=1"
        goto :eof
    )
)

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

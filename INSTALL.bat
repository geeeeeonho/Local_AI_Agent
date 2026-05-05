@echo off
setlocal EnableDelayedExpansion

title LLM Environment - Install
cd /d "%~dp0"

echo.
echo Starting LLM Environment Installer...
echo.

REM ----- Language -----
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
where python >nul 2>&1 || goto python_missing

python -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1 || goto python_old

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK] Python %PY_VER%
echo.

REM ----- Docker -----
echo [2/3] Checking Docker...
if "%DOCKER_OK%"=="1" (
    echo [OK] Docker running
) else (
    echo [WARN] Docker not available - continuing without it
)
echo.

REM ----- Install -----
echo [3/3] Running installer...
echo.

if "%DOCKER_OK%"=="1" (
    python -m installer --lang %UI_LANG%
) else (
    python -m installer --skip-sandbox --skip-search --lang %UI_LANG%
)

if errorlevel 1 (
    echo.
    echo [ERROR] Installation failed
    pause
    exit /b 1
)

echo.
echo Installation complete
echo Run RUN.bat next
pause
exit /b 0

REM ============================================================
REM   Docker detection (final robust version)
REM ============================================================

:detect_docker
set "DOCKER_OK=0"

REM 1) direct execution test
docker --version >nul 2>&1
if not errorlevel 1 (
    docker info >nul 2>&1
    if not errorlevel 1 (
        set "DOCKER_OK=1"
        goto :eof
    )
)

REM 2) fallback path
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

REM 3) try starting Docker Desktop
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
echo [ERROR] Python not found
pause
exit /b 1

:python_old
echo [ERROR] Python too old (need 3.11+)
pause
exit /b 1
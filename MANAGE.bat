@echo off
REM MANAGE_DISPATCH_v1 - install + model manage + diagnose (single entry)
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
title LLM Local Setup
cd /d "%~dp0"

REM ----- Read saved language (best effort) -----
set "UI_LANG=en"
set "CONFIG_FILE=launcher\settings\user_config.json"
if exist "%CONFIG_FILE%" (
    findstr /C:"\"language\": \"ko\"" "%CONFIG_FILE%" >nul 2>&1 && set "UI_LANG=ko"
)

REM ----- Direct argument (install / manage / diagnose) skips the menu -----
set "ARGMODE="
if /i "%~1"=="install"  ( set "ARGMODE=1" & goto do_install )
if /i "%~1"=="manage"   ( set "ARGMODE=1" & goto do_manage )
if /i "%~1"=="models"   ( set "ARGMODE=1" & goto do_manage )
if /i "%~1"=="diagnose" ( set "ARGMODE=1" & goto do_diagnose )

:menu
cls
echo ============================================================
echo   LLM Local Setup
echo ============================================================
echo.
echo   [1] Install / update environment
echo   [2] Manage models (install / delete)
echo   [3] Diagnose system
echo   [Q] Quit
echo.
set "CHOICE="
set /p "CHOICE=Select [1/2/3/Q]: "
if /i "%CHOICE%"=="1" goto do_install
if /i "%CHOICE%"=="2" goto do_manage
if /i "%CHOICE%"=="3" goto do_diagnose
if /i "%CHOICE%"=="Q" goto end
goto menu

REM ============================================================
:do_install
echo.
echo ===== Install / update environment =====
echo.
call :check_python
if errorlevel 1 goto after
if not exist "installer\__main__.py" (
    echo [ERROR] installer package not found next to this BAT file.
    echo         Extract the whole archive without renaming folders.
    goto after
)
set "DOCKER_OK=0"
call :detect_docker
echo.
echo [1/2] Python OK
if "%DOCKER_OK%"=="1" (
    echo [2/2] Docker running
) else (
    echo [2/2] Docker not available - sandbox/search will be skipped
)
echo.
if "%DOCKER_OK%"=="1" (
    python -m installer --lang %UI_LANG%
) else (
    python -m installer --skip-sandbox --skip-search --lang %UI_LANG%
)
if errorlevel 1 (
    echo.
    echo [ERROR] Installation failed.
) else (
    echo.
    echo Installation complete. Run RUN.bat to start.
)
goto after

REM ============================================================
:do_manage
echo.
echo ===== Manage models (install / delete) =====
echo.
call :check_python
if errorlevel 1 goto after
python -m installer.manage
goto after

REM ============================================================
:do_diagnose
echo.
echo ===== System diagnose =====
echo.
echo --- Python ---
where python
python --version 2>nul
echo.
echo --- Docker ---
where docker
docker --version 2>nul
docker info >nul 2>&1 && echo Docker running || echo Docker not running
echo.
echo --- PATH ---
echo %PATH%
goto after

REM ============================================================
:after
echo.
if defined ARGMODE goto end
pause
goto menu

:end
endlocal
exit /b 0

REM ============================================================
REM   Subroutine: Python check (exit /b 1 on failure)
REM ============================================================
:check_python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo         Install Python 3.11+ and tick "Add Python to PATH".
    exit /b 1
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is too old. Need 3.11 or newer.
    exit /b 1
)
exit /b 0

REM ============================================================
REM   Subroutine: Docker detection (sets DOCKER_OK=1/0)
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

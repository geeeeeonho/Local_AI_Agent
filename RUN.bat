@echo off
setlocal EnableDelayedExpansion

title LLM Environment - Run
cd /d "%~dp0"

echo.
echo Starting LLM Environment...
echo.

REM ----- Docker detect -----
set "DOCKER_OK=0"
call :detect_docker

if "%DOCKER_OK%"=="1" (
    echo [INFO] Docker available
) else (
    echo [INFO] Docker not available
)

REM ----- Check install -----
if not exist "llm_environment" (
    echo [ERROR] Installation not found
    pause
    exit /b 1
)

where python >nul 2>&1 || (
    echo [ERROR] Python not found
    pause
    exit /b 1
)

python -m launcher

echo.
pause
exit /b %errorlevel%

REM ============================================================
REM   Docker detection (same as INSTALL)
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
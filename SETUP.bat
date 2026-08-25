@echo off
setlocal
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
title Local AI Agent - Setup
cd /d "%~dp0"

set "MANAGED_PY=%~dp0llm_environment\venv\Scripts\python.exe"
if exist "%MANAGED_PY%" goto RUN_MANAGED

where python >nul 2>&1
if not errorlevel 1 goto RUN_PYTHON

py -3 -V >nul 2>&1
if not errorlevel 1 goto RUN_PY

goto NOPY

:RUN_MANAGED
"%MANAGED_PY%" -m installer %*
goto CHECK

:RUN_PYTHON
python -m installer %*
goto CHECK

:RUN_PY
py -3 -m installer %*
goto CHECK

:CHECK
if errorlevel 1 goto ERR
exit /b 0

:ERR
echo.
echo [WARN] Setup exited with an error. See messages above.
pause
exit /b 1

:NOPY
echo [ERROR] Python 3.11+ is required to install or manage the environment.
pause
exit /b 1

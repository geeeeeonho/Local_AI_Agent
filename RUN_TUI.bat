@echo off
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"

set "MANAGED_PY=%~dp0llm_environment\venv\Scripts\python.exe"
if exist "%MANAGED_PY%" goto RUN_MANAGED

where python >nul 2>&1
if not errorlevel 1 goto RUN_PYTHON

py -3 -V >nul 2>&1
if not errorlevel 1 goto RUN_PY

goto NOPY

:RUN_MANAGED
"%MANAGED_PY%" -m launcher --tui %*
goto CHECK

:RUN_PYTHON
python -m launcher --tui %*
goto CHECK

:RUN_PY
py -3 -m launcher --tui %*
goto CHECK

:CHECK
if errorlevel 1 goto ERR
exit /b 0

:ERR
echo.
echo [WARN] Launcher exited with an error. See messages above.
pause
exit /b 1

:NOPY
echo [ERROR] Python not found. Install Python 3.11+ or run INSTALL.bat.
pause
exit /b 1

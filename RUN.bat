@echo off
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"

set "MANAGED_PYW=%~dp0llm_environment\venv\Scripts\pythonw.exe"
set "MANAGED_PY=%~dp0llm_environment\venv\Scripts\python.exe"

if exist "%MANAGED_PYW%" goto RUN_MANAGED_GUI
if exist "%MANAGED_PY%" goto RUN_MANAGED_CONSOLE

where pythonw.exe >nul 2>&1
if not errorlevel 1 goto RUN_SYSTEM_GUI

where python >nul 2>&1
if not errorlevel 1 goto RUN_SYSTEM_CONSOLE

py -3 -V >nul 2>&1
if not errorlevel 1 goto RUN_PY

goto NOPY

:RUN_MANAGED_GUI
start "" "%MANAGED_PYW%" -m launcher %*
exit /b 0

:RUN_MANAGED_CONSOLE
"%MANAGED_PY%" -m launcher %*
goto CHECK

:RUN_SYSTEM_GUI
start "" pythonw.exe -m launcher %*
exit /b 0

:RUN_SYSTEM_CONSOLE
python -m launcher %*
goto CHECK

:RUN_PY
py -3 -m launcher %*
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

@echo off
setlocal
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
cd /d "%~dp0"

set "MANAGED_PYW=%~dp0llm_environment\venv\Scripts\pythonw.exe"
set "MANAGED_PY=%~dp0llm_environment\venv\Scripts\python.exe"
set "FORCE_TUI="
echo %* | findstr /I /C:"--tui" /C:"--install" /C:"--manage" /C:"--skip-" /C:"--help" >nul 2>&1 && set "FORCE_TUI=1"

if defined FORCE_TUI goto RUN_TUI
if exist "%MANAGED_PYW%" goto RUN_MANAGED_GUI
if exist "%MANAGED_PY%" goto RUN_MANAGED_CONSOLE

where pythonw.exe >nul 2>&1
if not errorlevel 1 goto RUN_SYSTEM_GUI
where python >nul 2>&1
if not errorlevel 1 goto RUN_SYSTEM_CONSOLE
py -3 -V >nul 2>&1
if not errorlevel 1 goto RUN_PY
goto NOPY

:RUN_TUI
if exist "%MANAGED_PY%" (
  "%MANAGED_PY%" -m apps.studio %*
  goto CHECK
)
where python >nul 2>&1
if not errorlevel 1 (
  python -m apps.studio %*
  goto CHECK
)
py -3 -V >nul 2>&1
if not errorlevel 1 (
  py -3 -m apps.studio %*
  goto CHECK
)
goto NOPY

:RUN_MANAGED_GUI
start "" "%MANAGED_PYW%" -m apps.studio %*
exit /b 0

:RUN_MANAGED_CONSOLE
"%MANAGED_PY%" -m apps.studio %*
goto CHECK

:RUN_SYSTEM_GUI
start "" pythonw.exe -m apps.studio %*
exit /b 0

:RUN_SYSTEM_CONSOLE
python -m apps.studio %*
goto CHECK

:RUN_PY
py -3 -m apps.studio %*
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
echo [ERROR] Python not found. Install Python 3.11+ or run SETUP.bat.
pause
exit /b 1

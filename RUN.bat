@echo off
setlocal
rem Single public entrypoint for Studio, Chat, Interpreter, Setup, install/repair, and TUI.
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
cd /d "%~dp0"

set "FORCE_CONSOLE="
echo %* | findstr /I /C:"--tui" /C:"--install" /C:"--skip-" /C:"--help" >nul 2>&1 && set "FORCE_CONSOLE=1"

if defined FORCE_CONSOLE goto RUN_CONSOLE

where pythonw.exe >nul 2>&1
if not errorlevel 1 goto RUN_SYSTEM_GUI
where pyw.exe >nul 2>&1
if not errorlevel 1 goto RUN_PYW
where python.exe >nul 2>&1
if not errorlevel 1 goto RUN_SYSTEM_CONSOLE
py -3 -V >nul 2>&1
if not errorlevel 1 goto RUN_PY
goto NOPY

:RUN_CONSOLE
where python.exe >nul 2>&1
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

:RUN_SYSTEM_GUI
start "" pythonw.exe -m apps.studio %*
exit /b 0

:RUN_PYW
start "" pyw -3 -m apps.studio %*
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
echo [ERROR] Python not found. Install Python 3.11+ and run RUN.bat --install.
pause
exit /b 1

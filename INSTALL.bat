@echo off
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"

where python >nul 2>&1
if not errorlevel 1 goto RUN_PYTHON

py -3 -V >nul 2>&1
if not errorlevel 1 goto RUN_PY

goto NOPY

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
echo [FAIL] Installer exited with an error. See messages above.
pause
exit /b 1

:NOPY
echo [FAIL] Python 3.11+ is required to run the installer.
pause
exit /b 1

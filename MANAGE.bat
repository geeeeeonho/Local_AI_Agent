@echo off
setlocal
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title LLM Local Setup - Manage
cd /d "%~dp0"
set "PYEXE="
where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE py -3 -V >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE goto NOPY
%PYEXE% -m installer.manage_gui %*
if errorlevel 1 goto ERR
goto END
:ERR
echo.
echo [WARN] Manage exited with an error. See messages above.
pause
goto END
:NOPY
echo [ERROR] Python not found. Install Python 3.11+ or add it to PATH.
pause
:END

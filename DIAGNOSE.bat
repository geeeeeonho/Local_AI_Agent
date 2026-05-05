@echo off
echo ===== SYSTEM DIAGNOSE =====
echo.

echo --- Python ---
where python
python --version

echo.
echo --- Docker ---
where docker
docker --version 2>nul
docker info >nul 2>&1 && echo Docker running || echo Docker not running

echo.
echo --- PATH ---
echo %PATH%

echo.
pause
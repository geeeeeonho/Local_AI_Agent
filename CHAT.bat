@echo off
call "%~dp0RUN.bat" --app chat %*
exit /b %errorlevel%

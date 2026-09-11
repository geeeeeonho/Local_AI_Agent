@echo off
call "%~dp0RUN.bat" --app interpreter %*
exit /b %errorlevel%

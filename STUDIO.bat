@echo off
call "%~dp0RUN.bat" --app studio %*
exit /b %errorlevel%

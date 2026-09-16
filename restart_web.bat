@echo off
cd /d "%~dp0"
call stop_web.bat --no-pause
timeout /t 1 /nobreak >nul
start start_web.bat

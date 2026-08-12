@echo off
title DBQuery Web Server
cd /d "%~dp0"

echo ================================================
echo   DBQuery Web Server Starting...
echo ================================================

:: Get IP
set "L_IP=127.0.0.1"
for /f "tokens=4" %%a in ('route print ^| findstr 0.0.0.0 ^| findstr /v 127.0.0.1') do set "L_IP=%%a"

echo.
echo   Local:   http://localhost:5000
echo   Network: http://%L_IP%:5000
echo.
echo   Hint: Add ?hide_header=1 for embedded mode.
echo ================================================
echo.

if exist "dist_final\DBQuery.exe" (
    start "" dist_final\DBQuery.exe --web
    echo Service started in background.
) else (
    echo Error: dist_final\DBQuery.exe not found.
    echo Please run build.bat first.
    pause
)

timeout /t 5

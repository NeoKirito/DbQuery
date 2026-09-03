@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Restart DBQuery Web Server
cd /d "%~dp0"

:: Restart needs elevation because the start script configures Windows Firewall.
net session >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator privileges to restart DBQuery Web...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================
echo   Restarting DBQuery Web Server...
echo ================================================
echo.

call "%~dp0stop_web.bat" --no-pause
if errorlevel 1 (
    echo.
    echo Restart cancelled because the old service could not be stopped.
    if /I not "%~1"=="--no-pause" pause
    exit /b 1
)

call "%~dp0start_web.bat"
if errorlevel 1 (
    echo.
    echo Restart failed while starting DBQuery Web.
    if /I not "%~1"=="--no-pause" pause
    exit /b 1
)

echo.
echo DBQuery Web restart completed.
if /I not "%~1"=="--no-pause" pause
endlocal

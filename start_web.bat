@echo off
setlocal EnableExtensions
title DBQuery Web Server
cd /d "%~dp0"

:: Set the Web service port here. All commands below use this value.
set "WEB_PORT=8094"
set "EXE_PATH=%~dp0dist_final\DBQuery.exe"
set "PORT_RULE_NAME=DBQuery_Web_%WEB_PORT%"
:: Allow a trusted reverse proxy to expose DBQuery below /dbquery.
set "DBQUERY_TRUST_PROXY_PREFIX=true"

:: Firewall rules require administrator privileges. Relaunch this script as admin.
net session >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator privileges to configure Windows Firewall...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================
echo   DBQuery Web Server Starting...
echo ================================================

if not exist "%EXE_PATH%" (
    echo.
    echo Error: dist_final\DBQuery.exe not found.
    echo Please run build.bat first.
    pause
    exit /b 1
)

:: Remove old Windows-generated DBQuery rules. Some of them explicitly block
:: DBQuery.exe on Public networks, and block rules override allow rules.
echo Configuring Windows Firewall...
netsh advfirewall firewall delete rule name="dbquery" dir=in >nul 2>&1
netsh advfirewall firewall delete rule name="DBQuery_Web_Access" dir=in >nul 2>&1
netsh advfirewall firewall delete rule name="%PORT_RULE_NAME%" dir=in >nul 2>&1
netsh advfirewall firewall delete rule name="DBQuery Program Allow" dir=in >nul 2>&1

netsh advfirewall firewall add rule name="%PORT_RULE_NAME%" dir=in action=allow protocol=TCP localport=%WEB_PORT% profile=any enable=yes >nul
if errorlevel 1 (
    echo Error: Failed to add firewall port rule.
    pause
    exit /b 1
)

netsh advfirewall firewall add rule name="DBQuery Program Allow" dir=in action=allow program="%EXE_PATH%" protocol=TCP profile=any enable=yes >nul
if errorlevel 1 (
    echo Error: Failed to add firewall program rule.
    pause
    exit /b 1
)
echo Firewall access enabled for TCP port %WEB_PORT%.

:: Get IP
set "L_IP=127.0.0.1"
for /f "tokens=4" %%a in ('route print -4 ^| findstr /R /C:"^[ ]*0\.0\.0\.0[ ]*0\.0\.0\.0" ^| findstr /V /C:"Default"') do set "L_IP=%%a"

echo.
echo   Local:   http://localhost:%WEB_PORT%
echo   Network: http://%L_IP%:%WEB_PORT%
echo.
echo   Hint: Add ?hide_header=1 for embedded mode.
echo ================================================
echo.

start "" "%EXE_PATH%" --web --port %WEB_PORT%
echo Service started in background.

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2"
endlocal & exit /b 0

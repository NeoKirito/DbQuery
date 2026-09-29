@echo off
setlocal EnableExtensions
title DBQuery Web Server
cd /d "%~dp0"

:: 默认服务端口（优先传参 %1，其次从 config.ini 读取，缺省为 6091）
set "WEB_PORT=6091"
if not "%~1"=="" (
    set "WEB_PORT=%~1"
) else if exist "%~dp0config.ini" (
    for /f "usebackq tokens=*" %%p in (`powershell -NoProfile -Command "try { $c=Get-Content '%~dp0config.ini' -Raw; if ($c -match '(?ms)\[web\][^\[]*^\s*port\s*=\s*(\d+)') { $matches[1] } else { '6091' } } catch { '6091' }"`) do set "WEB_PORT=%%p"
)
if "%WEB_PORT%"=="" set "WEB_PORT=6091"

if exist "%~dp0dist\DBQuery\DBQuery.exe" (
    set "EXE_PATH=%~dp0dist\DBQuery\DBQuery.exe"
) else if exist "%~dp0dist\DBQuery.exe" (
    set "EXE_PATH=%~dp0dist\DBQuery.exe"
) else if exist "%~dp0dist_final\DBQuery.exe" (
    set "EXE_PATH=%~dp0dist_final\DBQuery.exe"
) else if exist "%~dp0DBQuery.exe" (
    set "EXE_PATH=%~dp0DBQuery.exe"
) else (
    set "EXE_PATH=%~dp0dist\DBQuery\DBQuery.exe"
)

set "PORT_RULE_NAME=DBQuery_Web_%WEB_PORT%"
set "DBQUERY_TRUST_PROXY_PREFIX=true"

:: ── 检测是否在 AlwaysUp 服务环境运行或指定了服务常驻模式 ──
if /I "%~1"=="--service" goto :RUN_SERVICE
if /I "%~1"=="service" goto :RUN_SERVICE
if /I "%~1"=="/service" goto :RUN_SERVICE
if defined ALWAYSUP_APPLICATION_NAME goto :RUN_SERVICE
if defined ALWAYSUP goto :RUN_SERVICE

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
    echo Error: DBQuery.exe not found at "%EXE_PATH%".
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
echo   Local:   http://localhost:%WEB_PORT%/
echo   Network: http://%L_IP%:%WEB_PORT%/
echo   Health:  http://127.0.0.1:%WEB_PORT%/api/health
echo.
echo   Hint: Add ?hide_header=1 for embedded mode.
echo ================================================
echo.

start "" "%EXE_PATH%" --web --port %WEB_PORT%
echo Service started in background.

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2"
endlocal & exit /b 0

:RUN_SERVICE
:: ── AlwaysUp / Windows 服务常驻模式（前台阻塞运行，严禁 start 异步退出）──
if not exist "%EXE_PATH%" (
    echo [ERROR] DBQuery.exe not found at "%EXE_PATH%"
    exit /b 1
)
netsh advfirewall firewall add rule name="%PORT_RULE_NAME%" dir=in action=allow protocol=TCP localport=%WEB_PORT% profile=any enable=yes >nul 2>&1
netsh advfirewall firewall add rule name="DBQuery Program Allow" dir=in action=allow program="%EXE_PATH%" protocol=TCP profile=any enable=yes >nul 2>&1
echo [INFO] DBQuery Web Server starting in AlwaysUp service mode on port %WEB_PORT%...
"%EXE_PATH%" --web --port %WEB_PORT%
set "SVC_EXIT=%ERRORLEVEL%"
echo [INFO] DBQuery Web Server exited with code %SVC_EXIT%
endlocal & exit /b %SVC_EXIT%

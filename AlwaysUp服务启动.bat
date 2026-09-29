@echo off
setlocal EnableExtensions
title DBQuery Web 守护服务 (AlwaysUp)
cd /d "%~dp0"

:: ============================================================================
:: DBQuery Web 服务 - AlwaysUp / Windows 服务专用启动脚本
:: 1. 进程常驻：前台阻塞运行，严禁 start 异步退出，确保 AlwaysUp 正确跟踪 PID
:: 2. 健康监听：支持 AlwaysUp Sanity Check 定期 GET http://127.0.0.1:端口/api/health
:: 3. 退出码透传：DBQuery 异常退出时透传 ExitCode，触发 AlwaysUp 自动重启机制
:: ============================================================================

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

if not exist "%EXE_PATH%" (
    echo [ERROR] %date% %time% 未找到主程序: "%EXE_PATH%"
    exit /b 1
)

set "PORT_RULE_NAME=DBQuery_Web_%WEB_PORT%"
set "DBQUERY_TRUST_PROXY_PREFIX=true"

:: 静默放行防火墙（服务运行身份有权限则生效，无权限不报错阻塞）
netsh advfirewall firewall add rule name="%PORT_RULE_NAME%" dir=in action=allow protocol=TCP localport=%WEB_PORT% profile=any enable=yes >nul 2>&1
netsh advfirewall firewall add rule name="DBQuery Program Allow" dir=in action=allow program="%EXE_PATH%" protocol=TCP profile=any enable=yes >nul 2>&1

echo ============================================================================
echo   DBQuery Web AlwaysUp 守护服务正在运行...
echo   启动时间: %date% %time%
echo   监听端口: %WEB_PORT%
echo   存活监听: http://127.0.0.1:%WEB_PORT%/api/health
echo   主程序:   %EXE_PATH%
echo ============================================================================

"%EXE_PATH%" --web --port %WEB_PORT%

set "SVC_EXIT=%ERRORLEVEL%"
echo [INFO] %date% %time% DBQuery Web 服务退出，退出码: %SVC_EXIT%
endlocal & exit /b %SVC_EXIT%

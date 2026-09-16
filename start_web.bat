@echo off
chcp 65001 >nul
setlocal EnableExtensions
title DBQuery C# Web Server
cd /d "%~dp0"

set "PORT=8094"
if not "%~1"=="" set "PORT=%~1"

echo ================================================
echo   DBQuery C# (.NET 8) Web Server 启动中...
echo   监听端口: %PORT%
echo ================================================

:: 获取本机局域网 IP
set "L_IP=127.0.0.1"
for /f "tokens=4" %%a in ('route print -4 ^| findstr /R /C:"^[ ]*0\.0\.0\.0[ ]*0\.0\.0\.0" ^| findstr /V /C:"Default"') do set "L_IP=%%a"

echo.
echo 本机访问地址: http://localhost:%PORT%/login
echo 局域网访问地址: http://%L_IP%:%PORT%/login
echo 默认管理员: admin  密码: 123456
echo ================================================
echo.

start http://localhost:%PORT%/login
DbQuery.exe

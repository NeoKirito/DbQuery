@echo off
chcp 65001 >nul
title 停止 DBQuery C# Web Server
cd /d "%~dp0"

echo ================================================
echo   正在停止 DBQuery C# Web 服务...
echo ================================================

taskkill /f /im DbQuery.exe >nul 2>&1
if errorlevel 1 (
    echo DBQuery 服务未在运行。
) else (
    echo DBQuery 服务已成功停止。
)

if /I not "%~1"=="--no-pause" pause

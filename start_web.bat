@echo off
chcp 65001 > nul
title DBQuery Web Server (.exe)
setlocal enabledelayedexpansion

:: 设置当前目录
cd /d "%~dp0"

echo ================================================
echo   DBQuery Web 服务启动工具 (EXE 模式)
echo ================================================
echo.

:: 获取局域网 IP
set "L_IP=127.0.0.1"
for /f "tokens=4" %%a in ('route print ^| findstr 0.0.0.0 ^| findstr /v 127.0.0.1') do (
    set "L_IP=%%a"
)

:: 尝试开放防火墙 5000 端口
netsh advfirewall firewall show rule name="DBQuery_Web_5000" >nul 2>&1
if errorlevel 1 (
    echo 正在尝试为您在防火墙中开放 5000 端口...
    netsh advfirewall firewall add rule name="DBQuery_Web_5000" dir=in action=allow protocol=TCP localport=5000 >nul 2>&1
)

echo   本地访问：  http://localhost:5000
echo   局域网访问：http://!L_IP!:5000
echo.
echo   提示：嵌入模式请使用 http://!L_IP!:5000/?hide_header=1
echo ================================================
echo.

:: 启动程序 (进入 EXE 所在目录)
if exist "dist_final\DBQuery\DBQuery\DBQuery.exe" (
    cd /d "dist_final\DBQuery\DBQuery"
    start "" DBQuery.exe --web
    echo 服务已在后台启动。
) else (
    echo [错误] 未找到程序文件：dist_final\DBQuery\DBQuery\DBQuery.exe
    echo 请先运行 build.bat 进行打包。
)

echo.
timeout /t 5

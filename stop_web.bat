@echo off
chcp 65001 > nul
echo ================================================
echo   正在关闭 DBQuery Web 服务...
echo ================================================
echo.

:: 1. 按端口关闭
echo [1/2] 正在释放端口 5000...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"

:: 2. 按进程名关闭 (防止僵尸进程)
echo [2/2] 正在清理残留进程...
powershell -NoProfile -Command "Get-Process DBQuery -ErrorAction SilentlyContinue | Stop-Process -Force"

echo.
echo [完成] 服务已成功停止。
echo.
timeout /t 3

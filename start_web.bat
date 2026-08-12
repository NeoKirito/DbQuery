@echo off
chcp 65001 > nul
title DBQuery Web Server
echo ================================================
echo   DBQuery Web 服务启动中...
echo ================================================
echo.
python app.py --web
if errorlevel 1 (
    echo.
    echo [错误] 启动失败，请检查 Python 环境和依赖。
    pause
)

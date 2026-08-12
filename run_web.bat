@echo off
chcp 65001 > nul
echo ================================================
echo   DBQuery Web 服务启动
echo ================================================
echo.

:: ── 检查 Python ──
python --version 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python，请安装 Python 3.8 并加入 PATH
    pause & exit /b 1
)

:: ── 检查 Flask ──
python -c "import flask" 2>nul
if errorlevel 1 (
    echo [提示] 正在安装 Flask...
    pip install Flask==2.2.5 --quiet
)

echo.
echo   浏览器访问：http://localhost:5000
echo   按 Ctrl+C 停止服务
echo.
echo ================================================

python web_server.py
pause

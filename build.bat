@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

:: 设置当前目录
cd /d "%~dp0"

echo ================================================
echo   DBQuery 打包工具 (支持直接双击运行)
echo ================================================
echo.

:: 1. 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 python，请确保已安装 Python 3.7+ 并加入环境变量。
    pause
    exit /b 1
)

:: 2. 安装依赖
echo [1/4] 正在安装/更新必要依赖...
pip install -r requirements.txt --quiet

:: 3. 打包
echo [2/4] 正在清理旧文件并执行 PyInstaller 打包...
if exist build rmdir /S /Q build
if exist dist rmdir /S /Q dist

pyinstaller DBQuery.spec
if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请检查报错信息。
    pause
    exit /b 1
)

:: 4. 同步到发布目录
echo [3/4] 正在同步程序到发布目录 (dist_final)...
if not exist "dist_final\DBQuery" mkdir "dist_final\DBQuery"
if exist "dist_final\DBQuery\DBQuery" rmdir /S /Q "dist_final\DBQuery\DBQuery"
xcopy /E /Y /I "dist\DBQuery" "dist_final\DBQuery\DBQuery" > nul

:: 5. 复制配置
echo [4/4] 正在整理配置文件...
if exist config.ini copy /Y config.ini "dist_final\DBQuery\DBQuery\" > nul

echo.
echo ================================================
echo   打包成功！
echo   最新程序：dist_final\DBQuery\DBQuery\DBQuery.exe
echo ================================================
echo.
echo   [Win7 运行提示]：
echo   如果 Win7 提示丢失 DLL，请安装 VC 运行库：
echo   https://aka.ms/vs/17/release/vc_redist.x86.exe
echo.
pause

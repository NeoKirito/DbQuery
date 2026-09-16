@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo   正在编译并打包 DBQuery C# (.NET 8) 版本...
echo ================================================
dotnet publish -c Release -o ./dist
if errorlevel 1 (
    echo.
    echo 编译打包失败，请检查错误输出。
    pause
    exit /b 1
)

copy /y start_web.bat dist\ >nul 2>&1
copy /y stop_web.bat dist\ >nul 2>&1
copy /y restart_web.bat dist\ >nul 2>&1
copy /y "启动DBQueryWeb服务.bat" dist\ >nul 2>&1
copy /y "停止DBQueryWeb服务.bat" dist\ >nul 2>&1
copy /y "重启DBQueryWeb服务.bat" dist\ >nul 2>&1

echo.
echo ================================================
echo   打包完成！发布目录：.\dist
echo ================================================
pause

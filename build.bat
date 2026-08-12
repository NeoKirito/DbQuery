@echo off
chcp 65001 > nul
echo ================================================
echo   DBQuery 打包脚本（Win7 / Win10 / Win11 兼容）
echo ================================================
echo.

:: ── 检查 Python ──────────────────────────────────
python --version 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python，请安装 Python 3.8 并加入 PATH
    pause & exit /b 1
)

:: ── 安装依赖 ─────────────────────────────────────
echo [1/4] 安装依赖包...
pip install -r requirements.txt --quiet
if errorlevel 1 ( echo [错误] 依赖安装失败 & pause & exit /b 1 )

:: ── 诊断 UCRT DLL 是否存在 ───────────────────────
echo [2/4] 检查 Universal CRT DLL（Win7 兼容必需）...
set UCRT_FOUND=0
set UCRT_DIR=

if exist "C:\Windows\System32\downlevel\api-ms-win-core-sysinfo-l1-2-0.dll" (
    set UCRT_DIR=C:\Windows\System32\downlevel
    set UCRT_FOUND=1
    echo   [OK] 找到 downlevel 目录: %UCRT_DIR%
)

if %UCRT_FOUND%==0 (
    if exist "C:\Program Files (x86)\Windows Kits\10\Redist\ucrt\DLLs\x86\api-ms-win-core-sysinfo-l1-2-0.dll" (
        set UCRT_DIR=C:\Program Files (x86)\Windows Kits\10\Redist\ucrt\DLLs\x86
        set UCRT_FOUND=1
        echo   [OK] 找到 Windows Kits 目录: %UCRT_DIR%
    )
)

if %UCRT_FOUND%==0 (
    echo.
    echo   [警告] 未找到 Universal CRT DLL！
    echo   打出来的 EXE 在 Win7 上可能报"丢失 api-ms-win-*.dll"错误。
    echo.
    echo   解决方法（二选一）：
    echo   A. 在本机（打包机）安装 Windows 10 SDK：
    echo      https://developer.microsoft.com/windows/downloads/windows-sdk/
    echo      安装后 DLL 会出现在：
    echo      C:\Program Files (x86)\Windows Kits\10\Redist\ucrt\DLLs\x86\
    echo.
    echo   B. 继续打包，打包完成后手动把以下文件夹中所有 DLL
    echo      复制到 dist\DBQuery\ 目录：
    echo      C:\Windows\System32\downlevel\   (如果存在)
    echo      或从另一台 Win10 机器的同路径复制
    echo.
    choice /C YN /M "是否继续打包（EXE 可能在 Win7 无法运行）？"
    if errorlevel 2 ( pause & exit /b 0 )
)

:: ── 清理并打包 ────────────────────────────────────
echo [3/4] 清理旧构建并打包...
if exist build  rmdir /S /Q build
if exist dist   rmdir /S /Q dist

pyinstaller DBQuery.spec
if errorlevel 1 ( echo [错误] 打包失败 & pause & exit /b 1 )

:: ── 若 spec 未能自动收集，手动补充 UCRT DLL ────────
if %UCRT_FOUND%==1 (
    echo [4/4] 补充 UCRT DLL 到输出目录...
    copy /Y "%UCRT_DIR%\api-ms-win-*.dll"  "dist\DBQuery\" > nul 2>&1
    copy /Y "%UCRT_DIR%\ucrtbase.dll"      "dist\DBQuery\" > nul 2>&1
    echo   [OK] DLL 已复制
) else (
    echo [4/4] 跳过 DLL 复制（未找到 UCRT 目录）
)

:: ── 复制配置 ─────────────────────────────────────
if exist config.ini copy /Y config.ini dist\DBQuery\ > nul

echo.
echo ================================================
echo   打包完成！
echo.
echo   桌面版：dist\DBQuery\DBQuery.exe
echo   Web 版：dist\DBQuery\DBQuery.exe --web
echo     然后浏览器打开 http://localhost:5000
echo ================================================
echo.
echo   ─── Win7 部署必读 ───────────────────────────
echo.
echo   目标 Win7 机器若仍报"丢失 api-ms-win-*.dll"：
echo.
echo   【方法 1 — 推荐，一键安装】
echo   安装 Microsoft Visual C++ 2015-2022 Redistributable (x86)
echo   下载：https://aka.ms/vs/17/release/vc_redist.x86.exe
echo   （此包含 ucrtbase.dll 及全部 api-ms-win-*.dll）
echo.
echo   【方法 2 — Windows Update】
echo   安装补丁 KB2999226（通用 CRT for Win7 SP1）
echo   https://support.microsoft.com/kb/2999226
echo.
echo   【方法 3 — 手动放 DLL】
echo   从 Win10 机器的 C:\Windows\System32\downlevel\
echo   复制全部 api-ms-win-*.dll 和 ucrtbase.dll
echo   放入 DBQuery.exe 同目录即可
echo.
pause

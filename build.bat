@echo off
title DBQuery Build Tool
cd /d "%~dp0"

echo ================================================
echo   DBQuery Build Tool (Double-click supported)
echo ================================================
echo.

:: 1. Build
echo [1/2] Building with PyInstaller...
:: Added --noconfirm to skip Y/N prompt
pyinstaller --noconfirm DBQuery.spec
if errorlevel 1 (
    echo Error: Build failed.
    pause
    exit /b 1
)

:: 2. Sync
echo [2/2] Syncing to dist_final...
echo Closing running instances to unlock files...
:: Kill the process to release file lock
taskkill /f /im DBQuery.exe /t >nul 2>&1

powershell -NoProfile -Command "if (Test-Path 'dist_final') { Remove-Item -Recurse -Force 'dist_final' -ErrorAction SilentlyContinue }; if (!(Test-Path 'dist_final')) { Start-Sleep -s 1; New-Item -ItemType Directory -Path 'dist_final' -ErrorAction SilentlyContinue }; Copy-Item -Recurse -Force 'dist\DBQuery\*' 'dist_final\'"

echo.
echo Done! Target: dist_final\DBQuery.exe
echo.
pause

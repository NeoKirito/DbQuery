@echo off
title DBQuery Build & Packaging Tool
cd /d "%~dp0"

echo ================================================
echo   DBQuery Build Tool
echo ================================================
echo.

:: 1. Build
echo [1/2] Building with PyInstaller...
taskkill /f /im DBQuery.exe /t >nul 2>&1
pyinstaller --noconfirm DBQuery.spec
if errorlevel 1 (
    echo Error: Build failed.
    pause
    exit /b 1
)

:: 2. Assemble Deployment Packages
echo [2/2] Assembling Deployment Packages (Root: Bat/Config/Docs, Inner: dist/)...
python package_deploy.py
if errorlevel 1 (
    echo Error: Packaging failed.
    pause
    exit /b 1
)

echo.
echo ================================================
echo   Build & Packaging Completed Successfully!
echo   Deployment folder: DBQuery_Deploy
echo ================================================
echo.
pause

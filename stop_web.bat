@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Stop DBQuery Web Server
cd /d "%~dp0"

set "WEB_PORT=8094"
set "EXE_PATH=%~dp0dist_final\DBQuery.exe"
set "DBQUERY_EXPECTED_EXE=%EXE_PATH%"

:: The Web process is elevated by the start script, so stopping it also requires elevation.
net session >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator privileges to stop DBQuery Web...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================
echo   Stopping DBQuery Web Server...
echo ================================================

powershell -NoProfile -ExecutionPolicy Bypass -Command "$expected=[IO.Path]::GetFullPath($env:DBQUERY_EXPECTED_EXE); $targets=@(Get-WmiObject Win32_Process | Where-Object { $_.Name -eq 'DBQuery.exe' -and $_.ExecutablePath -and [string]::Equals([IO.Path]::GetFullPath($_.ExecutablePath),$expected,[StringComparison]::OrdinalIgnoreCase) -and $_.CommandLine -match '(?i)(^|\s)--web(\s|$)' }); if(-not $targets){ Write-Host 'DBQuery Web is not running.'; exit 0 }; foreach($target in $targets){ Stop-Process -Id $target.ProcessId -Force -ErrorAction Stop }; Start-Sleep -Milliseconds 500; $remaining=@(Get-WmiObject Win32_Process | Where-Object { $_.Name -eq 'DBQuery.exe' -and $_.ExecutablePath -and [string]::Equals([IO.Path]::GetFullPath($_.ExecutablePath),$expected,[StringComparison]::OrdinalIgnoreCase) -and $_.CommandLine -match '(?i)(^|\s)--web(\s|$)' }); if($remaining){ Write-Host 'Failed to stop DBQuery Web.'; exit 1 }; Write-Host 'DBQuery Web stopped.'"
set "STOP_RESULT=%ERRORLEVEL%"

echo.
if not "%STOP_RESULT%"=="0" echo Stop failed. Please check administrator privileges.
if /I not "%~1"=="--no-pause" pause
endlocal & exit /b %STOP_RESULT%

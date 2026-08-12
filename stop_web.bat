@echo off
title Stop DBQuery Web Server
echo ================================================
echo   Stopping DBQuery Web Server...
echo ================================================
echo.

taskkill /f /im DBQuery.exe /t

echo.
echo Done.
timeout /t 3

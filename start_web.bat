@echo off
chcp 65001 > nul
title DBQuery Web Server (.exe)
echo ================================================
echo   DBQuery Web Server Starting (EXE Mode)...
echo ================================================
echo.
echo Local Access:  http://localhost:5000
echo.
echo Hint: Add ?hide_header=1 to URL to hide navigation bar.
echo ================================================
echo.
cd /d " %~dp0dist_final\DBQuery\DBQuery\
start DBQuery.exe --web
echo Service started in background.
timeout /t 3

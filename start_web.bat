@echo off
cd /d " %~dp0\
echo Starting...
cd dist_final\DBQuery\DBQuery
start DBQuery.exe --web
echo Done.
timeout /t 3

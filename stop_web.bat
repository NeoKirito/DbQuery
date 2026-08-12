@echo off
echo Stopping...
taskkill /f /im DBQuery.exe
echo Done.
timeout /t 3

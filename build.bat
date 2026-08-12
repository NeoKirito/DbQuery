@echo off
cd /d " %~dp0\
echo Building...
pyinstaller DBQuery.spec
xcopy /E /Y /I \dist\DBQuery\ \dist_final\DBQuery\DBQuery\
echo Done.
pause

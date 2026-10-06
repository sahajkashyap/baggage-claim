@echo off
rem Shows the watcher working, in this window. It never stops the background
rem watcher (BaggageClaimWatcher.exe, started by Setup.bat and at every login).
rem When that watcher is running, this window follows its log and leaves it
rem alone, so closing the window cannot leave the class without a watcher.
cd /d "%~dp0"
title Baggage Claim watcher
if not exist logs mkdir logs
if not exist logs\watch.log type nul > logs\watch.log
tasklist /FI "IMAGENAME eq BaggageClaimWatcher.exe" 2>nul | find /I "BaggageClaimWatcher.exe" >nul
if errorlevel 1 goto not_running
echo.
echo  The watcher is already running in the background. This window follows its log.
echo  Close the window to stop looking; the watcher keeps going.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -LiteralPath 'logs\watch.log' -Tail 20 -Wait -Encoding UTF8"
echo.
echo  The watcher is still running in the background.
echo  Everything it does is written to the file logs\watch.log in this folder.
goto end
:not_running
echo.
echo  The background watcher is not running, so the watcher runs in this window.
echo  Closing this window stops it. To have it run by itself, and start again
echo  at every login, double-click Setup.bat.
echo.
BaggageClaim.exe --watch --settings settings.local.json --log logs\watch.log
:end
pause

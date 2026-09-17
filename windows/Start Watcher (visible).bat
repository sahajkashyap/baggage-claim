@echo off
cd /d "%~dp0"
taskkill /IM BaggageClaimWatcher.exe /F >nul 2>&1
if not exist logs mkdir logs
BaggageClaim.exe --watch --settings settings.local.json --log logs\watch.log
pause

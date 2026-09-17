@echo off
cd /d "%~dp0"
BaggageClaim.exe --check
echo.
tasklist /FI "IMAGENAME eq BaggageClaimWatcher.exe" | find /I "BaggageClaimWatcher.exe" >nul && echo  Watcher: running || echo  Watcher: NOT running (double-click Setup.bat)
pause

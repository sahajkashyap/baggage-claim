@echo off
taskkill /IM BaggageClaimWatcher.exe /F >nul 2>&1 && echo Watcher stopped. || echo Watcher was not running.
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Baggage Claim Watcher.lnk" >nul 2>&1
echo It will no longer start at login. Double-click Setup.bat to turn it back on.
pause

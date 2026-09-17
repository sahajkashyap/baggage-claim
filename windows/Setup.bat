@echo off
setlocal
cd /d "%~dp0"
title Baggage Claim setup
echo.
echo  Baggage Claim setup
echo  ===================
echo.

rem ---- 1. Google Drive for desktop --------------------------------------------
set DRIVEOK=
if exist "%ProgramFiles%\Google\Drive File Stream" set DRIVEOK=1
if exist "%LOCALAPPDATA%\Google\DriveFS" set DRIVEOK=1
if defined DRIVEOK goto drive_present
echo  Google Drive for desktop is not installed. Installing it now (about a minute)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://dl.google.com/drive-file-stream/GoogleDriveSetup.exe' -OutFile \"$env:TEMP\GoogleDriveSetup.exe\""
if not exist "%TEMP%\GoogleDriveSetup.exe" ( echo  Could not download Google Drive. Check the internet connection and run Setup again. & pause & exit /b 1 )
"%TEMP%\GoogleDriveSetup.exe" --silent --desktop_shortcut
echo.
echo  Google Drive is installed. When it opens, SIGN IN WITH YOUR SCHOOL ACCOUNT.
echo  Wait until the class folder appears in File Explorer under "My Drive", then double-click Setup again.
echo.
pause
exit /b 0
:drive_present
echo  Google Drive for desktop: installed.

rem ---- 2. Self-check: reader, folders, class list -----------------------------
echo.
BaggageClaim.exe --check
if errorlevel 1 (
  echo.
  echo  Something above says FAIL or WARN. Usual causes:
  echo   - Google Drive is not signed in yet, or the class folder has not synced. Open Drive, wait, run Setup again.
  echo   - The class folder is not shared with this account yet.
  echo.
  pause
  exit /b 1
)

rem ---- 3. Start at login (Startup folder shortcut; needs no admin rights) -----
if not exist logs mkdir logs
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%STARTUP%\Baggage Claim Watcher.lnk'); $s.TargetPath='%~dp0BaggageClaimWatcher.exe'; $s.WorkingDirectory='%~dp0'; $s.Description='Baggage Claim watcher'; $s.Save()"
taskkill /IM BaggageClaimWatcher.exe /F >nul 2>&1
start "" "%~dp0BaggageClaimWatcher.exe"
echo.
echo  READY. The watcher is running now and will start every time you log in.
echo  Photos shared to Wall Inbox will be sorted into the children's folders.
echo  Progress is written to logs\watch.log in this folder.
echo.
pause
exit /b 0

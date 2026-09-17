@echo off
rem Baggage Claim watcher, Windows. Leave this window open (minimised is fine).
cd /d "%~dp0"
if not exist settings.local.json (
  echo No settings.local.json yet. Copy settings.example.json to settings.local.json and edit the paths.
  pause & exit /b 1
)
python baggage_claim.py --watch --settings settings.local.json --log logs\watch.log
pause

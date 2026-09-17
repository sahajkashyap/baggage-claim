@echo off
cd /d "%~dp0"
python baggage_claim.py --check
pause

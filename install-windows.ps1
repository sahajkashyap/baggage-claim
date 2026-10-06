# Baggage Claim, Windows install. Right-click > Run with PowerShell (or: powershell -ExecutionPolicy Bypass -File install-windows.ps1)
# Installs the Python packages, checks the reader, and registers the watcher to start at logon with no window.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
Write-Host "Baggage Claim: Windows setup" -ForegroundColor Cyan

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Write-Host "Python is not installed. Install it from python.org (tick 'Add python.exe to PATH'), then run this again." -ForegroundColor Red; exit 1 }
python -m pip install --quiet --upgrade pip
python -m pip install --quiet pillow numpy scipy winsdk pillow-heif
if ($LASTEXITCODE -ne 0) { Write-Host "pip install failed" -ForegroundColor Red; exit 1 }

if (-not (Test-Path settings.local.json)) {
  Copy-Item settings.example.json settings.local.json
  Write-Host "Created settings.local.json from the example. Edit the paths in it, then run this again." -ForegroundColor Yellow
  notepad settings.local.json
  exit 0
}

python baggage_claim.py --check
if ($LASTEXITCODE -ne 0) { Write-Host "Fix the FAIL lines above, then run this again." -ForegroundColor Red; exit 1 }

New-Item -ItemType Directory -Force -Path logs | Out-Null
$pyw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pyw) { $pyw = $py.Source }
$action  = New-ScheduledTaskAction -Execute $pyw -Argument "`"$here\baggage_claim.py`" --watch --settings `"$here\settings.local.json`" --log `"$here\logs\watch.log`"" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3650) -StartWhenAvailable
Register-ScheduledTask -TaskName "Baggage Claim Watcher" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "Baggage Claim Watcher"
Start-Sleep -Seconds 3
$state = (Get-ScheduledTask -TaskName "Baggage Claim Watcher").State
Write-Host "Watcher registered to start at logon. State now: $state" -ForegroundColor Green
Write-Host "Log: $here\logs\watch.log    To stop: Unregister-ScheduledTask -TaskName 'Baggage Claim Watcher'"

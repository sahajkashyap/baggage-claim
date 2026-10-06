#!/bin/zsh
# Baggage Claim, Mac setup. Double-click me. Installs nothing system-wide: one small
# launchd job in your own Library folder starts the watcher when you log in and starts
# it again if it ever stops. macOS asks once whether Baggage Claim may read your Google
# Drive folder; click Allow.
HERE_DIR="$(cd "$(dirname "$0")" && pwd -P)"
# In the one-click bundle everything sits in one folder. Run from the source
# checkout, this file lives in mac/ and the tool folder is one level up.
TOOL="$HERE_DIR"; [ -f "$TOOL/watch.sh" ] || TOOL="$(cd "$HERE_DIR/.." && pwd -P)"
cd "$TOOL"
# BAGGAGE_NONINTERACTIVE=1 lets a script run this without waiting for a key.
pause() { [ -n "${BAGGAGE_NONINTERACTIVE:-}" ] || read -k1 "?Press any key to close."; }
[ -n "${BAGGAGE_NONINTERACTIVE:-}" ] || clear
echo; echo "  Baggage Claim setup"; echo "  ==================="; echo
# Apple chip only: both programs in this bundle are built for Apple chips.
if [ -x ./baggage-claim ] && [ "$(sysctl -in hw.optional.arm64 2>/dev/null)" != 1 ]; then
  echo; echo "  NOT READY: this Mac has an Intel chip. Baggage Claim for Mac runs only on a Mac with an"
  echo "  Apple chip (Apple menu > About This Mac says 'Chip  Apple M1' or later). Nothing was"
  echo "  changed on this Mac. Tell the person who sent you Baggage Claim: this Mac needs a different build."
  echo; pause; exit 1
fi
# 1. Google Drive for desktop
if [ ! -d "/Applications/Google Drive.app" ]; then
  echo "  Google Drive for desktop is not installed. Downloading it (about a minute)..."
  curl -sSL -o /tmp/GoogleDrive.dmg "https://dl.google.com/drive-file-stream/GoogleDrive.dmg" && open /tmp/GoogleDrive.dmg
  echo; echo "  A window with the Google Drive installer will open. Double-click GoogleDrive.pkg, finish it,"
  echo "  open Google Drive, SIGN IN WITH YOUR SCHOOL ACCOUNT, then double-click Setup again."; echo
  pause; exit 0
fi
echo "  Google Drive for desktop: installed."
# 2. clear the download quarantine on our own files so macOS lets them run
xattr -dr com.apple.quarantine . 2>/dev/null
# 3. self-check (the bundled program, or the source with the Mac's own Python)
if [ -x ./baggage-claim ]; then CHECK=(./baggage-claim --check); else CHECK=(/usr/bin/python3 baggage_claim.py --check); fi
echo; "${CHECK[@]}"
if [ $? -ne 0 ]; then
  echo; echo "  Something above says FAIL or WARN. Usual causes:"
  echo "   - Google Drive is not signed in yet, or the class folder has not synced."
  echo "   - The class folder is in 'Shared with me': on drive.google.com right-click it, Organize, Add shortcut, My Drive."
  echo "   - You clicked Don't Allow when macOS asked about Terminal. Go to System Settings > Privacy & Security >"
  echo "     Files and Folders, and under Terminal turn on Google Drive and Desktop Folder. Close Terminal, run Setup again."
  echo; pause; exit 1
fi
# 4. start at login, restart if it stops, and start now: a launchd job (see autostart.sh)
echo
if ! "$HERE_DIR/autostart.sh" install "$TOOL"; then
  echo; echo "  NOT READY: the watcher could not be set to start with the Mac."; echo; pause; exit 1
fi
sleep 5
echo; "$HERE_DIR/autostart.sh" status "$TOOL"
echo; echo "  READY. If macOS asks whether Terminal or Baggage Claim may access your Google Drive or Desktop, click Allow."
echo "  Progress is written to logs/watch.log in this folder. 'Check Setup.command' shows whether it is alive."
echo; pause

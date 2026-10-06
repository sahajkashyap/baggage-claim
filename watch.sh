#!/bin/zsh
# Baggage Claim in watch mode against the folders named in settings.local.json.
# Started by launchd through "Baggage Claim.app" (see mac/autostart.sh), or by
# "Start Watcher.command" in a Terminal window.
#
# A second class watched by the same Mac has a launchd job of its own, which
# names that class's settings file and log:   watch.sh <settings file> <log file>
# With nothing after the name it is settings.local.json and logs/watch.log.
cd "$(dirname "$0")"
SETTINGS="${1:-settings.local.json}"
LOG="${2:-logs/watch.log}"
mkdir -p logs "$(dirname "$LOG")"
say() { print -r -- "$(date '+%b %d %I:%M %p'): $1" | tee -a "$LOG"; }
# Under launchd a quick exit is tried again after 30 seconds. Wait first, so a
# broken setup writes one line every ten minutes, not one every 30 seconds.
pause_then_exit() { [ -n "${BAGGAGE_LAUNCHD:-}" ] && sleep 600; exit 1; }
if [ -x ./baggage-claim ]; then
  PROG=(./baggage-claim)                       # the one-click bundle: Python and the name reader inside
else
  if [ ! -x vision ]; then                     # from source: build the name reader once
    swiftc -O vision.swift -o vision 2>>"$LOG"
    if [ ! -x vision ]; then
      say "The name reader is not built yet and Apple's compiler is not on this Mac, so the watcher cannot start. Open Terminal in this folder and run:  xcode-select --install   and then:  swiftc -O vision.swift -o vision"
      pause_then_exit
    fi
  fi
  PROG=(/usr/bin/python3 baggage_claim.py)
fi
if [ ! -f "$SETTINGS" ]; then
  if [ "$SETTINGS" = settings.local.json ]; then
    say "No settings.local.json in this folder yet, so there is nothing to watch. Copy it from the class's Drive folder into this folder; the watcher will pick it up by itself."
  else
    say "The settings file for this class is missing, so there is nothing to watch: $SETTINGS  Put the file back; the watcher will pick it up by itself."
  fi
  pause_then_exit
fi
exec "${PROG[@]}" --watch --settings "$SETTINGS" --log "$LOG"

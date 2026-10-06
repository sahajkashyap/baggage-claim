#!/bin/zsh
# Starts the Baggage Claim watcher in this Terminal window. Leave the window open
# (minimised is fine). Close it, or press Ctrl+C, to stop watching.
# When the background watcher (the launchd job from mac/Setup.command) is already
# running, this follows its log instead of starting a second watcher.
cd "$(dirname "$0")"
mkdir -p logs; touch logs/watch.log
if ./mac/autostart.sh loaded; then
  echo "The watcher is already running in the background. This window follows its log."
  echo "Close the window (or press Ctrl+C) to stop looking; the watcher keeps going."; echo
  tail -n 20 -f logs/watch.log
else
  exec ./watch.sh
fi

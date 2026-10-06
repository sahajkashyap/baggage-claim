#!/bin/zsh
# Shows the watcher working, in this window. When the background watcher (the
# launchd job from Setup.command) is already running, this follows its log rather
# than starting a second watcher.
HERE_DIR="$(cd "$(dirname "$0")" && pwd -P)"
TOOL="$HERE_DIR"; [ -f "$TOOL/watch.sh" ] || TOOL="$(cd "$HERE_DIR/.." && pwd -P)"
cd "$TOOL"; xattr -dr com.apple.quarantine . 2>/dev/null
mkdir -p logs; touch logs/watch.log
if "$HERE_DIR/autostart.sh" loaded; then
  echo "The watcher is already running in the background. This window follows its log."
  echo "Close the window (or press Ctrl+C) to stop looking; the watcher keeps going."; echo
  tail -n 20 -f logs/watch.log
else
  exec /bin/zsh ./watch.sh
fi

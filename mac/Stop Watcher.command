#!/bin/zsh
# Stops the watcher and its launchd job, so it does not come back at login.
HERE_DIR="$(cd "$(dirname "$0")" && pwd -P)"
"$HERE_DIR/autostart.sh" remove
read -k1 "?Press any key to close."

#!/bin/zsh
# Stops the watcher and its launchd job, so it does not come back at login or
# after 30 seconds. Double-click mac/Setup.command to turn it back on.
cd "$(dirname "$0")"
./mac/autostart.sh remove
read -k1 "?Press any key to close."

#!/bin/zsh
# Starts the Baggage Claim watcher in this Terminal window. Leave the window open
# (minimised is fine). Close it, or press Ctrl+C, to stop watching.
cd "$(dirname "$0")"
exec ./watch.sh

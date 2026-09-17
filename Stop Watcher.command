#!/bin/zsh
pkill -f "baggage_claim.py --watch" && echo "Mac watcher stopped." || echo "No Mac watcher was running."
read -k1 "?Press any key to close."

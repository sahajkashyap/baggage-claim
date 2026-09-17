#!/bin/zsh
# Baggage Claim in watch mode against the folders named in settings.local.json.
# Run from "Start Watcher.command" or the "Baggage Claim Watcher" app.
cd "$(dirname "$0")"
[ -x vision ] || swiftc -O vision.swift -o vision
[ -f settings.local.json ] || { echo "No settings.local.json yet. Copy settings.example.json and edit the paths."; exit 1; }
mkdir -p logs
exec /usr/bin/python3 baggage_claim.py --watch --settings settings.local.json --log logs/watch.log

#!/bin/zsh
cd "$(dirname "$0")"
[ -x vision ] || swiftc -O vision.swift -o vision
python3 -m coverage run --source=. --omit='tests/*' -m unittest discover -s tests -v 2>&1 | tail -25
python3 -m coverage report -m
echo; read -k1 "?Press any key to close."

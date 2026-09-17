#!/bin/zsh
# One-off run: sorts whatever is in the inbox named in settings.local.json (or ./inbox if none).
cd "$(dirname "$0")"
[ -x vision ] || swiftc -O vision.swift -o vision
echo "Baggage Claim"
if [ -f settings.local.json ]; then
  read "project?What is the work? (Enter keeps the default in settings): "
  read "grade?Grade? (Enter keeps the default in settings): "
  python3 baggage_claim.py --settings settings.local.json ${project:+--project "$project"} ${grade:+--grade "$grade"} "$@"
else
  read "project?What is the work? (e.g. Self-Portrait) [Artwork]: "
  read "grade?Grade? (e.g. Kindergarten) []: "
  python3 baggage_claim.py --project "${project:-Artwork}" --grade "$grade" "$@"
  open sorted 2>/dev/null
fi
echo; read -k1 "?Done. Press any key to close."

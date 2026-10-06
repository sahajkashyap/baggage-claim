#!/bin/zsh
# Set up a class from its class list, on this Mac only. See class_setup.py.
# The names are read here, shown to the person at this Mac to check, and used
# to make the folders. They are never printed in this window: counts only.
cd "$(dirname "$0")"
[ -x vision ] || swiftc -O vision.swift -o vision 2>/dev/null
LIST=".tmp/class list - check me.txt"
mkdir -p .tmp

ask() {  # ask "question" "default answer" -> the typed answer, or nothing if Cancel
  osascript -e "text returned of (display dialog \"$1\" default answer \"$2\" with title \"Set up a class\")" 2>/dev/null
}
say_done() {
  osascript -e "display dialog \"$1\" buttons {\"OK\"} default button 1 with title \"Set up a class\"" >/dev/null 2>&1
}
finish() { rm -f "$LIST"; exit "${1:-0}"; }

FROM=$(osascript -e 'button returned of (display dialog "Where is the class list?\n\nA screenshot, a Word file or a text file: choose \"A file\".\nA Google Doc or Sheet: select the names, copy them (Command-C), then choose \"What I copied\"." buttons {"Cancel", "A file", "What I copied"} default button 3 with title "Set up a class")' 2>/dev/null) || finish

if [ "$FROM" = "A file" ]; then
  SRC=$(osascript -e 'POSIX path of (choose file with prompt "Choose the class list: a screenshot, a Word file or a text file")' 2>/dev/null) || finish
  OUT=$(python3 class_setup.py prepare --source "$SRC" --out "$LIST" 2>&1)
else
  OUT=$(python3 class_setup.py prepare --out "$LIST" 2>&1)
fi
if [ $? -ne 0 ]; then say_done "${OUT//\"/'}"; finish 1; fi

open -e "$LIST"
osascript -e "button returned of (display dialog \"$OUT\n\nThe list is open in TextEdit. One child per line, written the way it will be on the name labels. Fix any name that was misread, delete any line that is not a child, then save (Command-S).\n\nThen click Continue.\" buttons {\"Cancel\", \"Continue\"} default button 2 with title \"Set up a class\")" >/dev/null 2>&1 || finish
osascript -e 'tell application "TextEdit" to close (every document whose name is "class list - check me.txt") saving yes' >/dev/null 2>&1

CLASS=$(ask "Name of the class folder, for example: Grade 2 - Room 5 2026 to 2027" "") || finish
[ -n "$CLASS" ] || finish
GRADE=$(ask "Grade, for the file names (you can leave this empty)" "") || finish
PROJECT=$(ask "The first project, the folder each child's work goes into" "Artwork") || finish

OUT=$(python3 class_setup.py build --list "$LIST" --class-name "$CLASS" --grade "$GRADE" --project "${PROJECT:-Artwork}" 2>&1)
CODE=$?
echo "$OUT"
say_done "${OUT//\"/'}"
finish $CODE

#!/bin/zsh
# Baggage Claim on a Mac: keep the watcher running with launchd, the part of macOS
# that starts things at login and starts them again if they stop. Setup.command,
# Check Setup.command and the Start/Stop scripts call this; it is not meant to be
# double-clicked.
#
#   autostart.sh install <tool folder>   write the launchd job for this folder and start it
#   autostart.sh remove                  stop every job and forget it (nothing starts at login)
#   autostart.sh status <tool folder>    say what is really running, from launchd and the log
#   autostart.sh loaded                  exit 0 if the launchd job is loaded, 1 if not
#   autostart.sh render <tool folder>    print the job file (the tests read this)
#
# One job watches one class. The job above is for the class in settings.local.json.
# A Mac that watches a second class has a second job, named for that class's
# settings file, with a log of its own (logs/<class>.log):
#   autostart.sh install <tool folder> <settings file>   add the job for that class
#   autostart.sh remove <tool folder> <settings file>    stop that one class only
#   autostart.sh render <tool folder> <settings file>
# A watcher started by hand in Terminal (nohup ... &) is not a job: it ends when the
# Mac restarts and nothing starts it again, which is why a class gets a job instead.
#
# The job runs "Baggage Claim.app" (a tiny helper built from mac/launcher.swift),
# which runs watch.sh. macOS only asks "may this program read your Google Drive
# folder?" for a real app; a plain script started by launchd is refused silently.
set -u
LABEL="com.sahajkashyap.baggage-claim"
AGENTS="${BAGGAGE_LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
PLIST="$AGENTS/$LABEL.plist"
LAUNCHCTL="${BAGGAGE_LAUNCHCTL:-/bin/launchctl}"
DOMAIN="gui/$(id -u)"
APP_NAME="Baggage Claim.app"
LAUNCHER_REL="$APP_NAME/Contents/MacOS/Baggage Claim"
OLD_LOGIN_ITEM="Baggage Claim Watcher"
SELF="${0:A}"            # this file, wherever the folder is: mac/autostart.sh from source, autostart.sh in the bundle

xml_escape() { local s="$1"; s="${s//&/&amp;}"; s="${s//</&lt;}"; s="${s//>/&gt;}"; print -r -- "$s"; }

abs_dir() { (cd "$1" 2>/dev/null && pwd -P) }

abs_file() { local d; d="$(abs_dir "${1:h}")" || return 1; [ -f "$d/${1:t}" ] || return 1; print -r -- "$d/${1:t}"; }

# ---- one job per class ---------------------------------------------------------
# The class a settings file is for: its file name without ".json".
class_of() { print -r -- "${${1:t}%.json}"; }

# The launchd label for a settings file: letters, digits and dashes only, and a
# number made from the whole name so two classes never share a job.
label_for() {
  [ -n "${1:-}" ] || { print -r -- "$LABEL"; return 0; }
  local name slug
  name="$(class_of "$1")"
  slug="$(print -rn -- "$name" | LC_ALL=C tr -cs 'A-Za-z0-9' '-' | LC_ALL=C tr 'A-Z' 'a-z')"
  slug="${slug#-}"; slug="${slug%-}"
  print -r -- "$LABEL.class.${slug:-class}-$(print -rn -- "$name" | cksum | cut -d' ' -f1)"
}

# The settings file as the job will be given it, or nothing for settings.local.json
# in the tool folder, which is the first job's class.
settings_for() {   # settings_for <tool folder> <settings file>
  local s; s="$(abs_file "$2")" || return 1
  [ "$s" = "$1/settings.local.json" ] && s=""
  print -r -- "$s"
}

plist_value() { /usr/libexec/PlistBuddy -c "Print :$2" "$1" 2>/dev/null; }

class_plists() { local p; for p in "$AGENTS"/"$LABEL".class.*.plist(N); do print -r -- "$p"; done; }

# The Wall Inbox a settings file names. Two settings files with the same one are the same class.
inbox_of() { sed -n 's/.*"inbox"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$1" 2>/dev/null | head -1 | sed 's:[/ ]*$::'; }

# Says which settings file already has a job for the same Wall Inbox, if any.
same_class_already_watched() {   # <tool folder> <settings file> <its label>
  local mine other p s; mine="$(inbox_of "$2")"
  [ -n "$mine" ] || return 1
  if [ -f "$1/settings.local.json" ] && [ "$(inbox_of "$1/settings.local.json")" = "$mine" ]; then
    print -r -- "settings.local.json"; return 0
  fi
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    [ "${p:t:r}" = "$3" ] && continue
    s="$(plist_value "$p" EnvironmentVariables:BAGGAGE_SETTINGS)"
    if [ -n "$s" ] && [ "$(inbox_of "$s")" = "$mine" ]; then print -r -- "$s"; return 0; fi
  done <<< "$(class_plists)"
  return 1
}

# Watcher processes that were started with this settings file, by launchd or by hand.
watcher_pids() {
  ps -axww -o pid=,command= | grep -E 'baggage_claim\.py --watch|baggage-claim --watch' \
    | grep -F -- "--settings $1 " | awk '{print $1}' | tr '\n' ' ' | sed 's/ *$//'
}

# The line to type in Terminal to have this Mac watch a class.
install_line() { print -r -- "${(q-)SELF} install ${(q-)1} ${(q-)2}"; }

# ---- the job file ------------------------------------------------------------
render() {
  local tool; tool="$(abs_dir "$1")" || { echo "no such folder: $1" >&2; return 1; }
  local settings=""
  if [ -n "${2:-}" ]; then
    settings="$(settings_for "$tool" "$2")" || { echo "no such settings file: $2" >&2; return 1; }
  fi
  local label; label="$(label_for "$settings")"
  local launcher="$tool/$LAUNCHER_REL"
  local -a prog
  if [ -x "$launcher" ]; then
    prog=("$launcher" /bin/zsh "$tool/watch.sh")
  else
    # no helper app: launchd runs the script itself. It works only if macOS has
    # been told to let it read the Drive folder (see status / the README).
    prog=(/bin/zsh "$tool/watch.sh")
  fi
  # a second class: watch.sh is told which settings file and which log are this class's
  [ -n "$settings" ] && prog+=("$settings" "$tool/logs/$(class_of "$settings").log")
  print -r -- '<?xml version="1.0" encoding="UTF-8"?>'
  print -r -- '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
  print -r -- '<plist version="1.0">'
  print -r -- '<dict>'
  print -r -- "  <key>Label</key><string>$(xml_escape "$label")</string>"
  print -r -- '  <key>ProgramArguments</key>'
  print -r -- '  <array>'
  local p; for p in "${prog[@]}"; do print -r -- "    <string>$(xml_escape "$p")</string>"; done
  print -r -- '  </array>'
  print -r -- "  <key>WorkingDirectory</key><string>$(xml_escape "$tool")</string>"
  print -r -- '  <key>RunAtLoad</key><true/>'
  print -r -- '  <key>KeepAlive</key><true/>'
  print -r -- '  <key>ThrottleInterval</key><integer>30</integer>'
  print -r -- '  <key>EnvironmentVariables</key>'
  if [ -n "$settings" ]; then
    print -r -- "  <dict><key>BAGGAGE_LAUNCHD</key><string>1</string><key>BAGGAGE_SETTINGS</key><string>$(xml_escape "$settings")</string></dict>"
  else
    print -r -- '  <dict><key>BAGGAGE_LAUNCHD</key><string>1</string></dict>'
  fi
  print -r -- "  <key>StandardOutPath</key><string>$(xml_escape "$tool/logs/launchd.log")</string>"
  print -r -- "  <key>StandardErrorPath</key><string>$(xml_escape "$tool/logs/launchd.log")</string>"
  print -r -- '</dict>'
  print -r -- '</plist>'
}

# ---- the helper app ------------------------------------------------------------
build_launcher() {
  # Build "Baggage Claim.app" next to watch.sh from mac/launcher.swift when the
  # source is there and the app is missing or older. The one-click bundle ships
  # it prebuilt, so on a teacher's Mac this does nothing.
  local tool="$1" src="$1/mac/launcher.swift" bin="$1/$LAUNCHER_REL"
  [ -f "$src" ] || return 0
  if [ -x "$bin" ] && [ ! "$src" -nt "$bin" ]; then return 0; fi
  echo "  Building the small helper app that lets the watcher ask for Drive permission..."
  mkdir -p "$(dirname "$bin")"
  if ! swiftc -O "$src" -o "$bin" 2>&1 | sed 's/^/    /'; then :; fi
  if [ ! -x "$bin" ]; then
    echo "  Could not build it (Apple's compiler is not installed: in Terminal run xcode-select --install)."
    echo "  The watcher will still be set up, but macOS may refuse to let it read the Drive folder."
    return 1
  fi
  write_launcher_plist "$tool/$APP_NAME/Contents/Info.plist"
  echo -n "APPL????" > "$tool/$APP_NAME/Contents/PkgInfo"
  codesign --force --sign - "$tool/$APP_NAME" >/dev/null 2>&1 || true
  echo "  Built $APP_NAME."
}

write_launcher_plist() {
  cat > "$1" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>Baggage Claim</string>
  <key>CFBundleIdentifier</key><string>com.sahajkashyap.baggage-claim.watcher</string>
  <key>CFBundleName</key><string>Baggage Claim</string>
  <key>CFBundleDisplayName</key><string>Baggage Claim</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSDesktopFolderUsageDescription</key><string>Baggage Claim reads wall photos from your Google Drive folder and files each child's work into the child's folder.</string>
  <key>NSDocumentsFolderUsageDescription</key><string>Baggage Claim reads wall photos from your Google Drive folder and files each child's work into the child's folder.</string>
</dict></plist>
EOF
}

# ---- launchd ------------------------------------------------------------------
loaded() { "$LAUNCHCTL" print "$DOMAIN/${1:-$LABEL}" >/dev/null 2>&1; }

job_pid() { "$LAUNCHCTL" print "$DOMAIN/${1:-$LABEL}" 2>/dev/null | sed -n 's/^[[:space:]]*pid = \([0-9]*\).*/\1/p' | head -1; }

job_state() { "$LAUNCHCTL" print "$DOMAIN/${1:-$LABEL}" 2>/dev/null | sed -n 's/^[[:space:]]*state = \(.*\)$/\1/p' | head -1; }

stop_old_ways() {
  # the Login Items applet, the windowless PyInstaller watcher, and any watcher started by hand
  pkill -f "Baggage Claim Watcher" 2>/dev/null
  pkill -f "baggage_claim.py --watch" 2>/dev/null
  pkill -f "baggage-claim --watch" 2>/dev/null
  return 0
}

remove_login_item() {
  # The old way: an applet in System Settings > General > Login Items. macOS may
  # refuse to let a script touch Login Items; then say what to do by hand.
  local names
  if ! names="$(osascript -e 'tell application "System Events" to get name of every login item' 2>/dev/null)"; then
    echo "  Could not look at Login Items. If '$OLD_LOGIN_ITEM' is listed in System Settings > General > Login Items, remove it there; launchd runs the watcher now."
    return 0
  fi
  if [[ "$names" == *"$OLD_LOGIN_ITEM"* ]]; then
    if osascript -e "tell application \"System Events\" to delete login item \"$OLD_LOGIN_ITEM\"" >/dev/null 2>&1; then
      echo "  Removed the old '$OLD_LOGIN_ITEM' Login Item; launchd runs the watcher now."
    else
      echo "  Could not remove the old '$OLD_LOGIN_ITEM' Login Item. Remove it in System Settings > General > Login Items; launchd runs the watcher now."
    fi
  fi
}

install() {
  local tool; tool="$(abs_dir "$1")" || { echo "no such folder: $1" >&2; return 1; }
  [ -f "$tool/watch.sh" ] || { echo "  $tool has no watch.sh; this is not the Baggage Claim folder." >&2; return 1; }
  local settings="" label="$LABEL" plist="$PLIST" same
  if [ -n "${2:-}" ]; then
    settings="$(settings_for "$tool" "$2")" || { echo "  There is no settings file at $2, so nothing was changed." >&2; return 1; }
  fi
  if [ -n "$settings" ]; then
    label="$(label_for "$settings")"; plist="$AGENTS/$label.plist"
    if same="$(same_class_already_watched "$tool" "$settings" "$label")"; then
      echo "  This Mac already watches that class: $same names the same Wall Inbox." >&2
      echo "  Two watchers for one class file every piece twice, so nothing was changed." >&2
      return 1
    fi
  fi
  mkdir -p "$tool/logs" "$AGENTS"
  build_launcher "$tool" || true
  [ -x "$tool/$LAUNCHER_REL" ] || echo "  No helper app: if the log says macOS is not letting the watcher read the folder, see 'Check Setup'."
  if [ -z "${BAGGAGE_TEST:-}" ]; then
    if [ -z "$settings" ]; then
      stop_old_ways
      remove_login_item
    else
      # a watcher for this class started by hand would keep the job's watcher out; the job replaces it
      local by_hand; by_hand="$(watcher_pids "$settings")"
      [ -n "$by_hand" ] && kill ${=by_hand} 2>/dev/null
    fi
  fi
  "$LAUNCHCTL" bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  render "$tool" "$settings" > "$plist"
  "$LAUNCHCTL" enable "$DOMAIN/$label" >/dev/null 2>&1 || true
  if "$LAUNCHCTL" bootstrap "$DOMAIN" "$plist" 2>/dev/null; then :
  elif "$LAUNCHCTL" load -w "$plist" 2>/dev/null; then :          # older macOS
  else
    echo "  macOS would not start the watcher job. Log out and back in, then double-click Setup again." >&2
    return 1
  fi
  if [ -n "$settings" ]; then
    echo "  The watcher for the class '$(class_of "$settings")' now starts with the Mac and is restarted if it ever stops (launchd job $label)."
    echo "  What it does is written to logs/$(class_of "$settings").log in the Baggage Claim folder. 'Check Setup.command' shows whether it is alive."
  else
    echo "  The watcher now starts with the Mac and is restarted if it ever stops (launchd job $LABEL)."
  fi
  return 0
}

remove_class_job() {   # <job file>: stop one class's job, forget it, and say how to bring it back
  local p="$1" label="${1:t:r}" s t name
  s="$(plist_value "$p" EnvironmentVariables:BAGGAGE_SETTINGS)"
  t="$(plist_value "$p" WorkingDirectory)"
  name="$(class_of "${s:-$label}")"
  "$LAUNCHCTL" bootout "$DOMAIN/$label" >/dev/null 2>&1 || "$LAUNCHCTL" unload "$p" >/dev/null 2>&1 || true
  rm -f "$p"
  if [ -z "${BAGGAGE_TEST:-}" ] && [ -n "$s" ]; then
    local left; left="$(watcher_pids "$s")"
    [ -n "$left" ] && kill ${=left} 2>/dev/null
  fi
  echo "  Watcher for the class '$name' stopped. It will no longer start at login."
  [ -n "$s" ] && [ -n "$t" ] && echo "  To have this Mac watch that class again, open Terminal and run:  $(install_line "$t" "$s")"
  return 0
}

remove() {
  local p
  if [ -n "${2:-}" ]; then            # one class only: remove <tool folder> <settings file>
    local tool settings
    tool="$(abs_dir "$1")" || { echo "no such folder: $1" >&2; return 1; }
    settings="$(settings_for "$tool" "$2")" || { echo "  There is no settings file at $2, so nothing was changed." >&2; return 1; }
    if [ -n "$settings" ]; then
      p="$AGENTS/$(label_for "$settings").plist"
      [ -f "$p" ] || { echo "  This Mac has no watcher job for the class '$(class_of "$settings")'. Nothing was changed."; return 0; }
      remove_class_job "$p"
      return 0
    fi
  else                                # everything: the other classes first, then the first job
    while IFS= read -r p; do
      [ -n "$p" ] && remove_class_job "$p"
    done <<< "$(class_plists)"
  fi
  if loaded; then
    "$LAUNCHCTL" bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || "$LAUNCHCTL" unload "$PLIST" >/dev/null 2>&1 || true
    echo "  Watcher stopped."
  else
    echo "  The watcher was not running as a launchd job."
  fi
  rm -f "$PLIST"
  if [ -z "${BAGGAGE_TEST:-}" ]; then
    if [ -n "${2:-}" ]; then
      local main_pids; main_pids="$(watcher_pids settings.local.json) $(watcher_pids "$tool/settings.local.json")"
      [ -n "${main_pids// /}" ] && kill ${=main_pids} 2>/dev/null
    else
      stop_old_ways
    fi
  fi
  echo "  It will no longer start at login. Double-click Setup.command to turn it back on."
}

# ---- the truth ----------------------------------------------------------------
status() {
  local tool; tool="$(abs_dir "$1")" || { echo "no such folder: $1" >&2; return 1; }
  local ok=0
  status_of_one_class "$tool" "" || ok=1
  other_classes "$tool" || ok=1
  local slog="$tool/logs/launchd.log"
  if [ -f "$slog" ] && grep -q "Traceback\|could not start" "$slog"; then
    echo "  System log has an error; last lines of $slog:"
    grep -v '^$' "$slog" | tail -3 | sed 's/^/    /'
  fi
  return $ok
}

# Every other class: the ones this Mac has a job for, each with its own four lines,
# and the ones that have a settings file in classes/ and no job, said plainly, so a
# class nobody is watching is not mistaken for one that is.
other_classes() {   # <tool folder>
  local tool="$1" ok=0 p s f by_hand
  local -a watched; watched=()
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    [ "$(plist_value "$p" WorkingDirectory)" = "$tool" ] || continue
    s="$(plist_value "$p" EnvironmentVariables:BAGGAGE_SETTINGS)"
    [ -n "$s" ] || continue
    watched+=("$s")
    echo; echo "  This Mac also watches the class '$(class_of "$s")':"
    status_of_one_class "$tool" "$s" || ok=1
  done <<< "$(class_plists)"
  for f in "$tool"/classes/*.json(N); do
    (( ${watched[(Ie)$f]} )) && continue
    [ -f "$AGENTS/$(label_for "$f").plist" ] && continue
    same_class_already_watched "$tool" "$f" "$(label_for "$f")" >/dev/null && continue
    echo; echo "  The class '$(class_of "$f")' has a settings file on this Mac, and this Mac does NOT watch it:"
    by_hand="$(watcher_pids "$f")"
    if [ -n "$by_hand" ]; then
      echo "    a watcher started by hand is running for it now (process $by_hand), but nothing starts it again"
      echo "    after the Mac restarts or you log out."
    else
      echo "    no watcher is running for it, and none starts at login. Photos saved to its Wall Inbox wait"
      echo "    until another computer sorts them."
    fi
    echo "    If this Mac should watch it, open Terminal and run:  $(install_line "$tool" "$f")"
    echo "    If another computer watches it, leave it as it is."
  done
  return $ok
}

status_of_one_class() {   # <tool folder> <settings file, or nothing for settings.local.json>
  local tool="$1" settings="${2:-}" label log pids
  local ok=0
  label="$(label_for "$settings")"
  if loaded "$label"; then
    echo "  Starts with the Mac: yes (launchd job $label is loaded, state: $(job_state "$label"), process $(job_pid "$label"))"
  elif [ -n "$settings" ]; then
    echo "  Starts with the Mac: NO. The launchd job is not loaded. In Terminal run:  $(install_line "$tool" "$settings")"; ok=1
  else
    echo "  Starts with the Mac: NO. The launchd job is not loaded. Double-click Setup.command."; ok=1
  fi
  if [ -n "$settings" ]; then
    pids="$(watcher_pids "$settings")"
    log="$tool/logs/$(class_of "$settings").log"
  else
    pids="$(print -r -- "$(watcher_pids settings.local.json) $(watcher_pids "$tool/settings.local.json")" | sed 's/^ *//; s/ *$//')"
    log="$tool/logs/watch.log"
  fi
  if [ -n "$pids" ]; then
    echo "  Watching right now: yes (process $pids)"
  else
    echo "  Watching right now: NO. No watcher process is alive."; ok=1
  fi
  if [ -f "$log" ]; then
    echo "  Log last changed: $(stat -f '%Sm' -t '%b %d %Y %I:%M %p' "$log")"
    local last; last="$(grep -E 'watching |control tower for |waiting|pieces, |another watcher|another control tower|not letting|nothing to watch|name reader|could not|error' "$log" | tail -1)"
    [ -n "$last" ] && echo "  Last log line: ${last:0:300}"
    if grep -q "macOS is not letting this program read" "$log" && tail -3 "$log" | grep -q "macOS is not letting this program read"; then
      echo "  PERMISSION NEEDED: macOS has not let the watcher read the Drive folder. If a dialog asked whether"
      echo "  Baggage Claim may access Google Drive, click Allow. Otherwise open System Settings > Privacy & Security >"
      echo "  Files and Folders (or Full Disk Access), find Baggage Claim, and turn Google Drive on."; ok=1
    fi
  else
    echo "  Log: none yet ($log has not been written)."
  fi
  return $ok
}

case "${1:-}" in
  build)   build_launcher "$(abs_dir "${2:?tool folder}")" ;;
  install) install "${2:?tool folder}" "${3:-}" ;;
  remove)  remove "${2:-}" "${3:-}" ;;
  status)  status "${2:?tool folder}" ;;
  loaded)  loaded ;;
  render)  render "${2:?tool folder}" "${3:-}" ;;
  *) echo "usage: autostart.sh install|remove|status|loaded|render <tool folder> [settings file of a second class]" >&2; exit 2 ;;
esac

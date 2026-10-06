#!/bin/zsh
# Says whether this Mac is ready and whether the watcher is really alive: is the
# launchd job loaded, is a watcher process running, when did the log last change,
# and what did it last say.
HERE_DIR="$(cd "$(dirname "$0")" && pwd -P)"
TOOL="$HERE_DIR"; [ -f "$TOOL/watch.sh" ] || TOOL="$(cd "$HERE_DIR/.." && pwd -P)"
cd "$TOOL"; xattr -dr com.apple.quarantine . 2>/dev/null
# Apple chip only: both programs in this bundle are built for Apple chips.
if [ -x ./baggage-claim ] && [ "$(sysctl -in hw.optional.arm64 2>/dev/null)" != 1 ]; then
  echo; echo "  NOT READY: this Mac has an Intel chip. Baggage Claim for Mac runs only on a Mac with an"
  echo "  Apple chip (Apple menu > About This Mac says 'Chip  Apple M1' or later). Nothing was"
  echo "  changed on this Mac. Tell the person who sent you Baggage Claim: this Mac needs a different build."
  echo; read -k1 "?Press any key to close."; exit 1
fi
if [ -x ./baggage-claim ]; then ./baggage-claim --check; else /usr/bin/python3 baggage_claim.py --check; fi
echo
"$HERE_DIR/autostart.sh" status "$TOOL"
echo; read -k1 "?Press any key to close."

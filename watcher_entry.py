"""Entry point for the windowless Windows watcher (BaggageClaimWatcher.exe).
Runs Baggage Claim in watch mode using settings.local.json and logs/watch.log
in the folder the program sits in. No console window, so everything goes to
the log."""
import os
import sys

import baggage_claim as bc

if __name__ == "__main__":
    here = bc.HERE
    settings = os.path.join(here, "settings.local.json")
    log = os.path.join(here, "logs", "watch.log")
    if not os.path.exists(settings):
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write("No settings.local.json next to the program; nothing to watch.\n")
        sys.exit(1)
    sys.exit(bc.main(["--watch", "--settings", settings, "--log", log]))

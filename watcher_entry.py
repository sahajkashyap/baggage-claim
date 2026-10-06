"""Entry point for the windowless Windows watcher (BaggageClaimWatcher.exe).
Runs Baggage Claim in watch mode using settings.local.json and logs/watch.log
in the folder the program sits in. No console window, so everything goes to
the log."""
import os
import sys

import baggage_claim as bc


def no_console_is_fine():
    """A program with no window has no console, and Python then has None
    where its output would go. Anything that writes there stops the watcher.
    Everything the watcher has to say goes to the log; whatever else is
    written goes nowhere, and stops nothing."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
        if getattr(sys, f"__{name}__") is None:
            setattr(sys, f"__{name}__", getattr(sys, name))


if __name__ == "__main__":
    no_console_is_fine()
    here = bc.HERE
    settings = os.path.join(here, "settings.local.json")
    log = os.path.join(here, "logs", "watch.log")
    if not os.path.exists(settings):
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write("No settings.local.json next to the program; nothing to watch.\n")
        sys.exit(1)
    import time
    import traceback
    while True:
        try:
            sys.exit(bc.main(["--watch", "--settings", settings, "--log", log]))
        except SystemExit:
            raise
        except Exception:
            os.makedirs(os.path.dirname(log), exist_ok=True)
            with open(log, "a", encoding="utf-8") as f:
                f.write("watcher error, retrying in 60 s:\n" + traceback.format_exc())
            time.sleep(60)

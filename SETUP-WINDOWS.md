# Baggage Claim on a Windows PC

**The short way:** use the one-click bundle built by GitHub (see the README,
"Windows, one click"): unzip, double-click `Setup.bat`, done. The steps
below are the from-source way, for anyone who wants to run or change the code.

The PC becomes the machine that watches the class's Drive inbox and files
each piece into the child's folder. Teachers only ever use their phone and
Drive. Nothing is uploaded anywhere except into the school's own Google
Drive; the reading of names happens on the PC with the reader built into
Windows 10 and 11.

## One-time setup (about 15 minutes)

1. **Google Drive for desktop.** Install it from google.com/drive/download,
   sign in with the school account, and in its settings choose **Mirror
   files** (not Stream) for My Drive, or right-click the class folder and
   choose *Available offline*. The class folder then appears at
   `C:\Users\<name>\My Drive\<class folder>`.
2. **Python.** Install from python.org (3.10 or newer). On the first
   installer screen tick **Add python.exe to PATH**.
3. **This folder.** Copy the whole `baggage-claim` folder onto the PC, for
   example to `C:\Users\<name>\baggage-claim`. Not inside Drive.
4. **Settings.** Right-click `install-windows.ps1` and choose *Run with
   PowerShell*. The first run creates `settings.local.json` and opens it in
   Notepad. Put in the real paths: the class folder, its `Wall Inbox`, its
   `Unsorted - needs a person` folder, and the class list file. Save.
5. **Run the installer again.** It installs the Python packages, runs a
   self-check (reader present, a test word read back, folders reachable), and
   registers *Baggage Claim Watcher* in Task Scheduler so it starts at logon
   with no window and restarts itself if it stops.

`Check Setup.bat` runs the self-check any time. `Start Watcher.bat` runs the
watcher in a visible window instead, for troubleshooting. Progress is written
to `logs\watch.log`.

## Class list

One first name per line, written the way the teacher writes it on the work.
Two children who share a first name both need a last initial
(`Maya R.` and `Maya T.`). Keep the list in the class's Drive folder so the
teacher can edit it; a new name gets a folder on the next photo.

## What is different from the Mac

Windows has no built-in paper-outline detector, so pieces are found by
colour (construction paper on a pale wall) and by texture (artwork is busy,
wall is flat). Both are the same code that runs on the Mac; the Mac simply
has a third detector on top. The Windows reader handles typed labels and
neat adult printing well. It has not yet been run against a real wall, so
the first real photo on the PC is a test: look at `logs\watch.log` and the
`Unsorted` folder afterwards.

## If something is wrong

- `NOT READY` from the self-check names the missing piece.
- Reader not available: Settings > Time & Language > Language, make sure
  English (United States) is installed with its optional features.
- Photos sit in the inbox unsorted: Drive may still be syncing them. The
  watcher waits until a file stops growing.
- A photo it cannot open goes to `Wall Inbox\failed`.

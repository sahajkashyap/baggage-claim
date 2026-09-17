# Baggage Claim

*Every piece of work returned to its owner.*

Photograph the wall of student work. Get one folder per child. Like the
carousel at the airport: every bag comes back to the person whose name is on it.

A teacher pins twenty pieces of work on the wall with each child's name
written on it. This tool takes a phone photo of that wall (six to eight pieces
per frame works best), finds every paper, straightens it, reads the
teacher-written name, matches it to the class roster, and saves each piece
into `sorted/<Child>/`. It works for artwork and for written work.

**Nothing a child made is sent anywhere to be read.** The sorting runs on a
Mac or a Windows PC in the building, using the text recognition built into
that machine (Apple's Vision framework on a Mac, Windows.Media.Ocr on a PC).
There is no network code in this project and no A.I. service is called. The
only place a piece goes is back into the school's own Google Drive, into the
child's folder. If the tool is unsure about a name, it saves the piece to
`unsorted/` with its best guess and a small strip showing only the name, so a
person can decide without the drawing being sent anywhere.

## Use it

1. Put the class list in `roster.txt`, one child per line, the way the teacher
   writes the name on the work. Two children with the same first name need a
   last initial for both (`Maya R.` and `Maya T.`).
2. Drop wall photos into `inbox/`.
3. Double-click `Baggage Claim.command`. It asks what the work is (for example
   `Self-Portrait`) and the grade (for example `Kindergarten`). Defaults, and
   a Google Drive folder for the per-child folders, live in
   `settings.local.json` (copy `settings.example.json`; ignored by git).

Every child on the roster gets a folder. Each filed piece lands at

```
sorted/Jordan Lee/Self-Portrait/Self-Portrait Kindergarten.jpg
```

A second piece of the same project for the same child becomes
`Self-Portrait Kindergarten 2.jpg`. Unsure ones go to `unsorted/`, and
`run-report.md` lists every piece, what was read, and where it went.
Processed photos move to `inbox/done/`.

Options (run `python3 baggage_claim.py --help`):

| flag | what it does |
|---|---|
| `--out <folder>` | put `sorted/` and `unsorted/` somewhere else, for example inside a synced Google Drive folder |
| `--inbox <folder>` | watch a different folder, for example a Drive folder the phone uploads to |
| `--docx` | also build `sorted/<Child>/<Child> - work.docx`, one page per piece, for sharing or printing |
| `--project <name>` | what the work is; becomes the folder and file name, e.g. `Self-Portrait` |
| `--grade <grade>` | added to the file name, e.g. `Kindergarten` |
| `--watch` | keep running and sort each new photo as it lands |
| `--grid 2x4` | skip detection and split the photo into an even grid |

## First real wall

Twenty-four kindergarten self-portraits on construction paper, two phone
photos of twelve each, typed name labels pinned on or beside the papers, a
row of alphabet cards underneath.

| | |
|---|---|
| Pieces found | 24 of 24 |
| Filed under the right child | 24 |
| Sent to unsorted for a person | 0 |
| Filed under the wrong child | 0 |

The first pass on that wall filed 19, found three junk crops, and missed
three papers. Everything below under "what the real wall taught it" came from
closing that gap.

## Phone to folders, hands off

The teacher photographs the wall and shares the photo to a Google Drive
folder called `Wall Inbox`. A Mac or Windows PC running the watcher sees it
arrive, sorts it, and the pieces appear in each child's Drive folder about ten
seconds later. Doubtful pieces go to a Drive folder the teacher can see and
fix. iPhone HEIC photos are converted on that machine, never online.

- `Start Watcher.command`: runs the watcher in a Terminal window.
- `Baggage Claim Watcher.app` (built locally, not in the repo): the same
  with no window, added to Login Items so it starts with the Mac. macOS asks
  once for permission to read the Drive folder; click Allow.
- `settings.local.json` (ignored by git) names the inbox, the class folder,
  the doubtful-pieces folder, the class list, the default project, and the
  grade. For a new project the teacher makes a folder inside `Wall Inbox`
  named for it and shares the photos there; the folder name becomes the
  project, so nobody edits settings for a new project.

The watching machine has to be awake with Google Drive running. Any Mac or
Windows PC in the building will do, and one machine can watch several
classes. A Chromebook cannot be the watcher, because the sorting runs on the
machine that holds the folders and a Chromebook does not run this kind of
program; a teacher with a Chromebook still uses the tool from their phone
and sees the results in Drive like anyone else.

## How it decides

- **Three paper detectors, two on Windows.** On a Mac, Apple's rectangle
  detector gives straight, perspective-corrected crops but occasionally skips
  a paper or catches only part of one. A colour detector finds construction
  paper against a pale wall and is the primary one when it applies. A texture
  detector (artwork is busy, a wall is flat) is the second opinion and the
  fallback. Windows has no built-in rectangle detector, so there the colour
  and texture detectors carry the job between them. Pieces far smaller than
  the typical piece, or with nothing on them, are dropped.
- **Two name readers.** Each crop is read on its own, and the wall just
  around each piece is read as well, so a label pinned beside the paper is
  found. Every line read near the wall goes to exactly one piece: the one
  it sits inside, or the nearest one. If a crop reads as nothing, it is read
  again at double size with spelling correction on.
- **Roster matching, not free reading.** The reader only has to decide which
  of the class's names it is looking at. Accents, stray marks, and look-alike
  letters from other alphabets are normalised first.
- **Written work.** A name at the top or bottom edge of the page is the
  teacher's label. The same name in the middle is a character in the story
  and is discounted. Everyday words (`the`, `day`, `my`) can never match a name.
- **What the real wall taught it.** Two touching papers of different colours
  merge into one blob; they are split where the paper colour changes,
  measured at the edges of each row where nobody has painted. A label beside
  one paper must not also count for the neighbour. What hangs below a paper
  (the next row, alphabet cards) is not this child's label. Reading a 48
  megapixel photo in one go loses the small labels; reading small regions
  does not.
- **Confidence, not guessing.** A piece is filed only when the match is
  strong and clearly ahead of every other child. Ties, weak matches, and
  unreadable names go to `unsorted/`. Being unsure is a result, not a failure.

## Tests

`Run Tests.command`, or:

```
python3 -m coverage run --source=. --omit='tests/*' -m unittest discover -s tests
python3 -m coverage report -m
```

The tests build fake walls (`tests/make_wall.py`: papers on a wall, scribbles,
names in a handwriting-style font, one unnamed, one blurred, and writing
samples that mention another child's name) and check that every paper is
found, every named one is filed under the right child, and nothing is ever
filed under the wrong one.

## Setup

Runs on a Mac or a Windows PC. Either one can be the machine that watches a
class's Drive inbox; the teachers never need it on their own computer.

**Mac.** Python 3.9+, Pillow, numpy, scipy. The Swift helper builds itself
the first time you run a `.command`, or:

```
swiftc -O vision.swift -o vision
```

**Windows, one click.** Every push builds a Windows bundle on GitHub
(Actions, `build-windows`): `BaggageClaim.exe` and a windowless
`BaggageClaimWatcher.exe` with Python and every package inside, plus
`Setup.bat`, which installs Google Drive for desktop if it is missing, runs
the self-check, and sets the watcher to start at login. Download the
`BaggageClaim-windows` artifact from the latest run, add a
`settings.local.json`, and hand the folder to the teacher. No Python
install. The name reader is the one built into Windows 10 and 11
(`Windows.Media.Ocr`), so the work still never leaves the machine.

**Windows, from source.** See `SETUP-WINDOWS.md`: Google Drive for desktop,
Python from python.org, then `install-windows.ps1`.

Both platforms read `settings.local.json` (copy `settings.example.json`),
which names the inbox, the class folder, the doubtful-pieces folder, the
class list, the project and the grade. Paths may use `{DRIVE}` for wherever
Google Drive's "My Drive" is on that machine. `python baggage_claim.py
--check` (or `BaggageClaim.exe --check`) proves a machine is ready.

Real photos, rosters, and sorted work are ignored by git and must never be
committed. The repo ships with a sample roster of made-up names only.

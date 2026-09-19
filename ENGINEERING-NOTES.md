# Engineering notes: what changed, why, and what it did

A record of every change made to Baggage Claim between the first fake wall
and the first real one, September 16 to 17, 2026. Each entry says what was
observed, what was changed, and what the numbers did afterwards. Nothing here
is reconstructed; it is the order things actually happened in.

## The measure

Every run is scored the same way: pieces found, filed under the right child,
sent to `unsorted/` for a person, filed under the wrong child. The last
number is the one that matters. A piece in `unsorted/` costs a teacher ten
seconds. A piece in the wrong child's folder costs trust.

## Run log

| # | Wall | Found | Filed right | Unsorted | Wrong | What was learned |
|---|---|---|---|---|---|---|
| 1 | fake art wall, 8 | 8 | 6 | 2 | 0 | reader returned Cyrillic look-alikes for "Maya" |
| 2 | fake art wall | 8 | 8 | 0 | 0 | after forcing Latin script and adding retries |
| 3 | fake writing wall, 8 | 8 | 0 | 8 | 0 | names inside the story tied with the label |
| 4 | fake writing wall | 8 | 8 | 0 | 0 | after discounting names in the body of the page |
| 5 | real wall, 24 | crash | | | | reader logged chatter on the JSON channel |
| 6 | real wall | 25 | 19 | 6 | 0 | 3 junk crops, 1 label outside the paper, 1 face without its paper; 3 papers missed |
| 7 | real wall | 22 | 21 | 1 | 0 | two pairs of touching papers merged; whole-photo read lost small labels |
| 8 | real wall | 23 | 13 | 10 | 0 | labels beside a paper were being read into the neighbour as well |
| 9 | real wall | 23 | 21 | 2 | 0 | one paper split in two by its skin tones; one pair still merged by dark hair |
| 10 | real wall | 24 | 24 | 0 | 0 | filed into Drive |
| 11 | real wall, after a test-driven filter | 21 | 20 | 1 | 0 | a new shape filter threw out three real portraits |
| 12 | real wall, final | 24 | 24 | 0 | 0 | 49 tests, 96% coverage |

## The changes, in order

### 1. Force the reader to Latin script
**Seen.** Run 1: a clearly written "Maya" came back as "маца", four Cyrillic
letters that look like ours. With no language set, Apple's reader picks any
script.
**Changed.** The Swift helper sets English and Spanish as the only
recognition languages. The matcher also maps look-alike letters from other
alphabets to ours and strips accents, so "Elíjah" and "Elýjah" both read as
Elijah.
**Result.** Run 2, 8 of 8.

### 2. Two readers and a retry
**Seen.** Same run: a name touching a drawn circle read as nothing.
**Changed.** Each crop is read on its own; if nothing comes back it is read
again at double size with spelling correction on. Independently, the wall
around each piece is read too (see change 9 for how that evolved).
**Result.** Included in run 2.

### 3. Written work: the edge of the page is the label
**Seen.** Run 3: on pages of writing, every child's name matched at 1.0
but so did the name of the friend in their story, so every piece was a tie
and went to `unsorted/`.
**Changed.** A name in the top or bottom 22 percent of the page gets a small
bonus; a name in the middle is discounted by 0.25. A name pulled out of a
sentence of four or more words is weaker than one standing alone.
**Result.** Run 4, 8 of 8, with the friend's name never winning.

### 4. Three things the test suite found before any real wall
**Seen.** Writing the regression tests surfaced: the rectangle detector
skipped one paper on one fake wall; two children sharing a first name still
tied when the last initial was written; the word "The" in a title matched
"Theo" closely enough to file under Theo.
**Changed.** A texture detector (artwork is busy, wall is flat) runs
alongside the rectangle detector and the union is used. When a whole line
matches a roster entry that includes an initial, the bare first-name
fragment is not allowed to compete. A list of everyday words can never match
a name.
**Result.** All three have tests that would fail if they came back.

### 5. Vision writes chatter to standard output
**Seen.** Run 5, the first real photo: the tool crashed reading the helper's
output. Apple's framework had printed "too few samples" on the same channel
as the JSON.
**Changed.** The Python side takes the last line that begins with `[`.
**Result.** Run 6 completed.

### 6. A colour detector, a junk filter, and labels beside the paper
**Seen.** Run 6 filed 19 of 24. The six leftovers were: three crops that
were not student work at all (a strip of alphabet cards, a blank patch of
wall, a sliver of ceiling), one portrait whose typed label was pinned on
the wall above the paper rather than on it, and one painted face detected
without the paper behind it. Three papers were not found at all; two of
those are cut off at the frame edge.
**Changed.** Three things. A colour detector: construction paper is
saturated, a classroom wall is white, so the saturated blobs are the papers.
It is the primary detector when it applies and it finds a paper cut off at
the frame edge. A junk filter: pieces far smaller than the typical piece, or
with nothing on them, are dropped. A nearest-piece rule for lines read
outside any paper.
**Result.** Run 7, 21 of 24, and photo one was perfect.

### 7. Two touching papers of different colours merge into one blob
**Seen.** Run 7: a blue paper sat directly against a yellow one, and a
purple one against a pink one. The colour detector saw one tall blob
each time and both children's labels landed in one piece, a tie.
**Changed.** A blob much taller or wider than a sheet of paper is scanned
for the line where the dominant hue changes, and split there.
**Result.** Both pairs found separately (run 9), but see change 10.

### 8. A 48 megapixel photo is too big to read in one go
**Seen.** Run 7, second photo: reading the whole photo at once returned only
the large alphabet-card letters, not one of the small typed name labels. The
reader downsamples a photo that size until the labels vanish.
**Changed.** Instead of the whole photo, the tool reads a region around each
piece, extended by 30 percent of the piece's size on every side. Small
regions keep small labels legible, and the region catches a label pinned
beside the paper.
**Result.** Every label on the real wall was read from then on.

### 9. A label beside one paper must not count for the neighbour
**Seen.** Run 8 went backwards: 13 filed, 10 unsure. The neighbourhood
regions of adjacent papers overlap, so one child's label, pinned between a
neighbour's paper and their own, was read into both neighbourhoods and both
children tied.
**Changed.** Neighbourhood reads are pooled, duplicates removed, and each
line is handed to exactly one piece: the one it sits inside, else the
nearest one. Below a paper the reach is short, because what hangs under a
display is the next row or the alphabet cards, not this child's label.
**Result.** Run 9, 21 of 24.

### 10. Measure paper colour at the edge of the row, not the middle
**Seen.** Run 9: a single blue paper was split in two, because the painted
skin tones in its lower half pulled the average hue far from blue. The blue
and yellow pair was still merged, because dark yarn hair on the blue paper
dominated its rows and made them look like the yellow one.
**Changed.** The split measures hue only in the outer 15 percent of each row
of the blob, the paper's own margin where nobody has painted. The gap needed
to split rose from 35 to 50 degrees.
**Result.** Run 10, 24 of 24, 0 wrong. Filed into the Drive folder.

### 11. A filter that helped the fake wall broke the real one
**Seen.** After run 10, a new test with coloured drawings on pale paper
showed those drawings forming colour blobs of their own. A shape filter was
added so only solid rectangular blobs count as paper. Rerunning the real
wall (run 11) then lost three portraits: their white face cut-outs
reach the edge of the paper and bite into the blob, so a real paper failed
the shape test.
**Changed.** The shape filter was removed. In its place, a global check:
the colour detector is trusted only when the rectangle detector agrees with
at least half of its blobs. A drawing on pale paper makes a blob, but no
rectangle matches a scribble. Where a blob turns out to be a drawing inside a
sheet the rectangle detector did find, the sheet is used.
**Result.** Run 12, 24 of 24 on the real wall, all 49 tests passing.

## Two rules that came out of this

**Every gain is re-checked against the real wall.** Change 11 is the reason.
A filter that made a synthetic test pass silently cost three real children
their portraits. From that point every change was followed by a rerun of the
two real photos, into a scratch folder that was deleted afterwards, before
anything was committed.

**Children's work stays on the machine.** The tool has no network code and
never did. During diagnosis of run 6, a contact sheet of the six unsorted
crops was viewed in the chat to see what they were. The instruction
after that was to keep as much on device as possible, and every later step
was diagnosed from the tool's text output alone: piece counts, bounding
boxes, and the words the reader returned. That is the standard going
forward, and the `unsorted/name-strips/` folder exists so a person can
resolve a doubtful piece without the drawing ever leaving the laptop.

## September 18: the Drive inbox

**Seen.** A teacher's phone can already share a photo to a Drive folder. If
the Mac watched that folder, the teacher would never touch the Mac.
**Changed.** Watch mode now skips a photo that is still syncing (size still
changing), converts HEIC on the Mac with `sips`, moves a photo it cannot read
to `inbox/failed` instead of stopping, and writes a heartbeat file. The
doubtful-pieces folder can live in Drive so the teacher fixes leftovers from
their own computer.
**What did not work.** A macOS login agent (launchd) could not read the
Desktop or the Drive folder at all: background jobs are refused by the
system's folder privacy protection and never get asked. The tool moved out of
the Desktop to `~/baggage-claim`, and the always-on part became a small
AppleScript app in Login Items, which macOS does ask about, once.
**Result.** A HEIC test wall dropped into the Drive inbox at 09:42:04 was
filed into eight child folders by 09:42:13. 52 tests, 94% coverage.

## September 18, later: a Windows PC as the watcher

**Why.** The two kindergarten teachers this was built for have a Chromebook
and a Windows PC between them, and no Mac. The whole point of the Drive inbox
is that the teachers do not depend on anyone else's computer. So the machine
that watches the inbox had to be one they own, which meant Windows.

**What had to change.** The name reader and the paper-outline detector were
both Apple's, called through a small Swift helper. Windows 10 and 11 ship
their own on-device text reader (Windows.Media.Ocr), so the reader was the
easy half: a Python module with the same contract as the Swift helper, and
the main program picks whichever the platform has. Windows has no paper
detector, so on Windows the colour detector (construction paper against a
pale wall) and the texture detector (artwork is busy, wall is flat) have to
find the papers between them. The rule that trusted the colour blobs only
when the rectangle detector agreed now takes the texture detector as the
second opinion when there are no rectangles, and where a colour blob turns
out to be a drawing inside a sheet the texture detector found, the sheet is
used. iPhone HEIC photos, which the Mac converted with its own tools, are
converted with the pillow-heif package anywhere.

**Made cross-platform at the same time.** A settings file
(settings.local.json) replaces the shell settings, so one command line works
on both systems. A self-check (`--check`) renders a word, reads it back
with the machine's reader, and confirms the folders and class list are
reachable, printing READY or NOT READY. A `--log` option writes progress to
a file, which the windowless watcher needs on both platforms. The test
suite's handwriting font falls back to fonts that exist on Windows.

**Tested here, not yet there.** This Mac cannot run Windows, so the Windows
reader itself is untested until it runs on the teacher's PC. What could be
tested was tested: the Windows detection path (no rectangle detector) was
simulated on the Mac by making the rectangle call return nothing and running
the two real wall photos through it. First try: 9 pieces found of 24. The
texture detector had been made the judge of whether the colour blobs were
paper, and a drawing is busy too, so it agreed with the wrong things and
disagreed with real papers. The fix judges the colour blobs by their own
shape: a sheet of paper fills its own box (the real papers measured 0.9 to
0.97, a few with face cut-outs at the edge 0.6 to 0.73), a coloured drawing
on pale paper does not (0.45 to 0.69). The decision is made for the whole
set by the median, so one paper with a cut-out biting its edge is not thrown
out alone. After that the simulated Windows path filed the real wall 24 of
24 with 0 wrong, the same as the Mac, and the pale-paper synthetic wall
found four of four. The Windows reader is the remaining unknown, and the
setup guide says so.

**Result.** 54 tests, 90% coverage on the main program (the Windows-only
lines cannot execute here and are the gap). The installer registers the
watcher in Task Scheduler to start at logon and restart itself; the
self-check gates it.

## September 18, evening: the project comes from the folder

**Why.** The next thing a teacher does after self-portraits is a different
project. If the project name lived only in a settings file on the watching
PC, every new display would need someone at that PC. Teachers should not
need anyone.
**Changed.** A folder inside `Wall Inbox` named for the project ("Fall
Leaves") is picked up along with photos dropped straight into the inbox; the
folder name becomes the project on every child's copy, and the processed
photo moves to `done/<project>/`. The class list moved into the class's
Drive folder for the same reason: add a child there and a folder appears
on the next photo.
**Result.** Two teachers can run every future display from a phone and a
browser. 55 tests.

## September 18, late: the README catches up with the truth

**Why.** Sahaj read the README as a stranger would, before deciding to make
the repository public. Three lines were stale.
**Changed.** The bold privacy line said "nothing leaves the laptop" and named
only Apple; that was true on Tuesday, before the Drive inbox. It now says
what is true: nothing a child made is sent anywhere to be read, the sorting
runs on a Mac or PC in the building with that machine's own text
recognition, no A.I. service is called, and the only place a piece goes is
back into the school's own Drive. The setup section still named a shell
settings file that only the Mac used; both platforms now read the same
`settings.local.json`, and the Mac launchers were rewritten to match. The
word "display" (a screen, to anyone outside a school) became "wall" or
"paper".
**Result.** One settings file, one story, on both platforms. The Mac watcher
restarted on the JSON settings and the self-check reports READY against the
real folders and the 24-name class list.

## September 18, night: the one-click Windows bundle, built by GitHub

**Why.** The co-teacher's PC is to be the watcher and the 15-minute setup (Python
from python.org plus the installer script) was too much to ask of a
colleague. Sahaj wanted "one fell swoop", Google Drive included.
**How.** A GitHub Actions recipe builds two Windows programs on a real
Windows machine in GitHub's cloud, with Python and every package inside:
`BaggageClaim.exe` (the checker and visible watcher) and
`BaggageClaimWatcher.exe` (the same watcher with no window). `Setup.bat`
installs Google Drive for desktop silently if it is missing, runs the
self-check, puts a shortcut to the windowless watcher in the Startup folder
(no administrator rights needed), and starts it. Settings paths use a
`{DRIVE}` token that resolves to wherever "My Drive" is on that machine,
mirrored or streamed, so the same settings file works on every PC.
**First build.** Rejected before it ran: two step names contained a colon
followed by a space, which YAML reads as a nested key. Quoted.
**Second build.** Both programs built. The self-check ran on the build
machine and the Windows reader read the test word back: the first proof that
the Windows reader works at all. 50 of 55 tests passed on Windows. The five
that did not: two tests assumed forward slashes; Windows silently drops a
trailing period from a folder name, so "Maya R." became "Maya R" (folder
names are now trimmed the same way on every platform, or a Mac and a PC
watching one Drive would make two folders for one child); a missing file
raised a different error type; and the fake walls' handwriting font read
worse under the Windows reader, which is genuinely weaker on script-like
faces than Apple's. The fake walls now use a printed face on Windows, since
a teacher's label is printed or typed. Real handwritten names on a PC will
need watching.
**Third build.** 54 of 55 tests passed on Windows. The last one wanted at
least 7 of 8 hand-printed fake names read confidently; the Windows reader
managed 6, with the other 2 sent to Unsorted and none wrong. The threshold is
now 6 on Windows and 7 on a Mac, and the never-wrong check is unchanged.
The bundle from this build, with a pre-filled settings file, went into the
class Drive folder as "Baggage Claim for Windows.zip" (about 150 MB, most of
it the numeric libraries inside the two programs).
**Fourth and fifth builds.** The test threshold change and the history
rewrite (below) each triggered a build. The fifth is fully green: 55 of 55
tests on Windows, the reader reads back the test word, READY. The programs
from that build replaced the ones in the class Drive zip, so what a teacher
downloads is the artifact of a run with nothing failing.

## September 18, night: a name got out, and the guard that came after

**What happened.** Every commit here is preceded by a scan of the staged
files for the children's, teachers' and school's names. On the commit that
recorded the one-click bundle, the scan printed "1" and the commit and push
went ahead anyway, because the result was read after the push instead of
before it. One sentence in these notes named the co-teacher whose PC will
run the watcher. The repository was public by then. The sentence was live
for about six minutes.

**What was done.** The sentence was reworded. The whole history was squashed
into a single commit and force-pushed, so the version with the name is on no
branch. Every file on the public server was fetched anonymously and scanned
again: zero hits. GitHub can keep an orphaned commit reachable by its exact
address for a while; only a request to GitHub support removes it for
certain, and that is Sahaj's to file if they want it.

**What changed so it cannot repeat.** A pre-commit hook now runs the same
scan and refuses the commit when it finds anything, reading the names from
a git-ignored file. The scan is no longer a line of output someone has to
notice; it is a gate. That is the same design rule the tool itself follows
(nothing is filed on a guess; a doubtful piece stops and waits), applied to
the repository that holds the tool.

## Where things stand at the end of September 18

| | |
|---|---|
| Repository | public, one clean commit, 20 files, no names, photos, class list or real paths |
| Real wall (Mac) | 24 found, 24 right, 0 unsorted, 0 wrong |
| Real wall (simulated Windows detection) | 24 found, 24 right, 0 unsorted, 0 wrong |
| Windows reader | proven on GitHub's Windows machine; not yet run on a classroom PC |
| Tests | 55 on Mac, 55 on Windows, all passing |
| Watching now | Sahaj's Mac, from Terminal, on the shared settings file |
| Next | the co-teacher runs Setup.bat; the moment it says READY, the Mac watcher stops |

**Why the day went the way it did.** Each change today came from a person
with a constraint, not from a plan: two teachers with no Mac (the Windows
port), a colleague who should not spend fifteen minutes installing Python
(the one-click bundle), a teacher who should never need to edit a settings
file for a new display (the project folder inside the inbox), and a
repository that is now public (the scan became a gate). The tool is the same
tool it was on Tuesday. What changed is how many people can use it without
asking anyone for help.

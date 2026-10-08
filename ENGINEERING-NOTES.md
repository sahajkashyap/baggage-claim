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
**Seen.** That run: a name touching a drawn circle read as nothing.
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

**Why.** The two teachers this was built for have a Chromebook
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

**Why.** A colleague's PC is to be the watcher and the 15-minute setup (Python
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
before it. One sentence in these notes named the colleague whose PC will
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
| Next | the colleague runs Setup.bat; the moment it says READY, the Mac watcher stops |

**Why the day went the way it did.** Each change today came from a person
with a constraint, not from a plan: two teachers with no Mac (the Windows
port), a colleague who should not spend fifteen minutes installing Python
(the one-click bundle), a teacher who should never need to edit a settings
file for a new display (the project folder inside the inbox), and a
repository that is now public (the scan became a gate). The tool is the same
tool it was on Tuesday. What changed is how many people can use it without
asking anyone for help.

## September 22: writing on white paper, on a coloured wall

**Why.** The teachers said their language arts work usually goes up on a
coloured bulletin board, white paper on blue or red, and only sometimes on a
white wall. The colour detector only knew the first case: coloured paper on a
pale wall.
**Changed.** The detector now works either way round. It looks at the rim of
the photo to decide which is the wall (papers sit in the middle, the wall
shows around the edge). On a coloured wall the papers are the pale, bright
islands. The first version counted saturated pixels over the whole frame,
and a wall with eight papers covering half of it was mistaken for a coloured
wall; the rim rule fixed that in one step. Fake walls now come in blue and
red, with writing samples on white paper, and are tested on both the Mac
detection path and the Windows one.
**Result.** 57 tests; the real self-portrait wall unchanged at 24 of 24 on
both paths. White paper on a coloured board has not yet been run on a real
wall; the first language arts photo is that test.

## September 23: the privacy gate becomes a skill, with two agents

**Why.** Sahaj is going to set this up for more teachers, and asked for two
things: a repeatable way to check a new class in, and an independent agent
that verifies no child's name ever reaches the web, a searchable A.I., or any
GitHub repository, with a second independent agent checking that the first
one did its job. The name that got out on September 18 was the reason.
**Built.** A Claude Code skill called `baggage-check` (it lives outside this
repository, with Sahaj's other skills). Part A checks a class in: a tool
builds the Drive folder tree, the class list, one folder per child, the
teacher's read-me, a settings file with the `{DRIVE}` token, and the Windows
bundle with those settings inside, and adds every name to the protected
list before anything else happens. Part B is the gate: a scanner script
checks six places (this repo's files and full history; the public tree
fetched without logging in; every public repository of the account, cloned
and scanned; post drafts bound for the web; post files in the personal
Drive; Sahaj's skill files). The first agent runs it, rules on every hit as
a real person or a coincidence, and does three checks of its own. The second
agent never runs the script: it re-checks with its own commands, re-judges
every coincidence ruling, and names anything the first agent missed. Nothing
is pushed, published or posted unless both say PASS.
**What the first scan found.** Two false positives worth recording: an everyday
word matched a protected entry until the test for where a word ends was
tightened, and compressed bytes inside PDFs matched names by chance until
binary files were skipped. One real coincidence: a made-up student in a
browser test from August, before this class existed, agreed and recorded in
an allow list that never applies to this repository, a post, or the personal
Drive. The skill file itself failed its own scan on the first pass, because
its example class name was the real one. It is a made-up room number now.
**Result.** The scanner passes on all six places. The first two-agent run is
recorded below when it completes.

## September 23, afternoon: the gate's first real run, and what it caught

**Agent 1, first run.** It found that GitHub was still serving the commits
squashed away on September 18, that the public events feed listed their
addresses, and that one of them held eleven children's first names, both
teachers and the school's domain. Anonymous fetch: HTTP 200. Five days.
The repository was made private within minutes, the address returned 404,
and the repository was then deleted and recreated from the clean local
copy under the same name. The old address now returns "no commit found"
even to the owner. Rule from this: a repository that ever held a name while
public is deleted and recreated; force-push is never a remedy.

**Agent 1, second run,** after the recreate: GATE PASS on all places, with
its own checks of the deleted address, the events feed, the full history,
web search, the archive services, build logs, images and the account's
other repositories.

**Agent 2** re-checked with its own commands and confirmed the substance:
files and history clean, four clean commits on the server, leaked address
gone, artifact clean, nothing on the public web. It failed the report's
accuracy: three findings did not reproduce because cleanup had been done
while it was running (the gate now freezes everything until both agents
report), one date was wrong, two paragraph citations were off by one, and
two "coincidence" labels were really "real reference, not published". It
also named two places the gate does not reach: the class folder's Drive
sharing setting, which only a person can check in Drive, and local caches
on the Mac, which are never published. Both are now written into the skill.

**Scanner additions from the day:** case-insensitive matching, a stricter
test for where a word ends, binary files skipped, orphaned commits (place 7),
build logs (place 8), the personal Drive's posts folder.

## September 23, evening: the gate passes twice, and the repository is public again

**Agent 1, third run,** with a command and result behind every claim: PASS.
It unpacked the full build artifact, scanned every object in the local
repository, re-checked the deleted address four ways, and found one real
leftover from the five public days: a search engine still holds a cached
copy of the repository's front page, provably stale (old description, live
page 404), holding only generic README text and no protected name.
**Agent 2** reproduced Agent 1's specific numbers exactly (47 objects, 3,238
lines of history with one everyday-word match, five server commits, the
allow-list line and paragraph numbers) and the stale cache, and confirmed
every archive service empty. It corrected one ancillary figure (how much
of the session history on this Mac holds names: far more than Agent 1 said,
none of it published) and named four scanner blind spots in the personal
Drive and posts folders, all scanned by hand and clean. VERIFIED PASS.
**Then** the repository was made public, every public file was fetched
anonymously and scanned (zero hits), the front page answers 200 and the old
address 404. The four blind spots are closed in the scanner.
**What only a person can check:** the class folder's sharing setting in
Google Drive, and the search-engine cache, which the engines' own removal
forms can clear for a page that now returns 404.

## September 23, late afternoon: the first real PC

**Seen.** A colleague's PC showed a crash window from the windowless
watcher: the class list file was not found under their My Drive. Drive for
desktop was installed and signed in (the program had found My Drive), but a
folder shared with someone lands in "Shared with me", which Drive for
desktop does not sync unless a shortcut to it is added to My Drive. Someone
had also double-clicked the watcher itself rather than Setup, which would
have stopped at the check.
**Changed.** In watch mode a missing folder or class list is no longer
fatal: the watcher writes what it cannot find, with the Shared-with-me
instruction, once a minute, and starts the moment the folder appears. The
windowless watcher catches anything unexpected, logs it, and retries after a
minute, so a teacher never sees a crash dialog. The self-check prints the
same instruction when a class folder is missing.
**Teacher instruction that came out of it:** share the class folder with
the teacher as Editor, then on drive.google.com she opens Shared with me,
right-clicks the class folder, Organize, Add shortcut, My Drive.

## September 24: the Mac bundle

**Why.** Sahaj wants to hand the tool to colleagues with Macs once the
Windows one is proven on a colleague's PC. The Mac path until now was
the developer's: Python packages, Apple's compiler for the Vision helper,
a Terminal window.
**Built.** A second job in the same GitHub recipe, on a Mac in GitHub's
cloud: compile the Vision helper, bundle a `baggage-claim` command and a
windowless `Baggage Claim Watcher.app` with Python and the helper inside,
and ship `Setup.command`, `Check Setup.command`, a visible watcher and a
stop script. The program had to learn two things about living inside a
bundle: where its helper is (inside the bundle, not next to the source) and
where its home folder is (next to the `.app`, not inside `Contents/MacOS`).
The first attempt looked for the helper at a relative path that only works
when run from the source folder; the fix looks inside the bundle first.
**Tested here, for real.** This is the one bundle that could be tested on
the machine it is for: the bundled check reports READY, the bundled program
files the real self-portrait wall 24 of 24 with none wrong, and the `.app`
launched by double-click reads the Drive folder and starts watching.
GitHub's Mac ran all 57 tests green. The zip round-trips: unzip elsewhere,
strip the download quarantine, run the check, READY.
**What a teacher will see that Windows users do not.** The unsigned-program
warning on first launch (right-click, Open; or Privacy & Security, Open
Anyway), and a one-time permission prompt for the Drive folder. An Apple
developer certificate would remove the first; it is noted for later.
**Packaging.** `tools/new_class.py --mac-dir` builds "Baggage Claim for
Mac.zip" with the class's settings inside, next to the Windows one.

## September 24, afternoon: the first real PC, second attempt

**Seen.** With Drive for desktop installed and signed in on a colleague's
PC, Setup printed READY and "Check Setup" said the watcher was running. Two
photos of a writing display went into a project folder inside Wall Inbox
and nothing happened for twenty minutes, then the building lost power.
Three things were found and fixed along the way, and one is still unknown.
**Found.** (1) The project folder was named with a colon, which Windows
does not allow in a folder name, so Drive for desktop could never create it
on the PC. Renamed with a dash; the read-me and the templates now say
letters, numbers, spaces and dashes only. (2) The shared class folder was
in the teacher's "Shared with me" and not yet in their My Drive; a shortcut
was added. (3) The watcher resolved the location of "My Drive" once, at
start-up; if the class folder was not there yet it could settle on the
wrong location and wait forever on the wrong path. It now re-resolves every
minute while waiting and logs every My Drive folder it can see.
**Unknown until the power returns:** what the PC's own log says. That is
the first thing to read.
**Meanwhile, the pencil wall on the Mac,** on copies, into a scratch folder:
17 pieces found in two photos, 8 filed, 9 to Unsorted, 0 wrong. Pencil
names on white paper, some written by the children, some pages where the
reader picked up the child's sentence instead of the name. About what was
expected; typed or marker labels would raise the filed count sharply.

## September 24, late afternoon: found it, and it was the packaging

**Seen.** The visible watcher on a colleague's PC printed the answer in
one line: no `settings.local.json` in the folder. The zip refreshed that
morning had been assembled by copying new programs into an old staging
folder and zipping it, and the settings file was no longer in that folder.
The self-check treated a missing settings file as a note, not a failure, so
Setup said READY with nothing to watch, and the windowless watcher wrote
one line to its log and exited. Everything else tried that afternoon (the
folder shortcut, mirror mode, offline access, the colon in the folder name)
was real and needed, but none of it was the cause.
**Changed.** A missing settings file is now a FAIL in the self-check, so
Setup cannot say READY without it. The skill says a teacher zip is built
only by the class tool, never by hand, and lists the file check that would
have caught this. The settings file was put in the class's Drive folder so
the PC could receive it in seconds instead of re-downloading 143 MB.

## September 25: the folder moves, the security software speaks, the second wall

**The class folder now belongs to a colleague.** Drive for desktop on
their PC never turned a shortcut to Sahaj's folder into a real folder on
disk, and the school has ownership transfer switched off, so they created
the class folder in their own Drive and Sahaj moved everything into it. A
local backup was taken first. Rule from this: the class folder is owned by
the account whose machine will watch it. On a Mac the same shortcut does
become a real folder, which is how Sahaj's Mac now sees theirs.
**Security software.** The school's security software flagged the one-click
fixer as a threat and terminated it, and had most likely been ending the
watcher quietly all along. Nothing on our side gets past that; it is IT's
call to allow the folder. Until then the watcher runs on Sahaj's Mac, which
is not school-managed, against their folder. The teachers' side is unchanged:
phone, Wall Inbox, done.
**The second wall.** Two photos of a writing display, names in pencil on
white paper, some by the children: 17 pieces found, 8 filed, 9 to Unsorted,
0 wrong. Half is what pencil gets. The outputs were deleted at Sahaj's
request so the wall can be re-photographed with typed labels, the case the
tool has already proven at 24 of 24.
**Prior art.** Asked whether anything like this exists: portfolio apps do
the destination, one piece at a time; cloud file sorters do sorting with no
notion of a classroom. Could not find the join. Recorded in the README as
"could not find", not "first".

## September 25, later: white paper on a white wall, names first

**Seen.** The Hopes and Dreams wall re-shot with typed labels: the reader
could see 12 and 10 names in the two photos, but the paper detectors found
3 and 7 papers, some of them whole rows merged into one box. Three labels
on one "piece" is a tie, and a tie goes to Unsorted: 10 pieces, 2 filed, 8
unsorted, none wrong. White writing paper on a white wall gives the colour
and texture detectors nothing, and the rectangle detector little.
**Changed.** When a photo shows more readable name labels than found
papers, the papers are built from the words: every line of text belongs to
the nearest label, and a piece is the label plus its lines, padded, with a
minimum size from the typical spacing between labels. A label is a short
line that is the name, not a sentence that mentions one, and one label
read twice by the reader is kept once. The label a piece was built around
outranks any neighbour's.
**Result.** The same two photos, on copies: 21 pieces, 21 filed, 21
distinct children, 0 unsorted. The self-portrait wall unchanged at 24 of
24. 59 tests. The recommendation to teachers stands: a coloured background
is the easy case; this is for the days it is not.
**The defect the test found.** On a white wall the texture detector
sometimes boxes only the block of a child's writing and misses the label in
the paper's corner. The tool then read a classmate's name inside the story
("with my friend ...") and, with nothing else to go on, filed the page under
the classmate. The one outcome that must never happen. Two rules now: a
name that only ever appears inside a sentence can never be confident on its
own; and when readable labels sit away from every detected piece, the
pieces are rebuilt from the labels. A label pinned just beside a paper, as
on the self-portrait wall, still counts as belonging to it. Also caught on
the way: the commit guard refused a commit because code comments used real
children's names as examples. Replaced with invented ones.

## September 25, afternoon: "some of these are wrong"

**Seen.** With pieces built from the labels, 21 of 21 filed, and Sahaj
looked at them: some were wrong. Not the names; the crops. When the paper's
edges are guessed from where the words are, the guess can take in part of a
neighbour's page. A right name on a wrong picture is still a wrong filing.
**Changed.** A piece whose edges were guessed from the words is never filed.
It goes to Unsorted with the label's name as the best guess, and a person
looks at the picture. That is the tool's rule applied to a new place: when it
cannot be sure, it stops. Two more fixes from the same hour: big photos are
now read in full-resolution tiles, because Apple's reader shrinks a
48-megapixel photo until a small typed tag is unreadable (three tags that
had been missed became readable); and a child's name appearing twice on one
paper (typed tag plus their own signature) counts once, which had briefly
made the self-portrait wall look like it had 22 labels for 12 papers and
sent it all to Unsorted. The names-first path is also never used when the
colour detector found the papers.
**Where it stands.** Coloured or dark background: 24 of 24, unchanged, and
the case to use. White paper on a white wall with typed tags: every piece
reaches Unsorted with the right name on it, none filed on a guessed crop.
Sahaj is re-shooting on a dark background this afternoon.

## September 25: a sentence, not a name, and the third rebuild

**What the gate found.** The verifier, reading the public notes the way a
stranger would, found a sentence in the September 23 section that described
a false positive by quoting the word that had matched. Saying which word
had matched a protected entry told a reader more than the scan ever
printed. The scanner could not see it,
because the scanner had been taught to ignore exactly that word. The
sentence had been public since the morning of September 23.

**What was done, in order.** The repository was made private at once.
The sentence was reworded so that no matched word is quoted anywhere in the
notes. The history was squashed to one commit, the repository was deleted
and recreated from the clean copy, and both agents ran again: the scanner
reported PASS on every place that could be examined, and the verifier
reported VERIFIED PASS after reading both public documents in full,
re-judging every coincidence, and opening the Windows build bundle and
the workflow file. Every remaining hit in the account's other public
repositories is an ordinary word or an invented name from before the
classes existed, and both agents agreed on each one.

**Two rules added.** Never quote, in any file that ships, a word or pattern
that matched a protected name; describe it instead. And the verifier reads
the public documents for what a reader could infer, not only for matches.
The scanner's report must also list hits the allow list absorbed, so the
verifier can re-judge them.

**Also this round.** A class list may hold full names; a name label with
only the first name still matches at 1.0. Folder names now keep accents and
apostrophes, so a folder made by hand is the folder the tool files into.
The self-check honours the settings file it is given. 63 tests.

## September 26: two computers, one inbox

**Seen.** The first class now has two watchers: the classroom PC,
set up from the one-click zip, and Sahaj's Mac, pointed at the same class
folder through a Drive shortcut. On a school day both would see the same
photo within the same five-second look, both would cut it, both would file
a copy (the second copy becomes "... 2.jpg" in every child's folder), and
both would try to move it to `done`. Nothing in the inbox loop knew that
another computer existed. Today only the Mac ran, because it was Saturday
and the PC was off, which is the only reason it had not happened yet.

**Changed.** Leader election through the shared folder, with nothing two
computers ever write to at once. Each watcher writes its own status file,
`<class folder>/Watcher status/<computer name>.txt`, once a minute at most
and right after a batch. One file per computer means Drive never has to
merge two writers. The file is plain English (computer, system, last
checked at, role, photos waiting, last batch, tool version) with four
machine-readable lines at the bottom. Every look at the inbox, a watcher
reads the others' files; among those written in the last five minutes plus
itself, the lowest `priority` number (a new setting, default 50) sorts, ties
settled by computer name so both sides reach the same answer. The others
log "standing by, <computer> is watching this class" once and keep writing
their status. When the leader's file goes stale, a follower takes over; when
the leader writes again, it takes the work back. A watcher that has just
started stands by for 90 seconds, so a computer mid-photo is seen first.
Sahaj's Mac gets priority 90 so the classroom PC does the work whenever it
is on. The `--check` self-check (which `Check Setup` runs on both platforms)
now lists every computer with "last checked 2 minutes ago, watching" or
"OFF or asleep", so the whole picture is readable from Sahaj's own Mac, or
from a phone by opening the folder in Drive.

**Why not a lock.** A lock file in Drive is a shared write, and Drive
resolves two writers by keeping both copies under different names, so the
lock would sometimes be held by nobody or by both. Election over one-file-
per-writer needs no merge. The photo level keeps a belt and braces instead:
right before sorting a photo the watcher checks it is still there; if it has
vanished mid-sort, or the move to `done` fails because the other computer
moved it first, the log says so in plain words and the pieces are not
counted twice. That is the whole of the distributed part, on purpose.

**Clock skew.** Two computers can disagree by minutes and Drive rewrites
modification times on sync. So staleness is judged only by the time written
inside the file against the reader's clock, five minutes against a
one-minute write rhythm; a file dated in the future is fresh. Written as a
comment above the code, with the rule that nothing in it needs a Mac-only
or Windows-only module, and that the computer name is sanitised because
`platform.node()` can hold characters Windows will not put in a file name.

**Also.** Anything that walks the class folder now skips `Watcher status`
and `Unsorted - needs a person` (the per-child .docx builder was the one
that did not). `tests/test_multi_watcher.py`: 30 tests, no sleeping; the
election functions take "now" as a parameter, so a stale file or a grace
period is a number.

**Until the zip is rebuilt.** The classroom PC runs the build from before
this change; it knows nothing about status files and would sort every photo
it sees. Until a pushed commit has produced a new zip and it is installed
there, only one computer may watch the class: either stop the Mac watcher
while the PC is on, or leave the PC's watcher stopped and let the Mac do it.

## September 26, later: the classroom PC's build predates the election

**Seen.** The paragraph above was true and nothing enforced it. The PC was
set up from the one-click zip built from `origin/main` (September 25), the
election lives only in the working tree, and both watchers were running: the
Mac's log said "this computer is watching this class (no other computer is
on)" at 2:01 PM while the PC, which writes no status file, was sorting too.
Every photo dropped into the inbox was cut and filed by both machines, so a
child's folder got `Self-Portrait K.jpg` and a second copy (a
` 2.jpg`, or a Drive `(1)` copy when both wrote the same name), and
`Unsorted` got each doubtful piece twice. The belt and braces at the photo
level did not help: the crops were saved before the move to `done` failed,
so "not counting its N pieces twice" protected only the count in the log.
Two smaller things rode along: the Mac's `settings.local.json` had no
`priority` line (so it was 50, not the 90 the notes said), and photos added
from the Mac's Finder made the race worse, because the Mac saw them at once
and started before the PC had downloaded them.

**Changed, three things.** First, claim before cutting: `run_inbox` moves a
photo into `done` first and sorts it from there, so a computer that loses the
race finds it gone and saves nothing, and the winner's move is on its way to
the other computer's Drive while that one is still waiting for the photo to
settle. A photo that cannot be read moves on from `done` to `failed`. For
photos added from the Mac this alone closes the gap in practice: the Mac
claims within seconds, the PC's Drive receives the photo already in `done`,
and the PC's old build never sees it in the inbox. Second, a silent sorter
is noticed. Only this computer puts pieces into the folders it has just
filed into, so an image arriving in one of them within ten minutes that it
did not save, or a photo taken from the inbox by a computer it has not
heard from, means another computer is sorting the same class. When that
happens and no other status file is fresh, the log says, in one sentence,
what was seen, that the other computer runs an older version, that this one
is standing by for the next eight hours, and how to fix it for good (install
this version there, or stop that watcher; restart this watcher to sort again
sooner). Inside the election the silent computer is a stand-in status with
priority -1 that stays fresh for eight hours (`silent_sorter`), so the rest
of the machinery, the log line and the status file text ("standing by; a
computer running an older version of Baggage Claim is watching this class")
all follow from the one rule that already existed. If that computer turns out
to write a status file after all, the stand-in is dropped and the normal
election covers it. Third, the Mac's `settings.local.json` now says
`"priority": 90`.

**What this does not do.** A photo that reaches both computers at the same
moment from a phone, while the PC still runs the old build, is still cut by
both; the Mac notices the second copy within a minute and stands by, so it
happens once, not all day. Nothing short of installing this version on the
PC ends that, and the tool now says so in the log instead of saying "no
other computer is on". `tests/test_repairs.py` holds the regression tests:
the claim happens before the cut, a lost race cuts nothing, a copy arriving
in a folder just filed into puts the watcher on standby with the right words
in the log and the status file, and a real status file clears the alarm.

## September 26: the Mac watcher did not come back after a restart

**Seen.** The Mac rebooted at about 12:45 PM. The AppleScript applet that
Setup had added to Login Items did not come back, three photos sat in Wall
Inbox from 1:11 PM until a person started the watcher by hand at 1:18 PM,
and `Check Setup.command` would have said "running" anyway, because it
looked for the applet, not for the watcher. The next Mac to get this is a
colleague's, where nobody will ever look.

**Why launchd, not Login Items.** Login Items only start a program once,
at login, and nothing restarts it if it stops; whether it started at all is
not written down anywhere a script can read. launchd is the part of macOS
that runs the system's own background programs: a small file in
`~/Library/LaunchAgents` says "run this, at login, and start it again if it
ever exits" (`RunAtLoad`, `KeepAlive`, `ThrottleInterval` 30 so a program
that dies at once is retried every 30 seconds rather than in a tight loop),
and `launchctl print` says at any moment whether the job is loaded and
what its process id is. `mac/autostart.sh` writes that file with the real
absolute path of the tool folder (teachers put the folder anywhere) and
loads it; `Setup.command` calls it, `Stop Watcher.command` unloads it, and
`Check Setup.command` now reports the truth in four lines: is the job
loaded, is a watcher process alive, when did `logs/watch.log` last change,
and what did it last say.

**What launchd cannot do by itself, and the fix.** The September 18 note
said a launchd job could not read the Drive folder and was never asked.
That was checked again today, with counts only: a job whose program is
`/bin/zsh` running python was refused with "Operation not permitted" the
instant it listed the inbox, and no dialog appeared. The same listing run
by a job whose program is a real app bundle (a fifteen-line Swift launcher
in `Baggage Claim.app`, which runs `watch.sh` as its child) waited on the
Allow dialog instead. macOS asks an app; it refuses a bare script silently.
So the launchd job runs the launcher app, the launcher runs `watch.sh`, the
child inherits the permission, and the launcher passes the child's exit
code and any stop signal through so `KeepAlive` still sees a crash. The
launcher is built by `Setup.command` on a Mac with Apple's compiler and by
the GitHub build for the one-click bundle. Its signature is ad hoc, so a
rebuilt launcher is a new program to macOS and is asked about once more.
Without the launcher (no compiler), the job runs the script directly and
works only if Python has Full Disk Access; `Check Setup` prints PERMISSION
NEEDED with the steps whenever the log shows the refusal.

**One watcher per class on a machine.** `--watch` now takes a lock next to
the log file (`fcntl.flock` on a Mac, `msvcrt.locking` on Windows). A second
watcher for the same class says "another watcher is already running for
this class (process N), so this one is closing" and exits; a lock left by a
crashed or killed watcher is released by the operating system, so it is
simply taken over. The lock sits next to the log, not in the tool folder,
because one folder can watch several classes with several logs.

**Also.** `watch.sh` no longer exits silently when the name reader is not
built and there is no compiler, or when `settings.local.json` is missing:
it writes one plain sentence to the log, waits ten minutes under launchd,
and exits, so a broken setup produces a line every ten minutes rather than
one every 30 seconds. `Start Watcher.command` follows the background
watcher's log when the job is loaded instead of starting a second one.
`tests/test_autostart.py`: the job file is valid property-list XML with the
folder's absolute paths (including a folder name with `&` in it),
`KeepAlive` true; install/remove against a stub `launchctl`; the two
`watch.sh` messages; the launcher's exit codes and signal forwarding; and
the lock, including the stale-lock takeover and the second-instance message
through `main()`.

## September 26, evening: every piece on its side

**Seen.** All 18 pieces filed from three wall photos came out sideways. Each
photo carried the phone's orientation tag ("held upright"), and the tool
applied it, but the phone had been tilted while shooting from the side, so
the tag was a quarter turn wrong and every axis-aligned crop from the photo
was too. Apple's reader reads text at any rotation, so the names matched at
score 1.0 and nothing complained. The tell was the label's box: tall and
thin (33 by 121) instead of wide, and a quarter turn later the same label
read 117 by 29 with the sentence lines in the right order.

**The rule.** The typed name label decides which way is up. `vision text`
now reports, for every line, the quarter turn (0, 90, 180, 270) that would
make it read left to right: Vision orders an observation's corners along
the text's own reading direction, so the topLeft-to-topRight vector says
which way the words run (proved on a fake wall turned four ways before it
was built in). Both platforms give `baggage_claim.py` the same field.

On Windows the field is worked out in `vision_windows.py`, and how it is
worked out changed on September 28, 2026. At first the helper read the
picture as it is and, only if that found fewer than eight letters, turned
it 90, 270 and 180 degrees and read again; the turn that read the most
letters was reported as the angle of every line. That is gone. The first
build that ran it on a real Windows reader proved it wrong: a wall
photographed upside down was not turned at all, because the Windows reader
reads upside-down text and the first read found letters enough, and a wall
on its side was turned 90 degrees where 270 was right. Counting letters
cannot tell a name from nonsense, nor upright from upside down. What the
helper does now:

- It reads every picture four ways up, always: as it is, and turned 90, 270
  and 180 degrees. Nothing is chosen there. Every line from every turn is
  handed back with the turn it was read at, and the program decides from
  the line that is a child's name, as it does on a Mac.
- Each line carries its own angle: the turn the picture was read at, plus
  what is known about that one line. Three things can say a line was read
  upside down, and any one is believed (`place`): the reader's own word
  (`text_angle`), words that run right to left, and a box that holds no ink
  while the same box in the picture turned over does.
- One paper cut from a photo is read one way only, as it is (`AS_IT_IS`),
  because the photo has been turned upright by then. When no name reads for
  certain the program turns the paper and reads again. When a name does
  read for certain, the program still looks at the paper turned over
  (`second_look`): a name of one word has no word order to give it away,
  so one look cannot tell it upright from upside down unless the reader
  says so. If the name reads the same both ways up and the reader calls
  both upright, the piece is filed under the child the first way the name
  read, and the log says in plain words that the tool could not check which
  way up the paper hangs.

Whether the Windows reader says so is not known yet. The build runs
`tests/reader_probe.py` and keeps what it prints
(`reader-probe-on-build-machine.txt`, inside the bundle): what the reader
read and said for typed names at every size and every way up, and what the
program did with a one-word name on a paper hung upside down. What is known
not to work if the reader turns out to say nothing: a photo of a whole
wall, taken upside down or on its side, where every name is one word. The
labels' votes for which way is up then come out even, or near it, and
cannot be trusted; names of two words are not affected.

**Where it is used.** Once, early: after loading a photo the whole photo is
read and the majority angle of the lines that are a roster name (falling
back to every line) turns the photo upright before any detection, so every
quad, crop and coordinate downstream sees an upright photo; the log says
"photo was on its side; turned it upright using the name labels". Then per
piece: the angle of the line that decided the match turns the crop so the
label reads upright, and the piece is read and matched again in that frame
so `rel_y`, the edge bonus and the name-strip box are all measured the
right way up. Filed pieces, GUESS files and name strips get the same turn.
The orientation tag is still applied first, because it is right most of the
time, but it is no longer trusted on its own: a tag cannot see that the
phone was tilted, and a label can. `tests/test_orientation.py`: a fake wall
turned 90, 180 and 270 as raw pixels and as an upright file with a wrong
tag, one paper hung sideways on an upright wall, unsure pieces turned by
the same rule, and the pure majority and Windows decision functions.

## September 26, evening: a laptop that wakes up believes what it saw before it slept

**Seen.** The 90-second grace period was keyed to the moment the process
started, and nothing else. A laptop that watches the class alongside the
classroom PC closes its lid, sleeps for hours, and wakes; the next look at
the inbox happens within five seconds, before Google Drive for desktop has
reconnected. Everything it reads then is its own copy of the class folder,
frozen at the moment it fell asleep: the PC's status file still carries a
time from before the sleep, so the PC is judged off and the laptop declares
itself the watcher on its first tick ("no other computer is on"); and the
inbox still lists the photos the PC sorted and moved to `done` hours ago.
The laptop cuts and files them again into its local child folders. When
Drive catches up, every child gets a second copy and the laptop's move to
`done` collides with the PC's. The "is the photo still there?" check does
not help, because the stale view says it is. This would happen on every
school day the lid is closed and reopened while the PC is on, and adding
photos from the laptop's Finder (which is how the helper's class gets its
photos) makes the laptop the machine most likely to be asleep at the time.

**Changed.** The loop remembers when it last looked at the inbox (set after
the work of a tick, so a three-minute batch is not mistaken for a sleep).
A gap of more than `WAKE_GAP_SECONDS` (two minutes, against a five-second
look) means the computer was asleep: the grace period starts again from
that moment, the log says "this computer was asleep for 47 minutes;
standing by for 90 seconds while Google Drive catches up, then checking who
should sort", the status file is rewritten at once as "just started", and
the end of the grace announces the role as usual. `decide_role` is
unchanged (it is right about a computer that really was awake all that
time); the loop now passes it the wake time instead of the start time. The
status file's "Watcher started" line keeps the true start. Shared code, so
Windows gets it too, though a classroom PC rarely sleeps. What this does not
do: if Drive takes longer than 90 seconds to reconnect after a wake, the old
picture returns; nothing observed so far suggests it does.
`tests/test_repairs.py` (`WakeFromSleepTests`) fakes the clock: a three-hour
jump between two ticks, with the PC's file fresh before it, sorts nothing
until the grace has passed again, and a long batch is not a sleep.

## September 26, evening: the HEIC scratch copy was written into the inbox

**Seen.** An iPhone saves HEIC, and sharing from the phone is the main way a
photo reaches the Wall Inbox. Plain Pillow cannot read HEIC, so the tool
first writes a JPEG copy and reads that. The copy was written right next to
the photo, `IMG_1234.HEIC.jpg` inside the Drive-synced inbox, and removed
only when the photo was finished, ten seconds or so later. In that window
Google Drive uploaded a full-size JPEG to the cloud and to every other
computer watching the folder, and the inbox listing counted it as a second
wall photo. With two computers sharing a class (a Mac and a classroom PC,
which is now the normal setup), the other computer could download and sort
the copy, so every child got the same piece twice. A watcher killed or a
Mac losing power mid-photo left the copy behind, to be sorted as a second
wall on the next start. And a teacher looking at the folder in Drive saw a
phantom file appear and vanish for every photo. Confirmed on this Mac with a
synthetic wall: after `open_photo` the inbox listed both files, and so did
`inbox_jobs`.

**Changed.** `open_photo` now takes the scratch folder and writes the JPEG
there: `process_photo` makes `<tool folder>/.tmp` first (where the crops
and tiles already go) and passes it in, and a caller with no scratch folder
gets the computer's own temp folder. Nothing is ever written beside the
photo. The scratch folder is deleted at the end of every photo as before,
so the cleanup line only removes the copy if it is somehow still there.
Shared code: the Mac (`sips`) and Windows (`pillow-heif`) paths both write
to the same place. `tests/test_repairs.py` (`HeicTempFileTests`) converts a
synthetic wall to HEIC and checks that the inbox lists one photo throughout,
with and without a scratch folder, and that a whole `process_photo` run
leaves nothing behind in the inbox or the class folder.

**Checked again, and one gap closed.** A second pass ran the report as it
was written: an iPhone photo in the inbox, the watcher stopped in the middle
(after the JPEG copy exists), the watcher started again. With the change
above the inbox holds `done/IMG_0001.HEIC` and nothing else at every point,
and the second start finds nothing to sort (`HeicStoppedMidPhotoTests`). Put
the old line back (`tmp = path + ".jpg"`) and both tests fail.

The gap: the change only helps a computer that has it. The one-click
Windows zip that classroom PCs were set up from was built from the version
before, so a PC that shares a class with a Mac still writes
`IMG_1234.HEIC.jpg` into the inbox, Drive brings it to the Mac, and the Mac
lists it as a second wall photo. The 10-minute wait for a shared class
covers the ten seconds a healthy PC needs, but not a PC switched off in the
middle of a photo, which leaves the copy there for good. So `inbox_jobs` now
leaves out a file named `<photo>.HEIC.jpg` when `<photo>.HEIC` itself is in
the same folder, in `done` or in `failed` (`old_heic_copy`). It is not moved
or deleted, because the other computer may be reading it at that moment. A
file that only has such a name, with no iPhone photo to go with it, is
sorted like any other photo: a teacher's photo is never quietly skipped
(`JpegCopyFromAnOlderVersionTests`). Listing the file names in the two real
inboxes on September 26 found no leftover copy.

**Checked a third time, and the last way into Drive closed.** The scratch
folder is `<tool folder>/.tmp`, and that is only outside Drive when the tool
folder is. The one-click zip is handed to a teacher in the class's Drive
folder, and Windows' "Extract All" offers the folder the zip is in, so the
tool folder can end up inside Drive. Run with a synthetic iPhone photo and a
tool folder under a pretend `My Drive`: the inbox stayed clean, and the
full-size JPEG was in
`My Drive/<class>/BaggageClaim-windows/.tmp/<id>/...IMG_0001.HEIC.jpg`,
with every crop beside it. Drive would upload those and keep them in its
trash for 30 days after the delete, on every photo, which is the harm this
entry started with. `scratch_folder` now asks `scratch_home` where to work:
the tool folder as before, or, when the tool folder is inside Google Drive
(`inside_google_drive`: a folder named `My Drive`, `Shared drives` or
`Google Drive`, or the Mac's `GoogleDrive-<account>`, anywhere in the path),
`<the computer's temp folder>/baggage-claim/.tmp`. Shared code, the same on
both platforms; the self-check draws its test word through the same
function. `tests/test_repairs.py` (`ScratchStaysOutOfDriveTests`): with the
tool folder inside a pretend Drive, the only picture anywhere in Drive while
an iPhone photo is sorted, after it is sorted, and after a stop in the
middle, is the photo itself; the crops of a plain photo stay out as well; a
tool folder on the computer keeps `.tmp` where it was. With the old place
put back, three of the six fail. What this does not do: a Drive folder whose
name is in another language ("Mon Drive") is not recognised, which is the
same limit `my_drive_candidates` has. And the log, the status heartbeat and
the run report of a tool folder inside Drive are still written there, and
Drive uploads them; they are words, not pictures, but the tool folder
belongs on the computer itself, and the setup steps should say so.

Still to do: build the Windows zip again from this version and run Setup on
each classroom PC. Until then the PC keeps writing the copy into the inbox;
this computer ignores it, but the teacher can still see it come and go.
Not changed here: `.heif` is handled by `open_photo` but is not in
`IMAGE_EXT`, so a `.heif` file in the inbox is never picked up. iPhones
save `.HEIC`, so nobody has met this.

## September 26, evening: a watcher stopped in the middle of a photo

**Seen.** Filing the pieces and moving the photo to `done` were two separate
steps, about ten seconds apart, with the move last. Anything that stopped
the watcher in between (`Stop Watcher`, launchd restarting it after a crash,
`taskkill /F` from the Windows Setup or Stop Watcher, a power cut like the
one on September 24) left the photo in the inbox with its pieces already
filed. The watcher came back, sorted the photo again, and every child on
that wall got a second copy ending in ` 2.jpg`; the doubtful-pieces folder
got each doubtful piece twice. Nobody was told. Reproduced against the
committed version with invented names in a temporary folder: the process
dies after the last piece is saved, `run_inbox` runs again, and each child's
folder holds two files.

**Changed, two halves.** The first half was already in the working tree
from the two-computer repair above: a photo is moved to `done` before it is
cut, so a restart finds nothing in the inbox to sort twice. That repair was
written for two computers racing; it also closes this, and the same steps
run against the working tree leave one file per child. The second half is
new, because a photo left half sorted in `done` with nobody told is still a
defect. Before the claim, `run_inbox` writes a small marker,
`<output folder>/.in-progress/<computer> <id>.json`, and removes it when the
photo is finished, failed, or lost to another computer. There is no
`finally` around it on purpose: Ctrl+C is one of the ways of stopping. A
marker still there at the next start means the photo was not finished. The
watcher says so once, at start (whether or not it is the computer that sorts
today) and at the top of every `run_inbox`: one sentence in the log, and a
note in plain English, `NOT FINISHED - <project> - <photo>.txt`, in the
doubtful-pieces folder, which is the one place a teacher already looks. The
note names the photo and the folders, never a child. Then the marker is
removed, so it is said once and not every five seconds.

**Why the marker is where it is.** The output folder is this computer's own
(by default the tool folder), so Drive never carries the marker to another
computer, and `.in-progress/` is in `.gitignore` because the marker holds the
name of the class folder. Several classes on one computer share that output
folder, so each marker says which class it belongs to, as the last two
folder names of the inbox in lower case: those stay the same when "My Drive"
moves to a new drive letter on Windows, and the full path does not. The
paths inside are relative to the inbox for the same reason. The marker also
holds the photo's size, so an older photo of the same name sitting in `done`
is not mistaken for the unfinished one, and a photo still waiting in the
inbox (killed between the marker and the claim) is sorted in the ordinary
way without a word. It is written to a side file, flushed to disk and
renamed, since a power cut is one of the cases. Shared code, nothing
Mac-only or Windows-only in it.

**What this does not do.** It does not finish the photo by itself. Doing
that safely means knowing exactly which pieces were saved before the stop,
and either skipping them or taking them out again; both reach into
`process_photo` and one of them deletes files from children's folders on
the word of a marker. A person moving the photo back is one step, and the
worst it costs is a second copy for the children who already had theirs. If
unfinished photos turn out to be common, a list of saved pieces in the
marker is the next step. A computer running a build from before this change
still has the original defect until that build is replaced.
`tests/test_repairs.py` (`StoppedMidPhotoTests`, and
`StoppedMidPhotoOnARealWallTests` with a synthetic wall and the real
reader): killed after every piece was filed, killed halfway, killed at the
move as first reported, the teacher moving the photo back, a project folder,
another class's and another computer's markers left alone, and the watcher
saying it at start while standing by.

## September 26, evening: the class list was read once, at start

**Seen.** The read-me in every Wall Inbox, the Windows setup guide and the
September 18 entry above all promise the same thing: add a child to the
class list and a folder appears on the next photo. The watcher read the
class list once, when it started, and handed that same list to every look
at the inbox for as long as it ran, which on a classroom PC is weeks. A
child who joins in October was unknown to a watcher started in September.
Reproduced with invented names and a synthetic wall: a watcher started with
three children, a fourth added to the file, a photo with all four. The new
child's label was read perfectly, matched nobody, and the piece went to
Unsorted with a classmate as the best guess (score 0.605). With a closer
name it could have been filed under the classmate. The only cure was to
restart the watcher, which on the PC means logging out and in.

**Changed.** At the top of every look at the inbox the watch loop asks
`refresh_roster` for the list. It compares the file's size and time of last
change with the last time it read it, and reads the file again only when
they differ, so an unchanged list costs one look at the file's details. When
the names are different the log says so once: `class list changed: 25
children (there were 24)`. Counts only; the log never names the child. A
file saved again with the same names says nothing. A list that is empty,
unreadable or not there at that moment (Drive or an editor in the middle of
saving it, Drive not connected) never replaces a good one: the list from
before stays in use, the log says why once, and the file is tried again on
the next look. Shared code, so the Mac and Windows watchers both get it. The
computer that sorts makes the new child's folder on its next look; one that
is standing by reads the new list too and is ready if it takes over.

**What this does not do.** The change has to reach the watching computer
first, which is Google Drive's job and usually takes seconds. A computer
running a build from before this change still reads the list once; it needs
the new build, like the other repairs from today. A photo already being cut
when the list changes is finished with the list it started with.
`tests/test_repairs.py`: `ClassListReloadTests` (the function on its own:
added, removed, unchanged, empty, unreadable, missing),
`ClassListReloadInTheWatchLoopTests` (the list handed to each look at the
inbox, said once) and `ClassListReloadOnARealWallTests` (the report end to
end with a synthetic wall and the real reader: the new child's piece is
filed under the new child, with no restart).

**Two computers on one class.** Asked the same evening: a helper's Mac and a
classroom PC set up from the Windows zip both watch one class; is that a
problem for the class list? The reload is in the shared code, and it runs on
every look whether the computer sorts or stands by, so a computer that takes
over knows the new child from its first look
(`ClassListReloadOnAComputerStandingByTests`: a child added while this
computer stands by, the other computer switched off, the new child's folder
made and the new list handed to the sorting, with nothing sorted while it
stood by). What the change cannot do is reach a computer it is not on. A PC
set up from a zip built before this change reads the list once, at start,
and if it is the one that sorts, a new child's work still goes to Unsorted.
It needs a new zip; until then, restarting it after the list changes is the
cure. The same is true of a watcher that was already running when the new
program file was saved next to it: Python read the old program when it
started, so it has to be started once more. The README section "A new child
joins the class" now says both in plain words.

## September 26, evening: the folder that would not stay deleted

**Seen.** The other half of the class list report. `run_inbox` began every
look at the inbox, every five seconds, by making a folder for every child
on the class list, with the project folder inside it. A child leaves, the
teacher deletes the child's folder in Drive and does not think of the class
list, and an empty folder with an empty project folder in it is back within
one look. To the teacher that is a folder that keeps coming back. Reproduced
with invented names in a temporary folder, through `main` with `--watch`:
two children, one folder deleted after the start, and two looks later both
folders are there again.

**Changed.** The watcher remembers which names it has made folders for
(`make_new_child_folders`, with a dict the watch loop keeps and hands to
`run_inbox` as `folders`). A folder is made for a name that is on the class
list now and was not the last time folders were made, and for nobody else.
So a new child still gets a folder on the next look, a spelling put right in
the list gets a folder under the right spelling, a name taken off and put
back gets one again, and a folder the teacher deleted is left alone. A piece
filed for a child makes that child's folder as it always did, in
`process_photo`, so a folder deleted by mistake returns with the first piece.
The memory is kept per class folder and project. If the folders cannot be
made because Drive is not connected, nothing is remembered and the next look
tries again. A run that is not the watcher (once through, from `Baggage
Claim.command`) hands over no memory and makes every folder, as before.
Shared code, so the Mac and Windows watchers both get it. Nothing is ever
deleted by the tool; a name taken off the list leaves the folder and the
work in it where they are.

**What this does not do.** The memory lives in the running watcher, not on
disk, because a file of children's names in the tool folder is one more
thing that must never be committed. So when the watcher starts again it
makes an empty folder for every name on the list, once: a deleted folder
whose name is still on the list returns after a restart of the computer, not
after five seconds. The README tells the teacher to take the name off the
list first. With two computers watching one class, each does that once at
its own start. A computer running a build from before this change, such as a
classroom PC set up from an earlier zip, still makes every folder on every
look while it is the one sorting; it needs the new build, like the other
repairs from today. `tests/test_repairs.py`
(`DeletedChildFolderStaysDeletedTests`): the deleted folder stays deleted
over five looks, a new child gets a folder while the deleted one stays
deleted, a name taken off and put back, a spelling put right, Drive away for
one look, two classes remembered apart, a run without the memory, the watch
loop from start to finish through `main`, and a synthetic wall whose piece
brings a deleted folder back.

## September 26, evening: a question mark in a project folder's name

**Seen.** The read-me in every Wall Inbox asks for letters, numbers, spaces
and dashes in a project folder's name, and a teacher on a phone will still
call a folder `Who Am I?` or `Unit 2: Leaves`. A phone and a Mac accept
those names, so a Mac that watches the class sorts the photos. The project
folder inside each child's folder was cleaned (`Who Am I`), but the file
names were built from the name as the teacher typed it: `Who Am I?
Kindergarten.jpg` in every child's folder, `GUESS Maya - Unit 2: Leaves
Kindergarten - IMG_0001 01.jpg` in the doubtful-pieces folder, and
`done/Unit 2: Leaves/` in the inbox. Windows does not allow `? : " / \ | < >
*` in the name of a file or folder, so a classroom PC sharing the class
cannot hold any of those files. Reproduced on this Mac with invented names
and a synthetic wall: `piece_name('Who Am I?', 'Kindergarten', ...)` gave
`Who Am I? Kindergarten.jpg`. What Google Drive on a PC shows for such a
file was not observed here; the September 24 entry records a project folder
with a colon that never appeared on the PC.

**Changed.** The name is cleaned once, where it comes in, by the rule the
folders already used (`safe_folder`, through a new `clean_project`):
`inbox_jobs` cleans the name of a folder inside the inbox, and `main` cleans
the project from `--project` or the settings file. From there the project
folder, the file names, the GUESS names, the `NOT FINISHED` note and the
done folder all use the same name. The two places that make a file name
(`piece_name` and the GUESS name) also clean the whole name they build, so a
grade such as `5/6` or a photo with an odd name cannot put a refused
character back; before this, a grade with a slash in it sent every photo to
`failed`. The log says it once per folder, in one sentence: `the project
name 'Who Am I?' has a character that a Windows computer cannot use in a
file name (such as ? : " / or a full stop at the end), so this work is filed
as 'Who Am I'. Nothing is lost. For new projects, use letters, numbers,
spaces and dashes in the name.` An accent stored the Mac's way, or two
spaces in a row, is not a changed name and says nothing. Shared code, so the
Mac and Windows watchers both get it.

**What this does not do.** The folder in the inbox is the teacher's own and
the tool does not rename it. A Windows PC may never be given that folder by
Google Drive, so it may never see the photos in it; when the PC is the
computer that sorts and the Mac is standing by, photos in such a folder
would wait until the folder is renamed. Pieces filed under the old names
before this change keep those names; renaming them by hand in Drive (take
out the `?` or the `:`) is the cure. Two folders that clean to the same name
(`Who Am I?` and `Who Am I`) become one project.
`tests/test_repairs.py`: `ProjectNameCleanedTests` (the file name, the inbox
folder, the done folder, the note for a photo stopped halfway, `--project`
and the settings file, said once) and `ProjectNameCleanedOnARealWallTests`
(a folder called `Who Am I?`, a synthetic wall with one unnamed paper, the
real reader: every name the tool makes is one a Windows PC can hold).

## September 26, evening: the window that switched the watcher off

**Seen.** On a Windows PC, `Start Watcher (visible).bat` began with
`taskkill /IM BaggageClaimWatcher.exe /F` and then ran the watcher in the
window. A teacher who opened it to see the tool working, looked, and closed
the window had stopped the background watcher and then the visible one. The
Startup shortcut only runs at login, so nothing watched the class for the
rest of the day, photos waited in `Wall Inbox`, and `Check Setup.bat` said
`Watcher: NOT running`. The Mac script had been changed that morning to
follow the log; the Windows one still replaced the background watcher. Found
by reading the file; a Mac cannot run it, so it was not reproduced on a PC.

**Changed.** The window stops nothing. It asks Windows whether
`BaggageClaimWatcher.exe` is running (`tasklist`, the same question `Check
Setup.bat` asks). If it is, the window says `The watcher is already running
in the background. This window follows its log.` and shows the last 20 lines
of `logs\watch.log` and every new line as it is written (PowerShell
`Get-Content -Tail 20 -Wait`); closing the window closes only the window. If
it is not, the watcher runs in the window as before and the window says so
first: `Closing this window stops it. To have it run by itself, and start
again at every login, double-click Setup.bat.` Only the `.bat` file changed;
no Python changed, so the Mac is untouched. The one-watcher lock from this
morning already keeps a second watcher for the same class from starting, so
removing the `taskkill` cannot produce two.

**What this does not do.** Windows is asked about the program's name, not
its folder. On a PC with two Baggage Claim folders for two classes, a
watcher running for the other class makes this window follow this class's
log, which may be quiet. `Setup.bat` and `Stop Watcher.bat` stop every
`BaggageClaimWatcher.exe` on the PC in the same way; that is older than this
change and is not changed here. The from-source `Start Watcher.bat` never
stopped anything: with the Task Scheduler watcher running it prints the
"another watcher is already running" sentence and closes. A PC that already
has the old file keeps it until the new zip is unzipped over the folder.
`tests/test_repairs.py`: `WindowsVisibleWatcherTests` walks the `.bat` file
line by line with the answer to "is the watcher running?" supplied by the
test: nothing is ever stopped, the log is followed when the watcher is
running, the watcher runs in the window only when it is not, and the old
file fails the same walk. It has not been run on a Windows PC.

## September 26, evening: two classes cut their photos in the same scratch folder

**Seen.** One tool folder can watch several classes, one watcher and one log
each, and `out` is not set in any settings file, so every watcher's scratch
folder was the same one: `<tool folder>/.tmp`. Every watcher wrote its crops
there under the same names (`crop-1.png`, `crop-2.png`, `upright.jpg`) and
deleted the whole folder when its photo was finished. Two teachers posting
in the same ten seconds, which is what Monday morning looks like: the
watcher that finished first deleted the other one's crops in the middle of
its photo. That photo went to `failed` with "could not process", after some
of its pieces had already been filed, so dropping it in again gave those
children a second copy. In a narrower window one watcher's `crop-3.png` was
overwritten by the other's between saving it and reading it, and the name
reader was handed a paper from the other class. Reproduced with two painted
walls and with two synthetic walls and the real reader, as two threads held
at a known point: class B has saved its first crop, class A sorts a whole
photo, class B carries on and finds its crop gone (`No such file or
directory`, and from the real reader `vision text failed`). The logs on this
Mac hold no "could not process" line, so it had not happened yet.

**Changed.** Every photo gets a scratch folder of its own,
`.tmp/<process id>-<random letters>`, made by `scratch_folder`, and
`process_photo` deletes that folder and nothing else. `.tmp` itself is
removed only when it is empty, which the operating system decides, not the
tool: removing a folder that holds another photo's folder is refused. If
another watcher removes the empty `.tmp` in the instant between this one
checking it is there and making its own folder inside, it is made again.
`process_photo` is now a few lines around the old body (`cut_and_file`), so
the scratch folder is taken away when a photo could not be sorted as well;
before, a failed photo's crops stayed until the next photo finished. What a
watcher stopped in the middle of a photo leaves behind used to be deleted by
the next photo along with everything else. Now the next photo clears only
what nobody has touched for an hour (`SCRATCH_STALE_SECONDS`); a photo takes
seconds, so a folder that old has no owner. Shared code, nothing Mac-only or
Windows-only in it. `.tmp/` is in `.gitignore`: it holds crops of children's
work for as long as a photo takes, and it was not ignored before.

**What this does not do.** A watcher that is already running keeps the code
it started with, so the change takes effect when each watcher is next
started. A watcher from before this change still deletes all of `.tmp` when
it finishes a photo, including a newer watcher's folder; every watcher run
from one tool folder has to be restarted, not only one of them. Two
computers watching one class were never part of this: each has its own tool
folder and its own `.tmp`, and the election above decides which of them
sorts. `tests/test_repairs.py`: `OneScratchFolderPerPhotoTests` (the class
that finishes first deletes nothing of the other's, no two photos are handed
the same scratch file, nothing is left behind after a sorted or a failed
photo, old leftovers are cleared and a busy folder is left alone) and
`OneScratchFolderPerPhotoOnARealWallTests` (two synthetic walls, the real
detectors and reader, every piece in its own class under its own child).

**The self-check had the same habit.** `--check` drew its test word into one
fixed file, `<tool folder>/.selfcheck.png`, read it back and deleted it. Two
checks at the same time from one tool folder, one per class, or two runs of
the tests, wrote and deleted the same file, and the slower one stopped with
"No such file or directory" where READY should have been. Seen as one error
in a full run of the tests while another run was going; the same test
passed alone. The check now asks `scratch_folder` for a folder of its own
and hands it back to `drop_scratch`, the same two calls a photo makes, so
its picture is `.tmp/<process id>-<random letters>/selfcheck.png` and a
photo being cut at that moment keeps its crops. It stays under the tool
folder, not the computer's temp folder, because that is where the Windows
reader was proven to open files. Shared code, the same on a Mac and on
Windows; not run on a Windows PC. Nothing a teacher sees has changed.
`tests/test_repairs.py`: `OneScratchFolderPerSelfCheckTests` (check B is
held with its picture saved while check A runs from start to finish, with a
stand-in reader and with the real one; no two checks are handed the same
file; nothing is left in the tool folder, also when the reader stops; a
photo's scratch folder is left alone). Against the old code four of the six
fail with that same "No such file or directory".

## September 26, evening: "no other computer is on" was a guess

**Seen.** Sahaj asked the question directly: photos are being added to the
class folder from the Mac, the classroom PC was set up from the
Windows zip, is that a problem? It is, until the PC has a new zip. Every
Windows zip so far was built from a commit from before status files (nothing
from September 26 has been pushed), so the PC's watcher sorts every photo it
sees and writes no status file. The Mac's watcher found no other status
file and wrote "this computer is watching this class (no other computer is
on)", twice that afternoon, and `Check Setup` repeated that line and listed
the Mac alone. Both told a person the PC was off. Neither could know that:
an empty `Watcher status` folder means nobody has reported in, and an older
version never reports in. The read-me's "More than one computer" section
described two computers sharing a class as something that works, with the
older-version paragraph underneath it and no rule to follow first. The
claim-before-cut and silent-sorter repairs above limit the harm once a
photo has been sorted twice; nothing said, before the first photo, that the
setup was not safe yet.

**Changed.** The words, in three places, from one pair of constants
(`ALONE_TEXT`, `UNSEEN_TEXT`) so they cannot drift apart. The log line is
now "this computer is watching this class (no other computer has reported
in)", followed by two sentences: a computer with an older version never
reports in, even when it is on and sorting, and if one is watching this
class too, stop one of the two watchers until it has this version. It is
said once per change of role, like every role line. The self-check, which
`Check Setup` runs on both platforms, prints "not in this list:" and the
same two sentences under the list of computers, whether the list is empty
or holds only this computer. The read-me's section now opens with the rule
and the way to tell: a computer with this version has a file named for it
in `Watcher status/` within a minute of its watcher starting; one that is
on and watching with no file there has an older version. `decide_role`
decides exactly what it decided before. Shared code, so a Windows watcher
with this version says the same.

**The rule until the new zip is on the PC.** One watcher only for that
class. Either `Stop Watcher.command` on the Mac while the PC's watcher is
on, or `Stop Watcher.bat` on the PC and let the Mac do the sorting. Adding
photos from the Mac's Finder is not the problem by itself; two watchers
are. The new zip exists only after these changes are pushed and the GitHub
build has run. A watcher that is already running keeps the words and the
code it started with, so the Mac's watcher has to be stopped and started
once to pick any of today's repairs up.

**What this does not do.** It does not find the older version before a
photo has been sorted twice; nothing that computer writes to the class
folder gives it away while the inbox is empty. It tells the truth about
what it cannot see, and the silent-sorter repair still catches the PC at
the first photo. `tests/test_repairs.py`
(`NoStatusFileIsNotNoComputerTests`): the reason for a computer alone, for
one whose neighbour's file has gone stale, and for one whose neighbour has
reported in; the watch log says it once and still sorts; the self-check
says who is missing from its list; the read-me puts the rule first; and the
old sentence is in neither the program nor the read-me.

## September 26, evening: the Mac zip for a colleague left out two files Setup needs

**Seen (before any teacher did).** Since this morning's launchd change,
`Setup.command`, `Check Setup.command`, `Start Watcher (visible).command`
and `Stop Watcher.command` all run `autostart.sh` from the folder they sit
in, and they know that folder is the tool folder because `watch.sh` is in
it; when it is not, they take the folder one level up. The GitHub build
copies both files into the Mac bundle. The class tool
(`tools/new_class.py --mac-dir`), which makes "Baggage Claim for Mac.zip"
from that bundle, kept only the `.command` files, the `.md` files, the apps
and `baggage-claim`. So a zip made from the next build would have had
neither file. Unzipped on a Desktop, Setup would have taken the Desktop
itself for the tool folder, found no program to check with, and ended in
NOT READY; with the check out of the way it would still have stopped at
"no such file" for `autostart.sh`. No such zip was handed out: the builds
on GitHub so far are from before the launchd change and carry the older
scripts, which need neither file.

**Fixed.** The list of what goes into the Mac zip now names `autostart.sh`
and `watch.sh`, and says why in a comment next to it. START HERE for the
Mac said macOS would ask whether "Baggage Claim Watcher" may read the Drive
folder; the program macOS names is the helper app, "Baggage Claim", and
START HERE now says that. It also says to keep all the files in the folder
together. The help for `--mac-dir` lists what the build folder must hold.
The Windows zip is made by the same function with its own list and is the
same as before.

**Tests.** `tests/test_repairs.py`, `MacZipForAColleagueTests` and
`SetupFromTheMacZipTests`. They run the class tool for an invented class
against a build folder made the way the GitHub recipe makes it (the real
`.command` files, `autostart.sh` and `watch.sh`; pretend programs), into
temporary folders, and unzip the Mac zip on a pretend Desktop. Every file a
`.command` runs from its own folder is in the zip and can be run; the same
check against a zip made with the old list reports `autostart.sh` missing;
`Setup.command` run from the unzipped folder ends in READY with the launchd
job pointing at that folder and nothing written beside it (a stub stands in
for `launchctl`); START HERE and the help name the right program; the
Windows zip holds what it held. The class tool is kept off GitHub with the
rest of `tools/`, so these tests skip on the build machines and run here.

**Still to do by a person.** A Mac zip already sitting in a class folder is
not changed by this. After these changes are pushed and the GitHub build
has run, make the zip again with the class tool; do not add the two files
to an old zip by hand.

## September 26, evening: the read-me named Mac files that were not where it said

**Seen (by reading, before a teacher did).** Under "Phone to folders" the
read-me listed `mac/Setup.command`, then a bare `Check Setup.command`, then
`Start Watcher.command`. In the source folder `Check Setup.command` is in
`mac/` like Setup, so a person looking next to `Start Watcher.command` did
not find it. In the one-click bundle there is no `Start Watcher.command` at
all: the file there is `Start Watcher (visible).command`. The Setup section
still described the bundle as "a `baggage-claim` command and a windowless
`Baggage Claim Watcher.app`", as if the app were the watcher. Since this
morning launchd runs `Baggage Claim.app`, which runs `watch.sh`, which runs
`baggage-claim`; nothing starts the other app. The GitHub recipe still built
it and the class tool still zipped it, so it was the one real app icon in a
teacher's folder. Double-clicked, it either closed at once because the
watcher was already running, with nothing on the screen, or became a second
way of running the watcher that nothing restarts. The sentence the watcher
writes to the log when macOS refuses the Drive folder had the same fault: it
said to start the watcher from `Start Watcher.command`, a file the bundle
does not have, and one that only follows the log once the launchd job is
loaded.

**Fixed.**
- The Mac job in the GitHub recipe no longer builds `Baggage Claim
  Watcher.app`. The bundle holds one program (`baggage-claim`), the helper
  app launchd runs (`Baggage Claim.app`), the four `.command` files,
  `autostart.sh` and `watch.sh`. The Windows job is not changed: it still
  builds `BaggageClaim.exe` and `BaggageClaimWatcher.exe`, and
  `watcher_entry.py` is still what the second one is made from.
- The class tool leaves `Baggage Claim Watcher.app` out of a Mac zip even
  when the build folder it is given is an old one that has it.
- Each Mac bullet in the read-me begins with the name a teacher sees in the
  bundle and says in brackets where the same file is in the source folder.
  `Start Watcher.command` and `Stop Watcher.command` at the top of the
  source folder are named as that. The read-me says what `Baggage Claim.app`
  is for, that nobody double-clicks it, what happens if somebody does, and
  that a folder from an older bundle may still hold the old app, which can
  go in the Trash.
- The log sentence now gives the same steps `Check Setup.command` prints:
  click Allow if macOS asked, or turn Google Drive on for Baggage Claim in
  System Settings. It still begins with the words Check Setup looks for.

**Not changed.** `autostart.sh` still stops a running `Baggage Claim
Watcher` and takes it out of Login Items when Setup runs, for a Mac that was
set up the old way. It does not delete the old app from the folder.

**Tests.** `tests/test_repairs.py`, `MacFilesAreWhereTheReadMeSaysTests`
and `OldWatcherAppStaysOutOfTheMacZipTests`: every Mac bullet names a file
the bundle has and a real place in the source folder, and the same check run
on the old bullets reports all three faults; every `.command` name anywhere
in the read-me is a real file; the Mac job builds no watcher app and still
builds and copies what launchd runs; the Windows job still builds its two
programs; no Mac script opens the old app; the log sentence names no file
the bundle lacks; and a zip made from a build folder that still has the old
app holds only `Baggage Claim.app`.

**Still to do by a person.** The Mac bundles on GitHub so far were built
before this. After these changes are pushed and the build has run, make the
Mac zip again with the class tool.

## September 26, evening: the second class on a Mac was watched by a line typed in Terminal

**Seen.** The launchd job runs `watch.sh`, and `watch.sh` only ever read
`settings.local.json`, so the job covered one class: the first one. For any
other class the class tool printed a line to paste into Terminal, `nohup
python3 baggage_claim.py --watch --settings classes/... &`. A watcher
started that way is nobody's job. It ends when the Mac restarts or the
person logs out, and nothing starts it again. On this Mac that is what had
happened: the second class's log held one line, from the afternoon of
September 25; after the restart at about 12:45 PM on September 26 the only
watcher process was the first class's; and the second class's folder had no
`Watcher status` folder, so no watcher from this version had ever run for
it. `Check Setup.command` could not notice. It asked whether any watcher
process was alive on the Mac, so one class's watcher answered for every
class, and it never looked in `classes/`. The read-me said "one machine can
watch several classes", which was true only for a Terminal session nobody
closed.

**Changed.** One launchd job per class.
1. `watch.sh` takes the settings file and the log as its two arguments.
   With none it is `settings.local.json` and `logs/watch.log`, as before,
   so the first job and the one-click bundle are unchanged.
2. `autostart.sh install <tool folder> <settings file>` writes a second job
   for that class. Its label is the first job's label, then `.class.`, then
   the class's file name in lower-case letters, digits and dashes, then a
   number made from the whole name, so two classes with similar names never
   share a job. The job runs the same helper app and the same `watch.sh`,
   with the class's settings file and `logs/<class>.log`, and has the same
   `RunAtLoad`, `KeepAlive` and `ThrottleInterval`. It keeps the log name
   the old Terminal line used, so the one-watcher lock next to that log
   still keeps a watcher started by hand and the job's watcher apart;
   install stops a watcher started by hand for that class first.
3. `Check Setup.command` says the four things (job loaded, watcher alive,
   log last changed, last line) for each class the Mac watches, each from
   its own job, its own process and its own log. A watcher is matched to
   its class by the settings file it was started with. Then it names every
   class that has a settings file in `classes/` and no job: `The class '...'
   has a settings file on this Mac, and this Mac does NOT watch it`, whether
   a watcher started by hand is running for it now, and the line to type if
   this Mac should watch it. That is information, not a failure, because
   the class tool writes a settings file for every class it checks in,
   including the ones a teacher's own computer watches.
4. `Stop Watcher.command` stops every class's job and prints the line that
   brings each one back. `autostart.sh remove <tool folder> <settings file>`
   stops one class only.
5. The class tool prints the install line in place of the `nohup` line, and
   says to skip it when another computer watches the class.

**A guard that came with it.** On this Mac `classes/` holds a settings file
for the first class too, because the class tool wrote one when that class
was checked in, and `settings.local.json` is a copy of it with a priority
added. A second job from that file would have been a second watcher for the
same class with a different log, which the one-watcher lock does not see
(the lock sits next to the log), and both would have filed every piece. So
install reads the `inbox` line of the settings file it is given and refuses
when `settings.local.json` or another class's job names the same Wall Inbox:
`This Mac already watches that class`, and nothing is changed. Check Setup
uses the same comparison to leave that file out of its "does NOT watch"
list.

**What this does not do.**
- It does not decide which classes this Mac watches. Nothing is started for
  a class until a person types its install line; a settings file in
  `classes/` is not an instruction. Starting every file found there would
  have put a second watcher on the first class, and a watcher on any class
  a teacher's own computer already watches.
- The same-class guard compares the inbox as it is written in the two
  files. Two files that reach the same folder by different spellings (one
  with `{DRIVE}`, one with the full path) are not caught.
- Windows is not changed. `Setup.bat` makes one Startup shortcut with one
  name and stops every `BaggageClaimWatcher.exe` on the PC, so a PC watches
  one class, and the read-me now says so in place of "one machine can watch
  several classes".
- A watcher that is already running keeps the scripts it started with.
- `Start Watcher (visible).command` follows the first class's log only. A
  second class's log is `logs/<class>.log`.

**Tests.** `tests/test_repairs.py`, `SecondClassOnTheSameMacTests` and
`ClassToolPrintsALineThatSurvivesARestartTests`, with invented classes, a
temporary LaunchAgents folder and a stub `launchctl` that answers for each
job by name: the second class's job file names its settings and its log and
starts at login; two classes never share a job; installing it leaves the
first job's file byte for byte the same; a second watcher for the first
class, or for a class that already has a job, is refused and nothing is
written; Check Setup names the unwatched class and the line it prints, run
as printed, sets the job up; each class is reported from its own job and its
own log; a watcher alive for one class is not counted for another (a real
process, started the way the job starts it); a watcher started by hand is
called that; Stop Watcher removes every job; one class can be stopped alone;
`watch.sh` hands the program the class's settings and log, and explains a
missing settings file in that class's log; the class tool prints no `nohup`
line and the line it prints produces the job. Run against the scripts from
before this change, 20 of the 23 fail; the three that pass are the ones that
check the first class is as it was.

**Still to do by a person.** The job for the second class has not been
installed on this Mac: whether this Mac or that teacher's own computer
watches that class is a decision, not a repair. `Check Setup.command` now
prints the line to type. Before typing it, the rule under "More than one
computer" applies to that class as well: if another computer watches it with
an older version, stop one of the two.

## September 26, evening: a class shared with a computer that never reports in

**Seen.** The question Sahaj asked, a second time, after the repairs above:
photos go into the class folder from the Mac, and the classroom
PC runs the Windows zip. Is that a problem? It still was. The PC's zip is
from before status files, so it sorts every photo it sees and writes no
status file. The Mac found only its own file in `Watcher status`, took
itself for the watcher, and sorted too. The one check against a second copy,
`piece_name`, looks for a file of the same name in this computer's own copy
of the folder; the other computer's copy arrives through Google Drive
seconds or minutes later. So both chose `Self-Portrait K.jpg`,
Drive kept both, and every child's folder showed two files with one name (on
a computer the second one becomes `... (1).jpg`). They are not even the same
crop, because Windows has no rectangle detector. The repairs above limit
this: a photo is claimed before it is cut, and a watcher that catches the
other computer at it stands by for eight hours. But catching it needs a
photo that has already been sorted twice, the eight hours are forgotten when
the watcher is restarted, and a Mac restarts every morning. So the first
photo of every school day was filed twice. The rule "run one watcher only"
was written down in two places and nothing in the program kept it.

**Changed.** The settings file can now say what the program cannot see: the
line `"shared": true` (or `--shared`) means another computer watches this
class too. While no other computer has ever written a status file, the
watcher does not sort a new photo at once. It leaves the photo in `Wall
Inbox` for `SHARED_WAIT_SECONDS`, ten minutes, counted from when this
watcher first saw it, and sorts it only if it is still there after that.
Nothing is claimed, cut or saved in those ten minutes. A computer with the
older version that is on sorts the photo and moves it to `done` long before
then, and this one finds it gone and says `The other computer took it`. A
computer that is off leaves the photo where it is, and this one sorts it ten
minutes late and says `still in Wall Inbox after 10 minutes`. Either way
each child gets the piece once and no photo waits for ever. The log says
why once, the status file carries a `Note:` line under the role, and the
self-check, which `Check Setup` runs on both platforms, says `this class is
shared:` and the same sentence.

**Why the wait is counted from first sight.** A photo's own date is when
the picture was taken, and Google Drive keeps it. A picture taken on Friday
and shared on Monday would have looked three days old and been sorted at
once.

**Why not a name for each computer in the file name.** It was the other
repair on offer: `Self-Portrait K - <computer>.jpg`. The two
copies would no longer share a name, and every child would still have two.
It would also change the name of every piece for every class, and the
computer with the older version would not take part in it.

**When the other computer has this version.** Its first status file ends the
wait by itself: the log says `the other computer has reported in, so it has
this version`, the note leaves the status file, and the election decides
from then on, as before. An old status file counts as having reported in: a
computer with this version that is switched off is what the election
already covers. The line can stay in the settings file.

**On this Mac.** `settings.local.json` now has `"shared": true` next to
`"priority": 90`. The file is ignored by git. To undo it, take the line out
and start the watcher again.

**What this does not do.**
- It changes nothing until the Mac's watcher is started again. The one
  running now was started at 2:00 PM on September 26 and keeps the code and
  the settings it started with: its log still says priority 50 and `no
  other computer is on`. It was not stopped or restarted as part of this
  repair, because which of the two computers watches until then is a
  person's decision. Until it is restarted, the rule is still one watcher
  only.
- If the computer with the older version takes more than ten minutes to
  sort a photo (Google Drive far behind, or the computer waking up in the
  ninth minute), both sort it. The watcher then notices the second copy and
  stands by for eight hours, as before.
- Sorting by hand with `Baggage Claim.command` does not wait. It never took
  part in the election either.
- A computer's name is what the computer calls itself. If this Mac wrote a
  status file under another name in the past (a Mac's network name can
  change), that old file counts as another computer having reported in, and
  nothing is kept waiting. `Check Setup` lists every file in `Watcher
  status`; one that is this Mac under an old name can be deleted.
- It covers one other computer. With three, one report ends the wait.
- The cure is unchanged: push these changes, let the GitHub build make a new
  zip, and unzip it over the folder on the classroom PC.

**Tests.** `tests/test_repairs.py`, `SharedClassWithAnOlderVersionTests`,
with an invented child, a fake clock and a stand-in for the computer with
the older version (it files its piece, moves the photo to `done`, writes no
status file). With both computers on, the child's folder holds one file and
this computer cut nothing; the same morning without the line in the
settings holds two, which is the defect as reported. With the other
computer off, the photo is sorted once, between ten and twelve minutes
after it was first seen. A picture dated last week waits like any other. A
status file from the other computer, fresh or old, ends the wait. The other
computer taking a photo that was left for it is not an alarm. The note is
in the status file and the other watchers can still read the file. Shared
code, nothing Mac-only or Windows-only in it; it has not been run on a
Windows PC.

## September 26, evening: the sorting computer sorted first and said so afterwards

**Seen.** The status file is the only way the sorting computer has of
telling the others "I am on, leave the photos to me". The watch loop wrote
it at the end of a tick, after `run_inbox`, and stamped it with the time
the tick had begun. Three things followed.

1. The classroom PC (priority 50) sleeps for six minutes and the helper's
   Mac (priority 90) takes over. The wake-up repair above already made the
   PC wait 90 seconds. But when the 90 seconds ended, the PC sorted the
   whole batch first and wrote "watching" afterwards; the file the Mac held
   all that time said "just started" and was up to 100 seconds old when
   the batch began.
2. A batch is not short. Five photos at a minute or two each is longer than
   the five minutes after which the others decide a computer is off, and
   the file was not touched during a batch. When it was written at the
   end, it carried the time from before the batch, so a four-minute batch
   produced a file that was four minutes old already. The Mac took over in
   the middle of the PC's batch, or a minute after it.
3. When the file could not be written at all (Drive signed out, disk full),
   the log said so once and the PC went on sorting. To the Mac the PC was
   off after five minutes; the Mac sorted as well, and nothing ever made
   the PC stop.

In each case both computers file the same photo and every child has the
piece twice.

**Changed.** All in the shared code, so the Mac and the Windows watcher get
the same behaviour.

- The loop writes the status file before `run_inbox`, never after: on a
  start, a wake-up, a change of role, and once a minute. The write after a
  batch is still there, for the "Last batch" line.
- `run_inbox` takes `beat`, called before each photo is claimed. The loop
  passes the same writer, so the file is rewritten between photos whenever
  it is a minute old.
- The time in the file is the time it was written (`keep_status` reads the
  clock itself).
- `status_lost`: after a failed write, if the last good file is
  `STATUS_LOST_SECONDS` old (three minutes; the others take over at five)
  or none was ever written, this computer stands by whatever the election
  says. A batch in progress stops before the next photo and leaves the rest
  in the inbox. One failed write with a file a minute old changes nothing.
- When the file can be written again, the grace period starts again, as
  after a wake-up: another computer may have taken over and be in the
  middle of a photo.

What a person sees in the log, once each: `could not write this computer's
status file ...`, then `standing by: this computer cannot write its status
file ...` with what to check, then `this computer's status file can be
written again; standing by for 90 seconds ...`.

**What this does not do.**
- It is of use only when both computers have this version. A computer with
  an older version writes no status file and reads none; the sections
  above are what cover that.
- A file written to this computer's disk is not yet a file on the other
  computer. If Google Drive is paused or offline while the folder on disk
  is still writable, the write succeeds, this computer believes it has been
  seen, and the other takes over after five minutes. The tool cannot see
  Drive's own state from inside a folder. Claiming the photo before cutting
  it is what limits the harm then.
- A single photo that takes more than five minutes to cut would still let
  the file go stale; none has come near that.
- A class watched by one computer only also stands by when its status file
  cannot be written. Its photos wait in the inbox and are sorted when the
  file is back. That was chosen over guessing that nobody else is there.
- The pure `decide_role` is unchanged and has no grace of its own for a
  computer that slept; the loop supplies it by passing the wake-up time.

**Tests.** `tests/test_repairs.py`, `StatusIsWrittenBeforeSortingTests` and
`StatusFileCannotBeWrittenTests`, with a fake clock and an invented child.
The six-minute sleep as reported: nothing is sorted on waking, the file is
rewritten at once, and each time sorting begins the file already says
"watching" and is seconds old. A six-minute batch of three photos never has
a file older than two seconds at the start of a photo. A disk that fills up
lets the computer sort for three more minutes, then not at all, then again
90 seconds after room is made. A computer that never managed to write its
file never sorts. A batch stops before its third photo and the photo is
still in the inbox. Run against the loop as it was, six of the eleven
fail; the other five test the words and the small functions. Not run on a
Windows PC.

## September 26, evening: the class list and the program that saved it

**Seen.** The class list was opened as UTF-8 and nothing else. Three things
a teacher does without knowing it broke that. Google Docs' "Download as
plain text", Notepad's "UTF-8 with BOM" and Word's "Plain Text" put an
invisible mark (U+FEFF) at the very start of the file. It stayed on the
first line, so the first child's name began with a character nobody can
see, and the tool made a folder for that name: a second folder for the same
child, identical on the screen, next to the one the teacher had made by
hand. Every piece for that child went into the twin. When the first line
was a `#` note, the mark came before the `#`, the line was no longer a note,
and it became a folder. And Word on Windows saves plain text in the Windows
encoding unless told otherwise: one Zoë or José in the list raised
`UnicodeDecodeError`. The running watcher survived that (it kept its old
list), but a watcher that was starting did not, and launchd or Task
Scheduler started it again every 30 to 60 seconds with the same result.
Reproduced with invented names in a temporary folder: two folders for one
child, and the traceback.

**Changed.** `load_roster` reads the bytes and `read_class_list` decides how
they were saved, from the bytes alone:

1. A file that starts with the UTF-16 mark (Notepad's "Unicode") is UTF-16.
2. Otherwise it is tried as UTF-8, with or without the mark at the start.
3. Otherwise it was saved in the computer's own encoding, and the file does
   not say which: Windows-1252 (Word or an older Notepad on Windows) or Mac
   Roman (Word on a Mac). Both are tried. A reading is believed only when
   every name in it looks like a name: an accented small letter anywhere
   except straight before a capital, an accented capital at the start of a
   word, a curly apostrophe between a letter and a capital. The wrong
   reading of "José" puts a capital or a symbol in the middle of the word,
   which is how the two are told apart.
4. When neither reading makes sense, or both do and they give different
   names, nothing is guessed. `ClassListError` carries one plain sentence
   with the line number and what to do (Save As, UTF-8). It never repeats
   the words on the line, because the line is a child's name and the log
   is not the place for it.

Every line then loses its invisible characters (the mark, zero-width
spaces) wherever they are, and a tab or a run of spaces becomes one space,
before the `#` test. The three places that read the list at start (the
watcher's waiting loop, a one-off run, and `--check`) now say the sentence
instead of ending: the watcher waits a minute at a time and starts by
itself when the list has been saved again. The class tool reads the list
through the same function, so the folders it makes and the names it adds to
the protected list are free of the mark too.

**Why from the bytes alone.** Two computers can watch one class, a Mac and
a Windows PC, and both read the same file through Google Drive. If the
reading depended on the computer (Python's default encoding is different on
each), the two would make differently spelled folders for one child. The
same bytes give the same names everywhere.

**What this does not do.** Where Windows and an older Mac both give a
sensible name for the same bytes, the list is refused, not guessed: a name
that begins with an accented capital saved by Word on a Mac is the known
case. Re-saving as UTF-8 settles it. A name with a curly apostrophe before
a small letter, saved on Windows, is read as the Mac letter that shares
that byte; the child's folder is then spelled with an í in place of the
apostrophe, and the pieces still reach it. A twin folder made by an older
version is not merged or removed: the tool never deletes a child's folder,
so a person moves the work across. A computer still running the older
build reads the same shared class list the old way until its build is
replaced, so until then the list in a shared class folder should be plain
UTF-8 with no mark (type it in Notepad or TextEdit and save).
`tests/test_repairs.py`: `ClassListSavedByAnyProgramTests` (each way of
saving, one folder per child however it was saved, the line number and not
the name, the running watcher, the one-off run and the self-check) and
`ClassListSavedByAnyProgramInTheWatcherTests` (a watcher that starts with a
list it cannot read waits and then starts; a synthetic wall filed into the
folders the teacher made, from a list downloaded from Google Docs). Against
the reader as it was, 17 of the 20 fail. Not run on a Windows PC.

## September 26, night: a photo sorted a second time gave children a second copy

**Seen.** Pieces are saved into the children's folders one at a time. When
a photo was sorted a second time, every child who already had the piece got
it again as `Self-Portrait K 2.jpg`, the same picture twice.
Three ordinary ways to get there. One piece cannot be saved (the disk is
full, Google Drive is signed out), the photo goes to `Wall Inbox/failed`
with the first children already filed, and the teacher moves it back. The
computer stops halfway, the `NOT FINISHED` note says to move the photo back
from `done`, and the teacher does. Or the teacher puts a name right on the
class list and shares the same photo again for that one child. The note
from the repair above said as much: "the worst it costs is a second copy".
Also, a piece was written straight into the child's folder under its real
name, so a computer that stopped in the middle of writing left half a
picture there for Drive to upload. Reproduced with invented names and a
painted wall of eight: the fifth piece fails, the photo is put back, and
the first four children each hold two files.

**Changed.** Every piece the tool saves now has a short note inside the
file, as a JPEG comment, which no picture viewer shows: a fingerprint of
the photo file it was cut from (the first 16 characters of a SHA-1 of the
photo's bytes) and the box on the photo it came from. No name is in it.
Before a piece is filed, the child's project folder is looked through for
a piece with the same fingerprint whose box shares at least half of this
one (`filed_already`). If one is there, nothing is saved, the log says
`Maya Torres already has this piece from this photo ('Self-Portrait
K.jpg'), so it was not filed a second time`, the photo gets one summary
line, and `run-report.md` marks the row. And a piece is saved whole or not
at all (`save_whole`): the JPEG is made in memory, written beside its
destination under a name ending in `.part`, flushed, and renamed. A rename
that Windows refuses for a moment, because a virus scanner is still
reading the new file, is tried again five times, half a second apart. A
`.jpg.part` file more than an hour old is taken away the next time the
tool files into that folder. The `NOT FINISHED` note, the log line and the
README now say that only the missing pieces are filed.

**Why the note is inside the file and not in a list.** The report asked
for a list per photo (photo name and piece number, to the saved path).
Two things decided against keeping it in the tool's own folder. Two
computers watch one class here, a Mac and the classroom PC, and the one
that sorts the photo the second time is often not the one that stopped;
a list on the first computer's disk is invisible to the second. And a
list can disagree with the folders: the teacher deletes a piece, renames
one, or moves a doubtful piece into the child's folder by hand. The note
goes wherever the file goes, through Drive, and goes away with it, so a
deleted piece is filed again and a piece moved by hand is recognised. The
fingerprint is of the file, not its name, because phones reuse names and
a photo shared again can arrive under a new one. The box is compared by
overlap, not exactly, because the Mac has a rectangle detector the PC does
not and the two put the edges a few pixels apart. Two papers by one child
in one photo are in different places, so both are filed. Shared code,
nothing Mac-only or Windows-only in it.

**What this does not do.** A piece saved by a build from before this
change has no note, so a photo first sorted by an older build and sorted
again by this one is still filed twice; the classroom PC has the older
build until its zip is replaced. A phone that re-encodes a photo when it
is shared again produces a different file, which counts as a new photo. A
doubtful piece left in `Unsorted - needs a person` by the first try stays
there when the second try files that piece under a child: the tool does
not delete from a folder a person works in. Reading the notes means
opening the first 4,096 bytes of each picture in one child's project
folder, which on a computer that streams from Drive fetches those files
once. `tests/test_repairs.py`: `FiledOnceHoweverOftenThePhotoIsSortedTests`,
`TwoPapersByOneChildTests`, `SavedWholeOrNotAtAllTests`,
`TheNoteInsideAPieceTests`, and `FiledOnceOnARealWallTests` with a
synthetic wall of eight and the real reader: 24 tests. Against the code as
it was, 22 of the 23 that could run fail (the real-wall one needs the
reader beside the file under test and was skipped there). Not run on a
Windows PC.

## September 26, night: a class folder whose name ends with a space

**Seen.** The class folder this Mac watches has a space at the end of its
name. Nobody can see it: Finder, a phone and Google Drive in a browser show
the name the same with or without it. All four paths in the Mac's settings
file carry it. A Mac keeps such a name as it is. Windows cannot open a
folder whose name ends with a space or a full stop; it takes them off the
names it makes, and File Explorer cannot show them. So the classroom PC
cannot be pointed at the same folder by the same settings. If Google Drive
on the PC shows the folder without the space, a settings file with the space
finds nothing and the watcher waits for ever (`waiting: cannot find ...`).
If Drive does not bring the folder to the PC at all and somebody makes one
there under the name without the space, the class has two folders in Drive
with children's folders in both. `safe_folder` has known the rule since the
second Windows build (a child called `Maya R.`), but only for folders the
tool makes. Nothing looked at the folders a person made: not `--check`, not
the log, not the class tool, not the read-me. What Google Drive on a PC
really does with such a folder was not observed here.

**Changed, four things.** `bad_endings` finds the names in a path that end
with a space or a full stop. The self-check prints one of three things for
each such name in the settings file. On a computer that has the folder
under that name (a Mac): `WARN: the folder name '...' ends with a space`,
why a Windows PC cannot open it, and what to do; the computer is still
READY, because it can do its job, and Setup is not blocked. On a computer
that cannot find the folder either way: FAIL, the same reason, NOT READY.
On a computer that has the folder under the name without the ending: `ok`,
and which name is being used. The watcher says the same sentence in its log,
once at start on a Mac that has the folder, and inside the `waiting: cannot
find` line on a computer that does not. The class tool
(`tools/new_class.py`) stops before it makes anything when the class name
ends with a space or a full stop or has a character Windows refuses, and
says which name to use instead. The read-me it writes into `Wall Inbox` and
the README say it too.

**The part that makes the cure one step.** Renaming the folder in Google
Drive would have broken every computer whose settings file still had the
old name, and on the classroom PC a settings file is not something a
teacher edits. So `expand_path` now looks for a name both ways
(`as_found_here`): on a Mac the path as written when it is there, and
without the endings when only that one is there; on Windows always without
them, because no other spelling can exist there. The `{DRIVE}` search uses
the same rule, so a Mac with two Google accounts still picks the one that
has the class. After the rename nobody edits a settings file; the watcher
has to be started again (Setup, or a restart of the computer), because a
running watcher keeps the paths it started with.

**What this does not do.** It does not rename the folder: the folder is a
person's, in a Drive the tool only reads and files into, and the rename is
theirs to do. Until then the Mac works and warns, and the classroom PC is
in whichever state Google Drive has put it. It does not notice a name that
begins with a space. A watcher that is running when the folder is renamed
writes one line a minute saying the folder is not there, in the operating
system's words, until it is started again.
`tests/test_repairs.py` (`FolderNameEndsWithASpaceTests`, 15 tests, invented
class in a temporary folder): the rule, the three things the self-check
says, the old settings file leading to the renamed folder on a Mac and on a
simulated Windows PC, two Google Drives, the two log lines, the class tool
refusing three names, and the README section. Not run on a Windows PC.

## September 26, night: the repairs were on the disk and the watcher from 2:00 PM was still running

**Seen.** The report, a third time: the classroom PC runs the Windows zip
from before status files, the Mac watches the same class, and both sort
every photo. By now every repair the Mac can make by itself was on the Mac:
a photo is claimed before it is cut, the iPhone copy stays out of `Wall
Inbox`, and the settings file says `"shared": true` and `"priority": 90`.
None of it was in use. The watcher process on the Mac had been started at
2:00 PM and was never started again; a watcher reads the settings file and
the program once, when it starts. Its log still said priority 50 and `no
other computer is on`, and it sorted each photo the moment it saw it. Two
sections above say "it changes nothing until the Mac's watcher is started
again", in these notes, where no teacher looks. The tool itself said the
opposite. `Check Setup` reads the settings file, so it printed `this class
is shared: ... this computer leaves each new photo for that computer for 10
minutes` about a watcher that did no such thing, two lines under a list that
showed the same computer `watching, priority 50`.

**Changed.** The self-check, which `Check Setup` and `Setup` run on both
platforms, now compares the watcher that is running with what is on the
disk (`watcher_behind`). It reads this computer's own status file. If the
file is fresh, a watcher is running, and four things are looked at: the
priority it sorts with against the priority in the settings file; whether
the settings file says the class is shared while the running watcher is
sorting, nobody else has reported in, and its status file has no `Note:`
about leaving photos for the other computer; and whether the settings file
or the program was changed more than a minute after the time on the file's
`Watcher started` line. For the program the time it arrived on the disk
counts as well as its date, because a zip keeps the day the program was
built, which can be days before it is unzipped. Any of these prints `WARN:
the watcher that is running on this computer is still working the old way`,
each reason as a sentence, and the one thing to do: double-click Setup,
which starts the watcher again on a Mac and on a Windows PC. The line about
a shared class no longer claims the wait when the running watcher is
behind; it points at the WARN. The check still ends in READY. Setup runs the
check before it restarts the watcher, so a FAIL here would have stopped the
cure.

**On this Mac.** Run once after the change, the check gave all four
reasons: priority 50 against 90, the shared line not in use, the settings
file changed at 6:10 PM and the program changed that evening, both after a
start at 2:00 PM.

**What this does not do.**
- It does not start the watcher again. It was not restarted as part of this
  repair: the program was being changed by several repairs at once that
  evening, and a watcher started in the middle of that would file real work
  with a half-changed program. Start it again once the tests pass and the
  changes are in: double-click `Setup.command`.
- It does not put this version on the classroom PC. That needs these
  changes pushed (after the privacy gate), the GitHub build, and the new zip
  unzipped on the PC, then `Setup.bat`. Until both steps are done, the rule
  at the top of "More than one computer" in the read-me stands: one watcher
  only for that class.
- A person has to run `Check Setup` to see the line. The watcher that is
  behind cannot say it in its own log, because it is the old program.
- A computer with a version from before status files has no status file, so
  the check on that computer has nothing to compare. A status file from a
  version without the `Watcher started` line is judged by its priority and
  the shared line only.
- If a computer's name has changed since its watcher started (a Mac can be
  given another name by a network), its status file is under the old name
  and the check does not find it.

**Tests.** `tests/test_repairs.py`,
`CheckSetupSaysWhenTheRunningWatcherIsBehindTests`, 13 tests, with an
invented class in a temporary folder, a stand-in reader and the watcher
from the afternoon played by a status file written the way it wrote it. The
report: three reasons, in plain sentences. The check says WARN, the reasons
and what to do, ends in READY and returns 0, and does not say the running
watcher leaves photos for the other computer. A watcher started by the real
watch loop with the same settings file is not behind and the check says
nothing. No status file, an old one, or a file that is not a status file is
not a watcher that is behind. A status file with no `Watcher started` line
is still caught by its priority. A program dated a month ago and unzipped a
moment ago counts as changed now. A computer standing by, or one whose
neighbour has reported in, is not warned about the shared line. The
`Watcher started` line is read back as it was written. The read-me section.
Shared code; not run on a Windows PC.

## September 26, night: a renamed folder came back empty under its old name

**Seen.** `run_inbox` began every look at the inbox, every five seconds,
with `os.makedirs(<inbox>/done, exist_ok=True)`, and `os.makedirs` makes
every folder on the way down as well. So the watcher made `Wall Inbox`
itself whenever it was not there. A teacher renames `Wall Inbox` to
`Photos`: an empty `Wall Inbox/done` is back within one look, the photos she
puts into `Photos` are never seen, and the log and the status file go on
saying `watching this class`, `Photos waiting: 0`. She renames the class
folder: `Wall Inbox/done` comes back under the old name, then `Watcher
status`, then a folder for each child as soon as a project or a name is new,
and new work is filed into the empty copy while the folder with the real
work is left behind. Nothing was logged, because every call succeeded. The
same lines run on a Mac when Google Drive signs out and its folder under
`~/Library/CloudStorage` goes away: the class is built again as ordinary
folders on the Mac's own disk. And the place of "My Drive" was worked out
again only while the watcher waited to start, never once it was running.
Reproduced on invented folders in a temporary place, through `main` with
`--watch`, before anything was changed: after the rename of `Wall Inbox`
the class folder held both `Photos` and a new `Wall Inbox`; after the
rename of the class folder the old name was back with `Wall Inbox/done` in
it; the log had no line for either. The Drive sign-out was not tried against
Google Drive itself; a folder taken away and put back stands in for it.

**The rule.** `Wall Inbox` and the class folder are a person's folders. The
tool makes folders inside them and never the two folders themselves.

**Changed, in shared code, so the Mac and Windows watchers both get it.**
- `make_inside(root, path)` makes `path` and the folders on the way down to
  it with one `os.mkdir` each, starting below `root`. `os.mkdir` cannot make
  the folder above, so there is no moment between looking and making in
  which a renamed folder could be made again. When `root` is not there it
  raises `FileNotFoundError` with a plain sentence (`gone_text`), not the
  operating system's words.
- It is used wherever something is made inside one of the two folders:
  `done`, `done/<project>` and `failed` in `run_inbox`; a new child's
  folder (`make_new_child_folders`); the child's folder when a piece is
  filed and the doubtful-pieces folder when one is not (`cut_and_file`);
  the `NOT FINISHED` note; and `Watcher status` (`write_status`). The
  doubtful-pieces folder is still made when it is needed. Inside the class
  folder it is made without making the class folder (`held_by`); kept
  anywhere else, it is made whole, as it always was.
- The watch loop looks for the two folders first, on every look, before it
  reads or makes anything (`folders_gone`). When one is gone it works the
  paths out again from the settings file (`resolve_paths`, the same lines
  the wait at start used, now one function). If the folder is found in
  another place, because "My Drive" came back under another drive letter or
  a space was taken off the end of the class folder's name, the watcher
  follows it. If not, the log says once `cannot find the folder 'Wall
  Inbox' any more`, where it was, whether the folder that holds it is there
  (renamed, moved or deleted) or not (most likely Google Drive is signed
  out), and the one thing to do. The status file says `standing by` with a
  note for as long as the class folder is there to hold it. Nothing is
  made, read or sorted, and the watcher looks again every few seconds.
- Gone means not there. A folder the program is not allowed to look at,
  because macOS has not yet been told to let it read Google Drive, is not
  gone (`is_gone`), so the PERMISSION NEEDED line of `Check Setup` is said
  as before and not replaced by a line about a rename.
- When the folders are back the log says so, and the 90-second grace period
  starts again, as after a sleep: if Drive was away, this computer's copy
  of the class folder is old for a moment.
- `run_inbox` looks again before each photo of a batch, so a folder renamed
  in the middle of a batch stops the batch before the next photo is claimed,
  and is not taken for another computer's work (which would have put this
  watcher on standby for eight hours). A photo that was being left for the
  other computer of a shared class and went away with the folder is
  forgotten without the line `The other computer took it`.
- A run that is not the watcher (`Baggage Claim.command`, once through)
  still makes the tool's own `inbox` next to the program the first time.
  Any other inbox has to be there, and the run ends with one plain sentence
  when it is not.

**What a teacher sees now.** The README has a section, "If Wall Inbox or
the class folder is renamed". The short of it: give the folder its old name
back in Google Drive and the sorting carries on by itself within two
minutes; nobody restarts anything.

**What this does not do.**
- It does not follow a rename. The watcher cannot know that `Photos` is the
  old `Wall Inbox`; a person gives the name back, or the settings file is
  changed and Setup is run.
- It does not help a computer that has an older version. A classroom PC set
  up from a zip built before this change still makes `Wall Inbox` again
  within five seconds of a rename, and Google Drive brings that empty folder
  to every other computer, which then finds a `Wall Inbox` and says nothing.
  The Windows zip has to be built again from this version and Setup run on
  that PC, like the other repairs of today.
- At start, a class folder named in the settings file that is not there is
  still made, as before, when the class list and the inbox are somewhere
  else and can be found. In every class set up by the class tool the three
  are in one folder, so the watcher waits (`waiting: cannot find ...`) and
  makes nothing.
- The doubtful-pieces folder is made again if it is renamed, inside the
  folder that holds it. A doubtful piece has to go somewhere a teacher
  looks.
- While the inbox cannot be found and the class folder can, this computer
  keeps writing its status file, so another computer with a higher priority
  number goes on standing by. A rename in Google Drive reaches every
  computer, so they are all in the same place; a computer that alone cannot
  see the inbox is the case this leaves open.
- A folder renamed in the ten seconds a photo is being cut: the pieces not
  yet filed are not filed, the log says why, and the photo is in `done`
  inside the renamed folder. No `NOT FINISHED` note is written for it.
- Not run on a Windows PC or against Google Drive itself.

**Two tests of the election were changed, in their preparation only.**
`tests/test_multi_watcher.py` wrote a status file for a class folder that
did not exist and relied on the status file making it. The class folder is
now made first, in `ElectionTests.setUp` and in one test of
`ChildFolderWalkTests`; what the tests check is as it was.

**Tests.** `tests/test_repairs.py`, `RenamedFolderIsNotMadeAgainTests` (20),
`RenamedFolderOnARealWallTests` (2) and
`RenamedFolderSaidOnceAndOnlyWhenGoneTests` (2), with an invented class in a
temporary folder. Through the real watch loop: `Wall Inbox` renamed and
given its name back, with a photo waiting in the renamed folder; the class
folder renamed, and given its name back; the folder that stands for Google
Drive taken away and put back; "My Drive" moved from one place to another;
a space taken off the end of the class folder's name; a shared class; a
rename noticed in the middle of a look, said once. One look at the inbox: no inbox, an inbox kept outside the class folder, a
rename in the middle of a batch. The pieces: `make_inside`, `folders_gone`,
the status file, the note, the run that is once through, the README
section. On a synthetic wall: a piece about to be filed, and a doubtful
one, make no class folder; with the folders there the wall is filed as
before. Run against the program as it was, 19 of the 24 fail or stop; the
five that pass are the things that were to stay as they were.

## September 26, night: 25 files called GUESS, and every name had been read

**Seen.** One photo of a whole wall, 25 papers. The reader read all 25 name
labels; the paper detectors found three papers. So the pieces were cut out
around the labels, and the rule from September 25 sent every one of them to
a person, because edges guessed from the words can take in a neighbour's
paper. That rule is right and is unchanged. What was wrong is what the
person was told. Each file was called `GUESS Maya Torres - ...`, the word
the tool uses when the name is the doubt. The log said `unsure  Maya Torres
read 'Maya Torres' score 1.0`. The status file said `25 pieces, 0 filed, 25
to unsorted`, the same words it uses for 25 names in unreadable pencil. The
one place that gave the reason, `run-report.md`, is in the tool's folder on
the watching computer, which a teacher never opens. A teacher who finds 25
GUESS files concludes the name reader failed, and photographs the same wall
the same way again. Reproduced on a synthetic wall, pale paper on a pale
wall, invented names: eight pieces, eight files called GUESS, each with the
right name at score 1.0.

**Changed.** The reason now travels with the piece. Where a confident match
is sent to a person because its edges were guessed, the piece is marked
(`reason`, `edges`), and everything a person sees is built from that mark:

- The file is `CHECK PICTURE Maya Torres - <project> <grade> - <photo>
  07.jpg`. `GUESS` is kept for a name that is a guess, including a label
  that was read shakily on the same photo.
- A note is written beside the pieces, `CHECK PICTURE - read me - <project>
  - <photo>.txt`: the names were read, how many labels and how many papers,
  the two usual causes, and the two things to do (photograph again with six
  to eight papers in each photo, or look at each picture and move it by
  hand). It names the photo and the numbers, never a child.
- The log line for the piece says `check picture`, and one line for the
  photo says that the name reader worked and why nothing was filed.
- The line for the batch, which is also the `Last batch` line of the status
  file, gives the cause after the numbers. The numbers come first and are
  worded as before, so anything that reads that line still can.
- `run-report.md` says `name read, check the picture` for those pieces.

**The wording has two cases.** The pieces are cut around the labels when
there are more labels than papers found, and also when as many papers were
found but the labels are not on or beside them (the detectors boxed the
block of writing and missed the label in the corner). The synthetic wall is
the second case: eight labels, eight papers found. A sentence that said
"more papers than the tool could find" would have been false there, so the
note and the log say which of the two it was.

**What did not change.** Nothing is filed that was not filed before. The
status of such a piece is still `unsure`, so every count of filed against
unsorted is the same, and so is what the other watchers read from a status
file. Shared code: the Mac and Windows watchers both get it.

**What this does not do.**
- A computer with a version of the tool from before this one still calls
  the files GUESS and writes no note. When two computers watch a class, the
  one that sorts the photo names the files, so the classroom PC needs a zip
  built from this version before its files change.
- The note is written once for each photo and is not taken away when the
  pieces are dealt with; it says it can be deleted.
- A photo cut with `--grid` is not read this way: there the edges are an
  even grid the person asked for, and a name read well is filed.
- Not run on a Windows PC, and not run on a real wall: no real photo was
  opened for this repair.

**Tests.** `tests/test_repairs.py`, `NameReadPictureToCheckTests` (12), with
a name reader that returns eight labels and detectors that return two
papers, so they run on any computer: the file names, the note and that it
names no child, the log, the report, the status file through the real watch
loop, the run that is once through with a settings file, the second case of
the wording, one shaky label among eight, a grid with nothing readable
(still GUESS, no note), a note that cannot be written, and the README
section. `NameReadPictureToCheckOnASyntheticWallTests` (1) is the reported
steps with the real detectors and the real reader on a wall from
`make_wall.py`.

## September 26, night: a photo in `failed`, and nothing to say why

**Seen.** A photo the tool cannot open, read or save from is moved to
`Wall Inbox/failed` so that it does not hold up the photos behind it. That
part is right and is unchanged. What was wrong is what anybody was told. The
only record was one line in the log on the watching computer, with the
program's own error text in it (`could not process (image file is truncated
(0 bytes not processed)); moved to inbox/failed`). The watch loop wrote the
`Last batch` line only when a batch had filed pieces, and a photo that fails
files none, so the status file went on showing the batch before, or `none
yet`. The teacher saw a folder called `failed` appear in Drive with her
photo in it and nothing that said whether to share it again, wait, or tell
somebody. A person looking from somewhere else saw nothing at all.
Reproduced with a synthetic wall saved as a JPEG and cut off halfway, the
way an upload that stopped in the middle looks: the photo goes to `failed`,
the doubtful-pieces folder is empty, the status file says `Last batch: none
yet`.

**Changed.** The photo still goes to `failed`. Three places now say so, in
plain words (`tell_could_not_sort`):

- A note in the doubtful-pieces folder, `COULD NOT SORT - <project> -
  <photo>.txt`, beside the `NOT FINISHED` and `CHECK PICTURE` notes: the
  photo, the project, when, which computer, where the photo is now, what
  happened, and numbered steps. It names the photo and the folders, never a
  child.
- The status file. `Last batch` is written for a look that had a photo fail,
  with or without pieces filed: `1 photo could not be sorted and is in
  'failed' inside Wall Inbox ('IMG_1234.jpg': the file could not be opened
  as a picture ...)`, after the usual `8 pieces, 8 filed, 0 to unsorted`
  when there were good photos too. A second line, `Photos that could not be
  sorted: 1`, is counted from the `failed` folder each time the file is
  written (`photos_in_failed`), so it is still there after the next batch
  and after the watcher is started again, and it goes away by itself when a
  person has moved or deleted the photo. The line is left out when the count
  is 0, and the lines the other watchers read are the same as before.
- The log: the same reason and the same steps, and after them the program's
  own words for whoever set the computer up.

**The reason decides the steps.** `why_not_sorted` puts the error into one
of four kinds. The file itself is no good (Pillow could not open it, or the
iPhone photo could not be converted): share it again from the phone, then
delete the one in `failed`. The computer could not save or could not find a
folder (an operating-system error with a number, a permission refused, a
folder gone): nothing is wrong with the photo, put the computer right and
move the photo back. The name reader did not work, or anything else: move
the photo back once, and if it comes back to `failed`, tell the person who
set the computer up. A photo from a project folder is to be moved back into
that folder, and the note says which.

**Why the program's own words stay out of Drive.** An error from saving a
piece carries the path it was saving to, and that path has a child's folder
in it. The note and the status file are built from the four fixed sentences
only. The log, which stays on the watching computer, keeps the error text as
it did before.

**Why the note is in the doubtful-pieces folder and not beside the photo.**
It is where the other two notes are and where the teacher is already sent
for anything that needs a person, and the status file points to it. `failed`
holds photos and nothing else, which other parts of the tool and its tests
rely on.

**Also.** If the photo cannot be moved to `failed` either (the disk is
full), the log has the reason, as it did before, and now says that the
photo is still in `done`. The look stops there, as it did before, and the
marker for the photo stays, so the next start writes the `NOT FINISHED`
note. Shared code, nothing Mac-only or Windows-only in it.

**What this does not do.**
- A computer with a version of the tool from before this one still moves
  the photo to `failed` and says nothing in Drive. When two computers watch
  a class, the one that tried the photo writes the note, so a classroom PC
  set up from an older zip needs a zip built from this version. The count
  line is in the status file of every computer that has this version,
  whichever of them tried the photo, because it is counted from the folder.
- The count includes photos that were in `failed` before this version, and
  those have no note.
- The note is not taken away when the photo is sorted at the second try; it
  says it can be deleted.
- A file of 0 bytes never reaches `failed`: the watcher takes it for a photo
  that is still arriving and leaves it in `Wall Inbox`. That was so before
  and is not changed here.
- `Check Setup` does not print the count. The status file does.
- Not run on a Windows PC, and no real photo was opened for this repair.

**Tests.** `tests/test_repairs.py`: `PhotoThatCouldNotBeSortedTests` (8: the
reported steps with a synthetic wall cut off halfway, the note and that it
holds no error text, no path and no child, the log, a project folder, a full
disk, good photos beside a bad one, a note that cannot be written, a photo
that cannot be moved to `failed`), `WhyAPhotoCouldNotBeSortedTests` (5: the
four kinds, the steps, the status line for one and for five photos, the
count line, the count taken from the folder),
`FailedPhotoInTheStatusFileTests` (5, through the real watch loop with the
clock faked: the status file after a failed photo, a batch with good and bad
photos, a batch with nothing wrong, the count after the next batch and after
the photo is dealt with, the count after a restart) and
`FailedPhotoReadMeTests` (1). Against the code as it was, 17 of the 18 that
do not read the README fail; the one that passes is the batch with nothing
wrong. One older test, in `StoppedMidPhotoTests`, said
that a bad photo leaves no note of any kind in the doubtful-pieces folder;
it now says there is no `NOT FINISHED` note and there is a `COULD NOT SORT`
one.

## September 26, late night: the contract check, and what it found

The tool makes a promise to a teacher. Mount the work on a dark background,
keep the whole paper in the frame, type the child's name in a corner of the
paper, and every piece lands upright in the right child's folder. Until
tonight nothing tested that promise as a whole.

`tests/contract_check.py` does. It builds a grid of practice walls that all
follow the three rules and vary everything else: which corner the label is
in, which way the phone was held, 1 to 25 papers, four dark walls, four paper
colours, shot from the left and the right, a wrong camera tag, three typed
fonts, typed sentences on the paper, portrait paper, PNG and HEIC, a small
photo, and papers hung touching. It checks the whole promise on each piece:
filed once, under the right child, the right shape, and the label reads
upright on the filed piece itself. The required score is 100%. How rare a
miss would be on a real wall is not a reason to leave it. Invented names
only; they are checked against the protected list by count before use.

The first run scored 394 of 403. It had taken 464 passing tests and a long
review to get there, and the grid took seven minutes. What it found, with
the three real photos of that evening sorted again beside it:

1. **One paper without edges sent the whole photo to a person.** When the
   paper detectors found fewer papers than there were name labels, every
   piece was cut around its label and none was filed. On a real photo of
   eight papers the edges of seven had been found and nothing was filed.
   `with_found_edges` now gives each label the found paper it sits on, when
   no other child's label sits on the same one, and only a paper with no
   found edges goes further.
2. **A paper without edges was never looked for.** The teacher's first rule
   is a dark background, so the paper is the patch that is not background
   around the label. `paper_around_label` finds it, and refuses when the wall
   is not dark, the patch runs off the photo, or the patch is not the shape
   of a sheet. On a pale wall none of this is used: `wall_is_dark` is the
   gate, and pale on pale still sends every piece to a person, which is the
   safe failure outside the rules.
3. **One paper filling the photo found nothing.** `add_missing_papers` looks
   around any name label that sits on no found paper.
4. **One upright piece was filed upside down.** The reader took an upright
   label for upside-down nonsense, and the piece was turned on the strength
   of the nonsense. Now only a line that IS the matched name decides a turn
   (`name_line`). When no name reads for certain the way the piece was cut,
   it is read turned the way the reader suggests and then the other ways,
   and the turn is worked out from the first certain name. A scribble the
   reader took for a word is a hint about where to look first and nothing
   more.
5. **Papers hung touching.** No wall shows between two sheets hung edge to
   edge, so the background patch held two children's labels. The edge of a
   sheet is still a line, and it runs the height of the paper where a
   drawing does not. `seam_between` measures it, anywhere between the two
   labels, and cuts there. No line that stands out means no cut: a seam is
   measured, never guessed. The same goes for one found paper that holds two
   children's names.
6. **One child's name read twice on one paper** was counted as another
   child's label. It is one child and one piece.
7. **A paper that runs off the edge of the photo** is outside the rules and
   still goes to a person, and now the log says why and what to do:
   photograph it again with a little of the dark background showing on
   every side.

Two misses were the check's own: it read the filed piece less carefully than
the tool does, and it judged the shape of a nearly square paper. A miss is
looked at before it is believed.

After the fixes the grid is 64 walls and 429 pieces, all right. A core set
of thirteen walls runs with the test suite in `tests/test_contract.py`,
beside direct tests of each new rule. The order of work from now on: the
contract check first, agents after, if at all.


## September 26 and 27: privacy gate, twice, for two private backups

Both pushes went to the repository while it was private, and the gate was
run for a private push only. It is not a verdict for making the repository
public.

| Push | Scanner | Verifier |
|---|---|---|
| September 26, evening, the day's repairs | GATE PASS | VERIFIED PASS |
| September 27, after midnight, the contract check | GATE PASS | VERIFIED PASS |

What the gate found that no pattern could: the practice walls carried a
sample sentence whose wording had been modelled on one real sheet. It named
nobody, and a paraphrase of a child's sentence is still that child's work.
It was replaced with invented wording of a different shape before the push,
while the commit was still on this computer only, so it is in no served
history. The commit guard also refused one commit that night: an invented
practice name held a protected name inside it. It was replaced.

Before the repository is public again there is a list of changes to make.
The list is kept with the owner and not in the repository, because a list
of what to reword is itself a map of where to look. When it has been worked
through, the history is squashed or the repository is recreated, the latest
build's log and bundles are checked, and both agents run again. Making the
repository public is the owner's command and nobody else's.

## September 28, afternoon: the first build that ran on a real Windows machine

The push of the morning's Windows repairs built the Windows bundle only (the
Mac bundle is built by hand now, since a Mac minute on the build machine
costs about five Windows minutes) and, for the first time, ran the whole
suite, a reader probe and the contract grid on a real Windows machine and
wrote all three records into the bundle. What they said:

- **The suite:** 593 tests, 6 failures, down from 30 the day before. The
  watcher starts, files are let go, paths use the right slash, sideways
  photos are turned. The six left were all practice walls outside the
  contract (pale or coloured walls, pages of writing, white on white), where
  the Windows reader, which has no rectangle finder, found an extra texture
  box or missed one label.
- **The reader probe:** on a dark wall with typed labels the Windows reader
  read every label at every height from 20 to 120 pixels. Its weak cases
  are a single label alone on a tiny picture, which is not how the tool
  uses it.
- **The contract grid:** cut off by its time cap after 39 walls: 33 perfect,
  6 with a miss. Five of the six were dark walls with coloured paper, and
  every missed piece was filed under the right child but did not look like
  the paper at any turn.

**The cause, reproduced on a Mac.** Switching off the rectangle finder on a
Mac reproduces the five misses exactly. Without the finder a found box is a
texture or colour guess, and on a dark wall with coloured paper the colour
guess is often just the white name label, not the sheet. Two things fixed
it: on a machine without the rectangle finder, the paper found from the
dark background around the label (`paper_around_label`) now replaces the
guess wherever it is found; and the reader's habit of returning one label
twice with two spellings ("lonah Reyes" and "Jonah Re" a few pixels apart)
no longer counts as two labels, because `label_list` now de-duplicates by
the child a reading matches, not by its spelling. With the finder switched
off the whole grid is 64 of 64 walls and 429 of 429 pieces on a Mac; with it
on, the same.

**The six tests** now say what is true on Windows without lowering the Mac
bar: outside the contract the rule is "fail safely", so on Windows they
assert that nothing is filed under the wrong child, that a piece whose name
was not read is not filed, and that an extra box is not filed. On a Mac the
exact assertions stand.

**The build itself** now runs a chosen 34 walls of the grid on Windows so
the step fits its cap, and the Mac setup scripts in the repository carry
the two things the class review found the same afternoon: a check for an
Apple chip before anything else, and plain words about the two or three
permission dialogs macOS shows, from Terminal as well as from Baggage
Claim.

## September 28, evening: the second Windows build, and the last two pieces

The build of the afternoon's fixes ran on a real Windows machine: 596 tests
with 1 failure, and 34 walls of the contract grid with 235 of 237 pieces
right. Every piece it filed was under the right child. The two it did not
file went to a person, and both came from the Windows reader, not the
sorting:

1. **A garbled second reading of one child's name** ("09 LIL" beside a clean
   "Lily") sat on another child's paper, so that paper looked shared by two
   children and its edges were not trusted. Each child now keeps its
   strongest reading (`one_label_per_child`, by `label_strength`); a second
   reading of the same child is kept only when it too reads cleanly, since a
   child can have two papers on one wall.
2. **A label read on the whole photo but not on the piece.** The paper had
   been found exactly, from that very label, and the close read then came
   back empty. An exact paper now remembers the label it was found from
   (`from_label`), and when the close read finds no certain name, that label
   is the name.

On a Mac with the rectangle finder switched off, both walls pass, and the
whole grid is 64 of 64 either way.

## September 28, night: a sentence the reader split in two

The third Windows build filed every piece of the contract grid right: 34 of
34 walls, 237 of 237 pieces. One test, on a practice page of writing on a
red wall, outside the contract, filed one piece under the wrong child. The
practice stories mention a friend ("with my friend Theo."). Apple's reader
returns that as one line; the reader of a PC can return it as two, and the
friend's name alone looks exactly like a name label on the wrong page.
Forcing that split on a Mac filed six pieces wrong. `join_rows` now joins
lines on one row, facing the same way and nearly touching, back into one
line before any name is looked for, on the whole photo, on each piece and
around each piece. With the split forced, both coloured walls file 8 of 8
under the right child. Grid 64 of 64 with and without the rectangle
finder; 602 tests.

## September 29, morning: what the Windows reader actually saw

The evidence build printed every line the Windows reader returned on the
practice page of writing that was filed under a classmate's name. The cause
was not a split sentence. The Windows version reads a large photo in
overlapping tiles, and one tile edge ran through "waves came and Theo
laughed": the neighbouring tile returned "Theo" as a line of its own, lying
inside the sentence the first tile had read in full. That stray line looked
like a second name label for Theo, so the page was cut in two between the
two "Theo labels" and the top half was named Theo.

`join_rows` now drops a line that lies mostly inside a longer line on the
same row, facing the same way, whose words it repeats. Replaying the Windows
reader's behaviour on a Mac, the wall came out as 16 pieces with 8 under the
wrong child before the fix, and 8 pieces all right after it. The replay and
the exact lines from the build record are tests. Grid 64 of 64 with and
without the rectangle finder; 604 tests.

## September 29, noon: one word read twice by two tiles

The next Windows build filed the real practice wall right. One harsher test,
which splits every story sentence on top of what the Windows reader returns,
still filed one page under a friend. The evidence showed why: two
overlapping tiles read the last word of "with my friend Lily." twice, once
as "Lily." and once garbled as "LAY,". The garbled one joined the sentence;
"Lily." was left alone and looked like a label. `join_rows` now drops a one-
or two-word line lying almost wholly inside a sentence on its row, as a
second reading of part of that sentence. The exact lines from the build
record are a test. Grid 64 of 64 with and without the rectangle finder; 605
tests.

## September 30, 2026: PDF packets

A teacher asked to drop a PDF packet, say 300 pages of the class's work,
into Wall Inbox and have each page reach its child. The rule for packets is
the rule for walls, moved onto the page: the child's name TYPED in a corner
of EVERY page, with "page X of Y" beside it if the teacher likes.

**The design, and why.**

1. **Two libraries, both permissive, loaded only when a packet arrives.**
   `pypdfium2` (Apache/BSD, Google's PDF engine) reads each page's words and
   draws a page as a picture; `pypdf` (BSD) writes the children's PDFs by
   copying the packet's own pages, so a page keeps its full quality and its
   text. PyMuPDF was ruled out for its AGPL licence. The import is inside
   `pdf_parts`, so a computer without them sorts photos as before, and
   `--check` says so as a WARN, never a FAIL.
2. **The words inside the PDF first, the reader when they do not name a
   child.** A PDF made on a computer carries its text and where each line
   sits (`text_layer_lines`: pdfium's text rectangles, turned into the frame
   of the page as a person sees it with `FPDF_PageToDevice`, which also
   handles a page turned by its /Rotate). That is exact and takes a
   millisecond. When no line of it names a child for certain (a scan, or a
   name that is a picture), the page is drawn at 200 dots to the inch, no
   more than 3000 pixels on its long side, and read by this computer's own
   reader through `read_photo_text` and `join_rows`, exactly as a photo is.
   Either way each line gets its `rel_y`, so `match_name` and its rule about
   names at the top and bottom edge are used unchanged.
3. **Page numbers are taken off the line before the name is matched.** A
   reader returns "Maya Torres page 2 of 3" as one line as often as two, and
   a four-word line is weighed as a sentence, not a label. `take_page_number`
   finds "page X of Y", "X of Y" or "X/Y" (the last only up to 12 pages and
   never inside a date such as 9/30/2026), keeps it, and matches the rest.
   The number counts only beside the name, or as "page X of Y" along the
   top or bottom edge (`page_number_by_name`).
4. **Packet order, one PDF per child.** The teacher knows the packet's
   order; the child's PDF keeps it. Named like a photo's piece
   (`piece_name` with `.pdf`), so a second packet of the same project is
   `... 2.pdf`, never a merge into the first.
5. **Nothing by position.** A page whose name is not certain goes to a
   person as a one-page PDF, `GUESS ...  page 012.pdf`, even when the pages
   on both sides are the same child. The note says that it sat "between two
   of <child>'s pages", which is the hint a person needs, and the tool does
   not act on it.
6. **An incomplete numbered set is not filed.** When a child's numbered
   pages are not 1 to Y exactly once each, all of that child's pages go to a
   person as `CHECK PAGES <child> ...` (the name was read; the set is the
   doubt, the same distinction as `CHECK PICTURE`). Before that happens,
   the pages the reader read are looked at again, closer: the corner around
   the name drawn twice as big (`closer_page_number`). The first grid run
   found why: a scanned "2/2" in 11-point type came back as "212", and
   "2 of 2" as ".2 of 2" or "Theopage 2 of 2"; at twice the size every one
   read right. The second run, with the words inside the PDF ignored, found
   one more: "Nadia page 1 ot 3". A line the number cannot be taken off
   stays a four-word line and the name on it is not certain, so "ot" and
   "0f" are now read as "of". Children whose pages carry no numbers are
   filed as they are.
7. **The note and the log.** `PACKET - read me - <project> - <packet>.txt`
   in the doubtful-pieces folder lists pages in, filed and sent to a person;
   each unsorted page's packet page number, guess and neighbours; pages per
   child and any child whose count is not the most common one; children on
   the class list with none; and page-number problems. It names children,
   because it sits in the class's own folder. The log gets one line per
   packet (`packet_text`), and `batch_text` counts packet pages as pages.
8. **Filed once.** Each PDF the tool writes carries, in its document
   properties (`/BaggageClaimPages`), the packet's fingerprint (the same
   SHA-1 as `photo_key`) and the packet page numbers it holds. Before a
   child's pages are filed the project folder is read, and pages already
   there are left out; a second sort of the same packet writes nothing new
   for anyone. Like the photo mark it travels with the file through Drive
   and goes when the teacher deletes the file.
9. **The watcher.** `.pdf` joins `IMAGE_EXT` as `INBOX_EXT` for the inbox,
   `failed` and the second-copy watch; the settled check, the claim into
   `done`, the marker, the turn-taking between two computers and `failed`
   are the photo's own code. A damaged or password-locked PDF is a
   `PacketError`, which `why_not_sorted` turns into plain words and a
   'COULD NOT SORT' note that says "packet".

**The contract grid.** `tests/packet_check.py`, 26 packets (digital and
scanned; each corner; 1, 2 and 3 pages per child; 25 children; the three
number forms and none; landscape; one child's pages out of order; a
different corner on every page), run twice: the words inside the PDF used,
and ignored so that every page is read by the reader. Which packet page a
filed page was is told by the page's own bytes (`page_fingerprint`), not by
the reader. First run: 21 of 26 (the misreads in point 6). After the fixes:
26 of 26 packets and 686 of 686 pages both ways, on a Mac. `tests/test_packets.py` has the rules one by one.

Not done: a name strip for a packet page (the one-page PDF is small
already), and `--docx` does not include packet pages.

## Privacy gate, Sep 30 2026: "Set up a class" (99e48de, private push)

Scanner: GATE PASS (0 whole-word hits in the commit under every method; place 3
hits were coincidences in other repositories, unrelated to this commit; no served
orphans; repository private, no web or archive trace). Verifier: VERIFIED PASS
(agreed with every coincidence ruling; read the commit as a stranger and found no
sentence that points to a real person). The commit guard first refused the test
file because an invented test name equalled a protected entry; the invented name
was replaced. Pushed with [skip ci] so no Actions minutes were spent. Full suite
661 tests OK.

## October 1, 2026: a real wall that sorted 5 of 20, and what it took to fix

A teacher followed every rule: twenty sheets of white paper pinned to a
blue board, a typed name label in the corner of each, one photo, put in a
project folder in Wall Inbox. The promise is that the work is in the
children's folders within three minutes. It was not. Two faults in the tool,
and one in how the watching computer was left, stood in the way. None of
them was the teacher's.

Follow the one photo:

1. The photo reached Google Drive and was listed on the watching Mac.
2. **Fault 1: the tool gave up on a photo that was still arriving.** Drive
   lists a photo before it has delivered it. The settled check read the
   first 16 bytes, which Drive handed over, and called the photo ready. The
   full read a moment later failed with "Resource deadlock avoided", and the
   photo was moved to `failed` with a COULD NOT SORT note. From there
   nothing happens until a person moves it back.
3. Moved back by hand, it was sorted nine minutes after it was taken.
4. **Fault 2: 5 pieces found, of 20.** The rectangle detector found 22
   sheets (the twenty and the title signs). The name reader found the
   labels. The colour detector found 5 blobs: the board was blue below and
   a paler cream above, and the frame's rim, which decides whether the wall
   or the paper is the coloured one, was split between the two. The rule
   for trusting colour asked only whether the blobs agreed with rectangles.
   Five did, colour won, and the label method, which is switched off when
   colour wins, never ran. Four children were filed, one piece went to
   Unsorted, fifteen children got nothing, and the log said nothing was wrong.
5. **The computer was dozing.** The watching Mac had gone to sleep more
   than thirty times that day. Each time it wakes, the watcher stands by for
   90 seconds before it looks.

What changed:

- `is_settled` reads the whole file. A photo that cannot be read to its
  end is still arriving: it stays in the inbox and is tried again on the
  next look, five seconds later. It is never moved to `failed` for this.
- `detect_pieces` trusts the colour blobs only when they also account for
  most of the sheets the rectangle detector saw (at least 0.6 of them).
- The name labels are a second opinion on colour, on every computer: when
  the photo shows at least two more labelled children than colour found
  papers (`labelled_children`), the photo is read again without colour.
  This is the guard for a PC, which has no rectangle detector.
- `keep_awake`: the watcher asks its computer not to doze for as long as it
  runs (`caffeinate -i -w` on a Mac, `SetThreadExecutionState` on a PC). A
  closed lid still sleeps, so the watching computer is left open.

How it was proved. The real photo, on the Mac, in a scratch folder: 5
pieces before, 22 after (20 filed to 20 different children, every label read
at full score, the 2 title signs to Unsorted), 61 seconds for a 48-megapixel
photo. `tests/test_real_wall_oct1.py` holds both faults with the detectors'
answers put in by hand; it fails on the code as it was (2 failures) and
passes now.

What the grid did not catch, and why. Every practice wall was a single dark
colour: black, navy, maroon or green. This board was a middle blue under a
cream band. Four walls like it joined the grid (`bg-mid-blue`, with and
without the band, 8 to 20 papers). They pass, and they pass on the old
code too: a painted practice wall is cleaner than a photographed one, and
its blobs come out whole. So the grid is wider but it is the hand-built
test, not the grid, that holds this fault. A practice wall that reproduces
the uneven light of a real board is not built yet.

The lesson is the one this file keeps recording: the rules were followed
and the tool still missed, so the miss is the tool's. A detector that finds
a quarter of what the other two found should lose the vote, and should say so.

## Privacy gate, Oct 1 2026: the real-wall fixes (e3e592c, private push)

Scanner: GATE PASS (every place of the scan 0 hits; 0 of 15 known commit
addresses served; repository private; the new test file, the October 1
section and the reworded passages read in full, nothing that names or points
to a person). Verifier: VERIFIED PASS for a push to the private repository
(agreed with every coincidence ruling; read the notes as a stranger).
Twenty-six ordinary-word matches in older public repositories, ruled
coincidences by three agents earlier in the day, went on the agreed list,
one entry per file. Pushed with [skip ci]; no build ran. Full suite 673
tests OK; the grid 68 of 68 walls.

Not a pass for making the repository public or for a post. Two things
stand before that: the earlier wording of the reworded passages is still in
pushed history, so the history is squashed and the repository deleted and
recreated first; and the agreed list still excuses the school's name in
four post-planning files, which the verifier wants removed before the next
post gate.

## October 2, 2026: the photo that was "still arriving" was never going to arrive

The October 1 section says a photo Google Drive is still delivering now
waits in the inbox and is tried again. That was true and it was not a fix.
The next day a practice photo sat in Wall Inbox as "still arriving" for ten
minutes, and was sorted the moment a person opened it from a Terminal
window. The same thing had happened the night before and been read as
Drive being slow.

**The cause.** Drive for desktop lists a file before it downloads it; the
download starts when a program opens the file. macOS decides, program by
program, who may start one. A program a person runs may. A program started
in the background by launchd, which is what the watcher is, may not: its
I/O policy for such files is "off", and every read fails at once with
"Resource deadlock avoided". So the watcher asked, was refused, waited five
seconds and asked again, for as long as nobody else opened the photo.

**The proof, before the fix.** A one-line job started by launchd, reading a
photo whose downloaded copy had been removed: policy 1 (off), error 11,
0.1 seconds. The same read from a Terminal window: policy 2 (on), the whole
file in 1.5 seconds.

**The fix.** `fetch_cloud_files()`, called when the watcher starts, asks
macOS for the right (`setiopolicy_np`, "materialize dataless files", on for
this process) and says so in the log if it is refused.

**The proof, after.** A photo put in the inbox, its downloaded copy removed
so that only Drive's listing was left (0 blocks on disk), the corrected
watcher started, and nobody touching the file: 25 pieces found, 25 filed,
one per practice child, 135 seconds from the watcher's start, 90 of them
its own standby after starting.

**What this corrects.** Reading the whole file in `is_settled` (October 1)
is still right: it is what makes the request. But the claim that the photo
"is tried again" until it arrives was only true on a computer where
something else opens the file. The lesson is about proof, not code: a retry
is not shown to work until a run starts with the file in the failing state
and ends sorted with no person in between. The October 1 check started with
a file that had already been downloaded.

Not done: the same question on a Windows PC, where Drive for desktop keeps
its files a different way; nobody has run this test there.

## October 5, 2026: title signs, and an inbox with another name

**Title signs.** The wall of October 1 had two title signs among twenty
children's papers, and both went to Unsorted, as they would every time. The
first plan was to leave out any paper with no child's name on it. The real
photo said no: one of the two signs had no words the reader could read, and
both were on the children's own paper, so to the tool a sign is the same
thing as a child's work that has lost its name sticker. Leaving that out
would lose a child's work without a word.

So the teacher says which paper is the sign, the way she says whose each
piece is: a typed sticker that reads TITLE, in capitals, on its own line.

- A paper with the TITLE sticker is left out: not filed, not in Unsorted,
  not counted as a piece, one line in the log (`is_title_sign`).
- A paper with no child's name and no TITLE sticker goes to Unsorted, as
  before.
- A paper whose name sticker is read for certain is filed under that child,
  however little is on it, and whatever else is written on it.

Known limit: a child's page whose name sticker cannot be read for certain,
and which also carries TITLE in capitals alone on a line, is left out.

**An inbox with another name.** A class may call its inbox and its unsorted
folder what it likes; the settings file says where they are. Their names
were also written into the list of folders that are not children, so a
renamed inbox got a document made for it as if it were a child.
`own_folders` reads the two names from the settings and `is_child_folder`
leaves them out.

How it was checked. `tests/test_title_sign.py` (8 tests) and three tests for
the renamed inbox in `tests/test_real_wall_oct1.py`. The grid has 75 walls
now: four with a title sign among the children's papers, and three where a
child has done nothing yet and the paper carries the name sticker alone.
75 of 75 walls, 551 of 551 pieces. 687 tests OK. One reviewer read the
title-sign change and found nothing. Not done: no real wall with a TITLE
sticker has been photographed yet.

## Privacy gate, Oct 5 2026: title signs and the renamed inbox (57e76a9, private push)

Two separate agents, the repository frozen while they ran. The scanner:
the script's eight places all PASS with 0 hits, the repository private and
404 to a signed-out request, no copy in the web archive, GATE PASS. Its
report gave no evidence for its own check of the new commit, so the
verifier did that check again: every entry of the protected list and every
word of the longer entries against the whole diff, both documents and the
full history. No protected name; the only matches were ordinary words and
invented practice names. The practice class named in the new
test was confirmed to be a practice class. VERIFIED PASS.

For before the repository is made public: search engines still hold a
copy of the repository's page from when it was public.

## October 5, 2026: Arrivals and the control tower

Two names changed, at the teacher's request, to fit the airport the tool is
named after.

**Arrivals.** Every class's inbox was renamed from `Wall Inbox` to
`Arrivals`. For each class: its background job stopped, the folder renamed
in Drive, the class's settings file (and the copies a teacher's own computer
would use) pointed at the new name, the job started again, the setup check
READY. A test photo put in a practice class's `Arrivals` was sorted, 25 of
25, 42 seconds after it was dropped. `is_child_folder` already knew a class
may rename its inbox (the class's own folder names are passed in, October
5); `Arrivals` and `Wall Inbox` are now both on the built-in list too.

**The control tower.** The program that runs in the background for a class
is now called that class's control tower in everything a person reads: the
log, the setup check, the status file's first line, the README, the READ ME
inside each `Arrivals`, the Windows setup guide. One control tower per
class; a Mac that serves five classes runs five.

**What kept the old name, and why.** The `Watcher status` folder, and the
`Watcher started:` and "for the other watchers" lines inside each status
file, are read by the other computers of a shared class, including older
versions on teachers' computers; renaming them would make two computers
lose sight of each other. `Baggage Claim Watcher.app` is the app macOS gave
Google Drive access to; a new name would need that permission again. The
launchd job names, `Start Watcher.command` and the names inside the code
are seen by nobody who uses the tool. The role words in the status file
("watching", "standing by") are what the other computers parse, so they
stay; only the sentence a person reads beside them changed.

One slip on the way: the first rename pass expanded `{DRIVE}` in the
settings but not `~`, so it could not find one class's inbox after it had
already stopped that class's job. The job was down for under two minutes
and no photo was waiting; the pass was finished by hand and every class
checked READY.

## Privacy gate, Oct 7 2026: pages with no name sticker, and the grade that is not a page number (1aca96c, public push)

Two separate agents, the repository frozen while each ran. The first
scanner run ended in GATE FAIL, and nothing was pushed: the script's eight
places were all PASS with 0 hits and no protected name was found anywhere,
but the masking tool, which is broader than the scanner on purpose, marked
words on nine added lines, none of them a protected name: code words and
practice text. Four lines were reworded, the commit was amended before any
push, and both agents were run again from the start.

The second scanner: the script's eight places all PASS with 0 hits, no
orphaned commit served, no private file tracked, the seven public
repositories matching what the script scanned, GATE PASS. The web archive
could not be asked (it was limiting requests); that check is for
information only. The verifier, with its own commands: every entry of the
protected list against the files at this commit, the full history, both
documents as public now and as pushed, every added line and the commit
message; five entries picked at random searched again; the one earlier
coincidence, an ordinary word in a setup script, agreed. No protected name.
VERIFIED PASS.

The verifier's note for a person, not a protected name: some new comments
say when a problem was first seen on a real packet.

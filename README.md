# Baggage Claim

*Every piece of work returned to its owner.*

Photograph the wall of student work. Get one folder per child. Like the
carousel at the airport: every bag comes back to the person whose name is on it.

A teacher pins twenty pieces of work on the wall with each child's name
written on it. This tool takes a phone photo of that wall (one photo can hold
the whole wall), finds every paper, straightens it, reads the
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
2. Drop wall photos into `inbox/`. Hold the phone any way you like: the
   typed name label decides which way is up, for the photo and for each
   paper, so a paper hung sideways still comes out upright in the child's
   folder. Print the name and put it in a corner of the paper for the best
   result.

   How many papers in one photo: as many as the wall holds. One photo of
   twenty-four papers files twenty-four pieces. Two photos of twelve each
   give sharper pieces, because each paper gets a bigger share of the
   photo. Three things matter more than the count:

   - Every paper is whole in its photo, with a little of the dark
     background showing on every side of it.
   - No paper is in two photos. A paper photographed twice gives that
     child the same piece twice.
   - The photo is taken and shared at full size. A photo saved at a
     quarter of the size gives pieces a quarter of the size, however few
     papers are in it.
3. Double-click `Baggage Claim.command`. It asks what the work is (for example
   `Self-Portrait`) and the grade (for example `Kindergarten`). Defaults, and
   a Google Drive folder for the per-child folders, live in
   `settings.local.json` (copy `settings.example.json`; ignored by git).

Every child on the roster gets a folder. Each filed piece lands at

```
sorted/Jordan Lum/Self-Portrait/Self-Portrait Kindergarten.jpg
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
| `--priority 90` | when two computers watch one class, the lowest number sorts and the other stands by (default 50) |
| `--shared` | another computer watches this class too; until it has reported in, each new photo is left for it for 10 minutes |
| `--grid 2x4` | skip detection and split the photo into an even grid |

## Set up a class

**The simple way:** drag a screenshot of the class list onto the **Make class
folders** icon on the Desktop (or copy the names and double-click the icon).
It shows the names it read, asks one thing, the class folder name, and makes
the folders and the labels page. Build the icon once with
`osacompile -o "$HOME/Desktop/Make class folders.app" "mac/Make class folders.applescript"`.

The longer way, with more choices:

Double-click `Set up a class.command` (Mac). It asks where the class list is:

- **A screenshot** of the list, read by this Mac's own text reader, the same
  one that reads name labels.
- **What I copied:** select the names in a Google Doc or Sheet and copy them.
  (A Google Doc cannot be read from the computer, only from the browser.)
- **A Word, CSV or text file.**

Numbering, bullets and headings like "Name" are taken off, and the list opens
in TextEdit for the person at the Mac to check: one child per line, fix a
misread name, delete any line that is not a child. Then it asks for the class
folder name, grade and first project, and makes the class folder in Google
Drive with one folder per child, the Arrivals, the doubtful-pieces folder,
and a page of name labels to cut out (first names, or the whole name when two
children share one), in the class folder and on the Desktop.

The names never leave the Mac and no A.I. reads them. The window shows counts
only ("21 of 21 child folders made, 21 name labels"), never a name, so the
result can be shared without sharing the class. The code is `class_setup.py`;
the tests (`tests/test_class_setup.py`) use invented names only.

## PDF packets

A PDF goes into `Arrivals` (at the top, or in a project folder) exactly
like a photo: for example 300 pages of the class's work, scanned or made on a
computer. The tool files every page into the right child's folder.

- **The rule:** the child's name is typed in a corner of the first page of
  that child's work (a name sticker). The pages scanned right after it need
  no name: a page with no name sticker goes to the child named on the page
  before it, until the next page with a name. Scan three pages with
  `Jordan Lum` on the first only, and all three are Jordan's. Keep each
  child's pages together; if they are mixed, put the name on every page.
- **Where that stops.** A page that has a sticker the tool cannot read for
  certain goes to a person, and so does every page with no sticker after
  it, up to the next name: it may be the next child's first page. Pages
  before the first name in the packet go to a person too. The note lists
  every page that was filed because of the page before it.
- **Optional:** `page 2 of 3` (or `2 of 3`, or `2/3`) right beside the name, on the same line or just under it; a number printed elsewhere on the page is not read as the page number. A class's own grade written with a slash is never a page number: `1/2` on the sheets of a class whose grade is set to `1-2` (likewise `3/4`, `5/6`) is the grade. Write `page 1 of 2` there. Then a
  child whose set is not whole, a page missing or a page there twice, is not
  filed at all: all of that child's pages go to a person, and the note says
  which page is missing or doubled. A page with no sticker takes the next
  number after the page before it, so `page 1 of 3` and two pages with no
  sticker are a whole set of three.
- **One PDF per child per packet**, holding that child's pages in the order
  they are in the packet, named like a photo's piece:
  `sorted/Jordan Lum/Reading Log/Reading Log Kindergarten.pdf`. The pages
  are copied from the packet, not redrawn, so nothing loses quality.
- **Nothing is filed under a guess.** A page whose name is not certain goes
  to the doubtful-pieces folder as a one-page PDF, `GUESS <best guess> -
  <project> <grade> - <packet> <code> page 012.pdf`. Pages held back because of a
  page number are called `CHECK PAGES <child> - ...`. The `<code>` is six
  letters and digits unique to the packet, so two packets with the same file
  name, such as a scanner's `Scan.pdf`, never overwrite each other.
- **The note:** after each packet, `PACKET - read me - <project> - <packet> <code>.txt`
  in the same folder says how many pages there were, how many were filed and
  how many went to a person; for each of those, its page in the packet, the
  best guess and where it sat ("between two of Jordan Lum's pages"); pages
  per child, and any child with more or fewer pages than most; children on
  the class list with no pages at all; and any page-number problem.
- A packet sorted again (moved back from `done`) gives nobody a second copy:
  each PDF the tool writes records, in its own properties, which pages of
  which packet it holds. A damaged PDF goes to `failed` with a note, like a
  photo that cannot be opened.

How a page is read: a PDF made on a computer carries its words inside it,
and when those name a child they are used as they are. A scanned page is
drawn as a picture on this computer and read by the same on-device reader as
a photo. Nothing is sent anywhere. The PDF parts are two libraries,
`pypdfium2` and `pypdf` (`pip install pypdfium2 pypdf`; the bundles carry
them); `--check` says whether this computer has them, and a computer without
them still sorts photos.

## First real wall

Twenty-four self-portraits on construction paper, two phone
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
folder called `Arrivals`. A Mac or Windows PC running the control tower sees it
arrive, sorts it, and the pieces appear in each child's Drive folder about ten
seconds later. Doubtful pieces go to a Drive folder the teacher can see and
fix. iPhone HEIC photos are converted on that machine, never online.

**The control tower.** The program that runs in the background for a class
is that class's control tower: it watches the class's `Arrivals` folder and
directs each piece to the right child's folder. There is one control tower
per class. A Mac that serves five classes runs five control towers, each with
its own settings, its own log and its own `Arrivals`; if one stops, the
others carry on. (Behind the scenes some names still say "watcher": the
`Watcher status` folder, `Start Watcher.command`, the app on the Mac. No
teacher needs them, and renaming them would break the link between
computers, so they stay.)

**The folder name.** Classes set up before October 5, 2026 called their
inbox `Wall Inbox`; all of them were renamed `Arrivals` that day. A class
may name its inbox anything, as long as its settings file names the same
folder: rename the folder and the settings together, then start the control
tower again.

On a Mac there are four files to double-click. In the one-click bundle a
teacher is given, all four sit side by side in the one folder. In the source
folder from GitHub they are inside the `mac` folder.

- `Setup.command` (from source: `mac/Setup.command`): sets the control tower up to
  start with the Mac and to be started again by itself if it ever stops,
  using launchd, the part of macOS that does exactly this for the system's
  own background programs. Nobody has to be logged in to a Terminal or
  remember to start anything. macOS asks once whether Baggage Claim may read
  the Drive folder; click Allow. It asks again after the program is updated,
  once.
- `Check Setup.command` (from source: `mac/Check Setup.command`): says
  whether the launchd job is loaded, whether a control tower process is really
  alive right now, when the log last changed, and what the last line said.
  On a Mac that watches more than one class it says the same for each
  class, and it names any class that has a settings file on the Mac and no
  control tower. If it prints PERMISSION NEEDED, macOS has not yet let the control tower read the
  Drive folder: click Allow in the dialog, or turn Google Drive on for
  Baggage Claim under System Settings > Privacy & Security > Files and
  Folders.
- `Start Watcher (visible).command` (from source: `mac/Start Watcher
  (visible).command`, or `Start Watcher.command` at the top of the source
  folder, which does the same): opens a Terminal window that shows the
  control tower working. When the background control tower is already running, the
  window follows its log and stops nothing. Only when no background control tower
  is running does the control tower run in the window itself. Only one control tower
  runs per class on a machine; a second one says so and closes.
- `Stop Watcher.command` (from source: `mac/Stop Watcher.command`, or the
  one at the top of the source folder, which does the same): stops the
  control tower and its launchd job, so it does not come back until Setup is run
  again. On a Mac that watches more than one class it stops all of them.
- The bundle also holds `Baggage Claim.app`. It is not for double-clicking:
  it is the small helper that launchd starts, so that macOS asks for
  permission to read the Drive folder. Double-clicked while the control tower is
  running, it finds the control tower already there and closes, and nothing
  appears on the screen. Double-clicked when no control tower is running, it
  starts one with no window, which nothing starts again if it stops; use
  `Setup.command` instead. There is no `Baggage Claim Watcher.app` any
  more; see Setup, below, if a folder still has one.
- On a Windows PC the same four are `Setup.bat`, `Check Setup.bat`,
  `Start Watcher (visible).bat` and `Stop Watcher.bat`. `Start Watcher
  (visible).bat` opens a window that shows the control tower working. When the
  background control tower is running, the window follows its log and stops
  nothing: close the window whenever you like and the control tower keeps going.
  Only when no background control tower is running does the control tower run in the
  window itself; the window says so, and closing it stops the watching
  until `Setup.bat` is double-clicked.
- `settings.local.json` (ignored by git) names the inbox, the class folder,
  the doubtful-pieces folder, the class list, the default project, and the
  grade. For a new project the teacher makes a folder inside `Arrivals`
  named for it and shares the photos there; the folder name becomes the
  project, so nobody edits settings for a new project. Letters, numbers,
  spaces and dashes are the names that work on every computer. A phone or a
  Mac will also accept a name such as `Who Am I?` or `Unit 2: Leaves`, but a
  Windows PC cannot hold a file or folder with `? : " / \ | < > *` in its
  name, or a full stop at the end. The tool leaves those characters out:
  photos in a folder called `Who Am I?` are filed as `Who Am I`, in each
  child's folder, in every file name, in the doubtful-pieces folder and in
  `done`, and the log says so once. The same goes for the project in
  `settings.local.json` and for `--project`.

The watching machine has to be awake with Google Drive running. Any Mac or
Windows PC in the building will do. A machine watches the class named in
its `settings.local.json`. A Mac can watch more classes as well, each set
up once; see "One Mac, more than one class" below. A Windows PC watches one
class. A Chromebook cannot be the control tower, because the sorting runs on the
machine that holds the folders and a Chromebook does not run this kind of
program; a teacher with a Chromebook still uses the tool from their phone
and sees the results in Drive like anyone else.

### One Mac, more than one class

`Setup.command` starts one control tower, for the class in `settings.local.json`.
It does not cover any other class. Each other class the same Mac is to
watch is added once, by the person who set the Mac up, with that class's
settings file:

1. Open Terminal and go to the Baggage Claim folder, for example
   `cd ~/baggage-claim`.
2. Type this line, with the name of the class's settings file in it, and
   press Return (in the one-click bundle the file is `./autostart.sh`, with
   no `mac/` in front):

```
mac/autostart.sh install . "classes/Grade 1 - Room 4.json"
```

3. Double-click `Check Setup.command`. Under the first class it now says
   `This Mac also watches the class 'Grade 1 - Room 4'`, and whether that
   control tower is alive.

From then on that class has a launchd job of its own: its control tower starts
with the Mac and is started again if it stops, the same as the first one,
and it writes to a log of its own, `logs/Grade 1 - Room 4.log`.
`Check Setup.command` also names every class that has a settings file in
the `classes` folder and no control tower on this Mac, with the line to type, so a
class nobody is watching is not mistaken for one that is.
`Stop Watcher.command` stops every class's control tower and prints the line that
brings each one back; `Setup.command` brings back only the first. To stop
one class and leave the others, type the same line with `remove` in place
of `install`.

The tool will not add a control tower for a class this Mac already watches: two
settings files that name the same `Arrivals` are the same class, and two
control towers for one class file every piece twice.

Do not start a class's control tower with a Terminal line that ends in `&`.
Versions of the class tool from before September 26, 2026 printed such a
line. A control tower started that way ends when the Mac restarts or the person
logs out, nothing starts it again, and photos wait in `Arrivals` with
nobody told.

### A new child joins the class

Open the class list in the class folder (`Class list - one first name per
line.txt`), add the child's name on a line of its own, and save. That is
all. Nobody restarts anything: the control tower reads the class list again
whenever the file has changed, a few seconds after Google Drive has brought
the change to the watching computer. The child gets a folder, and their work
is filed from the next photo. The log says it once: `class list changed: 25
children (there were 24)`. Taking a name off the list works the same way;
the child's folder and the work in it stay where they are. If the list is
empty or cannot be read for a moment, because it is still being saved, the
control tower keeps using the list it had and says so in the log. Wait for that
log line, or about a minute, before photographing the new child's work.

When two computers watch the same class, both need this version. A computer
that still has a version of the tool from before the evening of September
26, 2026 reads the class list only when it starts, so it does not know the
new child. If that computer is the one that sorts the photo, the new child's
work goes to `Unsorted - needs a person`, or to a classmate whose name is
spelled almost the same. Until it has the new version, restart that computer
after adding a child to the class list, and photograph the new child's work
after it has started again. A control tower that was already running when this
version was put on the computer is the same: it has to be started once more
before it reads the class list again by itself.

### The class list can be saved from any program

The class list is a plain text file with one name on each line. Type it in
Notepad or TextEdit, save it from Word as `Plain Text`, or download it from
Google Docs as `Plain text (.txt)`: all of them work, and a name with an
accent, such as Zoë or José, is fine. A Mac and a Windows PC read the same
file the same way, so two computers that watch one class make the same
folders. A line that begins with `#` is a note to yourself and is skipped.

If the tool cannot make out a name, it does not guess. The log names the
line, for example `class list could not be read (line 7 has a letter this
program cannot make out, most likely one with an accent ...)`, and `Check
Setup` says the same. A control tower that is already running carries on with
the list it had. A control tower that is starting waits, sorts nothing, and
starts by itself within a minute of the list being saved again. To put it
right, open the class list, choose Save As, pick `UTF-8` where it asks for
the encoding, and save. A Word document (`.docx`) is not a plain text file,
even with its name changed to end in `.txt`.

Versions of the tool from before the evening of September 26, 2026 could
make a second folder for the first child on a list that came from Google
Docs or Word, with a name that looks the same on the screen, and stopped
working on a list from Word that had an accent in it. If a class folder has
two folders that look like the same child, move the work into one of them
and delete the other; the tool now files into the one whose name is typed
the ordinary way.

### A child leaves the class

First take the child's name off the class list and save. Then move the
child's folder to wherever the school keeps such work, or delete it. A
folder you delete stays deleted. The control tower makes a folder only for a child
who is new on the class list, and it never deletes a child's folder or the
work in it.

Two things bring a deleted folder back, and both need the name to be on the
class list still. When the control tower starts again, for example after the
computer is restarted, it makes an empty folder for every name on the list.
And when a piece of work is read with that child's name on it, the piece is
filed into a folder made for it. So the name comes off the list first.

Versions of the tool from before the evening of September 26, 2026 made
every child's folder again every five seconds, so a deleted folder was back
almost at once. A computer that still does that needs this version.

### If the computer stops in the middle of a photo

Sorting a photo takes about ten seconds. If the computer is switched off,
loses power, or the control tower is stopped in those seconds, the photo is not
sorted a second time when the control tower comes back, so no child gets the same
piece twice. Some children may be missing their piece from that photo,
though, and the tool says so: a note called `NOT FINISHED - <project> -
<photo>.txt` appears in the doubtful-pieces folder (`Unsorted - needs a
person`), and the log has the same sentence. To finish the photo, move it
from `Arrivals/done` back into `Arrivals`. It is sorted again, and only
the missing pieces are filed: a child who already has the piece from that
photo keeps it and is not given a second copy. The log says so for each
child, for example `Maya Torres already has this piece from this photo`.

The same goes for a photo that is shared again. A photo that could not be
finished is put in `Arrivals/failed`; when it is moved back into `Arrivals`, the children who were filed the first time are left as they are.
A teacher who puts a name right on the class list and shares the same photo
again gets that one child's piece filed and nothing doubled for the others.
Only the very same photo counts: a new photo of the same wall is new work,
and its pieces are saved beside the first ones with a 2 at the end of the
name. A piece the teacher has deleted is filed again.

How the tool knows: every piece it saves has a short note inside the file,
which no picture viewer shows, saying which photo it was cut from and where
on the photo it was. There is no name in the note. It travels with the file
through Google Drive, so a second computer watching the class knows too. A
piece saved by a version of the tool from before the evening of September
26, 2026 has no note, so a photo first sorted by an older version and sorted
again by this one is still filed a second time; delete the copies with a 2
at the end of the name.

A piece is also saved whole or not at all. While it is being written its
name ends in `.part`, and it gets its real name when it is complete, so a
computer that stops in that moment never leaves half a picture in a child's
folder. A leftover `.part` file is not a picture; the tool takes it away the
next time it files into that folder, once it is an hour old.

### A photo in the folder called failed

Sometimes a photo cannot be sorted at all: the upload from the phone stopped
halfway and the file is damaged, or the watching computer could not save
(its disk is full, or Google Drive is signed out). The tool puts such a photo
in a folder called `failed` inside `Arrivals`, so that it does not hold up
the photos after it, and says why in three places.

- A note in the doubtful-pieces folder (`Unsorted - needs a person`), called
  `COULD NOT SORT - <project> - <photo>.txt`. It names the photo, says in
  plain words what happened, and gives the steps.
- The computer's file in `Watcher status`, which can be read from a phone.
  Its `Last batch` line says, for example, `1 photo could not be sorted and
  is in 'failed' inside Arrivals ('IMG_1234.jpg': the file could not be
  opened as a picture ...)`. A second line, `Photos that could not be sorted:
  1`, stays in the file for as long as the photo is in `failed`, also after
  the next batch and after the computer is restarted. It goes away by itself
  when the photo has been moved or deleted.
- The log on the watching computer, which also keeps the program's own words
  for the person who set the computer up.

What to do depends on what happened, and the note says which:

1. The file is damaged or is not a photo. Share the photo to `Arrivals`
   again from the phone it was taken with, or photograph the wall again.
   Then delete the one in `failed`.
2. The computer could not save. Nothing is wrong with the photo. When Google
   Drive is signed in and the disk has room, move the photo from `Arrivals/failed` back into `Arrivals` (or into the project folder it was
   shared to). A child who already has their piece from this photo keeps it
   and is not given a second copy.
3. The name reader did not work, or something else went wrong. Move the
   photo back the same way, once. If it comes back to `failed`, tell the
   person who set the computer up.

When two computers watch one class, the note and the status file name the
computer that tried the photo.

Versions of the tool from before the night of September 26, 2026 moved the
photo to `failed` and said nothing in Drive: no note, and a status file that
still showed the batch before. A computer that still does that needs this
version.

### Files called CHECK PICTURE

Two kinds of file land in the doubtful-pieces folder (`Unsorted - needs a
person`), and the first word of the name says which.

- `GUESS Maya Torres - ...`: the tool could not read the name for certain.
  Maya Torres is its best guess. Look at the name on the paper.
- `CHECK PICTURE Maya Torres - ...`: the name was read. What the tool could
  not find for certain is where the paper begins and ends, so it cut the
  piece out around the name label. The piece may be missing part of the
  paper, or show part of a neighbour's. Look at the picture.

Against a dark background a `CHECK PICTURE` file is one paper here and
there: a paper that runs off the edge of the photo, or two papers hung edge
to edge with no line showing between them. Every other paper in the photo
is filed as usual. On a pale wall with pale paper the `CHECK PICTURE` files
come together, one for every name label on the photo, because there the
tool trusts none of the edges it finds. The number of papers in the photo is
not the cause: one photo can hold the whole wall. The name reader did not
fail. A note in the same folder, `CHECK PICTURE - read me - <project> -
<photo>.txt`, says how many names were read and how many papers were found,
and what to do, which is one of two things:

1. Photograph those papers again against a dark background, the whole of
   each paper in the photo and a little of the background showing on every
   side, and share the new photo to `Arrivals`. Then delete the
   `CHECK PICTURE` files.
2. Or open each file. If the picture shows that child's whole paper and
   nothing of a neighbour's, move it into the child's folder. If it does
   not, delete it and photograph that paper again.

The tool never files such a piece by itself, however well the name was
read: a right name on a picture that shows half of a neighbour's paper is
still a wrong filing.

The reason is also in the places a person looks from somewhere else. The
computer's file in `Watcher status` says, for example, `Last batch: Sep 26
09:12 PM: 25 pieces, 0 filed, 25 to unsorted (on 25 of them the name was
read, but the tool could not find the edges of the papers for certain: pale
paper on a pale wall, or papers hung with no edge showing between them. A
person checks each picture. See the note in 'Unsorted - needs a person')`. The log has the same
line, and its line for each of those pieces says `check picture` where a
doubtful name has `unsure`. A last batch that says only `25 to unsorted`,
with nothing after it, means the names themselves could not be read.

Versions of the tool from before the night of September 26, 2026 called
these files `GUESS` as well, wrote no note, and gave no reason in the status
file. A computer that still does that needs this version. When two computers
watch one class, the files are named by whichever of them sorted the photo.

### A class folder whose name ends with a space

A Mac, a phone and Google Drive in a browser keep a folder's name exactly
as it was typed. So a class folder can be called `Grade 1 - Room 4 `,
with a space after the 3 that nobody can see, or `Room 3 Jr.`, with a full
stop at the end. A Windows PC cannot open a folder whose name ends with a
space or a full stop. A classroom PC that is to watch such a class may never
be given the folder by Google Drive, or may have it under a different name,
so its control tower waits for a folder it cannot find while a Mac watching the
same class works.

`Check Setup` says so on both. On a computer that can open the folder it
prints `WARN: the folder name 'Grade 1 - Room 4 ' ends with a space`
and still says READY, because that computer can do its job. On a computer
that cannot find the folder it prints FAIL with the same reason, and NOT
READY. The control tower's log has the same sentence.

The cure is one step. In Google Drive (drive.google.com), rename the folder
and take the space or the full stop off the end. Then double-click Setup
again on every computer that watches this class, or restart it, so that its
control tower starts again. The settings file can stay as it is: a computer whose
settings file still has the old name finds the folder under the new one, and
`Check Setup` says which name it is using.

The same goes for a project folder inside `Arrivals`: no space or full
stop at the end of its name.

### If Arrivals or the class folder is renamed

The control tower finds two folders by their names: `Arrivals`, and the class
folder that holds it. Leave both names as they are. Everything inside them
can be renamed, moved or deleted as you like.

If one of the two is renamed, moved or deleted while the control tower runs, the
control tower stops sorting and says so. It never makes a new folder in its place.

- The log says it once, for example `cannot find the folder 'Arrivals' any
  more`, with where the folder was and what to do. `Check Setup` shows that
  line.
- The computer's file in `Watcher status` says `standing by`, with a note
  that the folder cannot be found. This is the place to look from a phone.
  When it is the class folder itself that was renamed, the file cannot be
  written, so its "last checked" time stops moving.
- Photos put into a folder with another name, such as `Photos`, are not seen
  and stay where they are. Nothing is lost.

To put it right, give the folder its old name back in Google Drive
(drive.google.com). The control tower carries on by itself within two minutes,
and sorts the photos that are in the folder by then. Nobody restarts
anything. To keep a new name for the class folder instead, the
settings file on every computer that watches the class has to say the new
name; ask the person who set the computer up, and then double-click Setup.

The same happens when Google Drive is signed out or closed on the watching
computer. The log says that most likely Google Drive is signed out, nothing
is made on the computer's own disk, and sorting carries on by itself once
Google Drive is signed in again.

Versions of the tool from before the night of September 26, 2026 did the
opposite. They made an empty `Arrivals`, or a whole empty class folder,
under the old name within five seconds, filed new work into it, and said
nothing. Every computer that watches the class needs this version: a
computer with an older one still makes the folder again, and Google Drive
brings that empty folder to the others. If a class has an empty `Arrivals` beside a folder of photos, or two class folders that look alike,
that is what happened: move the photos into `Arrivals`, move any work
into the class folder the settings file names, and delete the empty one.

### More than one computer

**Before a second computer watches a class, both must have this version of
the tool.** The way to tell: within a minute of its control tower starting, a
computer with this version has a file named for it in `Watcher status/`
inside the class folder. A computer that is on and watching and has no file
there has an older version. It sorts every photo it sees and tells nobody,
so with two control towers on, every child gets the same piece twice. Until that
computer has this version, run one control tower only: double-click `Stop
Watcher.command` (Mac) or `Stop Watcher.bat` (Windows) on one of the two.

If both have to stay on until then, say so on the computer that has this
version: add the line `"shared": true` to its `settings.local.json` and
start its control tower again. While the other computer has never reported in,
that control tower leaves each new photo for the other computer for 10 minutes,
and sorts it only if it is still in `Arrivals` after that. So the computer
with the older version does the sorting whenever it is on, and no child gets
a piece twice. On a day it is off, the pieces appear ten minutes later than
usual. The log says what happened to every photo: `left in Arrivals for
the other computer`, and then `The other computer took it` or `still in
Arrivals after 10 minutes`. The computer's file in `Watcher status/` has
a note that says the same. The day the other computer has this version and
reports in, the wait ends by itself and the log says so.

Two computers can watch the same class, for example the classroom PC and a
helper's Mac at home, and only one of them sorts at a time. Each control tower
writes a small text file about itself into `Watcher status/` inside the
class folder, once a minute at most, and reads the others'. Of the
computers heard from in the last five minutes, the one with the lowest
`priority` number in its `settings.local.json` does the sorting (default
50; give a helper's computer 90) and the others stand by, so nobody gets a
piece twice. When the sorting computer is switched off or falls asleep, its
file stops being updated and a standing-by computer takes over within about
five minutes; when it comes back, it takes the work back. A control tower that
has just started waits 90 seconds before sorting, in case another computer
was in the middle of a photo. A computer that wakes from sleep (a laptop
whose lid was closed) waits the same 90 seconds again, because for a moment
after waking its copy of the class folder is as old as the sleep: Google
Drive has not yet told it what the other computer did while it was asleep.
The log says `this computer was asleep for 47 minutes; standing by for 90
seconds while Google Drive catches up`. A photo is claimed before it is cut: the
control tower moves it into `done` first and sorts it from there, so a computer
that loses the race finds the photo gone and saves nothing. (A photo that
turns out to be unreadable moves on from `done` to `failed`.)

The sorting computer writes its file before it touches a photo, and again
between the photos of a long batch, so the others never mistake a busy
computer for one that is off. If a computer cannot write its status file
for three minutes (Google Drive signed out or closed, or the disk full), it
stops sorting, because the others can no longer tell that it is on and one
of them is about to take over. Its log says `standing by: this computer
cannot write its status file`, and what to check. New photos wait in `Arrivals` until then; nothing is lost. When the file can be written again the
log says `this computer's status file can be written again`, the computer
waits the usual 90 seconds, and sorting carries on by itself.

A computer running a version of this tool from before `Watcher status/`
existed sorts every photo it sees and never writes a status file, so the
others cannot see it. When a control tower catches one at it, because a photo was
taken from the inbox by a computer it has not heard from, or because a copy
of a piece it just filed appears in the same folder, the log says so in
plain words and that control tower stands by for eight hours (or until it is
restarted), and its status file says `standing by; a computer running an
older version of Baggage Claim is watching this class`. The cure is to
install this version on that computer; until then, run only one control tower.
A control tower can only catch the other computer after a photo has been sorted
twice, which is why the rule at the top of this section comes first. For
the same reason a control tower that finds no other status file does not say the
other computer is off. Its log says `this computer is watching this class
(no other computer has reported in)`, and then that a computer with an
older version never reports in, even when it is on and sorting.

An iPhone photo (`IMG_1234.HEIC`) has to be turned into a JPEG before it can
be read. This version keeps that copy in its own scratch folder, so `Arrivals` only ever holds the photos the teacher put there. The scratch folder
is on the computer itself and never in Google Drive: if the Baggage Claim
folder was unzipped inside the class's Drive folder, the copy and the cut-out
pieces are kept in the computer's temporary folder while a photo is sorted,
so nothing extra is uploaded and nothing lands in Drive's trash. A computer with an
older version puts the copy into `Arrivals` itself, as
`IMG_1234.HEIC.jpg`, for as long as it works on the photo, so a teacher
looking at the folder on her phone can see a second file appear and go away
again. This version knows that file for what it is and never sorts it as a
second photo of the same wall. If the older computer was switched off in the
middle of a photo, the copy stays in `Arrivals`. It is safe to delete, and
it stops appearing the day that computer has this version.

### How to see it is alive from anywhere

Open the class folder in Google Drive, on any computer or phone, and open
`Watcher status/`. There is one file per computer, named for the computer,
and it says in plain words when that computer last checked the inbox, whether
it is watching or standing by, how many photos are waiting and what the last
batch did. A "last checked" time more than five minutes old means that
computer is off, asleep, or not signed in to Drive. `Check Setup.command`
(Mac) and `Check Setup.bat` (Windows) print the same list, freshest first,
for example `Classroom PC: last checked 2 minutes ago, watching`. A
computer with an older version of the tool is not in the folder or in the
list, even when it is on and sorting; the list says so underneath.

### After a change, start the control tower again

A control tower reads `settings.local.json` and the program once, when it starts,
and works that way until it is started again. So a new line in the settings
file (`"shared": true`, a different `priority`) or a new version of the tool
changes nothing while the control tower from before is still running. To start it
again, double-click `Setup.command` (Mac) or `Setup.bat` (Windows). Photos
in `Arrivals` wait for those few seconds and are sorted afterwards.

`Check Setup` says when this is needed. It compares the control tower that is
running on the computer with the settings file and the program, and prints
`WARN: the control tower that is running on this computer is still working the old
way`, with what is different underneath, for example `It sorts with priority
50; the settings file says 90.` It still says READY, because the computer can
do the job; the WARN is the thing to act on. Versions of the tool from before
the night of September 26, 2026 did not say this: `Check Setup` read the
settings file and described the control tower the file asks for, not the one that
was running.

## Does this already exist?

The two halves do; the join is what I could not find. Digital portfolio
apps (Seesaw, ClassDojo Portfolios, ManageBac and others) all let a teacher
photograph a piece of work and post it to a child's portfolio: one photo,
pick the child, post, repeat. General A.I. file sorters exist too, in the
cloud, with no idea what a name label on a piece of construction paper is.
I could not find a tool that takes one photo of the whole wall, finds each
paper, reads the label, files each piece to the child, does the reading on
the teacher's own machine, and says "not sure" instead of guessing. Two web
searches are not a patent search, so if you know of one, tell me. The
portfolio apps are where the pieces could end up; this could be the front
door that feeds them.

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
- **Where the name sits.** A child's name on its own short line is the
  teacher's label wherever it is on the paper: top, bottom, or the middle of
  a drawing. On a page of writing, a name at the top or bottom edge counts a
  little extra, and the same name inside a sentence in the middle of the page
  is a character in the story and is discounted. A name in the middle that
  was read shakily still goes to a person. Everyday words (`the`, `day`,
  `my`) can never match a name.
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

## The promise, and the check that holds the tool to it

Mount the work on a dark background. Keep the whole paper in the photo, with
a little of the background showing on every side. Type the child's name in a
corner of the paper. Follow those three rules and every piece lands upright
in the right child's folder: one paper or twenty-five, the phone held any
way, the papers spaced out or hung touching.

A title sign on the wall is a paper too. Put a typed sticker that reads
TITLE, in capitals, on the sign and it is left out: not filed, and not sent
to a person. A paper with no child's name and no TITLE sticker still goes to
a person, because it may be a child's.

`python3 tests/contract_check.py` proves it on 75 practice walls that all
follow the rules (551 pieces, invented names). The required score is 100%.
A word after the command runs only the walls whose name holds that word, for
example `python3 tests/contract_check.py rot90`.

Outside the rules the tool fails safely: it never files a piece it is not
sure of. Pale paper on a pale wall, or a paper that runs off the edge of the
photo, goes to `Unsorted - needs a person` with the name in the file's name,
and the log says why.

## Tests

`Run Tests.command`, or:

```
python3 -m coverage run --source=. --omit='tests/*' -m unittest discover -s tests
python3 -m coverage report -m
```

The tests build fake walls (`tests/make_wall.py`: papers on a wall, scribbles,
names typed in Arial, as the rule a teacher is given asks, one unnamed, one
blurred, and writing samples that mention another child's name) and check
that every paper is found, every named one is filed under the right child,
and nothing is ever filed under the wrong one. The walls are typed in the
same face on a Mac and on a Windows PC, so both are tested on the same
promise. Until September 28, 2026 the names were in a handwriting-style
font, which is harder than the rule; `make_wall(hand=True)` still draws
them that way, and only the reader probe (`tests/reader_probe.py`) asks
for it.

## Setup

Runs on a Mac or a Windows PC. Either one can be the machine that watches a
class's Drive inbox; the teachers never need it on their own computer.

**Mac, one click.** The same GitHub build makes a Mac bundle
(`BaggageClaim-mac`): one program, `baggage-claim`, with Python and the
Vision helper inside, plus `Setup.command`, which downloads Google Drive
for desktop if it is missing, runs the self-check, and installs a launchd
job that starts the control tower at login and restarts it within 30 seconds if
it ever stops. The job runs a small `Baggage Claim.app` (built from
`mac/launcher.swift`), which runs `watch.sh`, which runs `baggage-claim`.
The app is there because macOS only asks a real app for permission to read
a Drive folder; a plain script started in the background is refused
without a word. Nobody double-clicks the app or `baggage-claim`:
`Setup.command` is the one to double-click. Bundles made before September
26, 2026 also held a windowless `Baggage Claim Watcher.app`, which was the
control tower then. It is no longer built and nothing starts it. If a folder
still has one, leave it alone or put it in the Trash; `Setup.command` stops
it if it is running and takes it out of Login Items.
`Setup.command` and the other three `.command` files run
`autostart.sh` and `watch.sh` from the folder they sit in, so the bundle, and
the zip made from it for a teacher, holds both: keep all the files in the
folder together. macOS shows a warning for a downloaded program that is not
signed by an Apple developer: right-click and Open, or Privacy & Security,
Open Anyway, once. It asks once for permission to read the Drive folder,
and once more after an update.

**Mac, from source.** Python 3.9+, Pillow, numpy, scipy. The Swift helper
builds itself the first time you run a `.command`, or:

```
swiftc -O vision.swift -o vision
```

Then `mac/Setup.command` (it finds the tool folder one level up) builds
`Baggage Claim.app` with the same compiler and installs the launchd job for
this folder, wherever the folder is. Without the compiler the job runs
`watch.sh` directly and works only after the Mac's Python has been given
Full Disk Access.

**A word about school-managed laptops.** A school's security software may stop a program it has never seen, silently. On one
teacher's school-managed PC it terminated both the setup script and
the control tower. If the watching machine is school-managed, ask IT to allow the
Baggage Claim folder first, or watch from a machine the school does not
manage. A code-signing certificate would make the Windows programs look
like ordinary software to such tools; it is on the list.

**Windows, one click.** Every push builds a Windows bundle on GitHub
(Actions, `build-windows`): `BaggageClaim.exe` and a windowless
`BaggageClaimWatcher.exe` with Python and every package inside, plus
`Setup.bat`, which installs Google Drive for desktop if it is missing, runs
the self-check, and sets the control tower to start at login. Download the
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
committed. No roster ships with the repo; the tests build their own walls
from made-up names.

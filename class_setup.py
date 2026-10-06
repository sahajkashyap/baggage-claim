#!/usr/bin/env python3
"""
Set up a class from its class list, on this computer, with nobody else reading it.

The list can come from a screenshot (read by this computer's own text reader,
the same one that reads name labels), from what the teacher just copied (a
Google Doc or Sheet, selected and copied), or from a text, CSV or Word file.
Nothing is sent anywhere: there is no network code here, and no A.I. reads
the names.

Two steps, run by "Set up a class.command":

  prepare  reads the list, keeps the lines that look like a child's name, and
           writes them one per line to a file the teacher checks and fixes on
           their own screen before anything is made.
  build    makes the class folder, one folder per child, the Wall Inbox and the
           doubtful-pieces folder (tools/new_class.py), and a page of name
           labels to cut out. It prints counts only, never a name.

Run:  python3 class_setup.py prepare [--source FILE] --out LIST
      python3 class_setup.py build --list LIST --class-name NAME [--grade G] [--project P]
"""
import argparse
import csv
import datetime
import io
import os
import re
import subprocess
import sys
import zipfile
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import baggage_claim as bc  # noqa: E402

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".heic", ".tif", ".tiff", ".gif", ".bmp"}
TEXT_EXT = {".txt", ".text", ".md", ".rtf"}
TABLE_EXT = {".csv", ".tsv"}
GOOGLE_STUB_EXT = {".gdoc", ".gsheet"}
GOOGLE_STUB_WHY = ("a Google Doc or Sheet cannot be read from this computer, only from the browser. "
                   "Open it, select the names, copy them, then run Set up a class again and choose "
                   "'What I copied'.")

# Lines in a class list that are headings, not children. Only a whole line that
# is exactly one of these is dropped; the teacher sees the list before anything
# is made, so anything else odd is theirs to delete.
HEADINGS = {"name", "names", "first name", "first names", "last name", "full name", "first", "last",
            "student", "students", "student name", "student names", "child", "children",
            "class list", "class", "roster", "class roster", "list"}
NUMBERING = re.compile(r"^\s*(?:[-*•●▪–]+|\(?\d{1,3}[.)\]:]?)\s+")


class SetupError(Exception):
    """A class list that cannot be read, with the reason in a plain sentence."""


# ------------------------------------------------------------ reading ---

def lines_from_image(path):
    """A screenshot or photo of the list, read by this computer's own reader.
    Each row comes back as its pieces left to right, each piece tagged with
    the column it starts in, so a table's name column can be told apart from
    its numbers and dates (pick_names). Rows top to bottom."""
    try:
        seen = bc.join_rows(bc.run_vision("text", path))
    except RuntimeError as e:
        raise SetupError(f"this computer's text reader could not read the picture ({e})") from None
    if not seen:
        return []
    width = max(t["x"] + t["w"] for t in seen) or 1

    def start(t):   # where the words begin: the reader sometimes reads a row number and the name as one piece
        m = NUMBERING.match(t["text"])
        return t["x"] + (t["w"] * len(m.group(0)) / max(len(t["text"]), 1) if m else 0)

    starts = sorted(start(t) for t in seen)
    col_of, col = {}, 0
    for i, x in enumerate(starts):   # a new column wherever the left edges jump
        if i and x - starts[i - 1] > 0.03 * width:
            col += 1
        col_of.setdefault(x, col)
    rows = []
    for t in sorted(seen, key=lambda t: t["y"]):
        if rows and abs(rows[-1][0]["y"] - t["y"]) < 0.5 * max(t["h"], 1):
            rows[-1].append(t)
        else:
            rows.append([t])
    # A real column runs down many rows; a column of one or two pieces is a
    # piece whose start was misjudged, so it joins the nearest real column.
    members = {}
    for t in seen:
        members.setdefault(col_of[start(t)], []).append(start(t))
    centre = {c: sum(xs) / len(xs) for c, xs in members.items()}
    real = [c for c, xs in members.items() if len(xs) >= max(3, len(rows) // 5)] or list(members)
    home = {c: c if c in real else min(real, key=lambda r: abs(centre[r] - centre[c])) for c in members}
    return [[(home[col_of[start(t)]], t["text"]) for t in sorted(r, key=lambda t: t["x"])] for r in rows]


def lines_from_docx(path):
    """Each paragraph, and each table row with its cells joined by a space
    (a Word table of first name | last name gives one name per row)."""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8")
    except (zipfile.BadZipFile, KeyError, OSError):
        raise SetupError("the Word file could not be opened") from None
    out = []
    body = re.sub(r"<w:tbl>.*?</w:tbl>", lambda m: "\n<ROW>" + _rows(m.group(0)) + "\n", xml, flags=re.S)
    for chunk in re.split(r"</w:p>|\n", body):
        if chunk.startswith("<ROW>"):
            out.extend([list(enumerate(r.split("\x01"))) for r in chunk[5:].split("\x00")])
        else:
            out.append(_text(chunk))
    return out


def _text(xml):
    t = "".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", xml))
    return t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&apos;", "'").replace("&quot;", '"')


def _rows(tbl):
    rows = []
    for tr in re.findall(r"<w:tr[ >].*?</w:tr>", tbl, flags=re.S):
        cells = [_text(tc) for tc in re.findall(r"<w:tc>.*?</w:tc>", tr, flags=re.S)]
        rows.append("\x01".join(c.strip() for c in cells))
    return "\x00".join(rows)


def lines_from_table_text(text):
    """CSV or tab-separated text (a copied Sheet arrives with tabs): each row's
    cells joined by a space."""
    delim = "\t" if "\t" in text else ","
    return [list(enumerate(c.strip() for c in row)) for row in csv.reader(io.StringIO(text), delimiter=delim)]


def lines_from_clipboard():
    try:
        text = subprocess.run(["pbpaste"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        raise SetupError("what was copied could not be read") from None
    if not text.strip():
        raise SetupError("nothing has been copied. Select the names in the Doc or Sheet, copy them, then run "
                         "Set up a class again.")
    return lines_from_table_text(text) if "\t" in text else text.splitlines()


def read_source(path=None):
    """The raw lines of the class list, from a file or (no file) the clipboard."""
    if path is None:
        return lines_from_clipboard()
    ext = os.path.splitext(path)[1].lower()
    if ext in GOOGLE_STUB_EXT:
        raise SetupError(GOOGLE_STUB_WHY)
    if not os.path.isfile(path):
        raise SetupError("the file could not be found")
    if ext in IMAGE_EXT:
        return lines_from_image(path)
    if ext == ".docx":
        return lines_from_docx(path)
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    if ext in TABLE_EXT or "\t" in text:
        return lines_from_table_text(text)
    if ext in TEXT_EXT or ext == "":
        return text.splitlines()
    raise SetupError("that kind of file cannot be read. Use a screenshot, a Word file, a text file, or copy "
                     "the names and choose 'What I copied'.")


def tidy_name(name):
    """Undo the reader's usual slips on a name, which always starts with one
    capital letter: a first word read all in capitals or all in small letters
    ('IVO', 'ignatius') gets its capital back, a small l read for a capital I
    at the very start ('lvo') becomes I, and an O' name read without its
    apostrophe ('OLeary') gets it back. Anything else is left exactly as read
    for the person to check."""
    words = name.split(" ")
    first = words[0]
    if len(first) > 1 and first[0] == "l" and first[1:].islower() and first[1] not in "aeiouly":
        first = "I" + first[1:]
    if first.isalpha() and (first.islower() or (first.isupper() and len(first) > 2)):
        first = first[0].upper() + first[1:].lower()
    words[0] = first
    words = [re.sub(r"^O([A-Z][a-z]{2,})$", r"O'\1", w) for w in words]
    return " ".join(words)


NOT_NAME_WORDS = {
    "name", "names", "first", "last", "full", "middle", "preferred", "nickname", "student", "students", "child",
    "children", "class", "classes", "grade", "grades", "room", "teacher", "teachers", "date", "birthday", "birth",
    "dob", "age", "group", "groups", "present", "absent", "tardy", "late", "total", "notes", "note", "comments",
    "score", "scores", "level", "reading", "math", "yes", "no", "none", "n/a", "parent", "parents", "guardian",
    "email", "phone", "address", "id", "number", "list", "roster", "period", "week", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday", "kindergarten", "preschool", "homeroom", "team",
    "table", "seat", "boy", "girl", "male", "female", "gender", "pronouns", "allergy", "allergies", "checked",
    "check", "done", "in", "out", "the", "of", "my", "our", "and", "or", "to", "for", "with", "by", "fall",
    "spring", "winter", "summer", "year", "term", "semester", "oldest", "youngest", "sorted",
}
PARTICLES = {"de", "la", "del", "della", "da", "di", "dos", "das", "du", "van", "von", "der", "den", "le", "bin",
             "ibn", "al", "el", "y", "e", "ten", "ter", "st"}


def scrub(text):
    """A cell or line with what can never be part of a name taken out:
    numbering, anything holding a digit or an @ (dates, ids, emails, phone
    numbers), and stray punctuation."""
    text = text.replace("\u2028", " ").replace("\u00a0", " ")
    text = NUMBERING.sub("", text)
    words = [w.strip(",;:()[]|*\u2022") for w in text.split()]
    words = [w for w in words if w and not any(c.isdigit() or c in "@/\\=+#%$&<>" for c in w)
             and any(c.isalpha() for c in w)]
    return " ".join(words)


def looks_like_name(text):
    """One to four words, each a capitalised word of letters (a hyphen or an
    apostrophe allowed) or a small joining word such as de or van, none of
    them a word that labels a column ("Name", "Grade", "Present")."""
    words = text.split()
    if not 1 <= len(words) <= 4:
        return False
    proper = 0
    for w in words:
        bare = w.replace("-", "").replace("'", "").replace("\u2019", "").rstrip(".")
        if not bare.isalpha() or w.lower().rstrip(".") in NOT_NAME_WORDS:
            return False
        if w.lower() in PARTICLES:
            continue
        if not w[0].isupper():
            return False
        proper += 1
    return proper >= 1 and len("".join(words)) >= 2


def pick_names(rows):
    """The children's names in what was read. A row is a line of text, or a
    table row as (column, text) cells. In a table, the columns that are
    mostly names are kept and the rest (numbers, dates, ticks, groups) are
    not; a first-name column and a last-name column next to each other are
    joined into one name, first name first. A line that is not a table is
    kept only if what is left of it, once numbers and the like are taken out,
    looks like a name. Headings are dropped either way."""
    table = [r for r in rows if isinstance(r, list)]
    keep_cols, order = set(), []
    if table:
        stats = {}
        for r in table:
            for col, text in r:
                t = tidy_name(scrub(text)) if scrub(text) else ""
                if t:
                    named, filled, words = stats.get(col, (0, 0, 0))
                    ok = looks_like_name(t)
                    stats[col] = (named + ok, filled + 1, words + (len(t.split()) if ok else 0))
        enough = 1 if len(table) < 3 else max(2, len(table) // 3)
        keep_cols = {c for c, (named, filled, _) in stats.items() if named >= enough and named >= 0.5 * filled}
        if keep_cols:   # a column filled on only a few rows is a side note ("Oldest"), not a name column
            most = max(stats[c][0] for c in keep_cols)
            keep_cols = {c for c in keep_cols if stats[c][0] >= 0.5 * most}
        order = sorted(keep_cols)
        for r in table:   # a heading row that says Last before First puts the last-name column first
            heads = {c: t.lower() for c, t in r if c in keep_cols}
            last = [c for c, t in heads.items() if "last" in t.split()]
            first = [c for c, t in heads.items() if "first" in t.split()]
            if last and first:
                order = sorted(keep_cols, key=lambda c: (c not in first, c not in last, c))
                break
        single_words = any(stats[c][2] <= stats[c][0] * 1.3 for c in keep_cols)   # a first-name column
    out = []
    for r in rows:
        if not isinstance(r, list):
            t = tidy_name(scrub(r)) if scrub(r) else ""
            if t and looks_like_name(t):
                out.append(t)
            continue
        cells = {c: tidy_name(scrub(text)) for c, text in r if c in keep_cols and scrub(text)}
        cells = {c: t for c, t in cells.items() if looks_like_name(t)}
        if not cells:
            continue
        if len(cells) > 1 and single_words:
            out.append(" ".join(cells[c] for c in order if c in cells))   # First | Last columns
        else:
            out.extend(cells[c] for c in order if c in cells)            # one full name per cell
    return out


def clean(lines):
    """The children's names, in order, each once (pick_names says how a name
    is told apart from everything else on a class list)."""
    out, seen = [], set()
    for ln in pick_names(lines):
        ln = " ".join(ln.split())
        key = ln.casefold()
        if key not in seen:
            seen.add(key)
            out.append(ln)
    return out


# ------------------------------------------------------------- labels ---

def label_names(roster):
    """What goes on each cut-out label: the first name, or the whole name when
    two children on the list share a first name (the label has to tell them apart)."""
    firsts = [n.split()[0] for n in roster]
    return [n if firsts.count(f) > 1 else f for n, f in zip(roster, firsts)]


LABEL_COLS = 3
CELL_W = 3240   # 2.25 in, in twentieths of a point
CELL_H = 1296   # 0.9 in


def labels_docx(names, path):
    """A page of name labels to cut out: a 3-column table of dashed boxes,
    Arial bold 20 pt, centered, Letter paper with 0.75 in margins."""
    border = "".join(f'<w:{s} w:val="dashed" w:sz="6" w:space="0" w:color="999999"/>'
                     for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
    run = ('<w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial" w:eastAsia="Arial"/>'
           '<w:b/><w:sz w:val="40"/><w:szCs w:val="40"/></w:rPr>')
    rows = []
    for i in range(0, len(names), LABEL_COLS):
        cells = []
        for n in (names[i:i + LABEL_COLS] + [None] * LABEL_COLS)[:LABEL_COLS]:
            para = ('<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:before="0" w:after="0"/></w:pPr>'
                    + (f'<w:r>{run}<w:t xml:space="preserve">{escape(n)}</w:t></w:r>' if n else "") + "</w:p>")
            cells.append(f'<w:tc><w:tcPr><w:tcW w:w="{CELL_W}" w:type="dxa"/><w:vAlign w:val="center"/></w:tcPr>'
                         f"{para}</w:tc>")
        rows.append(f'<w:tr><w:trPr><w:trHeight w:val="{CELL_H}" w:hRule="exact"/><w:cantSplit/></w:trPr>'
                    + "".join(cells) + "</w:tr>")
    grid = "".join(f'<w:gridCol w:w="{CELL_W}"/>' for _ in range(LABEL_COLS))
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           f'<w:tbl><w:tblPr><w:tblW w:w="{CELL_W * LABEL_COLS}" w:type="dxa"/><w:jc w:val="center"/>'
           f'<w:tblBorders>{border}</w:tblBorders><w:tblLayout w:type="fixed"/>'
           '<w:tblCellMar><w:left w:w="115" w:type="dxa"/><w:right w:w="115" w:type="dxa"/></w:tblCellMar></w:tblPr>'
           f'<w:tblGrid>{grid}</w:tblGrid>{"".join(rows)}</w:tbl><w:p/>'
           '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
           '<w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080" w:header="720" w:footer="720" w:gutter="0"/>'
           "</w:sectPr></w:body></w:document>")
    types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/word/document.xml" '
             'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
             "</Types>")
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" Target="word/document.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)


def stamp(now=None):
    now = now or datetime.datetime.now()
    return f"{now.strftime('%b')} {now.day} {now.year} {now.strftime('%I').lstrip('0')}.{now.strftime('%M %p')}"


# -------------------------------------------------------------- steps ---

def prepare(source, out):
    names = clean(read_source(source))
    if not names:
        raise SetupError("no names were found in the class list")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(names) + "\n")
    return len(names)


def folder_name(class_name):
    """The class name as a folder every computer can open: a slash or a colon
    becomes a dash, the characters a Windows PC cannot hold in a folder name
    are left out, and no space, dash or full stop is left at either end."""
    name = re.sub(r"[/\\:]+", "-", class_name)
    name = re.sub(r'[?"*<>|]', "", name)
    return " ".join(name.split()).strip(" .-")


def build(list_path, class_name, grade="", project="Artwork", drive_root=None, labels_dir=None,
          new_class=None, now=None):
    """Make the class and its labels. Returns a dict of counts and file paths;
    nothing in it is a child's name (the class folder name is the teacher's)."""
    roster = bc.load_roster(list_path)
    if not roster:
        raise SetupError("the class list is empty")
    class_name = folder_name(class_name)
    if not class_name:
        raise SetupError("the class folder needs a name")
    new_class = new_class or os.path.join(ROOT, "tools", "new_class.py")
    if not os.path.isfile(new_class):
        raise SetupError("the class-setup part (tools/new_class.py) is not on this computer")
    cmd = [sys.executable, new_class, "--class-name", class_name, "--roster", list_path, "--project", project,
           "--grade", grade]
    if drive_root:
        cmd += ["--drive-root", drive_root]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        why = (res.stderr.strip().splitlines() or ["the class folder could not be made"])[-1]
        raise SetupError(why)
    found = re.search(r"^class folder: (.+)$", res.stdout, flags=re.M)
    if not found:
        raise SetupError("the class folder could not be made")
    cls = found.group(1).strip()
    folders = sum(1 for n in roster if os.path.isdir(os.path.join(cls, bc.safe_folder(n))))
    labels = label_names(roster)
    title = f"1 — {bc.safe_folder(class_name)} NAMES to cut out — {stamp(now)}.docx"
    written = []
    for d in [cls] + ([labels_dir] if labels_dir else []):
        p = os.path.join(d, title)
        labels_docx(labels, p)
        written.append(p)
    return {"children": len(roster), "folders": folders, "labels": len(labels), "class_folder": cls,
            "label_files": written}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="step", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--source", default=None, help="screenshot, Word, CSV or text file; leave out to use what was copied")
    p.add_argument("--out", required=True)
    b = sub.add_parser("build")
    b.add_argument("--list", required=True)
    b.add_argument("--class-name", required=True)
    b.add_argument("--grade", default="")
    b.add_argument("--project", default="Artwork")
    b.add_argument("--drive-root", default=None)
    b.add_argument("--labels-dir", default=os.path.join(os.path.expanduser("~"), "Desktop"))
    a = ap.parse_args(argv)
    try:
        if a.step == "prepare":
            print(f"{prepare(a.source, a.out)} names found.")
        else:
            r = build(a.list, a.class_name, a.grade, a.project, a.drive_root, a.labels_dir)
            ok = r["folders"] == r["children"]
            print(f"{r['folders']} of {r['children']} child folders made, {r['labels']} name labels."
                  + ("" if ok else " Some folders are missing: check the class folder."))
            print(f"The class folder is called: {os.path.basename(r['class_folder'])}")
            print("The labels page is in the class folder" + (" and on the Desktop." if a.labels_dir else "."))
            return 0 if ok else 1
    except (SetupError, bc.ClassListError) as e:
        print(f"Could not set up the class: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The contract check.

The contract: the work is against a dark background, the whole paper is in the
frame, and the child's name is typed in a corner of the paper. When a teacher
follows those rules, every piece must land, upright, in the right child's
folder. Every case below follows the rules, so the required score is 100%.
A miss is a bug, however rare the case.

Run the whole grid:   python3 tests/contract_check.py
Run a few cases:      python3 tests/contract_check.py corner rot90
No real photo and no real name is used.

Which way up a filed piece is, is decided by its pixels and not by the
reader. The practice walls are made here, so the check knows what each paper
looks like: it shrinks the filed piece and the paper to the same small black-and-white
square and compares them at each quarter turn. What the reader makes of the
filed piece is printed beside the result, as information; it is never a
reason for a miss. A wall that this computer cannot write at all (a HEIC photo
where nothing can write one, a font that is not here) is SKIPPED, and said so:
it is not a miss and it is not a pass."""
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import baggage_claim as sw  # noqa: E402
from contract_wall import contract_wall, from_the_side, font_file, FontNotFound, FONTS, NAMES, DARK, WALLS  # noqa: E402

SMALL = 32       # the filed piece and the paper are both shrunk to SMALL x SMALL black-and-white before they are compared
FINE = 4         # the wall around the paper is looked for at SMALL * FINE, then left out of the comparison
NEAR = 48        # how near the wall's colour (on every channel) a pixel must be to count as wall
CLEAR = 0.10     # upright must match better than every quarter turn by at least this much
TURNS = (0, 90, 180, 270)

SIGN = "TITLE"   # what the teacher's sticker on a title sign reads

GRID = {1: (1, 1), 2: (1, 2), 4: (2, 2), 6: (2, 3), 8: (2, 4), 9: (3, 3), 12: (3, 4), 16: (4, 4), 20: (4, 5), 25: (5, 5)}


def cases():
    out = []
    def add(name, n=6, turn=0, exif=None, side=None, fmt="jpg", **kw):
        out.append({"case": name, "n": n, "turn": turn, "exif": exif, "side": side, "fmt": fmt, "kw": kw})
    for corner in ("tl", "tr", "bl", "br"):
        for turn in (0, 90, 180, 270):
            add(f"corner-{corner} rot{turn}", corner=corner, turn=turn, seed=len(out) + 1)
    for n in (1, 2, 4, 8, 9, 12, 16, 20, 25):
        add(f"pieces-{n}", n=n, seed=40 + n)
    for bg in DARK:
        for paper in ("white", "cream", "yellow", "blue"):
            add(f"bg-{bg} paper-{paper}", bg=bg, paper=paper, seed=len(out) + 1)
    for side in ("left", "right"):
        for strength in (0.06, 0.12):
            add(f"side-{side}-{strength}", side=(side, strength), seed=len(out) + 1)
    for tag in (6, 8, 3):
        add(f"wrong-tag-{tag}", exif=tag, seed=len(out) + 1)
    for font in ("arial", "times", "verdana"):
        add(f"font-{font}", font=font, seed=len(out) + 1)
    for corner in ("tl", "br"):
        add(f"sentences corner-{corner}", corner=corner, sentences=True, seed=len(out) + 1)
        add(f"sentences corner-{corner} rot90", corner=corner, sentences=True, turn=90, seed=len(out) + 1)
    add("portrait-paper", portrait_paper=True, seed=len(out) + 1)
    add("portrait-paper rot270", portrait_paper=True, turn=270, seed=len(out) + 1)
    add("png", fmt="png", seed=len(out) + 1)
    add("heic", fmt="heic", seed=len(out) + 1)
    add("small-photo 2016x1512", size=(2016, 1512), seed=len(out) + 1)
    add("touching-2", n=2, touching=True, seed=len(out) + 1)
    add("touching-6", n=6, touching=True, seed=len(out) + 1)
    add("touching-6 rot90", n=6, touching=True, turn=90, seed=len(out) + 1)
    add("touching-12 paper-cream", n=12, touching=True, paper="cream", seed=len(out) + 1)
    # a middle-blue display board, with and without a band of cream wall above it
    add("bg-mid-blue paper-white 20", n=20, bg="mid-blue", seed=len(out) + 1)
    add("bg-mid-blue band 20 sentences", n=20, bg="mid-blue", band=0.3, sentences=True, seed=len(out) + 1)
    add("bg-mid-blue band 16 portrait", n=16, bg="mid-blue", band=0.3, portrait_paper=True, seed=len(out) + 1)
    add("bg-mid-blue band 8 rot90", n=8, bg="mid-blue", band=0.3, turn=90, seed=len(out) + 1)
    # a child who has not done much yet: the name sticker and nothing else.
    # The sticker is what files the paper, so it is filed all the same
    add("blank-paper 6", blank=True, seed=len(out) + 1)
    add("blank-paper 9 corner-tl", n=9, blank=True, corner="tl", seed=len(out) + 1)
    add("blank-paper 6 paper-cream bg-navy", blank=True, paper="cream", bg="navy", seed=len(out) + 1)
    # a title sign among the children's work, with the teacher's TITLE sticker
    # on it: left out, and every child still gets the right piece
    add("title-sign 6", sign=True, seed=len(out) + 1)
    add("title-sign 9 rot90 corner-tl", n=9, sign=True, corner="tl", turn=90, seed=len(out) + 1)
    add("title-sign 6 sentences", sign=True, sentences=True, seed=len(out) + 1)
    add("title-sign 20 mid-blue band", n=20, sign=True, bg="mid-blue", band=0.3, seed=len(out) + 1)
    return out


def say(text=""):
    """Print on any computer: a character its screen cannot show becomes a question mark."""
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(str(text).encode(enc, "replace").decode(enc, "replace"), flush=True)


def heic_writer():
    """What on this computer can write a HEIC photo: the Mac's own sips, or
    the pillow-heif package. None when neither is here."""
    if shutil.which("sips"):
        return "sips"
    try:
        import pillow_heif  # noqa: F401
    except Exception:
        return None
    return "pillow-heif"


def write_heic(img, path):
    """Write the wall as a HEIC photo. Returns (True, what wrote it) or
    (False, why not, in plain words)."""
    why = []
    if shutil.which("sips"):
        jpg = os.path.splitext(path)[0] + ".src.jpg"
        img.save(jpg, quality=92)
        try:
            r = subprocess.run(["sips", "-s", "format", "heic", jpg, "--out", path], capture_output=True)
            if r.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 0:
                return True, "sips"
            why.append("sips could not write it")
        except OSError as e:
            why.append(f"sips could not be run ({e})")
        finally:
            if os.path.exists(jpg):
                os.remove(jpg)
    else:
        why.append("this computer has no sips")
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        img.save(path, format="HEIF", quality=92)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return True, "pillow-heif"
        why.append("pillow-heif wrote nothing")
    except ImportError:
        why.append("pillow-heif is not installed")
    except Exception as e:
        why.append(f"pillow-heif could not write it ({type(e).__name__}: {e})")
    if os.path.exists(path):
        os.remove(path)
    return False, "a HEIC photo cannot be written here: " + ", and ".join(why)


def save(img, path, fmt, exif):
    if fmt == "heic":
        return write_heic(img, path)[0]
    if exif:
        ex = Image.Exif(); ex[274] = exif
        img.save(path, quality=92, exif=ex)
    else:
        img.save(path, quality=92) if fmt == "jpg" else img.save(path)
    return True


def wall_at_the_edges(rgb, wall):
    """The pixels that are wall and reach the edge of the picture: the strips
    of dark background left around a paper. Typed letters and dark lines in a
    drawing are as dark as a wall, but they do not reach the edge, so they
    are not taken for wall."""
    near = np.abs(rgb - np.array(wall, dtype=float)).max(axis=2) < NEAR
    seen = np.zeros_like(near)
    seen[0, :], seen[-1, :], seen[:, 0], seen[:, -1] = near[0, :], near[-1, :], near[:, 0], near[:, -1]
    while True:
        grown = seen.copy()
        grown[1:, :] |= seen[:-1, :]
        grown[:-1, :] |= seen[1:, :]
        grown[:, 1:] |= seen[:, :-1]
        grown[:, :-1] |= seen[:, 1:]
        grown &= near
        if (grown == seen).all():
            return seen
        seen = grown


def fine_rgb(img):
    n = SMALL * FINE
    return np.asarray(img.convert("RGB").resize((n, n), Image.BOX), dtype=float)


def paper_part(img, wall):
    """The filed piece without the strips of wall around the paper."""
    n = SMALL * FINE
    paper = ~wall_at_the_edges(fine_rgb(img), wall)
    rows, cols = np.where(paper.mean(axis=1) > 0.5)[0], np.where(paper.mean(axis=0) > 0.5)[0]
    if len(rows) < n // 4 or len(cols) < n // 4:
        return img           # hardly any paper in it: compare the picture as it is
    w, h = img.size
    return img.crop((int(cols[0] * w / n), int(rows[0] * h / n),
                     min(w, int((cols[-1] + 1) * w / n + 0.999)), min(h, int((rows[-1] + 1) * h / n + 0.999))))


def small_shades(img, wall=None):
    """The picture as a SMALL x SMALL black-and-white square, and beside it how much of
    each small square counts (1 = all of it; 0 = it is wall, leave it out)."""
    rgb = fine_rgb(img)
    shades = rgb @ np.array([0.299, 0.587, 0.114])
    keep = np.ones(shades.shape)
    if wall is not None:
        keep[wall_at_the_edges(rgb, wall)] = 0.0
    counted = keep.reshape(SMALL, FINE, SMALL, FINE).sum(axis=(1, 3))
    total = (shades * keep).reshape(SMALL, FINE, SMALL, FINE).sum(axis=(1, 3))
    return total / np.maximum(counted, 1.0), counted / (FINE * FINE)


def alike(a, counts, b):
    """How alike two small black-and-white squares are: 1 is the same picture, 0 is
    nothing in common. `counts` says how much each square of `a` counts."""
    weight = counts.sum()
    if weight <= 0:
        return 0.0
    da, db = a - (a * counts).sum() / weight, b - (b * counts).sum() / weight
    size = np.sqrt((counts * da * da).sum() * (counts * db * db).sum())
    return float((counts * da * db).sum() / size) if size > 0 else 0.0


def which_way_up(piece, paper, wall=None):
    """How well the filed piece matches the paper it came from, after each
    quarter turn (counter-clockwise, as PIL's rotate() counts). The best
    match at 0 means the piece was filed upright; the best match at 90 means
    it would be upright after a 90 degree turn."""
    piece = piece.convert("RGB")
    if wall is not None:
        piece = paper_part(piece, wall)
    ref = paper if isinstance(paper, np.ndarray) else small_shades(paper)[0]
    shades, counts = small_shades(piece, wall)
    return {90 * k: round(alike(np.rot90(shades, k), np.rot90(counts, k), ref), 3) for k in range(4)}


def upright(piece, paper, wall=None):
    """Was the piece filed the right way up? Decided by the pixels alone.
    `piece` is the filed picture (or its path), `paper` the paper's own
    picture from the practice wall, `wall` the wall's colour.
    Returns (yes or no, why not, the match at each quarter turn)."""
    if isinstance(piece, str):
        with Image.open(piece) as im:
            piece = im.convert("RGB")
    match = which_way_up(piece, paper, wall)
    best = max(TURNS, key=lambda k: match[k])
    lead = match[0] - max(match[k] for k in TURNS if k)
    said = ", ".join(f"{k}: {match[k]:.2f}" for k in TURNS)
    if best != 0 and match[best] - match[0] >= CLEAR:
        return False, f"filed turned: it would be upright after a {best} degree turn (match at {said})", match
    if lead < CLEAR:
        return False, f"cannot tell from the filed piece which way is up (match at {said})", match
    return True, "", match


def looks_like(piece, papers, wall=None):
    """Whose paper the filed piece looks like: the match with each child's
    paper, at whichever quarter turn matches best. `papers` is
    {name: small black-and-white square}."""
    piece = piece.convert("RGB")
    if wall is not None:
        piece = paper_part(piece, wall)
    shades, counts = small_shades(piece, wall)
    return {name: max(alike(np.rot90(shades, k), np.rot90(counts, k), ref) for k in range(4))
            for name, ref in papers.items()}


def reader_says(path, name):
    """What this computer's reader makes of the filed piece. Information
    only: it depends on the reader and on the version of the system, so it
    is printed beside the result and never decides it."""
    try:
        with Image.open(path) as im:
            lines = sw.read_piece(path, im.copy())
        first = sw.norm(name).split()[0]
        hits = [t for t in lines if first in sw.norm(t.get("text", ""))]
        if not hits:
            return "label not read"
        angle = sw.text_angle(max(hits, key=lambda t: t.get("conf", 0)))
        return "upright" if angle == 0 else f"label read at {angle} degrees"
    except Exception as e:
        return f"reader failed ({type(e).__name__}: {e})"


def score_wall(res, truth, names, out, wall=None, ask_reader=True):
    """Hold what the tool filed against what was on the wall. Returns
    (pieces right, problems, information)."""
    problems, right = [], 0
    papers = {t["name"]: small_shades(t["paper"])[0] for t in truth}
    leads, read = [], []
    for t in truth:
        mine = [r for r in res if r.get("name") == t["name"] and r.get("status") == "confident"]
        if len(mine) != 1:
            others = [f"{r.get('status')}:{r.get('score')}" for r in res if r.get("name") == t["name"]]
            problems.append(f"{t['name']}: filed {len(mine)} times ({', '.join(others) or 'never read'})")
            continue
        f = mine[0]["file"]; f = f if os.path.isabs(f) else os.path.join(out, f)
        if not os.path.exists(f):
            problems.append(f"{t['name']}: file missing"); continue
        with Image.open(f) as im:
            piece = im.convert("RGB")
        if ask_reader:
            read.append((t["name"], reader_says(f, t["name"])))
        w, h = piece.size
        bw, bh = t["box"][2] - t["box"][0], t["box"][3] - t["box"][1]
        if abs(bw - bh) > 0.2 * max(bw, bh) and (w > h) != t["landscape"]:
            problems.append(f"{t['name']}: filed {'landscape' if w > h else 'portrait'}, paper is the other way"); continue
        ok, why, match = upright(piece, papers[t["name"]], wall)
        if not ok:
            problems.append(f"{t['name']}: {why}"); continue
        whose = looks_like(piece, papers, wall)
        other = max(whose, key=whose.get)
        if other != t["name"] and whose[other] - whose[t["name"]] >= CLEAR:
            problems.append(f"{t['name']}: the piece filed here looks like the paper of {other} "
                            f"(match {whose[other]:.2f}, against {whose[t['name']]:.2f} for the child's own)"); continue
        leads.append((round(match[0] - max(match[k] for k in TURNS if k), 3), t["name"]))
        right += 1
    wrong = [r for r in res if r.get("status") == "confident" and r.get("name") not in names]
    extra = len([r for r in res if r.get("status") == "confident"]) - len({r.get("name") for r in res if r.get("status") == "confident"})
    if wrong:
        problems.append(f"{len(wrong)} piece(s) filed under a name not on the wall")
    if extra > 0:
        problems.append(f"{extra} duplicate filing(s)")
    info = {}
    if leads:
        info["pixels"] = f"upright by {min(leads)[0]:.2f} or more"
    if read:
        agree = [n for n, s in read if s == "upright"]
        info["reader"] = f"read {len(agree)} of {len(read)} labels upright"
        if len(agree) < len(read):
            info["reader"] += " (" + "; ".join(f"{n}: {s}" for n, s in read if s != "upright") + ")"
    return right, problems, info


def run_case(c, work):
    names = NAMES[:c["n"]]
    rows, cols = GRID[c["n"]]
    wall = WALLS[c["kw"].get("bg", "black")]
    kw = dict(c["kw"])
    on_wall = names
    if kw.pop("sign", False):       # the last paper is the title sign, not a child's
        names, on_wall = names[:-1], names[:-1] + [SIGN]
    try:
        img, truth = contract_wall(on_wall, rows, cols, **kw)
        truth = [t for t in truth if t["name"] != SIGN]
    except FontNotFound as e:
        return {"case": c["case"], "pieces": len(names), "right": 0, "problems": [], "skipped": str(e)}
    if c["side"]:
        img = from_the_side(img, c["side"][1], c["side"][0], wall)
    if c["turn"]:
        img = img.rotate(c["turn"], expand=True)
    if c["exif"]:
        # pixels are upright; the tag claims otherwise, as a tilted phone does
        pass
    out = os.path.join(work, "out"); os.makedirs(out, exist_ok=True)
    photo = os.path.join(work, "wall." + c["fmt"])
    if c["fmt"] == "heic":
        ok, how = write_heic(img, photo)
        if not ok:
            return {"case": c["case"], "pieces": len(names), "right": 0, "problems": [], "skipped": how}
    elif not save(img, photo, c["fmt"], c["exif"]):
        return {"case": c["case"], "pieces": len(names), "right": 0, "problems": [],
                "skipped": "the practice photo could not be written"}
    log = []
    res = sw.process_photo(photo, names, out, "Contract", log=log.append, grade="K")
    right, problems, info = score_wall(res, truth, names, out, wall)
    if len(on_wall) > len(names) and len(res) != len(names):
        problems.append(f"the title sign was not left out: {len(res)} pieces came back for {len(names)} children")
    said = [str(line) for line in log]
    said += [f"  piece {r.get('piece')}: filed as {r.get('name')}, {r.get('status')}, turned {r.get('turned')}, "
             f"score {r.get('score')}, read {r.get('text')!r}" for r in res]
    return {"case": c["case"], "pieces": len(names), "right": right, "problems": problems, "found": len(res),
            "info": info, "said": said}


def is_skipped(r):
    return bool(r.get("skipped"))


def is_perfect(r):
    return not is_skipped(r) and r["right"] == r["pieces"] and not r["problems"]


def about_this_computer():
    """The lines at the top of the record: enough to know, from the record
    alone, which computer and which reader gave the score."""
    lines = [f"computer: {platform.platform()}, Python {platform.python_version()}, "
             f"Pillow {Image.__version__}, numpy {np.__version__}",
             f"reader: {sw.backend_name()}"]
    for font in sorted(FONTS):
        try:
            lines.append(f"font {font}: {font_file(font)}")
        except FontNotFound as e:
            lines.append(f"font {font}: NOT HERE. {e}")
    lines.append(f"the HEIC wall is written by: {heic_writer() or 'nothing here can write one, so that wall is skipped'}")
    lines.append(f"which way up a piece is: decided by its pixels ({SMALL} x {SMALL} black-and-white, upright must lead by {CLEAR}); "
                 "what the reader says is information")
    return lines


def main(argv):
    if not sw.backend_ready():
        say("The reader is not available on this computer."); return 2
    want = [a for a in argv if not a.startswith("-")]
    todo = [c for c in cases() if not want or any(w in c["case"] for w in want)]
    for line in about_this_computer():
        say(line)
    say()
    t0 = time.time(); rows = []
    for c in todo:
        work = tempfile.mkdtemp(prefix="contract-")
        t1 = time.time()
        try:
            r = run_case(c, work)
        except Exception as e:
            r = {"case": c["case"], "pieces": c["n"], "right": 0, "problems": [f"crashed: {type(e).__name__}: {e}"]}
        finally:
            shutil.rmtree(work, ignore_errors=True)
        rows.append(r)
        info = "; ".join(f"{k}: {v}" for k, v in sorted(r.get("info", {}).items()))
        if is_skipped(r):
            say(f"SKIP  {r['case']:<34}  -/{r['pieces']:<2}  not run: {r['skipped']}")
            continue
        mark = "PASS" if is_perfect(r) else "MISS"
        say(f"{mark}  {r['case']:<34} {r['right']:>2}/{r['pieces']:<2}  " + ("; ".join(r["problems"])[:150])
            + ("  " if r["problems"] and info else "") + (f"[{info}; {time.time() - t1:.0f} s]" if info else ""))
        if mark == "MISS":         # everything known about a miss goes in the record
            for p in r["problems"]:
                say(f"        problem: {p}")
            for line in r.get("said", []):
                say(f"        the tool said: {line}")
    ran = [r for r in rows if not is_skipped(r)]
    skipped = [r for r in rows if is_skipped(r)]
    pieces = sum(r["pieces"] for r in ran); right = sum(r["right"] for r in ran)
    passed = sum(1 for r in ran if is_perfect(r))
    left_out = ""
    if skipped:
        left_out = (f", {len(skipped)} wall{'s' if len(skipped) != 1 else ''} SKIPPED "
                    f"({', '.join(r['case'] for r in skipped)}: could not be written on this computer)")
    say(f"\nCONTRACT CHECK: {passed} of {len(ran)} walls perfect, {right} of {pieces} pieces right "
        f"({100.0 * right / max(1, pieces):.1f}%){left_out}, {time.time() - t0:.0f} seconds")
    if "--json" in argv:
        say(json.dumps(rows))
    return 0 if ran and passed == len(ran) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

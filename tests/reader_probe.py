"""What does this computer's reader read? A record, not a test.

Nobody who works on Baggage Claim can run a Windows PC. The only Windows
bench is the GitHub build, so the build runs this script and keeps what it
prints (reader-probe-on-build-machine.txt, inside the bundle). It draws typed
name labels, hands them to the reader the same way the program does
(run_vision), and prints one line for each: what was asked, what was read,
the box, the angle, the seconds it took. It asserts nothing and it never
stops the build: a case that goes wrong prints what went wrong and the next
case runs.

The cases:
  alone    one label on a small picture, letters 20 to 120 pixels high, in
           each typed face this computer has, upright and turned 90, 180
           and 270 degrees
  wall     six papers on a dark 4032 by 3024 wall, one label each, letters
           20 to 120 pixels high, the whole wall upright and turned
  tilted   one label hung five degrees off level
  row      the practice wall the tests use, typed and hand-printed
  paper    four papers with one-word names on a wall, all the right way up
           and then one hung upside down, sorted by the program itself:
           every line the program logged, and for each piece the turn it
           was given beside the right one
  beside   a one-word name with a typed word beside it on the same line,
           the name upright and upside down

On Windows each 'alone' case also prints what the reader gave for ONE plain
look at the picture (no turning, no sizes, no margin), and, look by look,
what each turn and size read and what the reader said about the turn. Those
lines settle what could only be reasoned about on September 28, 2026: does
the Windows reader read text that is upside down, does it say so, which
letter heights does it read, and where are its boxes.

'paper' and 'beside' are about a name of one word. Two words read upside
down run right to left and give themselves away; one word cannot. So the
program looks at a paper turned over as well as the way it is, and when the
reader reads the name both ways and calls both upright, the program files
the piece the first way the name read and says so in the log. 'paper' shows
which of those happens on this computer. 'beside' shows whether a typed word
put beside the name would let the order of the words say which way the name
faces: nothing in the program relies on that yet.

Invented names only, the ones the tests already use.

Run:  python3 tests/reader_probe.py
"""
import os
import shutil
import sys
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import baggage_claim as bc  # noqa: E402
import vision_windows as vw  # noqa: E402
import make_wall as mw  # noqa: E402

MAC = "/System/Library/Fonts/Supplemental"
WIN = os.path.join(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or "C:\\Windows", "Fonts")
FACES = [
    ("Arial", [os.path.join(MAC, "Arial.ttf"), os.path.join(WIN, "arial.ttf")]),
    ("Arial Bold", [os.path.join(MAC, "Arial Bold.ttf"), os.path.join(WIN, "arialbd.ttf")]),
    ("Times New Roman", [os.path.join(MAC, "Times New Roman.ttf"), os.path.join(WIN, "times.ttf")]),
    ("Verdana", [os.path.join(MAC, "Verdana.ttf"), os.path.join(WIN, "verdana.ttf")]),
    ("Calibri", [os.path.join(WIN, "calibri.ttf")]),
    ("hand-printed (not typed)", [os.path.join(MAC, "Bradley Hand Bold.ttf"), os.path.join(WIN, "comic.ttf")]),
]
HEIGHTS = [20, 30, 40, 60, 80, 120]          # the height of a capital letter, in pixels
TURNS = [0, 90, 180, 270]                    # how the picture is turned (counter-clockwise) before it is read
ALONE_NAMES = ["Maya Torres", "Theo"]        # two words, and one short word
WALL_NAMES = ["Maya Torres", "Jonah Reyes", "Sofia Lund", "Elijah Park", "Priya", "Marcus"]
ROW_NAMES = ["Maya", "Jonah", "Sofia", "Elijah"]
BESIDE = "Baggage"                           # the typed word put beside a name: not a name
INK, PAPER, DARK_WALL = (20, 20, 40), (255, 255, 255), (24, 24, 26)


def say(*parts):
    print(*parts, flush=True)


def shown(text):
    """Text exactly as read, with every unusual letter spelled out, so the
    record says the same thing on every console."""
    return "'" + (text or "").encode("unicode_escape").decode("ascii") + "'"


def faces_here():
    return [(name, next(p for p in places if os.path.exists(p)))
            for name, places in FACES if any(os.path.exists(p) for p in places)]


def font_of_height(path, height):
    """The font whose capital letters are `height` pixels high."""
    trial = ImageFont.truetype(path, 200)
    box = trial.getbbox("M")
    return ImageFont.truetype(path, max(4, round(200 * height / max(1, box[3] - box[1]))))


def label(name, font, height):
    """A white label with the name typed on it, a letter's height of margin all round."""
    box = font.getbbox(name)
    w, h = box[2] - box[0], box[3] - box[1]
    im = Image.new("RGB", (w + 2 * height, h + 2 * height), PAPER)
    ImageDraw.Draw(im).text((height - box[0], height - box[1]), name, fill=INK, font=font)
    return im, (height, height, w, h)


def turned_box(box, turn, width, height):
    """Where a box of the upright picture is once the picture is turned."""
    x, y, w, h = box
    if turn == 90:
        return (y, width - x - w, h, w)
    if turn == 180:
        return (width - x - w, height - y - h, w, h)
    if turn == 270:
        return (height - y - h, x, h, w)
    return box


def near(t, box):
    cx, cy = t["x"] + t["w"] / 2, t["y"] + t["h"] / 2
    x, y, w, h = box
    slack = max(w, h) * 0.25
    return x - slack <= cx <= x + w + slack and y - slack <= cy <= y + h + slack


def same(read, asked):
    return bc.norm(read or "") == bc.norm(asked)


def best_line(lines, asked, box):
    """The line read where the label is: the one that is the name if there is one."""
    here = [t for t in lines if near(t, box)]
    right = [t for t in here if same(t["text"], asked)]
    return (right or here or [None])[0], len(here)


def look_by_look(asked):
    """Windows only: what each turn and size read, and what the reader said about the turn."""
    for n in vw.LAST_READS:
        if n["lines"]:
            mark = "NAME" if any(same(t, asked) for t in n["lines"]) else "    "
            say(f"           {mark} turned {n['turn']:3d}  size {n['scale']:<4}  reader said turn {n['text_angle']}"
                f"  {n['seconds']}s  read {', '.join(shown(t) for t in n['lines'])}")


def plain_look(path):
    """Windows only: ONE look at the file as it is."""
    try:
        started = time.time()
        lines, said = vw.read_plain(path)
        took = time.time() - started
        if not lines:
            say(f"           plain look: nothing read; reader said turn {said}; {took:.2f}s")
        for text, words in lines:
            boxes = " ".join(f"{shown(w)}@({x:.0f},{y:.0f},{ww:.0f},{h:.0f})" for w, x, y, ww, h in words)
            say(f"           plain look: read {shown(text)}; reader said turn {said}; words {boxes}; {took:.2f}s")
    except Exception as e:      # a record, not a test
        say(f"           plain look: stopped: {type(e).__name__}: {e}")


def read(path):
    """The picture through the reader, the way the program asks: (lines, seconds)."""
    started = time.time()
    lines = bc.run_vision("text", path)
    return lines, time.time() - started


def one_case(kind, face, height, turn, asked, path, box, tally, already=None):
    """already: (lines, seconds) when one picture holds several labels and has been read."""
    want = (360 - turn) % 360
    try:
        lines, took = already or read(path)
        t, count = best_line(lines, asked, box)
        if t is None:
            verdict, got = "NOT READ", f"read nothing there ({len(lines)} lines elsewhere)"
        else:
            right = same(t["text"], asked) and t.get("angle") == want
            verdict = "ok" if right else ("WRONG TURN" if same(t["text"], asked) else "MISREAD")
            got = (f"read {shown(t['text'])}  box ({t['x']},{t['y']},{t['w']},{t['h']})  "
                   f"angle {t.get('angle')}  ({count} lines there, {len(lines)} in all)")
        tally.setdefault((kind, face, height), []).append(verdict == "ok")
        say(f"{kind:6s} {face:24s} {height:3d}px  turned {turn:3d}  asked {shown(asked):14s} {got}  "
            f"label at {tuple(int(v) for v in box)}  right angle {want}  {took:.2f}s  {verdict}")
    except Exception as e:      # a record, not a test
        tally.setdefault((kind, face, height), []).append(False)
        say(f"{kind:6s} {face:24s} {height:3d}px  turned {turn:3d}  asked {shown(asked):14s} "
            f"stopped: {type(e).__name__}: {e}")


def alone(faces, work, tally):
    say("\n== alone: one label on a small picture ==")
    for face, file in faces:
        for height in HEIGHTS:
            font = font_of_height(file, height)
            for asked in ALONE_NAMES:
                im, box = label(asked, font, height)
                for turn in TURNS:
                    path = os.path.join(work, "alone.png")
                    pic = im.rotate(turn, expand=True) if turn else im
                    pic.save(path)
                    one_case("alone", face, height, turn, asked, path, turned_box(box, turn, *im.size), tally)
                    if bc.IS_WIN:
                        look_by_look(asked)
                        plain_look(path)


def wall(faces, work, tally):
    say("\n== wall: six papers on a dark 4032 by 3024 wall, the name typed in the corner of each ==")
    for face, file in faces[:2]:
        img = Image.new("RGB", (4032, 3024), DARK_WALL)
        d = ImageDraw.Draw(img)
        labels = []
        for k, (asked, height) in enumerate(zip(WALL_NAMES, HEIGHTS)):
            x0, y0 = 172 + (k % 3) * 1300, 180 + (k // 3) * 1450
            d.rectangle((x0, y0, x0 + 1100, y0 + 1250), fill=PAPER)
            font = font_of_height(file, height)
            box = font.getbbox(asked)
            at = (x0 + 60, y0 + 60)
            d.text((at[0] - box[0], at[1] - box[1]), asked, fill=INK, font=font)
            labels.append((asked, height, (at[0], at[1], box[2] - box[0], box[3] - box[1])))
        for turn in TURNS:
            path = os.path.join(work, "wall.jpg")
            (img.rotate(turn, expand=True) if turn else img).save(path, quality=90)
            try:
                already = read(path)        # the whole wall once; its seconds are on each of its six lines
            except Exception as e:          # a record, not a test
                say(f"wall   {face:24s} turned {turn:3d}  stopped: {type(e).__name__}: {e}")
                continue
            for asked, height, box in labels:
                one_case("wall", face, height, turn, asked, path, turned_box(box, turn, 4032, 3024), tally, already)
            if bc.IS_WIN:
                for n in vw.LAST_READS:
                    say(f"           turned {n['turn']:3d}  size {n['scale']:<4}  tile {n['tile']}  "
                        f"{n['size'][0]}x{n['size'][1]}  reader said turn {n['text_angle']}  {n['seconds']}s  "
                        f"read {', '.join(shown(t) for t in n['lines']) or 'nothing'}")


def tilted(faces, work, tally):
    say("\n== tilted: one label five degrees off level, on a small picture ==")
    face, file = faces[0]
    for height in (30, 60):
        asked = "Maya Torres"
        im, box = label(asked, font_of_height(file, height), height)
        big = Image.new("RGB", (im.width + 200, im.height + 200), PAPER)
        big.paste(im, (100, 100))
        for lean in (5, -5):
            path = os.path.join(work, "tilted.png")
            big.rotate(lean, fillcolor=PAPER).save(path)
            say(f"  leaning {lean} degrees (counter-clockwise is positive):")
            one_case("tilted", face, height, 0, asked, path, (100 + box[0], 100 + box[1], box[2], box[3]), tally)
            if bc.IS_WIN:
                look_by_look(asked)
                plain_look(path)


def row(work):
    say("\n== row: the practice wall the tests use (four papers in a row, 2400 by 700) ==")
    for hand in (False, True):
        try:
            img, truth = mw.make_wall(ROW_NAMES, rows=1, cols=4, size=(2400, 700), hand=hand)
            path = os.path.join(work, "row.jpg")
            img.save(path, quality=90)
            lines, took = read(path)
            face = "hand-printed" if hand else "typed"
            for want in truth:
                x0, y0, x1, y1 = want["box"]
                here = [t for t in lines if near(t, (x0, y0, x1 - x0, y1 - y0))]
                right = [t for t in here if same(t["text"], want["name"])]
                say(f"row    {face:12s} asked {shown(want['name']):10s} "
                    f"{'read it' if right else 'NOT READ'}; lines on this paper: "
                    f"{', '.join(shown(t['text']) + '@' + str(t.get('angle')) for t in here) or 'none'}")
            say(f"row    {face:12s} whole wall {took:.2f}s, {len(lines)} lines")
        except Exception as e:      # a record, not a test
            say(f"row    stopped: {type(e).__name__}: {e}")


def paper(work):
    say("\n== paper: four papers with one-word names, sorted by the program itself ==")
    for hung in (None, 1):
        kind = "all the right way up" if hung is None else "one hung upside down"
        try:
            img, truth = mw.make_wall(ROW_NAMES, rows=2, cols=2, size=(2000, 1600), colored=True, seed=5, tilt=False)
            if hung is not None:
                box = truth[hung]["box"]
                img.paste(img.crop(box).rotate(180), box[:2])
            out = os.path.join(work, "paper-" + kind.replace(" ", "-"))
            os.makedirs(out)
            path = os.path.join(out, "wall.jpg")
            img.save(path, quality=90)
            hangs = [t["name"] + (" (upside down)" if k == hung else "") for k, t in enumerate(truth)]
            say(f"paper  {kind}: {', '.join(hangs)}")
            started = time.time()
            res = bc.process_photo(path, ROW_NAMES, out, "Art", log=lambda line: say("           log:", line))
            took = time.time() - started
            for r in res:
                # each name is on one paper, so the name says which paper the piece is
                want = 180 if hung is not None and r["name"] == truth[hung]["name"] else 0
                verdict = ("NOT FILED" if r["status"] != "confident"
                           else "ok" if r["turned"] == want else "WRONG TURN")
                doubt = "  (the program said it could not tell which way up)" if r.get("way_up") else ""
                say(f"paper  {kind}: piece {r['piece']}  filed as {shown(r['name'])}  {r['status']}  "
                    f"turned {r['turned']}  right turn {want}  {verdict}{doubt}")
            filed = sorted(r["name"] for r in res if r["status"] == "confident")
            say(f"paper  {kind}: {len(res)} pieces, {len(filed)} filed, "
                f"{'every child once' if filed == sorted(ROW_NAMES) else 'NOT every child once'}, {took:.2f}s")
        except Exception as e:      # a record, not a test
            say(f"paper  {kind}: stopped: {type(e).__name__}: {e}")


def beside(faces, work):
    say("\n== beside: a one-word name with a typed word beside it on the same line ==")
    face, file = faces[0]
    for height in (40, 80):
        font = font_of_height(file, height)
        name, _ = label(ALONE_NAMES[-1], font, height)
        word, _ = label(BESIDE, font, height)
        for turn in (0, 180):
            try:
                pic = Image.new("RGB", (name.width + word.width - height, max(name.height, word.height)), PAPER)
                pic.paste(word, (name.width - height, 0))
                pic.paste(name.rotate(turn) if turn else name, (0, 0))
                path = os.path.join(work, "beside.png")
                pic.save(path)
                started = time.time()
                lines = bc.run_vision("text", path, bc.AS_IT_IS)
                took = time.time() - started
                read = ", ".join(f"{shown(t['text'])} angle {t.get('angle')} box ({t['x']},{t['y']},{t['w']},{t['h']})"
                                 for t in lines) or "nothing"
                say(f"beside {face:24s} {height:3d}px  name turned {turn:3d}  "
                    f"asked {shown(ALONE_NAMES[-1] + ' ' + BESIDE)}  one look read {read}  {took:.2f}s")
                if bc.IS_WIN:
                    look_by_look(ALONE_NAMES[-1])
                    plain_look(path)
            except Exception as e:      # a record, not a test
                say(f"beside {face:24s} {height:3d}px  name turned {turn:3d}  stopped: {type(e).__name__}: {e}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    say(f"reader probe: {sys.platform}, reader: {bc.backend_name()}, Python {sys.version.split()[0]}")
    if not bc.backend_ready():
        say("no reader on this computer, so there is nothing to record")
        return 0
    if bc.IS_WIN:
        say(f"longest side the reader takes: {vw.longest_side()}; every way up: {vw.TURNS}; "
            f"sizes for a 740 by 610 paper: {vw.scales_for(740, 610)}; margin: {vw.BORDER}")
    faces = faces_here()
    say("typed faces on this computer: " + ", ".join(f"{n} ({p})" for n, p in faces))
    if not faces:
        say("no typed face found, so there is nothing to draw")
        return 0
    work = tempfile.mkdtemp(prefix="baggage-claim-probe-")
    tally = {}
    started = time.time()
    try:
        for part in (alone, wall, tilted):
            try:
                part(faces, work, tally)
            except Exception as e:      # a record, not a test
                say(f"{part.__name__} stopped: {type(e).__name__}: {e}")
        row(work)
        paper(work)
        try:
            beside(faces, work)
        except Exception as e:      # a record, not a test
            say(f"beside stopped: {type(e).__name__}: {e}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    say("\n== in short: labels read right (the name, and the right turn), by face and letter height ==")
    for kind in ("alone", "wall", "tilted"):
        for (k, face, height), oks in sorted(tally.items(), key=lambda kv: (kv[0][1], kv[0][2])):
            if k == kind:
                say(f"{kind:6s} {face:24s} {height:3d}px  {sum(oks)} of {len(oks)}")
    say(f"\nreader probe done in {time.time() - started:.0f} seconds")
    return 0


if __name__ == "__main__":
    sys.exit(main())

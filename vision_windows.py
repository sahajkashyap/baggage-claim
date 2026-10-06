"""
On-device text reading for Windows, using the reader built into Windows 10
and 11 (Windows.Media.Ocr). Same contract as the Mac helper `vision.swift`:

    read_text(path)  -> [{"text", "conf", "x", "y", "w", "h", "angle"}]
    read_rects(path) -> []   (Windows has no built-in paper detector; the
                             colour and texture detectors carry that job)

Every box is in pixels, origin top-left, in the frame of the picture as a
person sees it: the picture in the file, turned the way its own orientation
tag says. The Mac reader and open_photo use that frame too.

"angle" is the quarter turn (0, 90, 180, 270, counter-clockwise as PIL's
rotate() counts) that makes THAT LINE read upright, the same field the Mac
reader gives. Each line carries its own.

How a picture is read, and why. The build of September 28, 2026 was the
first time any of this ran on a real Windows reader. What that build's
record PROVES is marked so; the rest is the likeliest reading of it, and the
next build's reader probe (tests/reader_probe.py) settles it.

1. Every way up. The picture is read as it is and turned 90, 270 and 180
   degrees, always. Before, it was turned only when the first read found
   fewer than eight letters, and the turn with the most letters won. PROVED:
   a wall photographed upside down was not turned at all (its first read
   found letters enough), and the pieces of a wall on its side were filed
   turned 90 degrees where 270 was right. Counting letters cannot tell a
   name from nonsense, nor upright from upside down. So nothing is chosen
   here: every line from every turn is handed back with the turn it was
   read at, and the program decides from the line that IS a child's name,
   as it does on a Mac.
2. The reader's own word. The Windows reader says how far the text it read
   is turned (text_angle, degrees clockwise), and Microsoft's own example
   treats its boxes as lying in the frame of the picture turned straight.
   Both are used: a line the reader read upside down is reported as upside
   down, where it really is. Two more signs are believed when the reader
   says nothing: words that run right to left, and a box that holds no ink
   while the same box in the picture turned over does (see place()).
3. Several sizes. PROVED: names 70 points high were not read on one paper
   in three, while names 40 points high in the same face were all read.
   The Windows reader is known to read letters about 40 pixels high best.
   So each picture is read at its own size, at a half and a quarter, and,
   when it is small, at double size.
4. Never shrunk to fit. The reader takes pictures up to 2600 pixels a side.
   A larger picture is read in overlapping tiles at full size. Shrinking a
   whole wall to fit makes a small label a few pixels high.
5. A margin. A plain border goes around the picture before it is read: a
   label in the corner of a paper sits a few pixels from the edge of the
   crop. PROVED: names the program had read while sorting were not read
   again on the filed crop.
6. The orientation tag. The picture is opened and turned the way its tag
   says before anything else. Before, the first read followed the tag and
   the turned reads did not.
7. Scratch pictures are written in the computer's own temporary folder,
   never beside the photo: the photo sits in a folder Google Drive copies
   to every other computer.

read_text(path, as_it_is=True) reads the picture one way only, as it is
(steps 2 to 6). The program asks for that when it reads one paper: it has
already turned the photo upright, and when no name reads for certain it
turns the paper and looks again itself. When a name does read for certain,
the program still looks at the paper turned over (baggage_claim.second_look):
one look cannot tell a name of one word read upright from the same name read
upside down, unless the reader says so, and whether it does is not yet known.

Needs the `winsdk` package:  pip install winsdk
Nothing here touches the network.
"""
import asyncio
import math
import os
import re
import shutil
import sys
import tempfile
import time

_ENGINE = None

TURNS = (0, 90, 270, 180)      # a sideways phone is far more common than an upside-down one
AS_IT_IS = "as-is"             # the word run_vision passes on for a read that is not turned
LIMIT = 2600                   # the longest side the Windows reader takes, if it does not say so itself
SHY_OF_LIMIT = 20              # pictures are kept this much smaller than the longest side, to be sure
BORDER = 40                    # pixels of plain margin put around a picture before it is read
SMALLER = (0.5, 0.25)          # a picture is also read at these sizes: large letters read best smaller
LARGER = 2.0                   # and a small picture at this size: small letters read best larger
SHORTEST_SHRUNK = (200, 24)    # a shrunken picture is read only if its sides are at least this long
OVERLAP = 400                  # pixels shared by two tiles side by side, so a label on the seam is whole in one
BLANK = 6.0                    # less spread of light and dark than this inside a box: nothing is written there
SAME_SPOT = 0.3                # two boxes that share this much of their joint area are the same ink
CLEAR_MARGIN = 1.5             # how much stronger an upright line must be to call a turned one its shadow
LAST_READS = []                # one note per picture handed to the reader in the last read_text (for the probe)


def text_strength(lines):
    """How much real text a read found: letters in words of two letters or
    more. Garbage from a sideways picture is short and broken."""
    total = 0
    for t in lines:
        for word in re.findall(r"[A-Za-z]{2,}", t.get("text", "")):
            total += len(word)
    return total


def scales_for(width, height, room=LIMIT - 2 * BORDER):
    """The sizes one picture is read at. Its own size first. Smaller, while
    the shrunken picture is still a picture. Double, when the doubled picture
    still fits the reader in one piece (a small picture has small letters)."""
    scales = [1.0]
    for s in SMALLER:
        if max(width, height) * s >= SHORTEST_SHRUNK[0] and min(width, height) * s >= SHORTEST_SHRUNK[1]:
            scales.append(s)
    if max(width, height) * LARGER <= room:
        scales.append(LARGER)
    return scales


def tile_boxes(width, height, limit=LIMIT, overlap=OVERLAP):
    """The pieces a picture is read in: the whole picture when it fits the
    reader, else overlapping tiles of the reader's full size that cover it."""
    def starts(length):
        if length <= limit:
            return [0]
        return list(range(0, length - limit, limit - overlap)) + [length - limit]
    return [(x, y, min(width, x + limit), min(height, y + limit)) for y in starts(height) for x in starts(width)]


def edge_colour(im):
    """The colour most of the picture's edge has, for the margin around it,
    so that the margin adds no line of its own for the reader to trip on."""
    small = im.convert("RGB").resize((32, 32))
    px = small.load()
    edge = [px[x, y] for x in range(32) for y in range(32) if x in (0, 31) or y in (0, 31)]
    return tuple(sorted(c[i] for c in edge)[len(edge) // 2] for i in range(3))


def line_of(text, words):
    """One line as the reader gave it. words: (text, x, y, w, h) in reading
    order. The line's box is its words' boxes joined. 'backwards' says the
    first word sits to the right of the last: English reads left to right,
    so such a line was read upside down."""
    words = [w for w in words if w[3] > 0 and w[4] > 0]
    if not words or not (text or "").strip():
        return None
    x0 = min(w[1] for w in words)
    y0 = min(w[2] for w in words)
    x1 = max(w[1] + w[3] for w in words)
    y1 = max(w[2] + w[4] for w in words)
    first, last = words[0], words[-1]
    backwards = len(words) >= 2 and first[1] + first[3] / 2 > last[1] + last[3] / 2
    return {"text": text, "box": (x0, y0, x1 - x0, y1 - y0), "backwards": backwards}


def quarter(text_angle):
    """The reader's own word for how far the text is turned (degrees,
    clockwise), as the nearest quarter turn. No word, or a broken one, is 0."""
    try:
        return int(round(float(text_angle) / 90.0)) % 4 * 90
    except (TypeError, ValueError, OverflowError):
        return 0


def untilt(box, text_angle, width, height):
    """The reader gives its boxes in the frame of the picture turned
    straight: the picture turned about its own centre by text_angle. This
    puts a box back where it is in the picture that was handed over: its
    centre is turned clockwise by text_angle about the picture's centre; its
    size is kept, the sides swapped for a quarter turn."""
    try:
        a = math.radians(float(text_angle))
        cos, sin = math.cos(a), math.sin(a)
    except (TypeError, ValueError, OverflowError):
        return box
    if not (cos == cos and sin == sin) or text_angle == 0:      # not a number, or no turn
        return box
    x, y, w, h = box
    dx, dy = x + w / 2 - width / 2, y + h / 2 - height / 2
    cx, cy = width / 2 + dx * cos - dy * sin, height / 2 + dx * sin + dy * cos
    if quarter(text_angle) in (90, 270):
        w, h = h, w
    return (cx - w / 2, cy - h / 2, w, h)


def mirrored(box, width, height):
    """The same box in the picture turned upside down."""
    x, y, w, h = box
    return (width - x - w, height - y - h, w, h)


def ink(mono, box):
    """How much is written inside a box of a black-and-white picture: the spread of
    light and dark there. Plain paper and plain wall are near 0; letters are
    far above BLANK."""
    from PIL import ImageStat
    x, y, w, h = box
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(mono.width, int(x + w) + 1), min(mono.height, int(y + h) + 1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return 0.0
    return float(ImageStat.Stat(mono.crop((x0, y0, x1, y1))).stddev[0])


def place(line, text_angle, mono):
    """Where a line really is in the picture that was read, and which way it
    faces there: (box, turn), the turn counted as "angle" is. Three things
    can say a line was read upside down, and any one is believed:
    the reader's own word (text_angle); its words running right to left; its
    box holding nothing while the same box in the picture turned upside down
    holds ink (the reader read it turned and did not say so)."""
    box, turn = line["box"], quarter(text_angle)
    width, height = mono.size
    moved = untilt(box, text_angle, width, height)
    if moved != box and ink(mono, moved) * 2 < ink(mono, box):
        moved = box                 # this box was in the picture's own frame after all
    if turn:
        return moved, turn
    if line["backwards"]:
        return moved, 180
    other = mirrored(moved, width, height)
    if ink(mono, moved) < BLANK and ink(mono, other) >= 2 * BLANK:
        return other, 180
    return moved, 0


def overlap_share(a, b):
    """The share of their joint area that two lines' boxes have in common."""
    w = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    h = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    if w <= 0 or h <= 0:
        return 0.0
    both = w * h
    return both / max(1, a["w"] * a["h"] + b["w"] * b["h"] - both)


def letters(t):
    return re.sub(r"[^a-z]", "", t.get("text", "").lower())


def merge(lines):
    """Every line from every turn, size and tile, in one list. The same
    words read twice in the same place facing the same way are kept once.
    A turned line is dropped when an upright line in the same place is
    clearly stronger: it is that line's shadow, the nonsense the reader
    makes of good text seen the wrong way up. An upright line is never
    dropped, and nothing else is: the program chooses by the name."""
    kept = []
    for t in lines:
        if any(k["angle"] == t["angle"] and letters(k) == letters(t) and overlap_share(k, t) >= SAME_SPOT
               for k in kept):
            continue
        kept.append(t)
    upright = [t for t in kept if t["angle"] == 0]
    return [t for t in kept if not (
        t["angle"] and any(overlap_share(u, t) >= SAME_SPOT
                           and text_strength([u]) >= CLEAR_MARGIN * text_strength([t]) + 1 for u in upright))]


def box_back(box, angle, width, height):
    """A box (x, y, w, h) in the frame of the image turned `angle` degrees
    counter-clockwise, mapped back to the frame of the original image whose
    size is width x height."""
    x, y, w, h = box
    corners = [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]
    if angle == 90:      # original (x, y) -> (y, W - x)
        pts = [(width - cy, cx) for cx, cy in corners]
    elif angle == 180:   # original (x, y) -> (W - x, H - y)
        pts = [(width - cx, height - cy) for cx, cy in corners]
    elif angle == 270:   # original (x, y) -> (H - y, x)
        pts = [(cy, height - cx) for cx, cy in corners]
    else:
        return box
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys)))


def available():
    if sys.platform != "win32":
        return False
    try:
        import winsdk.windows.media.ocr  # noqa: F401
        return True
    except Exception:
        return False


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.globalization import Language
        eng = OcrEngine.try_create_from_language(Language("en-US"))
        if eng is None:
            eng = OcrEngine.try_create_from_user_profile_languages()
        if eng is None:
            raise RuntimeError("Windows OCR is not available: install the English language pack "
                               "(Settings > Time & Language > Language > Add a language > English)")
        _ENGINE = eng
    return _ENGINE


def longest_side():
    """The longest side the reader takes, by its own word."""
    try:
        from winsdk.windows.media.ocr import OcrEngine
        return int(OcrEngine.max_image_dimension) or LIMIT
    except Exception:
        return LIMIT


async def _recognize(path):
    from winsdk.windows.storage import StorageFile, FileAccessMode
    from winsdk.windows.graphics.imaging import BitmapDecoder

    eng = _engine()
    f = await StorageFile.get_file_from_path_async(os.path.abspath(path))
    stream = await f.open_async(FileAccessMode.READ)
    try:
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        result = await eng.recognize_async(bitmap)
        lines = []
        for line in result.lines:
            words = []
            for wd in line.words:
                r = wd.bounding_rect
                words.append((wd.text, r.x, r.y, r.width, r.height))
            lines.append((line.text, words))
        try:
            text_angle = result.text_angle
        except Exception:
            text_angle = None
    finally:
        try:                        # an open file cannot be deleted on Windows
            stream.close()
        except Exception:
            pass
    return lines, text_angle


def recognize(path):
    """One picture file, as it is, through the Windows reader. Returns
    (lines, text_angle): each line is (text, [(word, x, y, w, h), ...]) in
    the reader's own frame; text_angle is the reader's word for how far the
    text is turned, or None. The only place the reader is called."""
    return asyncio.run(_recognize(path))


def forget(path):
    try:
        os.remove(path)
    except OSError:
        pass                        # the scratch folder is taken away at the end anyway


def read_one_way(im, tmpdir, limit, turn=0, notes=None):
    """Read one picture (a PIL image) the way it is handed over: at each
    size, with a margin, in tiles when it is larger than the reader takes.
    Returns lines {"text", "conf", "x", "y", "w", "h", "angle"} with boxes in
    this picture's frame; "angle" is the turn that makes the line upright IN
    THIS PICTURE (0 unless the reader read it upside down or on its side)."""
    from PIL import Image, ImageOps
    out = []
    for scale in scales_for(im.width, im.height, limit - 2 * BORDER):
        sized = im if scale == 1.0 else im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))),
                                                  Image.LANCZOS)
        padded = ImageOps.expand(sized, border=BORDER, fill=edge_colour(sized))
        for n, (x0, y0, x1, y1) in enumerate(tile_boxes(padded.width, padded.height, limit), 1):
            tile = padded if (x0, y0, x1, y1) == (0, 0, padded.width, padded.height) else padded.crop((x0, y0, x1, y1))
            png = os.path.join(tmpdir, f"read-{turn}-{int(scale * 100)}-{n}.png")
            tile.save(png, compress_level=1)
            started = time.time()
            try:
                raw, text_angle = recognize(png)
            finally:
                forget(png)
            took = time.time() - started
            mono = tile.convert("L")
            texts = []
            for text, words in raw:
                line = line_of(text, words)
                if line is None:
                    continue
                (x, y, w, h), facing = place(line, text_angle, mono)
                # tile -> padded picture -> picture without its margin -> picture at its own size
                x, y = (x + x0 - BORDER) / scale, (y + y0 - BORDER) / scale
                w, h = w / scale, h / scale
                left, top = max(0, min(im.width, x)), max(0, min(im.height, y))
                right, bottom = max(0, min(im.width, x + w)), max(0, min(im.height, y + h))
                if right - left < 1 or bottom - top < 1:
                    continue        # read in the margin: not in the picture
                out.append({"text": text, "conf": 1.0, "x": int(left), "y": int(top),
                            "w": int(right - left), "h": int(bottom - top), "angle": facing})
                texts.append(text)
            if notes is not None:
                notes.append({"turn": turn, "scale": scale, "tile": n, "size": tile.size,
                              "text_angle": text_angle, "lines": texts, "seconds": round(took, 3)})
    return out


def read_text(path, as_it_is=False):
    """Every line of text in the picture, each with the turn that makes it
    read upright. The picture is read every way up (as it is, and turned 90,
    270 and 180 degrees), or one way only when as_it_is is asked for."""
    from PIL import Image, ImageOps
    with Image.open(path) as opened:
        im = ImageOps.exif_transpose(opened).convert("RGB")
    limit = longest_side() - SHY_OF_LIMIT
    notes, found = [], []
    tmpdir = tempfile.mkdtemp(prefix="baggage-claim-read-")
    try:
        for turn in (TURNS[:1] if as_it_is else TURNS):
            turned = im.rotate(turn, expand=True) if turn else im
            for t in read_one_way(turned, tmpdir, limit, turn, notes):
                x, y, w, h = box_back((t["x"], t["y"], t["w"], t["h"]), turn, im.width, im.height)
                found.append({**t, "x": x, "y": y, "w": w, "h": h, "angle": (turn + t["angle"]) % 360})
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        LAST_READS[:] = notes
    return merge(found)


def read_plain(path):
    """For the reader probe: ONE read of the file as it is, nothing turned,
    resized or added. Returns (lines, text_angle) as the reader gave them."""
    return recognize(path)


def run(mode, path, *extra):
    """What baggage_claim.run_vision asks of this computer's reader."""
    if mode != "text":
        return read_rects(path)
    return read_text(path, as_it_is=AS_IT_IS in extra)


def read_rects(path):
    return []


if __name__ == "__main__":
    import json
    mode, path = sys.argv[1], sys.argv[2]
    print(json.dumps(run(mode, path, *sys.argv[3:])))

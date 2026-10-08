#!/usr/bin/env python3
"""
Baggage Claim. Every piece of work returned to its owner.

Drop photos of the classroom wall into inbox/. Each piece of student work is
found, straightened, cropped, its teacher-written name read with Apple's
on-device text recognition, matched against roster.txt, and saved into
sorted/<Child>/. Anything the tool is not sure about goes to unsorted/ with its
best guess, plus a small strip showing only the name so a person (or Claude
Code, if you choose) can decide without ever seeing the artwork.
A title sign on the wall is left out when it carries a typed sticker that
reads TITLE.

Nothing leaves the laptop. There is no network code in this file.
"""
import argparse
import datetime as dt
import difflib
import errno
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from scipy import ndimage

# When bundled into a single Windows program, "here" is the folder the .exe
# sits in (where settings.local.json and logs live), not the temp unpack dir.
def _home_of_program():
    """The folder the user sees: next to the .exe on Windows, next to the .app
    on a Mac (not inside Contents/MacOS), or this file's folder when run from source."""
    if not getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(__file__))
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    if sys.platform == "darwin" and "/Contents/MacOS" in exe_dir:
        app_bundle = exe_dir.split("/Contents/MacOS")[0]      # .../<the program>.app
        return os.path.dirname(app_bundle)
    return exe_dir


HERE = _home_of_program()
# The Vision helper: built next to the source, or bundled inside the program.
def _find_vision():
    cands = []
    if getattr(sys, "_MEIPASS", None):                                   # bundled by PyInstaller
        cands.append(os.path.join(sys._MEIPASS, "vision"))
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "vision"))
    cands.append(os.path.join(HERE, "vision"))
    return next((c for c in cands if os.path.exists(c)), cands[-1])


VISION = _find_vision()
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff"}
PACKET_EXT = {".pdf"}                  # a PDF packet: many pages, one child's name typed on each (see "PDF packets")
INBOX_EXT = IMAGE_EXT | PACKET_EXT     # what the tool takes from Wall Inbox

CONFIDENT_SCORE = 0.80   # how close the read text must be to a roster name
CONFIDENT_MARGIN = 0.10  # how far ahead of the next-best child it must be
WEAK_SCORE = 0.55        # below this we say "no name read" rather than guess
EDGE_BAND = 0.22         # top/bottom share of the page where a teacher writes the name
EDGE_BONUS = 0.04        # a name at the edge beats the same name in the body
BODY_PENALTY = 0.25      # a name inside a child's own writing is probably a character in the story
BODY_LABEL_PENALTY = 0.12 # a roster name on its own short line in the middle of the paper is still
                         # the teacher's label (artwork); small enough that an exact read files,
                         # large enough that a shaky read still goes to a person and that the
                         # same name at the edge of a page of writing wins by a clear margin
LONG_LINE_PENALTY = 0.10 # a name pulled out of a sentence is weaker than a name on its own
# Everyday words that are close to a child's name in letters but never are one.
STOPWORDS = set("""the a an and or but if then than to of in on at by for with from as is was are
were be been am do did does has have had not no yes my me we us our you your he she it they them
his her its their this that these those there here what when who how why so up down out over
under into about all any some one two three four five six seven eight nine ten day days today
time year week best big little good bad new old went go get got like love very said say
title name date grade class room mrs mr ms miss school""".split())      # a name inside a child's own writing is probably a character in the story


# ----------------------------------------------------------------- vision ---

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"


def backend_ready():
    """Is an on-device reader available on this machine?"""
    if IS_MAC:
        return os.path.exists(VISION)
    if IS_WIN:
        import vision_windows
        return vision_windows.available()
    return False


def backend_name():
    if IS_MAC:
        return "Apple Vision (macOS, on device)"
    if IS_WIN:
        return "Windows.Media.Ocr (Windows, on device)"
    return "none"


AS_IT_IS = "as-is"       # asks the reader for one read of the picture the way it is handed over
ONE_LOOK = IS_WIN        # this computer's reader looks at a picture one way up at a time (see second_look)


def run_vision(mode, path, *extra):
    """Read text or find paper rectangles with the machine's own on-device
    reader. Mac: the compiled Swift helper. Windows: the built-in Windows
    reader (no rectangle detector; returns [] for rects). Returns a list of dicts.

    Each line of text carries text, conf, x, y, w, h in the frame of the
    picture as a person sees it, and "angle": the counter-clockwise quarter
    turn that makes that line read upright. Apple's reader reads every way up
    in one look. The Windows reader has to be handed the picture four times,
    once each way up. AS_IT_IS in `extra` asks for one look only, the picture
    as it is: four times quicker, and used for one paper cut from a photo
    that has already been turned upright. One look is never believed on its
    own there: the program turns the paper over and looks again (second_look).
    On a Mac the word changes nothing."""
    if IS_WIN:
        import vision_windows
        if not vision_windows.available():
            raise RuntimeError("Windows reader not available; run: pip install winsdk")
        if not os.path.exists(path):
            raise RuntimeError(f"vision {mode} failed: no such file {path}")
        return vision_windows.run(mode, path, *extra)
    if not IS_MAC:
        raise RuntimeError("Baggage Claim runs on macOS or Windows")
    if not os.path.exists(VISION):
        raise RuntimeError("vision helper not built; run: swiftc -O vision.swift -o vision")
    extra = [e for e in extra if e != AS_IT_IS]
    res = subprocess.run([VISION, mode, path, *extra], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"vision {mode} failed: {res.stderr.strip()}")
    # Vision sometimes logs chatter ("too few samples") on stdout; the JSON is the line that starts with [
    lines = [ln for ln in res.stdout.splitlines() if ln.startswith("[")]
    return json.loads(lines[-1] if lines else "[]")


# --------------------------------------------------------------- geometry ---

def quad_area(q):
    """Shoelace area of a quad given as dict with tl,tr,br,bl."""
    pts = [q["tl"], q["tr"], q["br"], q["bl"]]
    s = 0.0
    for i in range(4):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % 4]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def quad_bbox(q):
    xs = [p[0] for p in (q["tl"], q["tr"], q["br"], q["bl"])]
    ys = [p[1] for p in (q["tl"], q["tr"], q["br"], q["bl"])]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_overlap(a, b):
    """Fraction of box a that lies inside box b."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(1, (ax1 - ax0) * (ay1 - ay0))
    return inter / area_a


def dedupe_quads(quads, image_area):
    """Drop quads that are mostly inside a bigger one (the drawing inside the
    paper), quads that are basically the whole photo, and near-duplicates."""
    keep = []
    quads = sorted(quads, key=quad_area, reverse=True)
    for q in quads:
        a = quad_area(q)
        if a > 0.6 * image_area or a < 0.005 * image_area:
            continue
        box = quad_bbox(q)
        if any(bbox_overlap(box, quad_bbox(k)) > 0.6 for k in keep):
            continue
        keep.append(q)
    # left-to-right, top-to-bottom reading order (row by row)
    def key(q):
        x0, y0, x1, y1 = quad_bbox(q)
        return (round(y0 / max(1, (y1 - y0)) * 0.6), x0)
    return sorted(keep, key=key)


def fallback_boxes(img, min_frac=0.01):
    """Texture-based fallback when the rectangle detector finds nothing:
    artwork is busy, a wall is flat. Returns axis-aligned quads."""
    g = np.asarray(ImageOps.grayscale(img).resize((img.width // 4, img.height // 4)), dtype=float)
    sx = ndimage.sobel(g, axis=1)
    sy = ndimage.sobel(g, axis=0)
    mag = np.hypot(sx, sy)
    busy = mag > np.percentile(mag, 85)
    busy = ndimage.binary_closing(busy, iterations=6)
    busy = ndimage.binary_fill_holes(busy)
    busy = ndimage.binary_opening(busy, iterations=3)
    labels, n = ndimage.label(busy)
    quads = []
    total = g.size
    for i in range(1, n + 1):
        ys, xs = np.where(labels == i)
        if xs.size < min_frac * total:
            continue
        x0, x1, y0, y1 = xs.min() * 4, xs.max() * 4, ys.min() * 4, ys.max() * 4
        quads.append({"conf": 0.3, "tl": [x0, y0], "tr": [x1, y0], "br": [x1, y1], "bl": [x0, y1]})
    return quads


def color_boxes(img, sat_min=0.18, min_frac=0.004):
    """Find sheets of paper by colour, either way round.

    Usual case: coloured construction paper on a pale wall. The saturated
    pixels are the papers. Other case: white or pale paper on a coloured
    wall (a bulletin board covered in blue paper). Then most of the frame is
    saturated and the papers are the pale, bright islands in it. The frame
    decides which case it is. Each box carries `fill`, how much of its own
    rectangle the blob covers: a sheet fills its box, a drawing does not."""
    small = img.resize((max(1, img.width // 8), max(1, img.height // 8)))
    a = np.asarray(small, dtype=float) / 255.0
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    saturated = (sat > sat_min) & (mx > 0.15)
    # Which is the wall? Look at the rim of the photo: papers sit in the
    # middle, the wall shows around the edge. (Counting the whole frame fails
    # when eight papers cover half of it.)
    h, w = saturated.shape
    ry, rx = max(1, h // 25), max(1, w // 25)
    rim = np.concatenate([saturated[:ry].ravel(), saturated[-ry:].ravel(),
                          saturated[:, :rx].ravel(), saturated[:, -rx:].ravel()])
    if rim.mean() > 0.5:
        # coloured wall: papers are the pale bright regions
        mask = (sat < 0.16) & (mx > 0.5)
        split = False
    else:
        mask = saturated
        split = True
    mask = ndimage.binary_closing(mask, iterations=3)
    mask = ndimage.binary_fill_holes(mask)
    mask = ndimage.binary_opening(mask, iterations=2)
    hue = rgb_hue(a)
    labels, n = ndimage.label(mask)
    out = []
    for i in range(1, n + 1):
        blob = labels == i
        if blob.sum() < min_frac * mask.size:
            continue
        ys, xs = np.where(blob)
        parts = split_by_hue(blob, hue) if split else [(xs.min(), ys.min(), xs.max(), ys.max())]
        for x0, y0, x1, y1 in parts:
            pad = 1
            X0, X1 = max(0, x0 - pad) * 8, min(small.width - 1, x1 + pad) * 8
            Y0, Y1 = max(0, y0 - pad) * 8, min(small.height - 1, y1 + pad) * 8
            part = blob[y0:y1 + 1, x0:x1 + 1]
            out.append({"conf": 0.5, "fill": float(part.mean()),
                        "tl": [int(X0), int(Y0)], "tr": [int(X1), int(Y0)],
                        "br": [int(X1), int(Y1)], "bl": [int(X0), int(Y1)]})
    return out


def rgb_hue(a):
    """Hue in degrees for an HxWx3 float array in 0..1."""
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(axis=2), a.min(axis=2)
    d = np.where(mx - mn == 0, 1e-6, mx - mn)
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4))
    return (h * 60.0) % 360.0


def _circ_mean_deg(h):
    if h.size == 0:
        return None
    rad = np.deg2rad(h)
    return float(np.rad2deg(np.arctan2(np.sin(rad).mean(), np.cos(rad).mean())) % 360.0)


def _hue_gap(a, b):
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _margin_hue(row_mask, row_hue, frac=0.15):
    """Hue of a row measured only at its outer edges: the paper's own margin,
    where a child has not painted. The face and the yarn hair sit in the
    middle and would otherwise pull the colour of a blue sheet toward brown."""
    idx = np.where(row_mask)[0]
    if idx.size < 4:
        return None
    k = max(1, int(idx.size * frac))
    edge = np.concatenate([idx[:k], idx[-k:]])
    return _circ_mean_deg(row_hue[edge])


def split_by_hue(blob, hue, aspect_trigger=1.55, min_part=0.3, min_gap=50.0, depth=0):
    """Two touching papers of different colours become one blob. If the blob
    is much taller or wider than a sheet of paper, look for the line where
    the dominant hue changes and split there. Returns a list of boxes."""
    ys, xs = np.where(blob)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    h, w = y1 - y0 + 1, x1 - x0 + 1
    box = [(x0, y0, x1, y1)]
    if depth > 2:
        return box
    tall, wide = h / w > aspect_trigger, w / h > aspect_trigger
    if not (tall or wide):
        return box
    axis_len = h if tall else w
    means = []
    for k in range(axis_len):
        sl = blob[y0 + k, x0:x1 + 1] if tall else blob[y0:y1 + 1, x0 + k]
        hv = hue[y0 + k, x0:x1 + 1] if tall else hue[y0:y1 + 1, x0 + k]
        means.append(_margin_hue(sl, hv))
    best, best_gap = None, 0.0
    lo, hi = int(axis_len * min_part), int(axis_len * (1 - min_part))
    for cut in range(lo, hi):
        top = [m for m in means[:cut] if m is not None]
        bot = [m for m in means[cut:] if m is not None]
        if not top or not bot:
            continue
        gap = _hue_gap(_circ_mean_deg(np.array(top)), _circ_mean_deg(np.array(bot)))
        if gap > best_gap:
            best, best_gap = cut, gap
    if best is None or best_gap < min_gap:
        return box
    if tall:
        parts = [blob.copy(), blob.copy()]
        parts[0][y0 + best:, :] = False
        parts[1][:y0 + best, :] = False
    else:
        parts = [blob.copy(), blob.copy()]
        parts[0][:, x0 + best:] = False
        parts[1][:, :x0 + best] = False
    out = []
    for part in parts:
        if part.sum() > 0:
            out += split_by_hue(part, hue, aspect_trigger, min_part, min_gap, depth + 1)
    return out


def edge_energy(img, q):
    """How busy a region is. A blank patch of wall scores near zero."""
    x0, y0, x1, y1 = quad_bbox(q)
    crop = img.crop((max(0, x0), max(0, y0), min(img.width, x1), min(img.height, y1)))
    if crop.width < 8 or crop.height < 8:
        return 0.0
    g = np.asarray(ImageOps.grayscale(crop).resize((crop.width // 4 or 1, crop.height // 4 or 1)), dtype=float)
    return float(np.hypot(ndimage.sobel(g, axis=1), ndimage.sobel(g, axis=0)).mean())


def drop_junk(img, quads, min_area_frac=0.35, min_energy_frac=0.25):
    """Throw out pieces far smaller than the typical piece (alphabet cards,
    slivers) and pieces with nothing on them (a patch of wall)."""
    if len(quads) < 3:
        return quads
    areas = sorted(quad_area(q) for q in quads)
    med_area = areas[len(areas) // 2]
    kept = [q for q in quads if quad_area(q) >= min_area_frac * med_area]
    energies = {id(q): edge_energy(img, q) for q in kept}
    med_e = sorted(energies.values())[len(energies) // 2] if energies else 0
    return [q for q in kept if energies[id(q)] >= min_energy_frac * med_e]


def mutual_overlap(a, b):
    return min(bbox_overlap(a, b), bbox_overlap(b, a))


LAST_DETECTOR = None


def detect_pieces(img, path, allow_colour=True):
    """Two detectors, reconciled. Apple's rectangle detector gives straight,
    perspective-corrected quads but sometimes skips a paper or catches only
    part of one. The texture detector never skips a busy paper but only gives
    a rough box. Rules: a texture box nobody found becomes a piece; a
    rectangle that is a small part of a texture box (and the only one in it)
    is replaced by that box."""
    area = img.width * img.height
    rects = dedupe_quads(run_vision("rects", path), area)
    tex = dedupe_quads(fallback_boxes(img), area)
    colors = dedupe_quads(color_boxes(img), area)
    # Trust the colour blobs only when a second detector agrees with most
    # of them. Coloured drawings on pale paper make blobs too, but no
    # rectangle (or busy-texture box) matches a scribble the way it matches
    # a sheet. On Windows there is no rectangle detector, so the texture
    # boxes are the second opinion.
    second = rects if rects else tex
    if rects:
        agree = sum(1 for cb in colors if any(mutual_overlap(quad_bbox(r), quad_bbox(cb)) > 0.6 for r in rects))
    else:
        # No rectangle detector (Windows). The texture detector cannot be the
        # judge here: a drawing is busy too, so it agrees with drawings.
        # Judge the colour blobs by shape instead: a sheet of paper fills
        # its own box; a coloured drawing on pale paper does not. Decide for
        # the set by the median, so one paper with a face cut-out biting its
        # edge is not thrown out alone.
        fills = sorted(cb.get("fill", 1.0) for cb in colors)
        agree = len(colors) if colors and fills[len(fills) // 2] >= 0.8 else 0
    # The colour blobs must also account for most of the sheets the rectangle
    # detector saw. White paper on a wall that is blue below and cream above
    # gave 5 blobs against 22 rectangles, the 5 agreed, and 15 children got
    # nothing. Found on a real wall, October 1, 2026.
    by_colour = (allow_colour and len(colors) >= 2 and agree >= max(2, 0.5 * len(colors))
                 and not (rects and len(colors) < 0.6 * len(rects)))
    global LAST_DETECTOR
    LAST_DETECTOR = "colour" if by_colour else ("rectangles" if rects else "texture")
    if by_colour:
        # coloured paper on a pale wall: the colour blobs are the pieces.
        # Use a straight rectangle where one matches a blob, else the blob.
        out = []
        for cb in colors:
            cbb = quad_bbox(cb)
            match = [r for r in second if mutual_overlap(quad_bbox(r), cbb) > 0.6]
            if not match:
                # the blob may be a drawing sitting inside a sheet the
                # second detector did find: take that sheet instead
                match = [r for r in second if bbox_overlap(cbb, quad_bbox(r)) > 0.9
                         and quad_area(r) < 2.5 * quad_area(cb)]
            out.append(max(match, key=quad_area) if match else cb)
        return drop_junk(img, dedupe_quads(out, area))
    if not rects:
        return drop_junk(img, tex)
    out = []
    used = set()
    for q in rects:
        qb = quad_bbox(q)
        parent = None
        for j, tq in enumerate(tex):
            tb = quad_bbox(tq)
            if bbox_overlap(qb, tb) > 0.8:
                inside = [r for r in rects if bbox_overlap(quad_bbox(r), tb) > 0.8]
                if len(inside) == 1 and quad_area(q) < 0.6 * quad_area(tq):
                    parent = j
                break
        if parent is not None:
            out.append(tex[parent])
            used.add(parent)
        else:
            out.append(q)
    for j, tq in enumerate(tex):
        if j in used:
            continue
        tb = quad_bbox(tq)
        if not any(bbox_overlap(tb, quad_bbox(o)) > 0.3 or bbox_overlap(quad_bbox(o), tb) > 0.3 for o in out):
            out.append(tq)
    return drop_junk(img, dedupe_quads(out, area))


def join_rows(lines):
    """The reader of a PC can split one line of writing into pieces, so that
    the friend's name at the end of "with my friend Theo." comes back as a
    line of its own, and looks exactly like a name label on the wrong paper.
    Lines that sit on the same row, facing the same way, and nearly touch are
    joined back into one line before any name is looked for. Apple's reader
    already returns them as one line, so on a Mac this changes nothing.
    Found on the Windows build of September 28, 2026."""
    rows = sorted((dict(t) for t in lines), key=lambda t: (t.get("angle", 0), t["y"], t["x"]))
    # A photo read in overlapping tiles can return, beside a whole line, a
    # piece of it that a tile edge cut off ("Theo" inside "waves came and Theo
    # laughed"). A line lying mostly inside a longer line on the same row,
    # facing the same way, is that fragment, not a label: it is dropped.
    # Found on the Windows build of September 29, 2026, where such a fragment
    # made one page look like it had two children's labels and cut it in two.
    def inside(small, big):
        if small is big or small.get("angle", 0) != big.get("angle", 0):
            return False
        if len(small.get("text") or "") >= len(big.get("text") or "") or not big.get("text"):
            return False
        if norm(small.get("text") or "") not in norm(big["text"]):
            return False                 # a fragment repeats words of the line it came from
        ix = min(small["x"] + small["w"], big["x"] + big["w"]) - max(small["x"], big["x"])
        iy = min(small["y"] + small["h"], big["y"] + big["h"]) - max(small["y"], big["y"])
        return ix > 0 and iy > 0 and ix * iy >= 0.7 * max(1, small["w"] * small["h"])
    rows = [t for t in rows if not any(inside(t, o) for o in rows)]
    out = []
    for t in sorted(rows, key=lambda t: t["x"]):
        joined = False
        for o in out:
            if o.get("angle", 0) != t.get("angle", 0) or not o.get("text") or not t.get("text"):
                continue
            h = min(o["h"], t["h"])
            if h <= 0 or max(o["h"], t["h"]) > 1.6 * h:
                continue
            same_row = abs((o["y"] + o["h"] / 2) - (t["y"] + t["h"] / 2)) < 0.5 * h
            gap = t["x"] - (o["x"] + o["w"])
            if same_row and -0.5 * h <= gap < 1.2 * h:
                x0, y0 = min(o["x"], t["x"]), min(o["y"], t["y"])
                x1, y1 = max(o["x"] + o["w"], t["x"] + t["w"]), max(o["y"] + o["h"], t["y"] + t["h"])
                o.update(text=o["text"] + " " + t["text"], x=x0, y=y0, w=x1 - x0, h=y1 - y0,
                         conf=min(o.get("conf", 1.0), t.get("conf", 1.0)))
                joined = True
                break
        if not joined:
            out.append(t)
    # Two tiles can read the same word twice ("Lily." and a garbled "LAY," on
    # one spot). One joins its sentence; the other is left over, a lone name.
    # A one- or two-word line lying almost wholly inside a sentence on its row
    # is a second reading of part of that sentence, not a label: dropped.
    # Found on the Windows build of September 29, 2026 (noon).
    def covered(small, big):
        if small is big or small.get("angle", 0) != big.get("angle", 0):
            return False
        if len((big.get("text") or "").split()) < 3 or len((small.get("text") or "").split()) > 2:
            return False
        ix = min(small["x"] + small["w"], big["x"] + big["w"]) - max(small["x"], big["x"])
        iy = min(small["y"] + small["h"], big["y"] + big["h"]) - max(small["y"], big["y"])
        return ix > 0 and iy > 0 and ix * iy >= 0.7 * max(1, small["w"] * small["h"])
    out = [t for t in out if not any(covered(t, o) for o in out)]
    return sorted(out, key=lambda t: (t["y"], t["x"]))


def label_strength(t, roster):
    """How closely a line reads as one of the roster's names, 0 to 1."""
    n = norm(t.get("text") or "")
    words = n.split()
    cands = [n] + ([" ".join(words[:-1]), words[0]] if len(words) >= 2 else [])
    cands = [c for c in cands if c and c not in STOPWORDS and len(c) >= 3]
    best = 0.0
    for name in roster or []:
        for form in roster_forms(name):
            for c in cands:
                best = max(best, difflib.SequenceMatcher(None, c, form).ratio())
    return best


CLEAN_READ = 0.95


def one_label_per_child(labels, roster, get=lambda x: x):
    """The weaker reader of a PC can return a garbled second reading of a
    child's name somewhere else on the wall ("09 LIL" beside the real label).
    Each child keeps its strongest label; a second label of the same child is
    kept only when it too reads cleanly, since a child can have two papers."""
    if not roster:
        return list(labels)
    best = {}
    for x in labels:
        t = get(x); k = whose(t, roster); sc = label_strength(t, roster)
        if k is not None and sc > best.get(k, -1):
            best[k] = sc
    out = []
    for x in labels:
        t = get(x); k = whose(t, roster); sc = label_strength(t, roster)
        if k is None or sc >= best[k] or sc >= CLEAN_READ:
            out.append(x)
    return out


def label_hits(texts, roster, min_ratio=0.85):
    """Lines from a whole-photo read that are a child's name label."""
    out = []
    for t in join_rows(texts):
        n = norm(t["text"])
        words = n.split()
        # a label is a short line that IS the name, not a sentence that mentions one
        if len(n) < 2 or n in STOPWORDS or len(words) > 3:
            continue
        cands = [n]
        if len(words) >= 2:
            cands.append(" ".join(words[:-1]))   # "Nils G", "Zed Q": a stray mark read after the name
            cands.append(words[0])
        cands = [c for c in cands if c not in STOPWORDS and len(c) >= 3]   # "the beach" is not a name
        best = 0.0
        for name in roster:
            for form in roster_forms(name):
                for c in cands:
                    best = max(best, difflib.SequenceMatcher(None, c, form).ratio())
        if best >= min_ratio:
            out.append(t)
    return out


def labelled_children(texts, roster):
    """How many different children on the class list have a name label in the photo."""
    seen = set()
    for t in label_hits(texts, roster):
        n = norm(t["text"]); best, who = 0.0, None
        for name in roster:
            for form in roster_forms(name):
                for cand in [n] + n.split():
                    r = difflib.SequenceMatcher(None, cand, form).ratio()
                    if r > best:
                        best, who = r, name
        if who:
            seen.add(who)
    return len(seen)


def pieces_from_labels(img, whole, roster, quads):
    """White paper on a white wall gives the paper detectors nothing to find,
    but a typed label is easy to read. When the photo shows more readable
    name labels than found papers, build the papers from the words instead:
    every line of text belongs to the nearest label, and a piece is the
    label plus its lines, padded. Returns quads, or None to keep the old ones."""
    labels = label_hits(whole, roster)
    # the reader sometimes returns one label twice ("Jordan Lum" and "Jordan Leee"
    # a few pixels apart): keep one per child per spot
    def which(t):
        n = norm(t["text"]); best, who = 0.0, None
        for name in roster:
            for form in roster_forms(name):
                for cand in [n] + n.split():
                    r = difflib.SequenceMatcher(None, cand, form).ratio()
                    if r > best:
                        best, who = r, name
        return who
    kept = []
    for t in sorted(labels, key=lambda t: -len(t["text"])):
        cx, cy = t["x"] + t["w"] / 2, t["y"] + t["h"] / 2
        dup = False
        for k in kept:
            kx, ky = k["x"] + k["w"] / 2, k["y"] + k["h"] / 2
            if which(k) == which(t) and abs(kx - cx) < max(img.width, img.height) * 0.06 and abs(ky - cy) < max(img.width, img.height) * 0.06:
                dup = True
                break
        if not dup:
            kept.append(t)
    labels = kept
    # a child's name twice in one place (typed label plus the child's own signature)
    # is one child: keep one hit per child per detected piece
    boxes0 = [quad_bbox(q) for q in quads]
    seen = set(); once = []
    for t in labels:
        cx, cy = t["x"] + t["w"] / 2, t["y"] + t["h"] / 2
        inside = next((i for i, b in enumerate(boxes0) if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]), None)
        key = (which(t), inside)
        if inside is not None and key in seen:
            continue
        seen.add(key); once.append(t)
    labels = once
    if len(labels) < 3:
        return None
    boxes = [quad_bbox(q) for q in quads]
    outside = 0
    for t in labels:
        cx, cy = t["x"] + t["w"] / 2, t["y"] + t["h"] / 2
        near_one = False
        for b in boxes:
            h = b[3] - b[1]
            dx = max(b[0] - cx, 0, cx - b[2]); dy = max(b[1] - cy, 0, cy - b[3])
            if (dx * dx + dy * dy) ** 0.5 <= 0.3 * h:      # inside, or pinned just beside a paper
                near_one = True
                break
        if not near_one:
            outside += 1
    if len(labels) <= len(quads) and outside < max(1, 0.2 * len(labels)):
        return None
    centers = [(t["x"] + t["w"] / 2, t["y"] + t["h"] / 2) for t in labels]
    groups = [[t] for t in labels]
    for t in whole:
        if t in labels:
            continue
        cx, cy = t["x"] + t["w"] / 2, t["y"] + t["h"] / 2
        j = min(range(len(centers)), key=lambda k: (centers[k][0] - cx) ** 2 + (centers[k][1] - cy) ** 2)
        groups[j].append(t)
    # typical spacing between labels sets how far a piece may reach
    dists = []
    for i, (ax, ay) in enumerate(centers):
        others = [((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 for k, (bx, by) in enumerate(centers) if k != i]
        if others:
            dists.append(min(others))
    reach = 0.5 * (sorted(dists)[len(dists) // 2] if dists else max(img.width, img.height) / 4)
    out = []
    for lab, grp in zip(labels, groups):
        lx, ly = lab["x"] + lab["w"] / 2, lab["y"] + lab["h"] / 2
        near = [t for t in grp if abs(t["x"] + t["w"] / 2 - lx) <= reach * 2.5 and abs(t["y"] + t["h"] / 2 - ly) <= reach * 2.5]
        x0 = min(t["x"] for t in near); y0 = min(t["y"] for t in near)
        x1 = max(t["x"] + t["w"] for t in near); y1 = max(t["y"] + t["h"] for t in near)
        # a label alone (artwork, no writing) still needs a paper-sized box around it
        w, h = x1 - x0, y1 - y0
        minw, minh = reach * 1.2, reach * 1.2
        if w < minw:
            cx = (x0 + x1) / 2; x0, x1 = cx - minw / 2, cx + minw / 2
        if h < minh:
            cy = (y0 + y1) / 2; y0, y1 = cy - minh / 2, cy + minh / 2
        pad = 0.12
        X0 = int(max(0, x0 - w * pad - 40)); Y0 = int(max(0, y0 - h * pad - 40))
        X1 = int(min(img.width, x1 + w * pad + 40)); Y1 = int(min(img.height, y1 + h * pad + 40))
        out.append({"conf": 0.6, "tl": [X0, Y0], "tr": [X1, Y0], "br": [X1, Y1], "bl": [X0, Y1], "label": lab})
    return out


def label_list(img, whole, roster):
    """The typed name labels read on the whole photo, one per child per spot."""
    kept = []
    for t in sorted(label_hits(whole, roster), key=lambda t: -len(t["text"])):
        cx, cy = t["x"] + t["w"] / 2, t["y"] + t["h"] / 2
        far = max(img.width, img.height) * 0.06
        # the reader can return one label twice with two spellings ("lonah Reyes",
        # "Jonah Re"): two readings of the SAME CHILD at the same spot are one label
        if not any(whose(k, roster) == whose(t, roster)
                   and abs(k["x"] + k["w"] / 2 - cx) < far and abs(k["y"] + k["h"] / 2 - cy) < far for k in kept):
            kept.append(t)
    return one_label_per_child(kept, roster)


def centre(t):
    return (t["x"] + t["w"] / 2, t["y"] + t["h"] / 2)


def whose(t, roster):
    """The child a name label belongs to."""
    n = norm(t.get("text") or "")
    best, who = 0.0, None
    for name in roster or []:
        for form in roster_forms(name):
            for cand in [n] + n.split():
                r = difflib.SequenceMatcher(None, cand, form).ratio()
                if r > best:
                    best, who = r, name
    return who


OFF_THE_PHOTO = "the paper runs off the edge of the photo"
SEAM_STANDS_OUT = 2.5    # a seam is a line this many times stronger than the paper around it


def seam_between(lum, box, a, b, along_x):
    """Two papers hung touching leave no dark wall between them, but the
    edge where one sheet meets the other is still a line. Looks for that
    line between two labels, near where an even split would fall. Returns
    its position in the small picture, or None when no line stands out: a
    seam is measured, never guessed."""
    x0, y0, x1, y1 = box
    patch = lum[y0:y1 + 1, x0:x1 + 1].astype(np.float32)
    if not along_x:
        patch = patch.T
        a, b, x0 = (a[1], a[0]), (b[1], b[0]), y0
    step = np.abs(np.diff(patch, axis=1))
    rows = step.shape[0]
    inner = step[int(rows * 0.1):max(int(rows * 0.9), int(rows * 0.1) + 1)]
    line = np.median(inner, axis=0)                 # a seam runs the whole height; a drawing does not
    # The labels sit in the corners of their papers, so the seam can be
    # anywhere between the two labels, not only halfway.
    lo, hi = sorted((a[0] - x0, b[0] - x0))
    i0, i1 = max(1, int(lo) + 1), min(len(line) - 2, int(hi) - 1)
    if i1 <= i0:
        return None
    k = i0 + int(np.argmax(line[i0:i1 + 1]))
    rest = np.concatenate([line[i0:max(i0, k - 3)], line[k + 4:i1 + 1]])
    usual = float(np.median(rest)) if len(rest) else 0.0
    if line[k] < 4 or line[k] < SEAM_STANDS_OUT * max(usual, 1.0):
        return None
    return x0 + k + 1


def holds(box, point, slack=0):
    return box[0] - slack <= point[0] <= box[2] + slack and box[1] - slack <= point[1] <= box[3] + slack


DARK_WALL = 110          # the teacher's rule: the work is set against a dark background
PAPER_FILL = 0.70        # a sheet of paper fills most of its own box


def wall_is_dark(img, small=400):
    """The teacher's rule is a dark background. True when the photo has one:
    its outer frame, which is wall, is dark. On a pale wall the paper
    detectors can take a drawing for a sheet, so nothing here is trusted."""
    scale = small / float(max(img.width, img.height))
    sm = img.resize((max(8, int(img.width * scale)), max(8, int(img.height * scale))), Image.BILINEAR)
    lum = np.asarray(sm.convert("L"), dtype=np.int16)
    e = max(2, int(0.04 * min(lum.shape)))
    frame = np.concatenate([lum[:e].ravel(), lum[-e:].ravel(), lum[:, :e].ravel(), lum[:, -e:].ravel()])
    return float(np.median(frame)) < DARK_WALL


def paper_around_label(img, lab, centres, small=1000, kids=None, why=None):
    """The paper a name label is on, found from the dark background around
    it. Teachers are told to mount the work on a dark background, so the
    paper is the patch that is NOT background around the label. Returns a
    quad, or None when the wall is not dark, the patch runs off the photo,
    holds another child's label, or is not the shape of a sheet of paper."""
    scale = small / float(max(img.width, img.height))
    sm = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.BILINEAR)
    a = np.asarray(sm.convert("RGB"), dtype=np.int16)
    H, W = a.shape[:2]
    lum = a.sum(axis=2) / 3.0
    dark = a[lum < DARK_WALL]
    if len(dark) < 0.08 * H * W:
        return None                      # no dark background to speak of
    wall = np.median(dark, axis=0)
    mask = (np.abs(a - wall).sum(axis=2) > 120)
    m = Image.fromarray((mask * 255).astype(np.uint8))
    m = m.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))   # close pencil-thin gaps
    arr = np.asarray(m)
    x0, y0 = int(lab["x"] * scale), int(lab["y"] * scale)
    x1, y1 = int((lab["x"] + lab["w"]) * scale), int((lab["y"] + lab["h"]) * scale)
    x0, y0, x1, y1 = max(0, x0 - 2), max(0, y0 - 2), min(W - 1, x1 + 2), min(H - 1, y1 + 2)
    ys, xs = np.where(arr[y0:y1 + 1, x0:x1 + 1] > 0)
    if not len(xs):
        return None
    cx, cy = (x1 - x0) / 2.0, (y1 - y0) / 2.0
    k = int(np.argmin((xs - cx) ** 2 + (ys - cy) ** 2))
    ImageDraw.floodfill(m, (int(x0 + xs[k]), int(y0 + ys[k])), 128, thresh=0)
    ys, xs = np.where(np.asarray(m) == 128)
    if not len(xs):
        return None
    bx0, by0, bx1, by1 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
    bw, bh = bx1 - bx0 + 1, by1 - by0 + 1
    if bx0 <= 0 or by0 <= 0 or bx1 >= W - 1 or by1 >= H - 1:
        if why is not None:
            why.append(OFF_THE_PHOTO)
        return None                      # runs off the photo: the whole paper is not in the frame
    if len(xs) < PAPER_FILL * bw * bh:
        return None                      # not the shape of a sheet
    if bw * bh < 6 * max(1, (x1 - x0) * (y1 - y0)) or bw * bh > 0.92 * W * H:
        return None
    mine = centre(lab)
    kids = kids or [None] * len(centres)
    me = next((k for c, k in zip(centres, kids) if c == mine), None)
    small_box = (bx0, by0, bx1, by1)
    # other CHILDREN on the same patch (the same child's name read twice is one child)
    near = [(c[0] * scale, c[1] * scale) for c, k in zip(centres, kids)
            if c != mine and (k is None or k != me) and holds(small_box, (c[0] * scale, c[1] * scale))]
    if near:
        # papers hung touching: cut at the seams on either side of this label
        here = (mine[0] * scale, mine[1] * scale)
        along_x = (max(p[0] for p in near + [here]) - min(p[0] for p in near + [here])
                   >= max(p[1] for p in near + [here]) - min(p[1] for p in near + [here]))
        ax = 0 if along_x else 1
        lo, hi = (bx0, bx1) if along_x else (by0, by1)
        before = [p for p in near if p[ax] < here[ax]]
        after = [p for p in near if p[ax] > here[ax]]
        if before:
            cut = seam_between(lum, small_box, max(before, key=lambda p: p[ax]), here, along_x)
            if cut is None:
                return None
            lo = cut
        if after:
            cut = seam_between(lum, small_box, here, min(after, key=lambda p: p[ax]), along_x)
            if cut is None:
                return None
            hi = cut - 1
        bx0, by0, bx1, by1 = (lo, by0, hi, by1) if along_x else (bx0, lo, bx1, hi)
        small_box = (bx0, by0, bx1, by1)
        if not holds(small_box, here) or any(holds(small_box, p) for p in near):
            return None
    box = (int(bx0 / scale), int(by0 / scale), int((bx1 + 1) / scale), int((by1 + 1) / scale))
    X0, Y0, X1, Y1 = box
    return {"conf": 0.8, "tl": [X0, Y0], "tr": [X1, Y0], "br": [X1, Y1], "bl": [X0, Y1],
            "edges": "seam" if near else "background", "from_label": lab}


def with_found_edges(img, by_label, found, roster=None):
    """Pieces cut around their name labels are a guess and are never filed.
    But where the edges of a paper WERE found, that paper is not a guess:
    use its real edges. A label gets a found paper when it sits on exactly
    one and no other child's label sits on the same one; failing that, the
    paper is looked for against the dark background; failing that, the piece
    stays a guess for a person to check. One paper with no edges no longer
    sends the whole photo to a person."""
    if not wall_is_dark(img):
        return by_label
    by_label = one_label_per_child(by_label, roster, get=lambda q: q["label"])
    centres = [centre(q["label"]) for q in by_label]
    kids = [whose(q["label"], roster) if roster else None for q in by_label]
    areas = sorted(quad_area(q) for q in found)
    typical = areas[len(areas) // 2] if areas else 0
    out, taken = [], set()
    for q, c, kid in zip(by_label, centres, kids):
        others = [o for o, k in zip(centres, kids) if o != c and (k is None or k != kid)]
        fits = [(quad_area(f), j) for j, f in enumerate(found)
                if holds(quad_bbox(f), c)
                and not any(holds(quad_bbox(f), o) for o in others)
                and (not typical or 0.4 * typical <= quad_area(f) <= 2.5 * typical)]
        if fits:
            j = min(fits)[1]
            if j in taken:
                continue                 # this child's name read twice on one paper: one piece
            taken.add(j)
            out.append({**{k: v for k, v in found[j].items() if k != "label"}, "child": kid, "from_label": q["label"]})
            continue
        if kid is not None and any(p.get("child") == kid and not p.get("label") and holds(quad_bbox(p), c) for p in out):
            continue                     # this child's name read again on a paper already found: one piece
        why = []
        paper = paper_around_label(img, q["label"], centres, kids=kids, why=why)
        if paper and any(p.get("child") == kid and kid is not None and not p.get("label")
                         and mutual_overlap(quad_bbox(p), quad_bbox(paper)) > 0.6 for p in out):
            continue                     # the same paper again
        out.append({**paper, "child": kid} if paper else ({**q, "why": why[0]} if why else q))
    return out


def add_missing_papers(img, whole, roster, quads):
    """A name label that sits on no found paper means a paper was missed
    (one large sheet filling the photo is the usual case). Look for it
    against the dark background and add it."""
    if not wall_is_dark(img):
        return quads
    labels = label_list(img, whole, roster)
    centres = [centre(t) for t in labels]
    kids = [whose(t, roster) for t in labels]
    # one found "paper" holding two children's names is two papers hung
    # touching: cut it at the seams, or leave it as it was found
    kept = []
    for q in quads:
        on = [(t, k) for t, c, k in zip(labels, centres, kids) if holds(quad_bbox(q), c)]
        if len({k for _, k in on}) < 2:
            kept.append(q)
            continue
        parts, done = [], set()
        for t, k in on:
            if k in done:
                continue
            part = paper_around_label(img, t, centres, kids=kids)
            if part is None:
                parts = None
                break
            done.add(k)
            parts.append({**part, "child": k})
        kept += parts if parts else [q]
    # Without Apple's rectangle finder (a Windows PC) a found box is only a
    # texture or colour guess, and on a dark wall with coloured paper it is
    # often part of a sheet or a sheet plus wall. The paper found from the
    # background around the label is exact, so where it is found it replaces
    # the guess. On a Mac the rectangle finder is kept.
    if LAST_DETECTOR != "rectangles":
        exact = []
        for q in kept:
            on = [(t, k) for t, c, k in zip(labels, centres, kids) if holds(quad_bbox(q), c)]
            one_child = len({k for _, k in on}) == 1
            paper = paper_around_label(img, on[0][0], centres, kids=kids) if one_child else None
            exact.append({**paper, "child": on[0][1]} if paper else q)
        kept = exact
    quads = kept
    boxes = [quad_bbox(q) for q in quads]
    out = list(quads)
    for t, c in zip(labels, centres):
        if any(holds(b, c, slack=0.05 * (b[3] - b[1])) for b in boxes):
            continue
        paper = paper_around_label(img, t, centres, kids=kids)
        if paper and not any(bbox_overlap(quad_bbox(paper), b) > 0.5 for b in boxes):
            out.append(paper)
            boxes.append(quad_bbox(paper))
    return out


def grid_boxes(img, rows, cols):
    """Manual override: split the photo into an even grid."""
    w, h = img.width / cols, img.height / rows
    quads = []
    for r in range(rows):
        for c in range(cols):
            x0, y0, x1, y1 = int(c * w), int(r * h), int((c + 1) * w), int((r + 1) * h)
            quads.append({"conf": 1.0, "tl": [x0, y0], "tr": [x1, y0], "br": [x1, y1], "bl": [x0, y1]})
    return quads


def warp(img, q, pad=0.015):
    """Straighten one quad into a flat rectangle."""
    tl, tr, br, bl = (np.array(q[k], dtype=float) for k in ("tl", "tr", "br", "bl"))
    # push each corner slightly outward so the paper edge is kept
    cx, cy = (tl + tr + br + bl) / 4
    def out(p):
        return p + (p - np.array([cx, cy])) * pad
    tl, tr, br, bl = out(tl), out(tr), out(br), out(bl)
    w = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    h = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    w, h = max(w, 8), max(h, 8)
    data = (*tl, *bl, *br, *tr)  # PIL QUAD order: ul, ll, lr, ur
    return img.transform((w, h), Image.QUAD, data, Image.BICUBIC)


# ----------------------------------------------------------------- roster ---

# Letters the reader sometimes returns from other scripts that look like ours.
LOOKALIKES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "к": "k",
    "м": "m", "т": "t", "н": "h", "в": "b", "і": "i", "ј": "j", "ѕ": "s", "ц": "u",
    "А": "A", "Е": "E", "О": "O", "Р": "P", "С": "C", "У": "Y", "Х": "X", "К": "K",
    "М": "M", "Т": "T", "Н": "H", "В": "B", "І": "I", "Ј": "J", "Ѕ": "S",
    "ý": "y", "ÿ": "y",
})


def norm(s):
    """Lowercase letters and spaces only; accents stripped; look-alike
    letters from other alphabets mapped to ours."""
    s = s.translate(LOOKALIKES)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z ]", "", s.lower()).strip()


class ClassListError(UnicodeError):
    """The class list holds something this program cannot read as names. The
    message is one plain sentence for the log; it gives a line number and
    never the words on the line, because the line is a child's name."""


# Characters nobody can see, which editors put into a text file: the mark
# Google Docs, Notepad and Word write at the very start of a file (U+FEFF),
# and zero-width spaces. Left in, "Maya Torres" and the same name with the
# mark in front are two different folders that look identical on the screen.
INVISIBLE = dict.fromkeys(map(ord, "﻿​⁠"))

# Accented letters found in names. Used only for a class list that is not
# UTF-8, to tell a list saved on Windows from one saved on an older Mac.
NAME_ACCENTS = "àáâãäåæçèéêëìíîïñòóôõöøùúûüýÿšžœß"
HOW_TO_SAVE = ("Open the class list, choose Save As, pick 'UTF-8' where it asks for the encoding, "
               "and save it again")


def class_list_lines(text):
    """(line number, name) for every line of the class list that is a name:
    invisible characters removed, spaces tidied, blank lines and # comments
    left out. Line numbers start at 1, as an editor shows them."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        line = " ".join(line.translate(INVISIBLE).split())
        if line and not line.startswith("#"):
            out.append((n, line))
    return out


def odd_line(lines):
    """The number of the first line holding something that is not part of a
    name, or None. Plain letters, digits and punctuation always pass. An
    accented letter passes where a name would have it: a small one anywhere
    except straight before a capital, a capital one at the start of a word.
    A curly apostrophe passes between a letter and a capital (O'Hara). That
    is what tells 'José' from the same bytes read in the wrong encoding,
    which come out as a capital or a symbol in the middle of the word."""
    for n, line in lines:
        for i, ch in enumerate(line):
            if ch.isascii():
                if ch.isprintable():
                    continue
                return n
            before = line[i - 1] if i else " "
            after = line[i + 1] if i + 1 < len(line) else " "
            if ch == "’":
                ok = before.isalpha() and after.isupper()
            elif ch.lower() in NAME_ACCENTS:
                ok = (not after.isupper()) if ch.islower() else (not before.isalpha() or before.isupper())
            else:
                ok = False
            if not ok:
                return n
    return None


def read_class_list(data):
    """The names in the bytes of a class list file.

    A class list is made by a teacher with whatever is on their computer, and
    each program saves plain text its own way:
    - UTF-8, with or without the invisible mark at the start (Google Docs
      'Download as plain text', Notepad, TextEdit): read as it is.
    - UTF-16 (Notepad's 'Unicode'): it always starts with its own mark.
    - Windows-1252 (Word's 'Plain text' on Windows, older Notepad) or Mac
      Roman (Word's 'Plain text' on a Mac): the file does not say which, so
      both are tried and one is used only when every name comes out looking
      like a name and the other does not. When neither does, or both do and
      they disagree, nothing is guessed: ClassListError names the line.
    The answer depends on the bytes alone, never on the computer reading
    them, so a Mac and a Windows PC that watch the same class folder get the
    same names and make the same folders."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            lines = class_list_lines(data.decode("utf-16"))
        except UnicodeDecodeError:
            raise ClassListError("the file is damaged or still being saved. " + HOW_TO_SAVE) from None
    else:
        try:
            lines = class_list_lines(data.decode("utf-8-sig"))
        except UnicodeDecodeError:
            lines = None
    if lines is not None:
        bad = odd_line([(n, "".join(ch for ch in line if ch.isascii())) for n, line in lines])
        if bad:
            raise ClassListError(f"line {bad} is not text. The class list has to be a plain text file. "
                                 + HOW_TO_SAVE)
        return [line for _, line in lines]
    readings, bad = [], 0
    for encoding in ("cp1252", "mac_roman"):
        lines = class_list_lines(data.decode(encoding, errors="replace"))
        odd = odd_line(lines)
        if odd is None and lines not in readings:
            readings.append(lines)
        # the reading that got furthest before it stopped making sense is the
        # likelier one, so its line is the one to send the teacher to
        bad = max(bad, odd or 0)
    if len(readings) == 1:
        return [line for _, line in readings[0]]
    if readings:
        # both make sense and they are not the same names: send the teacher
        # to the first line they disagree on
        bad = next((a[0] for a, b in zip(*readings) if a != b),
                   max(r[-1][0] for r in readings if r))
    raise ClassListError(f"line {bad} has a letter this program cannot make out, most likely one with an accent. "
                         + HOW_TO_SAVE)


def load_roster(path):
    """One child per line: 'Maya' or 'Maya R.' Blank lines and # comments
    ignored. However the file was saved (see read_class_list), the names come
    back without invisible characters. Raises ClassListError, with a plain
    sentence naming the line, when a line cannot be read."""
    with open(path, "rb") as f:
        return read_class_list(f.read())


def roster_stamp(path):
    """Size and time of last change of the class list, or None when the file
    cannot be reached right now (Google Drive not connected for a moment)."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def refresh_roster(path, roster, seen, log=print):
    """The class list to use for this look at the inbox. The watcher runs for
    weeks; a teacher adds a child to the class list in October and expects
    the next photo to know that child, without anyone restarting anything.
    So the file is read again whenever its size or time of last change is
    different from the last time it was read, and the log says so once.

    `seen` is a dict this function keeps its memory in between calls. A list
    that is missing, empty or unreadable at this moment (Drive still writing
    it, or not connected) never replaces a good one: the list from before
    stays in use, the log says why once, and the file is tried again on the
    next look. Shared by the Mac and Windows watchers; nothing here is
    Mac-only or Windows-only."""
    stamp = roster_stamp(path)
    if stamp is None or stamp == seen.get("stamp"):
        return roster
    try:
        names = load_roster(path)
        problem = None if names else "is empty"
    except (OSError, UnicodeError) as e:
        names, problem = None, f"could not be read ({e})"
    if problem:
        if seen.get("said") != (stamp, problem):
            log(f"class list {problem}; still using the list of {len(roster)} children from before. "
                f"The file is '{os.path.basename(path)}' in the class folder")
            seen["said"] = (stamp, problem)
        return roster
    seen["stamp"] = stamp
    seen["said"] = None
    if names != roster:
        count = "1 child" if len(names) == 1 else f"{len(names)} children"
        new = [n for n in names if n not in roster]
        log(f"class list changed: {count} (there were {len(roster)}). "
            + ("A new child gets a folder, and their work is filed from the next photo" if new
               else "The next photo is sorted with the new list"))
    return names


# A child's work can carry a name that is not the one on the class list: the
# list has "Alexander" and the sticker says "Sasha", the name he goes by
# (October 8, 2026: a page with a clearly typed sticker went to a person for
# this reason alone). The class's settings file may say so:
#     "also_called": {"Alexander Lund": ["Sasha Lund"]}
# The name on the left is the class-list line, exactly; the page is still
# filed in that child's folder. Nothing is guessed: a name is only ever
# matched to the names written here.
ALSO_CALLED = {}


def set_also_called(table):
    """Take the "also_called" part of a settings file. Anything that is not a
    name with one or more other names is left out."""
    ALSO_CALLED.clear()
    if not isinstance(table, dict):
        return
    for name, others in table.items():
        others = [others] if isinstance(others, str) else others
        if isinstance(name, str) and isinstance(others, (list, tuple)):
            kept = [o for o in others if isinstance(o, str) and norm(o)]
            if kept:
                ALSO_CALLED[name] = kept


def roster_forms(name):
    """Strings a roster entry may appear as on the paper. A class list written
    last name first ("Doe, Jane", the way a class's own files were named on
    October 6, 2026) is also matched the way the paper says it: "Jane" and
    "Jane Doe". The other names a child goes by (ALSO_CALLED) count too."""
    forms = set()
    for one in [name] + ALSO_CALLED.get(name, []):
        n = norm(one)
        forms.add(n)
        parts = n.split()
        if parts:
            forms.add(parts[0])
        if "," in one:
            last, given = (norm(x) for x in one.split(",", 1))
            if last and given:
                forms.add(given.split()[0])
                forms.add(f"{given} {last}")
    return forms


def spelled_in_full(texts, name):
    """True when one line on the paper carries every word of this child's
    full name, spelled exactly, in either order: "Jordan Lum" or "Lum, Jordan
    2026/2027". A class-list entry of one word has no full name to find."""
    for one in [name] + ALSO_CALLED.get(name, []):
        want = set(norm(one.replace(",", " ")).split())
        if len(want) >= 2 and any(want <= set(norm(t["text"].replace(",", " ")).split()) for t in texts):
            return True
    return False


def match_name(texts, roster):
    """texts: list of {text, conf, x, y, w, h} from OCR.
    Returns dict(name, score, margin, text, box, status)."""
    full_forms = {f for name in roster for f in roster_forms(name) if " " in f}
    candidates = []
    for t in texts:
        raw = t["text"]
        words = raw.split()
        whole = norm(raw)
        # "Maya T." written as a whole line: the line is the name, do not let
        # the bare "maya" fragment tie with another Maya
        if any(difflib.SequenceMatcher(None, whole, f).ratio() >= 0.9 for f in full_forms):
            pieces = [(raw, 0.0)]
        else:
            penalty = LONG_LINE_PENALTY if len(words) >= 4 else 0.0
            pieces = [(raw, 0.0)] + [(w, penalty) for w in words]
            for i in range(len(words) - 1):
                pieces.append((" ".join(words[i:i + 2]), penalty))
        shortest = min(len(f) for name in roster for f in roster_forms(name))
        # the line with stray one-letter marks dropped ("Marcus м" -> "Marcus"):
        # a typed label with a speck read as a letter is still just the name
        core = norm(" ".join(w for w in words if len(norm(w)) > 1))
        for p, pen in pieces:
            n = norm(p)
            if len(n) < max(2, min(3, shortest)) or n in STOPWORDS:
                continue
            # from a short line (a label, "by Nils", "Zed Q") or a fragment of a sentence?
            standalone = len(words) <= 3
            # the whole short line IS this piece (a bare label such as "Theo"), as
            # opposed to a name pulled out of "my friend Theo"
            label_line = standalone and n in (whole, core)
            candidates.append((n, t, pen, standalone, label_line))

    best = {}  # roster name -> (score, text dict, piece)
    as_label = set()  # names seen as a standalone short line, not inside a sentence
    for n, t, pen, standalone, label_line in candidates:
        for name in roster:
            for form in roster_forms(name):
                score = difflib.SequenceMatcher(None, n, form).ratio() - pen
                if standalone and score >= CONFIDENT_SCORE:
                    as_label.add(name)
                # a bare roster name read cleanly on its own line: the teacher's
                # label, wherever it sits on the paper
                strong_label = label_line and score >= CONFIDENT_SCORE
                # a whole-line match is worth a little more than a fragment
                if n == norm(t["text"]):
                    score = min(1.0, score + 0.02)
                ry = t.get("rel_y")
                if ry is not None:
                    if ry <= EDGE_BAND or ry >= 1 - EDGE_BAND:
                        # written work: the top or bottom edge is where the teacher's name goes
                        score = min(1.0, score + EDGE_BONUS)
                    elif strong_label:
                        # artwork: the label can be anywhere on the paper. A bare roster
                        # name on its own line in the middle is still the label; only a
                        # small discount, so an exact read files and a shaky one does not
                        score = max(0.0, score - BODY_LABEL_PENALTY)
                    else:
                        # the same name inside a sentence in the middle of the page is
                        # a character in the story
                        score = max(0.0, score - BODY_PENALTY)
                # on a tie, keep the read that has a box (from the crop)
                if name not in best or score > best[name][0] or (
                        score == best[name][0] and best[name][1].get("nobox") and not t.get("nobox")):
                    best[name] = (score, t, n)

    if not best:
        return {"name": None, "score": 0.0, "margin": 0.0, "text": None, "box": None,
                "status": "no text read"}

    ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)
    top_name, (top_score, top_t, piece) = ranked[0]
    second = ranked[1][1][0] if len(ranked) > 1 else 0.0
    # two roster entries sharing a first name and only the first name read
    # will tie; a tie is never confident
    margin = top_score - second
    box = None if top_t.get("nobox") else (top_t["x"], top_t["y"], top_t["x"] + top_t["w"], top_t["y"] + top_t["h"])
    if top_score >= CONFIDENT_SCORE and margin >= CONFIDENT_MARGIN and top_name in as_label:
        status = "confident"
    elif top_score >= CONFIDENT_SCORE and margin >= CONFIDENT_MARGIN:
        # the name was only ever part of a sentence ("with my friend ..."):
        # a person decides, the tool does not
        status = "unsure"
    elif top_score >= WEAK_SCORE:
        status = "unsure"
    else:
        status = "no name read"
    if status == "unsure":
        # Two children whose names are nearly the same ("Lena" and "Lea") are
        # too close to call from a first name alone. When the paper also
        # carries the full name of exactly one of them, spelled out ("Lund,
        # Lena  2026/2027" on the sticker), that settles it: the page is
        # hers. October 7, 2026: a sticker read letter for letter went to a
        # person because another child's first name was one letter away.
        close = [n for n, (s, _, _) in ranked if s >= CONFIDENT_SCORE and top_score - s < CONFIDENT_MARGIN]
        full = [n for n in close if n in as_label and spelled_in_full(texts, n)]
        if len(close) > 1 and len(full) == 1:
            top_name = full[0]
            top_score, top_t, piece = best[top_name]
            box = None if top_t.get("nobox") else (top_t["x"], top_t["y"], top_t["x"] + top_t["w"],
                                                   top_t["y"] + top_t["h"])
            status = "confident"
    return {"name": top_name, "score": round(top_score, 3), "margin": round(margin, 3),
            "text": top_t["text"], "box": box, "status": status}


# ------------------------------------------------------------------ files ---

def texts_inside(texts, box):
    """Lines from a whole-photo read whose centre falls inside this piece.
    Their boxes are not in crop coordinates, so they carry no strip box."""
    x0, y0, x1, y1 = box
    out = []
    for t in texts:
        cx, cy = t["x"] + t["w"] / 2, t["y"] + t["h"] / 2
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            out.append({**t, "x": 0, "y": 0, "w": 0, "h": 0, "nobox": True,
                        "rel_y": (cy - y0) / max(1, y1 - y0)})
    return out


def read_neighborhood(img, q, others, tmpdir, i, reach=0.3):
    """Read the area just around a piece as well as the piece itself, so a
    name label pinned on the wall beside the paper is found. Lines that sit
    inside another piece are ignored. Reading a small region also keeps
    small labels legible; the whole photo at once is too big for the reader."""
    x0, y0, x1, y1 = quad_bbox(q)
    h, w = y1 - y0, x1 - x0
    X0, Y0 = max(0, int(x0 - reach * w)), max(0, int(y0 - reach * h))
    X1, Y1 = min(img.width, int(x1 + reach * w)), min(img.height, int(y1 + reach * h))
    region = img.crop((X0, Y0, X1, Y1))
    tmp = os.path.join(tmpdir, f"near-{i}.png")
    region.save(tmp)
    out = []
    for t in join_rows(run_vision("text", tmp, AS_IT_IS)):
        out.append({**t, "x": X0 + t["x"], "y": Y0 + t["y"]})   # photo coordinates
    os.remove(tmp)
    return out


def pool_lines(lines, tol=40):
    """Overlapping neighbourhoods read the same label twice; keep one."""
    kept = []
    for t in lines:
        cx, cy = t["x"] + t["w"] / 2, t["y"] + t["h"] / 2
        dup = False
        for k in kept:
            kx, ky = k["x"] + k["w"] / 2, k["y"] + k["h"] / 2
            if norm(k["text"]) == norm(t["text"]) and abs(kx - cx) < tol and abs(ky - cy) < tol:
                dup = True
                break
        if not dup:
            kept.append(t)
    return kept


def assign_texts(texts, quads, reach=0.3, reach_below=0.08):
    """Hand each line read near the pieces to exactly one piece: the one it
    sits inside, or, for a label pinned on the wall beside a paper, the
    nearest piece within `reach` of that piece's height. Below a paper the
    reach is short: what hangs under a display is the next row or the
    alphabet cards, not this child's label. Returns one list per quad."""
    boxes = [quad_bbox(q) for q in quads]
    per = [[] for _ in quads]
    for t in texts:
        cx, cy = t["x"] + t["w"] / 2, t["y"] + t["h"] / 2
        inside = [i for i, b in enumerate(boxes) if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]]
        if inside:
            i = inside[0]
            b = boxes[i]
            per[i].append({**t, "x": 0, "y": 0, "w": 0, "h": 0, "nobox": True,
                           "rel_y": (cy - b[1]) / max(1, b[3] - b[1])})
            continue
        best, best_d = None, None
        for i, b in enumerate(boxes):
            dx = max(b[0] - cx, 0, cx - b[2])
            dy = max(b[1] - cy, 0, cy - b[3])
            d = (dx * dx + dy * dy) ** 0.5
            limit = (reach_below if cy > b[3] else reach) * (b[3] - b[1])
            if d <= limit and (best_d is None or d < best_d):
                best, best_d = i, d
        if best is not None:
            # a label beside the paper is the teacher's label: treat as edge
            per[best].append({**t, "x": 0, "y": 0, "w": 0, "h": 0, "nobox": True, "rel_y": 0.0})
    return per


def read_photo_text(img, path, tmpdir, tile=2400, overlap=300):
    """Read every line of text in a whole photo at full resolution. Apple's
    reader shrinks a big photo before reading it, and a small typed name tag
    on a 48-megapixel photo becomes too small to read. So a large photo is
    read in overlapping tiles, each at its own full size, and the lines are
    merged. A small photo is read in one go."""
    if max(img.width, img.height) <= tile:
        return run_vision("text", path)
    lines = []
    step = tile - overlap
    ys = list(range(0, max(1, img.height - overlap), step))
    xs = list(range(0, max(1, img.width - overlap), step))
    n = 0
    for y in ys:
        for x in xs:
            box = (x, y, min(img.width, x + tile), min(img.height, y + tile))
            n += 1
            tp = os.path.join(tmpdir, f"tile-{n}.png")
            img.crop(box).save(tp)
            for t in run_vision("text", tp):
                lines.append({**t, "x": t["x"] + x, "y": t["y"] + y})
            os.remove(tp)
    return pool_lines(lines)


def text_angle(t):
    """The quarter turn (0, 90, 180, 270; counter-clockwise, as PIL's
    rotate() counts) that would make this line read upright. Both readers
    put it in the text dict as "angle"; a reader that does not know says 0."""
    try:
        return int(t.get("angle", 0)) % 360
    except (TypeError, ValueError):
        return 0


def majority_angle(texts, roster=None):
    """Which way is up, by the text. The typed name labels (lines that are a
    roster name) vote first; if none was read, every line votes. Ties go to
    the smaller turn, so 0 (leave it alone) wins a tie. Returns 0/90/180/270."""
    voters = label_hits(texts, roster) if roster else []
    if not voters:
        voters = texts
    counts = {}
    for t in voters:
        a = text_angle(t)
        counts[a] = counts.get(a, 0) + 1
    if not counts:
        return 0
    return min(counts, key=lambda a: (-counts[a], a))


def turn_upright(img, angle):
    """Rotate an image by a quarter turn (PIL counts counter-clockwise)."""
    angle = angle % 360
    return img.rotate(angle, expand=True) if angle else img


def decided_angle(texts, m, roster=None):
    """The turn that puts THIS piece upright: the angle of the line that
    decided the match (the label), else the majority of the label lines,
    else the majority of every line read on the piece."""
    if m.get("text") is not None:
        same = [t for t in texts if t.get("text") == m["text"]]
        with_box = [t for t in same if not t.get("nobox") and m.get("box")
                    and (t["x"], t["y"], t["x"] + t["w"], t["y"] + t["h"]) == tuple(m["box"])]
        pick = with_box or same
        if pick:
            return text_angle(pick[0])
    return majority_angle(texts, roster)


def is_own(t):
    """Read on the piece itself, not handed over from the wall around it."""
    return "rel_y" in t and not t.get("nobox")


def name_line(texts, m):
    """Where the line that IS the matched name was read, and the way it
    faces: ("own", angle) when it was read on the piece, in the piece's
    frame; ("wall", angle) when it was read on the wall around the piece, in
    the photo's frame; (None, 0) when no line is the name. Only the name
    decides which way is up: a scribble the reader took for a word does not."""
    same = [t for t in texts if m.get("text") is not None and t.get("text") == m["text"] and not t.get("nobox")]
    own = [t for t in same if is_own(t)]
    if own:
        return "own", text_angle(own[0])
    if same:
        return "wall", text_angle(same[0])
    return None, 0


def hint_angle(texts):
    """The way most lines on the piece seem to face: where to look first,
    never a reason to turn."""
    return majority_angle([t for t in texts if is_own(t)])


def read_piece(tmp_path, crop):
    """Read one straightened piece. If the plain read finds nothing, try
    again at double size and with the reader's spelling correction on.
    The piece is read the way it is handed over (AS_IT_IS): whoever calls
    turns it and reads again when no name reads for certain, and looks at it
    turned over when one does (second_look)."""
    texts = join_rows(run_vision("text", tmp_path, AS_IT_IS))
    for t in texts:
        t["rel_y"] = (t["y"] + t["h"] / 2) / max(1, crop.height)
    if not texts:
        up = tmp_path + ".up.png"
        crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS).save(up)
        for t in join_rows(run_vision("text", up, "corrected", AS_IT_IS)):
            texts.append({**t, "x": t["x"] // 2, "y": t["y"] // 2, "w": t["w"] // 2, "h": t["h"] // 2,
                          "rel_y": (t["y"] + t["h"] / 2) / max(1, crop.height * 2)})
        os.remove(up)
    return texts


def safe_folder(name):
    """A folder name that is the same on a Mac and a PC. Windows silently
    drops a trailing period ("Maya R." becomes "Maya R"), so it is dropped
    everywhere; otherwise two machines watching one Drive would make two
    folders for one child. Only the characters Windows refuses are removed:
    an accent or an apostrophe stays, so a folder made by hand for a child
    such as "Zoë O'Hara" is the folder the tool files into, not a second one
    beside it spelled "Zo OHara"."""
    name = unicodedata.normalize("NFC", name)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip().rstrip(". ") or "unknown"


def name_strip(crop, box):
    """A small image showing only the name, never the drawing."""
    if box:
        x0, y0, x1, y1 = box
        px, py = int((x1 - x0) * 0.5) + 20, int((y1 - y0) * 0.8) + 20
        return crop.crop((max(0, x0 - px), max(0, y0 - py),
                          min(crop.width, x1 + px), min(crop.height, y1 + py)))
    # no text found: top and bottom bands, where names usually live
    band = int(crop.height * 0.18)
    top = crop.crop((0, 0, crop.width, band))
    bottom = crop.crop((0, crop.height - band, crop.width, crop.height))
    out = Image.new("RGB", (crop.width, band * 2 + 6), "white")
    out.paste(top, (0, 0))
    out.paste(bottom, (0, band + 6))
    return out


def piece_name(project, grade, folder, ext=".jpg"):
    """'Self-Portrait Kindergarten.jpg'; a second piece of the same project
    for the same child becomes 'Self-Portrait Kindergarten 2.jpg'. The name
    is cleaned the same way as the folder it goes into (safe_folder), so a
    project called 'Who Am I?' is filed as 'Who Am I Kindergarten.jpg': a
    Windows PC cannot hold a file with ? : or " in its name, and Google Drive
    there would show every such piece as a sync error."""
    base = safe_folder(f"{project} {grade}")
    cand = base + ext
    n = 2
    while os.path.exists(os.path.join(folder, cand)):
        cand = f"{base} {n}{ext}"
        n += 1
    return cand


# ------------------------------------------------ one piece, filed once ---
#
# A photo can be sorted more than once: the computer stopped halfway and the
# teacher moved the photo back into Wall Inbox, one piece could not be saved
# and the photo went to 'failed', or the teacher uploaded the same photo again
# after putting a name right on the class list. The children who already had
# their piece used to get it again as '... 2.jpg'.
#
# So every piece the tool saves carries a short note INSIDE the file (a JPEG
# comment, which no viewer shows): which photo it was cut from, as a
# fingerprint of the photo file, and where on the photo it was. No name is in
# it. Before a piece is filed, the child's project folder is looked through
# for a piece with the same note; if one is there, the child has this piece
# and nothing is saved. The note travels with the file through Google Drive,
# so a second computer watching the class sees it too, and it goes when the
# teacher deletes the file, so a deleted piece is filed again. There is no
# separate list to keep in step with the folders.
#
# And a piece is written whole or not at all: first under a name ending in
# '.part', then renamed. A computer that stops in the middle of saving leaves
# a '.part' file, never half a picture under a child's real file name.
#
# Shared by the Mac and Windows watchers; nothing here is Mac-only or
# Windows-only.

MARK = b"Baggage Claim piece: "
PART = ".part"
SAME_PIECE = 0.5        # two boxes on one photo that share this much of each other are the same paper
RENAME_TRIES = 5        # Windows refuses a rename while a virus scanner is still reading the file
RENAME_WAIT = 0.5


def photo_key(path):
    """A fingerprint of the photo file itself (not its name: phones reuse
    names, and a teacher may rename a photo). None if it cannot be read."""
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
    except OSError:
        return None
    return h.hexdigest()[:16]


def piece_mark(key, box):
    """The note written inside a saved piece: the photo and the place on it."""
    if not key:
        return None
    return MARK + ("photo %s box %d %d %d %d" % ((key,) + tuple(int(v) for v in box))).encode("ascii")


def read_mark(path):
    """The note inside a saved piece, as (photo fingerprint, box); None for a
    file without one (saved by an older version, or not saved by this tool)."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return None
    at = head.find(MARK)
    if at < 0:
        return None
    m = re.match(rb"photo ([0-9a-f]{16}) box (-?\d+) (-?\d+) (-?\d+) (-?\d+)", head[at + len(MARK):])
    if not m:
        return None
    return m.group(1).decode("ascii"), tuple(int(v) for v in m.groups()[1:])


def jpeg_bytes(image, mark=None, quality=92):
    """The picture as a complete JPEG file in memory, with the note in it."""
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=quality)
    data = buf.getvalue()
    if mark:
        at = 2                                  # after the two bytes every JPEG starts with
        if data[2:4] == b"\xff\xe0":            # and after the JFIF header, which has to come first
            at = 4 + int.from_bytes(data[4:6], "big")
        data = data[:at] + b"\xff\xfe" + (len(mark) + 2).to_bytes(2, "big") + mark + data[at:]
    return data


def save_whole(image, dest, mark=None, quality=92):
    """Save a picture so that `dest` is either the whole picture or not there.
    It is written next to where it belongs under a name ending in '.part' and
    renamed when every byte is on the disk."""
    return write_whole(jpeg_bytes(image, mark, quality), dest)


def free_path(path):
    """The path itself if nothing is there yet, else "name 2.ext", "name 3.ext" ..."""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    k = 2
    while os.path.exists(f"{stem} {k}{ext}"):
        k += 1
    return f"{stem} {k}{ext}"


def write_whole(data, dest):
    """Write the bytes of a whole file so that `dest` is either all of it or
    not there: first under a name ending in '.part', then renamed. Used for a
    piece cut from a photo (save_whole) and for a PDF of packet pages."""
    part = dest + PART
    with open(part, "wb") as f:
        f.write(data)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass                                # a drive that cannot do this still has the whole file
    for tries_left in range(RENAME_TRIES - 1, -1, -1):
        try:
            os.replace(part, dest)
            return dest
        except PermissionError:
            if not tries_left:
                try:
                    os.remove(part)
                except OSError:
                    pass
                raise
            time.sleep(RENAME_WAIT)


def filed_already(folder, key, box, now=None):
    """The file in this folder that is this very piece (same photo, same place
    on it), or None. Also takes away a '.part' file nobody has touched for an
    hour: a computer stopped while saving it, and it is not a whole picture."""
    now = time.time() if now is None else now
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return None
    found = None
    for n in names:
        p = os.path.join(folder, n)
        if n.lower().endswith(".jpg" + PART):
            try:
                if now - os.path.getmtime(p) > SCRATCH_STALE_SECONDS:
                    os.remove(p)
            except OSError:
                pass
        elif key and not found and not n.startswith(".") and os.path.splitext(n)[1].lower() in (".jpg", ".jpeg"):
            got = read_mark(p)
            if got and got[0] == key and mutual_overlap(got[1], box) >= SAME_PIECE:
                found = p
    return found


def sorted_root(out_dir, sorted_dir=None):
    """Where the per-child folders live: sorted/ inside out_dir unless a
    separate folder (for example inside Google Drive) is given."""
    return sorted_dir or os.path.join(out_dir, "sorted")


# ----------------- a folder a person renamed, moved or took away -----------
#
# 'Wall Inbox' and the class folder are a person's folders. Somebody made
# them, Google Drive brings them to this computer, and the children's work is
# in them. The tool makes folders INSIDE them (done, a child's folder,
# 'Watcher status') and never the two folders themselves. It used to: every
# look at the inbox began with os.makedirs(<inbox>/done), which makes every
# folder on the way down as well. A teacher who renamed 'Wall Inbox' to
# 'Photos' had an empty 'Wall Inbox' back within five seconds, and the photos
# she put in 'Photos' were never seen. A class folder that was renamed came
# back under its old name, empty, and new work was filed into it. A Mac whose
# Google Drive signed out built the class again as ordinary folders on its own
# disk. Every call succeeded, so the log said nothing.
#   - make_inside makes a folder below one that has to be there already;
#   - folders_gone and gone_text are what the watcher looks at and says on
#     every look, before it reads or makes anything (see the watch loop).
# Nothing here is Mac-only or Windows-only.

GONE_NOTE = ("this computer cannot find the folder '{name}', so nothing is being sorted. The folder was renamed, "
             "moved or deleted. Give it its old name back in Google Drive and the sorting carries on by itself")
BACK_TEXT = ("the folders are there again (Arrivals is {inbox}); standing by for {grace} seconds while Google "
             "Drive catches up, then checking who should sort")


def holder_of(folder):
    """The folder that holds this one."""
    return os.path.dirname(os.path.abspath(os.path.normpath(folder)))


def is_gone(folder):
    """True when the folder is not there. A folder this program is not allowed
    to look at (macOS has not been told to let it read Google Drive yet) or
    cannot reach this instant is NOT gone: what is wrong then is said where
    the folder is read, in the words for that."""
    try:
        os.stat(folder)
    except (FileNotFoundError, NotADirectoryError):
        return True
    except OSError:
        return False
    return not os.path.isdir(folder)


def held_by(folder, root):
    """`root` when `folder` is inside it (or is it), otherwise None. For the
    doubtful-pieces folder: inside the class folder it is made with
    make_inside, so that the class folder is never made for its sake;
    anywhere else it is made whole, as it always was."""
    if not folder or not root:
        return None
    inner, outer = (os.path.normpath(os.path.abspath(p)) for p in (folder, root))
    return root if (inner + os.sep).startswith(outer + os.sep) else None


def folders_gone(*folders):
    """Those of the folders that are not there now, each once. A folder inside
    another one that is gone is left out: one thing happened, not two."""
    gone = []
    for f in folders:
        if f and is_gone(f) and os.path.normpath(f) not in gone:
            gone.append(os.path.normpath(f))
    return [g for g in gone if not any(g != o and g.startswith(o + os.sep) for o in gone)]


def gone_text(folder):
    """For the log, in plain words: this folder is not where it was, what that
    means for the photos, and the one thing to do."""
    folder = os.path.normpath(folder)
    name, holder = os.path.basename(folder), holder_of(folder)
    if os.path.isdir(holder):
        why = (f"It has been renamed, moved or deleted: the folder that holds it is there, and nothing in it is "
               f"called '{name}'.")
        cure = (f"To put it right, give the folder its old name back, '{name}', in Google Drive "
                f"(drive.google.com). If the new name is to stay, the settings file on this computer has to say "
                f"the new name, and then Setup has to be double-clicked.")
    else:
        why = (f"The folder that holds it is not there either, so most likely Google Drive is signed out, closed "
               f"or still starting on this computer; or the class folder was renamed, moved or deleted.")
        cure = (f"To put it right, open Google Drive on this computer and sign in. If the class folder was "
                f"renamed, give it its old name back, '{os.path.basename(holder)}', in Google Drive "
                f"(drive.google.com).")
    return (f"cannot find the folder '{name}' any more (it was {folder}). {why} Nothing is sorted until it is "
            f"back. Photos put into a folder with another name are not seen. This program does not make a new "
            f"folder in its place, because an empty folder with the old name would hide what happened. {cure} "
            f"The control tower carries on by itself when the folder is there again.")


def make_inside(root, path):
    """Make the folder `path`, which is inside `root`, and every folder on the
    way down to it, but never `root` itself. If `root` is not there, nothing
    is made and FileNotFoundError says so in plain words (gone_text). Each
    folder is made with one os.mkdir, which cannot make the folder above it,
    so there is no moment between looking and making in which a folder that
    was renamed could be made again. With no `root` (the tool's own sorted/
    and unsorted/, next to the program) everything is made, as it always was."""
    if not root:
        os.makedirs(path, exist_ok=True)
        return path
    rel = os.path.relpath(path, root)
    d = root
    for part in ([] if rel == os.curdir else rel.split(os.sep)):
        d = os.path.join(d, part)
        try:
            os.mkdir(d)
        except FileExistsError:
            pass
        except FileNotFoundError:
            if os.path.isdir(root):
                raise
            raise FileNotFoundError(gone_text(root)) from None
    if not os.path.isdir(root):
        raise FileNotFoundError(gone_text(root))
    return path


def make_child_folders(roster, out_dir, project=None, sorted_dir=None, inside=False):
    """Every child on the roster gets a folder, even before any work is filed;
    with a project, the project subfolder too. With `inside`, a class folder
    that the settings name has to be there already and is never made here
    (make_inside): that is how the watcher makes them after it has started."""
    root = sorted_root(out_dir, sorted_dir)
    for name in roster:
        d = os.path.join(root, safe_folder(name))
        if project:
            d = os.path.join(d, safe_folder(project))
        make_inside(sorted_dir if inside else None, d)


def make_new_child_folders(roster, out_dir, project, sorted_dir, made):
    """Folders for the children who are new on the class list, and for nobody
    else. For the watcher, which looks at the inbox every few seconds for
    weeks: making every child's folder on every look brought back, within
    seconds, a folder the teacher had just deleted (a child who left, the name
    still on the class list), and the teacher saw a folder that would not
    stay deleted.

    `made` is a dict the watcher keeps between looks: for each class folder
    and project, the names on the class list the last time folders were made.
    A name that is on the list now and was not then gets a folder; a name
    taken off the list and put back later gets one again. A folder is never
    taken away here. If the folders cannot be made (Google Drive not
    connected), nothing is remembered and the next look tries again. A piece
    filed for a child makes that child's folder whatever happened before
    (process_photo). Returns the names folders were made for. Shared by the
    Mac and Windows watchers; nothing here is Mac-only or Windows-only."""
    key = (os.path.normpath(sorted_root(out_dir, sorted_dir)), project or "")
    before = made.get(key)
    new = [n for n in roster if before is None or n not in before]
    if new:
        make_child_folders(new, out_dir, project, sorted_dir, inside=True)
    made[key] = set(roster)
    return new


def load_upright(path):
    """The picture in the file at `path`, turned the way its own orientation
    tag says, with every byte read and the file CLOSED again before this
    returns, whether the picture could be read or not. A file left open is
    harmless on a Mac. On a Windows PC a file that is still open cannot be
    moved or deleted, so a photo that was cut short stayed in 'done' and could
    not be put into 'failed', and the sorting stopped there."""
    with Image.open(path) as im:
        return ImageOps.exif_transpose(im).convert("RGB")


def open_photo(path, tmpdir=None):
    """Open a photo the reader can use. iPhones save HEIC, which plain Pillow
    cannot read. On a Mac, macOS's own `sips` converts it to JPEG locally;
    anywhere, the `pillow-heif` package does the same in process. Returns
    (PIL image, path of a readable file, temp path to delete or None).

    The converted JPEG goes into `tmpdir` (the tool's own scratch folder), or
    the computer's temp folder when none is given. It must NEVER be written
    next to the photo: the photo sits in the Drive-synced inbox, so a JPEG
    beside it would be uploaded to every other computer and would itself be
    picked up as a second wall photo, and if the program stopped mid-photo it
    would stay behind and be sorted again on the next start."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".heic", ".heif"):
        if tmpdir is None:
            import tempfile
            tmpdir = tempfile.gettempdir()
        tmp = os.path.join(tmpdir, f"baggage-claim-{os.getpid()}-{os.path.basename(path)}.jpg")
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
            load_upright(path).save(tmp, quality=95)
        except ImportError:
            if not IS_MAC:
                raise RuntimeError("HEIC photo but pillow-heif is not installed; run: pip install pillow-heif")
            res = subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "95", path, "--out", tmp],
                                 capture_output=True, text=True)
            if res.returncode != 0 or not os.path.exists(tmp):
                raise RuntimeError(f"could not convert {os.path.basename(path)}: {res.stderr.strip()}")
        return load_upright(tmp), tmp, tmp
    return load_upright(path), path, None


def is_settled(path, wait=2.0):
    """True once a file has stopped growing: Google Drive writes a syncing
    photo in pieces, and reading it early gives a half image."""
    try:
        a = os.path.getsize(path)
        time.sleep(wait)
        b = os.path.getsize(path)
    except OSError:
        return False
    if a != b or b == 0:
        return False
    try:
        # Read ALL of it, not the first bytes. Google Drive lists a photo
        # before it has delivered it, hands over the first bytes, and then
        # fails the rest with "Resource deadlock avoided". A photo that cannot
        # be read to its end is still arriving: it stays in the inbox and is
        # tried again on the next look. Found on a real wall, October 1, 2026,
        # when one such photo was moved to 'failed' and nothing was sorted.
        with open(path, "rb") as f:
            while f.read(1 << 20):
                pass
        return True
    except OSError:
        return False


def unsorted_root(out_dir, unsorted_dir=None):
    return unsorted_dir or os.path.join(out_dir, "unsorted")


SCRATCH_FOLDER = ".tmp"
SCRATCH_STALE_SECONDS = 3600   # scratch untouched for this long was left by a watcher stopped in the middle of a photo


def clear_old_scratch(root, keep, now=None):
    """Remove what a watcher that was stopped in the middle of a photo left in
    the scratch folder. Only things nobody has touched for an hour: a photo
    takes seconds, and another watcher's photo may be in there right now."""
    now = time.time() if now is None else now
    try:
        names = os.listdir(root)
    except OSError:
        return
    for n in names:
        p = os.path.join(root, n)
        try:
            if p == keep or now - os.path.getmtime(p) < SCRATCH_STALE_SECONDS:
                continue
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
        except OSError:
            continue    # gone this instant, or in use: not ours to worry about


DRIVE_FOLDER_NAMES = ("my drive", "shared drives", "google drive")


def inside_google_drive(path):
    """True when a folder is inside Google Drive on this computer: under 'My
    Drive' or 'Shared drives' (Windows and Mac), or under the Mac's
    'GoogleDrive-<account>' folder. Told by the folder names alone, so it
    works the same on both and for a Drive that is not signed in right now. A
    folder of the computer's own that merely has such a name counts as well;
    the only cost is that the scratch copies go to the temp folder."""
    parts = [p.lower() for p in re.split(r"[\\/]+", os.path.abspath(path)) if p]
    return any(p in DRIVE_FOLDER_NAMES or p.startswith("googledrive-") for p in parts)


def scratch_home(out_dir):
    """The folder that holds the scratch folder: the tool folder, unless the
    tool folder is itself inside Google Drive (the zip was unzipped where it
    was found, in the class's Drive folder). Then it is the computer's own
    temp folder. Everything in scratch is a copy of children's work: the JPEG
    made from an iPhone photo, every crop. Inside Drive each of them would be
    uploaded and, when it is deleted ten seconds later, kept in Drive's trash
    for 30 days."""
    if inside_google_drive(out_dir):
        return os.path.join(tempfile.gettempdir(), "baggage-claim")
    return out_dir


def scratch_folder(out_dir):
    """A scratch folder for ONE photo: <out_dir>/.tmp/<process id>-<random>
    (or, for a tool folder inside Google Drive, the same under the computer's
    temp folder: see scratch_home).
    One tool folder can watch several classes, one watcher each, and they all
    share <out_dir>/.tmp. When the crops went straight into it, under the same
    names (crop-1.png, upright.jpg), two classes posting in the same ten
    seconds overwrote each other's crops, and whichever finished first deleted
    the other's in the middle of its photo. So nothing two photos could both
    write is ever written into .tmp itself, only into a folder of their own."""
    root = os.path.join(scratch_home(out_dir), SCRATCH_FOLDER)
    for tries_left in (2, 1, 0):
        os.makedirs(root, exist_ok=True)
        try:
            mine = tempfile.mkdtemp(prefix=f"{os.getpid()}-", dir=root)
            break
        except FileNotFoundError:
            # another watcher finished this instant and took the empty .tmp away
            if not tries_left:
                raise
    clear_old_scratch(root, mine)
    return mine


def drop_scratch(tmpdir):
    """Delete this photo's own scratch folder, and .tmp itself once it is
    empty. Never anything that belongs to another photo."""
    shutil.rmtree(tmpdir, ignore_errors=True)
    try:
        os.rmdir(os.path.dirname(tmpdir))     # refuses while another photo's folder is in it
    except OSError:
        pass


# ------------------------------------------ name read, picture to check ---
#
# When one photo takes in the whole wall, or pale paper hangs on a pale wall,
# the paper detectors find fewer papers than there are name labels, and the
# pieces are cut around the labels instead (pieces_from_labels). The same
# happens when the detectors found papers and the labels are not on them. On
# such a piece the NAME was read; what is in doubt is the PICTURE, because
# edges guessed from the words can take in part of a neighbour's paper. The
# piece goes to a person either way, but everything that person sees has to
# say which of the two is in doubt. A file called 'GUESS <child>' says the
# name is, and here that is not true: a teacher who finds 25 of them concludes
# the name reader failed. So these are called 'CHECK PICTURE <child> ...',
# the log and the status file say why, and a note in the same folder says
# what happened and what to do. 'GUESS' is kept for a name that really is one.
#
# Shared by the Mac and Windows watchers; nothing here is Mac-only or
# Windows-only.

EDGES = "edges"                 # the 'reason' on a piece whose name was read and whose edges were guessed
CHECK_PICTURE = "CHECK PICTURE"
EDGES_CAUSE = "pale paper on a pale wall, or papers hung with no edge showing between them"


def edges_guessed(results):
    """The pieces whose name was read and whose paper edges were guessed."""
    return [r for r in results if r.get("reason") == EDGES]


# Which way up one paper hangs, on a computer whose reader looks at a picture
# one way up at a time (a Windows PC). Apple's reader sees every way up in one
# look and says which way each line faces. The Windows reader is handed one
# paper the way it is cut from the photo (AS_IT_IS), and the build of
# September 28, 2026 proved that it reads upside-down text as well as upright.
# Whether it SAYS the text was upside down is not known. When it does not,
# the words of a name of two words run right to left and give it away; a name
# of one word gives nothing away, and "Theo, upright" is what the reader says
# of a paper that hangs upside down. So a name is never believed on one look:
# the paper is looked at turned over as well (second_look). Three things can
# come of that:
#   the name does not read turned over, or reads there as upside down: the
#     first look was right, and nothing changes;
#   the first look said upside down: the paper is turned, as before;
#   the name reads for certain both ways up and the reader calls both
#     upright: nothing the reader gives can say which look is right. The
#     piece is filed under the child (the name is not in doubt) the first way
#     the name read, which is the way it is in the photo unless the paper
#     hangs on its side, and the log says so in plain words (tell_way_up).

EITHER_WAY_UP = "either"        # 'way_up' on a piece whose name read the same the right way up and turned over


def second_look(name_here, read_turned_over):
    """Is a paper, whose name was read for certain and upright in one look,
    read the same when it is turned over? name_here: the name that was read.
    read_turned_over(): the texts read on the paper turned upside down and
    what they match. True means the reader cannot tell the two ways up
    apart, so which way up the paper hangs is not known. Only a name read ON
    the paper turned over, for certain, the same name, and called upright
    there, counts: nonsense, another name, a name the reader calls upside
    down, or a label read on the wall beside the paper all leave the first
    look standing."""
    texts, m = read_turned_over()
    return (m["status"] == "confident" and m["name"] == name_here
            and name_line(texts, m) == ("own", 0))


def way_up_unsure(results):
    """The pieces filed without knowing whether they are the right way up."""
    return [r for r in results if r.get("way_up") == EITHER_WAY_UP]


def tell_way_up(photo_name, results, log=print):
    """Say in the log, once for a photo, which pieces were filed without the
    tool knowing which way up they are, and what to do. Returns the line, or
    None when there is no such piece."""
    unsure = way_up_unsure(results)
    if not unsure:
        return None
    n = len(unsure)
    which = "piece " + str(unsure[0]["piece"]) if n == 1 else (
        "pieces " + ", ".join(str(r["piece"]) for r in unsure[:-1]) + " and " + str(unsure[-1]["piece"]))
    line = (f"{photo_name}: the name was read on {which}, and {'it is in the' if n == 1 else 'each is in its'} "
            f"child's folder. What the tool could not check is which way up "
            f"{'that paper hangs' if n == 1 else 'those papers hang'}: this computer's reader read the name the "
            f"same with the paper one way up and with it turned upside down, and did not say which was which. "
            f"So {'it was' if n == 1 else 'each was'} filed the first way the name read. A paper that is the "
            f"right way up in the photo is filed the right way up. One that is upside down or on its side in "
            f"the photo may be upside down in the child's folder: open the picture and turn it round.")
    log(line)
    return line


def batch_text(results, unsorted_name="unsorted"):
    """'25 pieces, 0 filed, 25 to unsorted', and the cause when the cause is
    the photo and not the names. This is the line in the log and the 'Last
    batch' line of the status file, which is all a person looking from
    somewhere else has to go on."""
    conf = sum(1 for r in results if r["status"] == "confident")
    pages = sum(1 for r in results if r.get("packet"))
    count = (f"{len(results)} pieces" if not pages else f"{pages} packet pages" if pages == len(results)
             else f"{len(results) - pages} pieces and {pages} packet pages")
    text = f"{count}, {conf} filed, {len(results) - conf} to unsorted"
    guessed = edges_guessed(results)
    n = len(guessed)
    if n and all(r.get("why") == OFF_THE_PHOTO for r in guessed):
        text += (f" (on {n} of them the name was read, but {OFF_THE_PHOTO}, so the whole paper is not in the "
                 f"picture. A person checks each picture. See the note in '{unsorted_name}')")
    elif n:
        text += (f" (on {n} of them the name was read, but the tool could not find the edges of the papers for "
                 f"certain: {EDGES_CAUSE}. A person checks each picture. See the note in '{unsorted_name}')")
    return text


def edges_found_text(labels, papers):
    """What the paper detectors found, against the name labels that were read."""
    found = f"{papers} paper{'' if papers == 1 else 's'}"
    if papers < labels:
        return f"{labels} name labels read, and the edges of {found} found, fewer than there are names"
    return (f"{labels} name labels read, and {found} found, but some of the name labels were not on or beside "
            f"the papers that were found, so those could not be trusted")


def check_picture_note(photo_name, project, count, labels, papers):
    """The note for the teacher, in plain words. It names the photo and the
    numbers, never a child."""
    return (f"Baggage Claim read the names on this photo. It could not find the edges of the papers.\n\n"
            f"Photo:    {photo_name}\n"
            f"Project:  {project or ''}\n"
            f"Pieces:   {count} in this folder, each called '{CHECK_PICTURE}', then the child's name\n\n"
            f"What happened\n"
            f"The name reader worked. What the tool could not find for certain is where each paper begins and "
            f"ends: {edges_found_text(labels, papers)}. That happens when pale paper hangs on a pale wall, "
            f"when two papers hang edge to edge with no line showing between them, or when a paper runs off "
            f"the edge of the photo. It is not the number of papers: one photo can hold the whole wall. "
            f"So each of these pieces was cut out around its name label, and "
            f"where the paper begins and ends is a guess: a piece may be missing part of the child's paper, or "
            f"may show part of a neighbour's. The tool never files a piece cut that way. It asks a person to "
            f"look.\n\n"
            f"What to do: one of these two\n"
            f"1. Photograph those papers again against a dark background, the whole of each paper in the "
            f"photo and a little of the background showing on every side, and share the new photo to "
            f"Arrivals. Then delete the "
            f"'{CHECK_PICTURE}' files from this photo.\n"
            f"2. Or open each '{CHECK_PICTURE}' file. The name in the file's name is the name read from the "
            f"label. If the picture shows that child's whole paper and nothing of a neighbour's, move the file "
            f"into that child's folder. If it does not, delete it and photograph that paper again.\n\n"
            f"A file called 'GUESS' is different: there the name itself could not be read for certain.\n\n"
            f"You can delete this note when you are done.\n")


def tell_edges_guessed(photo_name, project, results, labels, papers, note_dir, log=print):
    """Say, in the log and in a note beside the pieces, that the names on this
    photo were read and the pictures are what a person has to check. Returns
    the note's path, or None when no piece of this photo is of that kind or
    the note could not be written."""
    n = len(edges_guessed(results))
    if not n:
        return None
    folder = os.path.basename(os.path.normpath(note_dir))
    note = os.path.join(note_dir, safe_folder(f"{CHECK_PICTURE} - read me - {project or ''} - {photo_name}") + ".txt")
    try:
        with open(note, "w", encoding="utf-8") as f:
            f.write(check_picture_note(photo_name, project, n, labels, papers))
        where = f"A note that says this is in '{folder}'."
    except OSError as e:
        note, where = None, f"A note for the teacher could not be written ({e})."
    off = sum(1 for r in edges_guessed(results) if r.get("why") == OFF_THE_PHOTO)
    cause = (f"on {off} of them {OFF_THE_PHOTO}" if off == n else
             f"the usual cause is {EDGES_CAUSE}" + (f"; on {off} of them {OFF_THE_PHOTO}" if off else ""))
    read = sum(1 for r in results if r["status"] == "confident" or r.get("reason") == EDGES)
    which = ("each paper begins and ends" if n == len(results) else "one paper begins and ends" if n == 1
             else f"{n} of the papers begin and end")
    log(f"{photo_name}: the name was read on {read} of the {len(results)} pieces, so the name reader worked. What "
        f"the tool could not find for certain is where {which} "
        f"({edges_found_text(labels, papers)}; "
        f"{cause}), so {'it was' if n == 1 else 'each of those was'} cut out around its name label and its "
        f"edges are a guess. {'That piece is' if n == 1 else f'Those {n} pieces are'} "
        f"in '{folder}', called '{CHECK_PICTURE}' and the child's name, for a person to look at the picture. "
        f"To have them filed by the tool, photograph those papers again against a dark background, with a "
        f"little of the background showing on every side of each paper. "
        f"{where}")
    return note


# A title sign on the wall is a paper too, and the detectors find it. It has no
# child's name on it, so it went to Unsorted for a person to look at, every
# time. On a real wall a sign cannot be told from a child's work that has lost
# its name sticker: one of the two signs on the wall of October 1 had no words
# the reader could read, and both were on the children's own paper. So the
# teacher says which paper is the sign, the way she says whose each piece is:
# a typed sticker that reads TITLE, in capitals, on its own. That paper is left
# out: not filed, not sent to a person, one line in the log. A paper with no
# child's name and no TITLE sticker still goes to Unsorted; it may be a child's.
TITLE_STICKER = "title"


def is_title_sign(texts):
    """True when one of the lines read on this paper is the TITLE sticker: the
    one word, in capitals, on a line of its own (a speck read as a letter
    beside it does not count against it). 'Title' at the top of a child's
    writing page is not in capitals, and is not the sticker."""
    for t in texts:
        raw = t["text"].strip()
        words = raw.split()
        if not words or len(words) > 3 or raw != raw.upper():
            continue
        core = norm(" ".join(w for w in words if len(norm(w)) > 1))
        if TITLE_STICKER in (norm(raw), core):
            return True
    return False


def process_photo(path, roster, out_dir, project, grid=None, log=print, grade="", sorted_dir=None, unsorted_dir=None):
    """Cut one photo and file its pieces, in a scratch folder of its own that
    is taken away again whether the photo was sorted or could not be."""
    tmpdir = scratch_folder(out_dir)
    try:
        return cut_and_file(path, roster, out_dir, project, tmpdir, grid, log, grade, sorted_dir, unsorted_dir)
    finally:
        drop_scratch(tmpdir)


def cut_and_file(path, roster, out_dir, project, tmpdir, grid=None, log=print, grade="", sorted_dir=None,
                 unsorted_dir=None):
    photo_name = os.path.basename(path)
    key = photo_key(path)       # of the photo as it arrived, before it is converted or turned
    img, path, tmp_photo = open_photo(path, tmpdir)
    # Which way is up? The phone's own orientation tag was already applied by
    # open_photo, but a phone tilted while shooting from the side gets that tag
    # a quarter turn wrong, and then every crop comes out on its side. The
    # typed name labels know: the text reader reports which way each line
    # reads, and the labels' majority turns the whole photo upright ONCE, here,
    # so detection, every crop and every coordinate downstream see an upright
    # photo. Ninety per cent of photos need no turn and nothing changes.
    whole = join_rows(read_photo_text(img, path, tmpdir))
    photo_turn = majority_angle(whole, roster)
    if photo_turn:
        img = turn_upright(img, photo_turn)
        path = os.path.join(tmpdir, "upright.jpg")
        img.save(path, quality=95)
        whole = join_rows(read_photo_text(img, path, tmpdir))
        log(f"{photo_name}: photo was on its side; turned it upright using the name labels ({photo_turn} degrees)")
    area = img.width * img.height
    papers_found = 0        # what the paper detectors found, when the pieces were cut around the labels instead
    if grid:
        quads, how = grid_boxes(img, *grid), f"grid {grid[0]}x{grid[1]}"
    else:
        quads, how = detect_pieces(img, path), "detectors"
        # The name labels are the second opinion on the colour blobs: a wall
        # that shows clearly more children's labels than the blobs found
        # papers was not read right by colour, on any computer. Look again
        # without it, and let the labels fill in what the detectors miss.
        if LAST_DETECTOR == "colour" and labelled_children(whole, roster) >= len(quads) + 2:
            quads = detect_pieces(img, path, allow_colour=False)
        # only when the paper detectors had nothing to work with (pale on pale);
        # coloured paper or a coloured wall is the case they are good at
        by_label = None if LAST_DETECTOR == "colour" else pieces_from_labels(img, whole, roster, quads)
        if by_label:
            papers_found = len(quads)
            mixed = with_found_edges(img, by_label, quads, roster)
            guessed = sum(1 for q in mixed if q.get("label"))
            if guessed < len(mixed):
                papers_found = len(mixed) - guessed
            how = (f"name labels ({len(by_label)} readable, detectors found {len(quads)})" if guessed == len(mixed)
                   else f"{len(mixed)} name labels; paper edges found for {len(mixed) - guessed}")
            quads = mixed
        else:
            more = add_missing_papers(img, whole, roster, quads)
            if len(more) != len(quads) or any(q.get("edges") for q in more):
                how = f"detectors, and {sum(1 for q in more if q.get('edges'))} found around a name label"
                quads = more
    log(f"{photo_name}: found {len(quads)} pieces ({how})")

    results = []
    # Second, independent reader: the whole photo at once. Its lines are
    # handed to whichever piece they sit inside. Two readers disagree in
    # useful ways; the union is matched and the best evidence wins.
    # Pass 1: read every piece on its own, and read the wall around it.
    # Pass 2: every line read near the pieces goes to exactly one piece, the
    # one it sits inside or the nearest one. A label pinned beside a paper
    # must never count for the neighbour as well.
    signs = 0       # title signs found among the papers, and left out
    crops, own, pool = [], [], []
    for i, q in enumerate(quads, 1):
        crop = warp(img, q)
        tmp = os.path.join(tmpdir, f"crop-{i}.png")
        crop.save(tmp)
        own.append(read_piece(tmp, crop))
        pool += read_neighborhood(img, q, [], tmpdir, i)
        crops.append((crop, tmp))
    nearby = assign_texts(pool_lines(pool), quads)
    for i, q in enumerate(quads, 1):
        crop, tmp = crops[i - 1]
        texts = own[i - 1] + nearby[i - 1]
        if q.get("label"):
            # the label this piece was built around outranks any neighbour's label
            texts = [{**q["label"], "x": 0, "y": 0, "w": 0, "h": 0, "nobox": True, "rel_y": 0.0}]
        m = match_name(texts, roster)
        if m["status"] != "confident" and q.get("from_label") and not q.get("label"):
            # the paper's edges are exact and were found from its own name label,
            # read on the whole photo; the close read of the piece missed it (the
            # reader of a PC misses one label now and then). That label is the name.
            lab = q["from_label"]
            with_label = texts + [{**lab, "x": 0, "y": 0, "w": 0, "h": 0, "nobox": True, "rel_y": 0.0}]
            m2 = match_name(with_label, roster)
            if m2["status"] == "confident" and m2["name"] == whose(lab, roster):
                texts, m = with_label, m2
        # A paper hung sideways on the wall: the label that decided the match
        # says which way the paper's own up is. Turn the crop, read it again
        # so every box and rel_y is in the upright frame, and match again.
        # The same turn applies whether the piece is filed or goes to unsorted.
        # Which way is up for THIS paper. A typed name read for certain says
        # so itself: the way it faces is the way the paper faces. The reader
        # can also misread an upright label as upside-down nonsense; then
        # there is no certain name this way up, and the piece is read turned
        # the way the reader suggests, then the other ways, until the name
        # reads for certain. A turn is only ever made on a certain name.
        base, turn, other = crop, 0, None

        def read_turned(total):
            c = turn_upright(base, total) if total else base
            c.save(tmp)
            t = read_piece(tmp, c) + nearby[i - 1]
            return c, t, match_name(t, roster)

        if q.get("label"):
            turn = text_angle(q["label"])
        elif m["status"] == "confident":
            turn = name_line(texts, m)[1]
        else:
            hint = hint_angle(texts)
            for way in [hint] + [w for w in (180, 90, 270) if w != hint]:
                if not way:
                    continue
                _, t2, m2 = read_turned(way)
                if m2["status"] == "confident":
                    where, facing = name_line(t2, m2)
                    turn, other = ((way + facing) % 360 if where == "own" else facing), m2
                    break
        if turn and q.get("label"):
            crop = turn_upright(base, turn)
            crop.save(tmp)
        elif turn:
            crop, t2, m2 = read_turned(turn)
            sure = other or m
            if m2["status"] == "confident" and m2["name"] == sure["name"]:
                texts, m = t2, m2
            else:       # read for certain another way up; its box is not in this frame
                m = {**sure, "box": None}
        else:
            crop = base
            crop.save(tmp)
            if other:
                m = {**other, "box": None}
        # One look is not enough for a reader that looks one way up at a time:
        # it may have read the name upside down and called it upright. Look at
        # the paper turned over as well (see second_look).
        if (ONE_LOOK and not q.get("label") and m["status"] == "confident"
                and name_line(texts, m) == ("own", 0)
                and second_look(m["name"], lambda: read_turned((turn + 180) % 360)[1:])):
            m["way_up"] = EITHER_WAY_UP
        if q.get("label") and m["status"] == "confident":
            # the name is right but the paper's edges were guessed from the
            # words, and a guessed crop can include a neighbour's work. A
            # person checks the picture; the tool does not file it. The
            # reason travels with the piece, so its file name, the log, the
            # report and the status file can say the name is not the doubt.
            m["status"] = "unsure"
            m["reason"] = EDGES
            if q.get("why"):
                m["why"] = q["why"]
        if m["status"] != "confident" and is_title_sign(own[i - 1] + nearby[i - 1] + texts):
            # the teacher's TITLE sticker: this paper is the sign, not a child's work
            os.remove(tmp)
            signs += 1
            log(f"  piece {i}: title sign (it has a TITLE sticker), left out: not filed, not sent to a person")
            continue
        mark = piece_mark(key, quad_bbox(q))
        already = None
        if m["status"] == "confident":
            dest_dir = os.path.join(sorted_root(out_dir, sorted_dir), safe_folder(m["name"]), safe_folder(project))
            make_inside(sorted_dir, dest_dir)       # the child's folder, never the class folder itself
            # sorted before (the computer stopped halfway, or the teacher put
            # the photo back): a child who has this piece is not given it again
            already = filed_already(dest_dir, key, quad_bbox(q))
            dest = already or os.path.join(dest_dir, piece_name(project, grade, dest_dir))
            if not already:
                save_whole(crop, dest, mark)
        else:
            guess = safe_folder(m["name"]) if m["name"] else "no-name"
            dest_dir = unsorted_root(out_dir, unsorted_dir)
            # the doubtful-pieces folder is made when it is needed, the class folder around it never
            make_inside(held_by(unsorted_dir, sorted_dir), os.path.join(dest_dir, "name-strips"))
            photo_id = os.path.splitext(photo_name)[0]
            # cleaned like every other name the tool makes, so the file can
            # exist on a Windows PC as well as on a Mac
            lead = CHECK_PICTURE if m.get("reason") == EDGES else "GUESS"
            base = safe_folder(f"{lead} {guess} - {project} {grade} - {photo_id} {i:02d}") + ".jpg"
            dest = os.path.join(dest_dir, base)
            save_whole(crop, dest, mark)
            save_whole(name_strip(crop, m["box"]), os.path.join(dest_dir, "name-strips", base))
        os.remove(tmp)
        rel = (sorted_dir and m["status"] == "confident") or (unsorted_dir and m["status"] != "confident")
        results.append({"piece": i, "file": dest if rel else os.path.relpath(dest, out_dir),
                        "bbox": quad_bbox(q), "turned": (photo_turn + turn) % 360, "already": bool(already), **m})
        shown = "check picture" if m.get("reason") == EDGES else m["status"]
        log(f"  piece {i}: {shown:12s} {m['name'] or '-':12s} "
            f"read '{m['text'] or ''}' score {m['score']}")
        if m.get("why") == OFF_THE_PHOTO:
            log(f"  piece {i}: {OFF_THE_PHOTO}, so the whole paper is not in the picture. Photograph it again "
                f"with a little of the dark background showing on every side of the paper.")
        if already:
            log(f"  piece {i}: {m['name']} already has this piece from this photo "
                f"('{os.path.basename(already)}'), so it was not filed a second time")
    tell_edges_guessed(photo_name, project, results, len(quads), papers_found,
                       unsorted_root(out_dir, unsorted_dir), log)
    tell_way_up(photo_name, results, log)
    if signs:
        log(f"{photo_name}: {signs} title sign{'' if signs == 1 else 's'} left out")
    again = sum(1 for r in results if r["already"])
    if again:
        log(f"{photo_name}: this photo has been sorted before. {again} of its {len(results)} pieces were already "
            f"in the children's folders and were left as they are; nobody was given a piece twice")
    if tmp_photo and os.path.exists(tmp_photo):   # process_photo takes the scratch folder away as well
        os.remove(tmp_photo)
    return results


# ------------------------------------------------------------ PDF packets ---
#
# A teacher can drop a PDF packet into Wall Inbox (at the top, or in a project
# folder) exactly like a photo: 300 pages of the children's work, scanned or
# made on a computer. The rule the teacher is given: the child's name TYPED in
# a corner of the FIRST page of that child's work (a name sticker), and, if
# they like, "page 2 of 3" beside it. The pages that follow need no sticker:
# a page with no name sticker belongs to the child named on the page before
# it, because that is the order the pages were scanned in (October 7, 2026;
# until then the name had to be on every page). A name on every page still
# works, and is the only way when one child's pages are not next to each other.
#
#   1. Each page is read. A page made on a computer has its words inside the
#      PDF (the text layer): those lines and where they sit are taken as they
#      are. A scanned page has none, or none that is a name on the class
#      list: it is drawn as a picture (about 200 dots to the inch) and read by
#      this computer's own reader, the same way as a photo. Either way the
#      lines are in the frame of the page as a person sees it, so the rule
#      about names at the top and bottom edge (match_name) works unchanged.
#   2. A "page X of Y" (or "X of Y", or "X/Y") beside the name is taken off
#      the line and kept as that page's number. One exception: "X/Y" that is
#      the class's own grade ("1/2" in a class whose grade is 1-2, "3/4",
#      "5/6") is the grade printed on the sheet, never a page number
#      (grade_written_with_a_slash).
#   3. All of one child's pages read for certain go into ONE PDF in that
#      child's project folder, in the order they are in the packet, named like
#      a photo's piece ('<project> <grade>.pdf', then ' 2' ...). The pages are
#      copied from the packet, not redrawn, so nothing loses quality.
#   4. A page with NO name sticker goes with the page before it: three pages
#      scanned one after the other, the name on the first only, are all that
#      child's. That holds until the next page that has a name. It is the one
#      case where a page is given to a child because of where it sits, and it
#      stops the moment the tool is not sure whose pages it is in:
#        - a page that HAS what looks like a name sticker (a short line at the
#          top or bottom edge, close to a child's name) that could not be read
#          for certain goes to a person, and so does every page with no
#          sticker after it, up to the next name read for certain. It may be
#          the next child's first page, so nothing after it is assumed;
#        - pages before the first name in the packet go to a person: there is
#          no page before them to go with.
#      A page sent to a person is a one-page PDF in 'Unsorted - needs a
#      person' called 'GUESS <best guess> - ... page 012.pdf'.
#      A page that went with the page before it takes the next page number
#      when that page carries one ("page 1 of 3", then two pages with no
#      sticker, is a whole set of three), so rule 5 still proves the set.
#   5. A child whose numbered pages are not a whole set (a page missing, or
#      one there twice) is not filed at all: every page of that child goes to
#      a person, called 'CHECK PAGES <child> - ...', because the name was read
#      and what is in doubt is the set.
#   6. A note in Unsorted says what happened, page by page and child by child
#      (packet_note), and the log gets one line (packet_text).
#
# Filed once: every PDF the tool writes carries, in its own properties, the
# packet's fingerprint (the same fingerprint a photo gets, photo_key) and the
# packet page numbers it holds. Before a child's pages are filed, the child's
# project folder is looked through, and a page that is already there is not
# filed again. Nothing leaves this computer: pypdfium2 and pypdf are libraries
# that run here, and they are loaded only when a packet arrives, so a
# computer without them still sorts photos.
#
# Shared by the Mac and Windows watchers; nothing here is Mac-only or
# Windows-only.

PACKET_TEXT_LAYER = True     # the tests switch this off to prove the reader alone files every page
PACKET_DPI = 200             # a page is drawn at this many dots to the inch for the reader...
PACKET_MAX_SIDE = 3000       # ...but never longer than this on its long side
PACKET_MARK = "/BaggageClaimPages"      # the property that says which packet pages a PDF holds
PACKET_NOTE = "PACKET - read me"
CHECK_PAGES = "CHECK PAGES"
PAGES = "pages"              # the 'reason' on a page whose name was read and whose child's set is not whole
PACKET_BAD = "packet"        # kinds for why_not_sorted
PACKET_PARTS = "pdf-parts"
PACKET_PARTS_WHY = ("this computer cannot read PDF packets, because two parts it needs (pypdfium2 and pypdf) "
                    "are not installed on it")
PACKET_BAD_WHY = ("the file could not be opened as a PDF. It is damaged, or it did not finish arriving, or it "
                  "is not a PDF")
PACKET_LOCKED_WHY = "the PDF is locked with a password, so its pages cannot be read"
PACKET_EMPTY_WHY = "the PDF has no pages"


class PacketError(Exception):
    """A packet that cannot be sorted, with the kind and the reason in plain
    words for why_not_sorted."""
    def __init__(self, kind, why):
        super().__init__(why)
        self.kind, self.why = kind, why


def is_packet(path):
    return os.path.splitext(str(path))[1].lower() in PACKET_EXT


def pdf_parts():
    """The two PDF libraries, loaded now and not before: photo sorting never
    needs them."""
    try:
        import pypdfium2
        import pypdf
    except ImportError:
        raise PacketError(PACKET_PARTS, PACKET_PARTS_WHY) from None
    return pypdfium2, pypdf


def pdf_parts_text():
    """The self-check line: can PDF packets be read on this computer?"""
    try:
        pdfium, pypdf = pdf_parts()
    except PacketError:
        missing = []
        for mod in ("pypdfium2", "pypdf"):
            try:
                __import__(mod)
            except ImportError:
                missing.append(mod)
        return (f"WARN: PDF packets cannot be read on this computer ({' and '.join(missing) or 'a part'} not "
                f"installed; run: pip install pypdfium2 pypdf). Photos are sorted as usual.")
    ver = getattr(getattr(pdfium, "version", None), "PYPDFIUM_INFO", None) or getattr(pdfium, "V_PYPDFIUM2", "")
    return f"ok: PDF packets can be read (pypdfium2 {ver}, pypdf {getattr(pypdf, '__version__', '')})"


PAGE_NUMBER_FORMS = (
    # the reader can run a name and "page" together ("Theopage 2 of 2") or
    # leave out a space ("2of 2"), so neither needs a space around it
    # and "of" can come back as "ot" or "0f" ("Nadia page 1 ot 3")
    ("page", re.compile(r"(?:page|\bpg|\bp)\s*\.?\s*(\d{1,3})\s*(?:o[ft]|0f|/)\s*(\d{1,3})(?!\d)", re.I)),
    ("of", re.compile(r"(?<![\d/])(\d{1,3})\s*(?:o[ft]|0f)\s*(\d{1,3})(?!\d)", re.I)),
    # "2/3": only small numbers, and never inside a date such as 9/30/2026
    ("slash", re.compile(r"(?<![\d/])(\d{1,2})\s*/\s*(\d{1,2})(?![\d/])")),
)
PAGE_NUMBER_MOST = 12        # "X/Y" with Y above this is a date or a fraction, not a page number


def grade_written_with_a_slash(grade):
    """{(1, 2)} for a class whose grade is "1-2" (or "1/2", "1st and 2nd"):
    the grade the way a worksheet prints it beside the child's name, "1/2".
    Empty for a grade that is not two numbers ("Kindergarten", "3", "").
    On October 7, 2026 the first real packet of a 1-2 class had "1/2" printed
    at the top of every sheet; it was read as "page 1 of 2", so a child with
    one page was held back for a second page that never existed. The same
    goes for a 3-4 class ("3/4") and a 5-6 class ("5/6")."""
    nums = re.findall(r"\d+", grade or "")
    return {(int(nums[0]), int(nums[1]))} if len(nums) == 2 else set()


def take_page_number(text, not_pages=()):
    """('Maya Torres', (2, 3, 'page')) for 'Maya Torres  page 2 of 3': the
    line without its page number, and the number. (text, None) when the line
    has none. `not_pages` holds the class's grade (grade_written_with_a_slash):
    "1/2" in a 1-2 class is the grade, so it is taken off the line like a
    page number but is not one. "page 1 of 2" and "1 of 2" still are."""
    if not_pages:       # the grade comes off the line first, wherever it is
        slash = PAGE_NUMBER_FORMS[-1][1]
        # ...unless it says "page" in front: "page 1/2" is a page number in every class
        kept = slash.sub(lambda mt: " " if (int(mt.group(1)), int(mt.group(2))) in not_pages and not re.search(
            r"(?:page|\bpg|\bp)\s*\.?\s*$", text[:mt.start()], re.I) else mt.group(0), text)
        if kept != text:
            text = re.sub(r"\s+", " ", kept).strip(" -|,;:.()[]\t")
    for form, rx in PAGE_NUMBER_FORMS:
        for mt in rx.finditer(text):
            x, y = int(mt.group(1)), int(mt.group(2))
            if y < 1 or x < 1 or (form != "page" and x > y) or (form == "slash" and y > PAGE_NUMBER_MOST):
                continue
            rest = (text[:mt.start()] + " " + text[mt.end():]).strip(" -|,;:.()[]\t")
            return re.sub(r"\s+", " ", rest), (x, y, form)
    return text, None


def page_lines(lines, height, not_pages=()):
    """The lines of one page ready for match_name, and the page numbers found
    on them. Each line gets its rel_y (see match_name); a page number is taken
    off its line and kept with that line's box. `not_pages`: see
    take_page_number."""
    out, numbers = [], []
    for t in lines:
        text, num = take_page_number((t.get("text") or "").strip(), not_pages)
        rel_y = (t["y"] + t["h"] / 2) / max(1, height)
        if num:
            numbers.append({"number": num, "x": t["x"], "y": t["y"], "w": t["w"], "h": t["h"], "rel_y": rel_y})
        if text:
            out.append({**t, "text": text, "rel_y": rel_y})
    return out, numbers


def page_number_by_name(numbers, m, width):
    """The page number that belongs to the name that was read: on the name's
    own line, or close beside it, or a 'page X of Y' along the top or bottom
    edge. None when the page carries none."""
    if not numbers or not m.get("box"):
        return None
    x0, y0, x1, y1 = m["box"]
    h = max(1, y1 - y0)
    cy = (y0 + y1) / 2
    near = []
    for n in numbers:
        ncy = n["y"] + n["h"] / 2
        gap = max(0, n["x"] - x1, x0 - (n["x"] + n["w"]))
        edge = n["rel_y"] <= EDGE_BAND or n["rel_y"] >= 1 - EDGE_BAND
        if (abs(ncy - cy) <= 3 * h and gap <= 0.4 * width) or (n["number"][2] == "page" and edge):
            near.append((abs(ncy - cy) + gap, n["number"][:2]))
    return min(near)[1] if near else None


def text_layer_lines(pdfium, page, width, height):
    """The lines a PDF made on a computer carries inside it, with their boxes
    turned into the frame of the page drawn `width` by `height` pixels, the way
    a person sees it (a turned page is handled by the PDF library itself)."""
    import ctypes
    tp = page.get_textpage()
    try:
        out = []
        for i in range(tp.count_rects()):
            left, bottom, right, top = tp.get_rect(i)
            text = re.sub(r"\s+", " ", tp.get_text_bounded(left, bottom, right, top) or "").strip()
            if not text:
                continue
            xs, ys = [], []
            for px, py in ((left, bottom), (right, top), (left, top), (right, bottom)):
                dx, dy = ctypes.c_int(), ctypes.c_int()
                pdfium.raw.FPDF_PageToDevice(page, 0, 0, width, height, 0, px, py, dx, dy)
                xs.append(dx.value)
                ys.append(dy.value)
            out.append({"text": text, "conf": 1.0, "x": min(xs), "y": min(ys),
                        "w": max(1, max(xs) - min(xs)), "h": max(1, max(ys) - min(ys)), "angle": 0})
        return out
    finally:
        tp.close()


def unread_sticker(m, height):
    """True when a page whose name was not read for certain still shows what
    looks like a name sticker: a short line (three words at most) at the top
    or bottom edge that is close to a child's name. Such a page may be the
    first page of the NEXT child, so it is never given to the child before it
    and neither are the pages after it. A guess that comes from the middle of
    the page, or from a sentence, is the child's own writing and not a
    sticker."""
    if m["status"] != "unsure":
        return False
    if not m.get("box") or not m.get("text"):
        return True             # a guess with nowhere to look: not safe to call it "no sticker"
    rel_y = (m["box"][1] + m["box"][3]) / 2 / max(1, height)
    return len(m["text"].split()) <= 3 and (rel_y <= EDGE_BAND or rel_y >= 1 - EDGE_BAND)


def read_packet_page(pdfium, page, roster, tmpdir, n, not_pages=()):
    """Read one page of a packet: {'m': match_name's answer, 'number': (x, y)
    or None, 'how': 'text layer' or 'reader', 'sticker': True when the page
    has a name sticker that could not be read for certain (unread_sticker)}."""
    w, h = page.get_size()
    scale = min(PACKET_DPI / 72.0, PACKET_MAX_SIDE / max(w, h, 1.0))
    width, height = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    typed, numbers, how = [], [], "text layer"
    m = {"name": None, "score": 0.0, "margin": 0.0, "text": None, "box": None, "status": "no text read"}
    if PACKET_TEXT_LAYER:
        typed, numbers = page_lines(text_layer_lines(pdfium, page, width, height), height, not_pages)
        if typed:
            m = match_name(typed, roster)
    if m["status"] != "confident":
        # a scanned page, or a name that is a picture: draw the page and read
        # it with this computer's own reader, exactly as a photo is read
        how = "reader"
        img = page.render(scale=scale).to_pil().convert("RGB")
        p = os.path.join(tmpdir, f"page-{n}.png")
        img.save(p)
        try:
            seen, more = page_lines(join_rows(read_photo_text(img, p, tmpdir)), img.height, not_pages)
        finally:
            try:
                os.remove(p)
            except OSError:
                pass
        width, height = img.width, img.height
        typed, numbers = typed + seen, numbers + more
        if typed:
            m = match_name(typed, roster)
    number = page_number_by_name(numbers, m, width) if m["status"] == "confident" else None
    return {"m": m, "number": number, "how": how, "scale": scale, "sticker": unread_sticker(m, height)}


def closer_page_number(page, read, tmpdir, n, times=2, not_pages=()):
    """Look again, closer, for the page number beside a name read for certain
    by the reader. Small type drawn at 200 dots to the inch can come back
    wrong ("2/2" read as "212"); the corner around the name drawn twice as
    big reads right. Only used for a child whose page numbers do not make a
    whole set, before that child's pages are sent to a person. Returns
    (x, y) or None."""
    m, scale = read["m"], read["scale"]
    if not m.get("box"):
        return None
    x0, y0, x1, y1 = m["box"]
    h = max(1, y1 - y0)
    img = page.render(scale=scale * times).to_pil().convert("RGB")
    w_now = img.width / times
    box = (int(max(0, x0 - 0.45 * w_now) * times), int(max(0, y0 - 3 * h) * times),
           int(min(w_now, x1 + 0.45 * w_now) * times), int(min(img.height / times, y1 + 3 * h) * times))
    crop = img.crop(box)
    p = os.path.join(tmpdir, f"page-{n}-closer.png")
    crop.save(p)
    try:
        seen = join_rows(run_vision("text", p))
    finally:
        try:
            os.remove(p)
        except OSError:
            pass
    back = [{**t, "x": (t["x"] + box[0]) / times, "y": (t["y"] + box[1]) / times, "w": t["w"] / times,
             "h": t["h"] / times} for t in seen]
    lines, numbers = page_lines(back, img.height / times, not_pages)
    near = match_name(lines, [m["name"]]) if lines else None
    if not near or near["status"] != "confident":
        return None             # the name itself did not read again: nothing here to trust
    return page_number_by_name(numbers, near, w_now)


def packet_mark(key, pages):
    """What a PDF of packet pages carries in its properties: the packet's
    fingerprint and the packet page numbers (from 1) it holds. No name."""
    return "packet %s pages %s" % (key, " ".join(str(i + 1) for i in pages))


def read_packet_mark(pypdf, path):
    """(packet fingerprint, {page numbers}) from a PDF this tool wrote, or None."""
    try:
        meta = pypdf.PdfReader(path, strict=False).metadata or {}
        got = str(meta.get(PACKET_MARK) or "")
    except Exception:           # a PDF this tool did not write, or one it cannot read: not ours
        return None
    mt = re.match(r"packet ([0-9a-f]{16}) pages ([\d ]+)$", got.strip())
    if not mt:
        return None
    return mt.group(1), {int(v) for v in mt.group(2).split()}


def packet_pages_filed(pypdf, folder, key, now=None):
    """{packet page number: the PDF in this folder that already holds it} for
    this packet. Also takes away a '.pdf.part' nobody has touched for an hour
    (a computer stopped while saving it)."""
    now = time.time() if now is None else now
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return {}
    have = {}
    for n in names:
        p = os.path.join(folder, n)
        if n.lower().endswith(".pdf" + PART):
            try:
                if now - os.path.getmtime(p) > SCRATCH_STALE_SECONDS:
                    os.remove(p)
            except OSError:
                pass
        elif key and not n.startswith(".") and n.lower().endswith(".pdf"):
            got = read_packet_mark(pypdf, p)
            if got and got[0] == key:
                for page in got[1]:
                    have.setdefault(page, p)
    return have


def pdf_of_pages(pypdf, reader, pages, mark):
    """A PDF, as bytes, of these pages of the packet (from 0), copied as they
    are, in this order."""
    writer = pypdf.PdfWriter()
    for i in pages:
        writer.add_page(reader.pages[i])
    writer.add_metadata({PACKET_MARK: mark, "/Producer": "Baggage Claim"})
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def page_number_problems(child, pages, follows=()):
    """What is wrong with one child's page numbers, in plain words: [] when the
    set is whole or the child's pages carry no numbers. `pages` is
    [(packet page, (x, y) or None)]; `follows` holds the packet pages that
    have no name sticker and took their number from the page before."""
    numbered = [(p, n) for p, n in pages if n]
    if not numbered:
        return []
    probs = []
    totals = {}
    for _, (x, y) in numbered:
        totals[y] = totals.get(y, 0) + 1
    total = max(sorted(totals), key=lambda t: totals[t])
    if len(totals) > 1:
        probs.append(f"{child}'s pages do not agree on how many pages there are "
                     f"({', '.join(f'of {t}' for t in sorted(totals))})")
    for p, n in pages:
        if not n:
            probs.append(f"packet page {p} carries no page number, though {child}'s other pages do")
    where = {}
    for p, (x, y) in numbered:
        where.setdefault(x, []).append(p)
        if x > y:
            probs.append(f"packet page {p} has no name sticker and would be page {x} of {y}" if p in follows
                         else f"packet page {p} says page {x} of {y}")
    for x in sorted(where):
        if len(where[x]) > 1:
            probs.append(f"page {x} of {total} is there {len(where[x])} times "
                         f"(packet pages {', '.join(str(p) for p in where[x])})")
    for x in range(1, total + 1):
        if x not in where:
            probs.append(f"page {x} of {total} is missing")
    return probs


def where_it_sat(i, names):
    """Where packet page i (from 0) sat, told by the pages either side of it
    that were read for certain."""
    before = names[i - 1] if i > 0 else None
    after = names[i + 1] if i + 1 < len(names) else None
    if before and before == after:
        return f"between two of {before}'s pages"
    left = ("it is the first page of the packet" if i == 0 else f"after a page of {before}" if before
            else "after another page sent to a person")
    right = ("it is the last page of the packet" if i + 1 == len(names) else f"before a page of {after}" if after
             else "before another page sent to a person")
    return f"{left}, {right}"


def packet_note(packet_name, project, results, names, per_child, problems, roster, unsorted_name):
    """The note for the teacher after a packet, in plain words. It names
    children, because it lives in the class's own folder, which already holds
    their names."""
    n = len(results)
    filed = sum(1 for r in results if r["status"] == "confident")
    lines = [f"Baggage Claim sorted this PDF packet.", "",
             f"Packet:   {packet_name}",
             f"Project:  {project or ''}",
             f"Pages:    {n} in the packet, {filed} filed into the children's folders, "
             f"{n - filed} sent to a person (in '{unsorted_name}')", ""]
    carried = {}
    for r in results:
        if r["status"] == "confident" and r.get("follows"):
            carried.setdefault((r["follows"], r["name"]), []).append(r["piece"])
    if carried:
        lines += ["Pages with no name sticker, filed with the page before them"]
        for (lead, child), got in sorted(carried.items()):
            lines.append(f"- Packet page{'' if len(got) == 1 else 's'} {', '.join(str(p) for p in got)}: filed for "
                         f"{child}, whose name is on packet page {lead}.")
        lines += ["A page with no name sticker goes to the child named on the page before it. If one of these "
                  "is another child's, that child's first page had no sticker: move the pages over by hand.", ""]
    guesses = [r for r in results if r["status"] != "confident" and r.get("reason") != PAGES]
    if guesses:
        lines += ["Pages sent to a person because the name could not be read for certain"]
        for r in guesses:
            i = r["piece"] - 1
            guess = ("no name sticker, and no page before it with a name read for certain to go with"
                     if r.get("nosticker") else
                     f"best guess {r['name']} (read '{r['text']}')" if r["name"] and r["status"] == "unsure"
                     else "no name could be read")
            lines.append(f"- Packet page {r['piece']}: {guess}; {where_it_sat(i, names)}.")
        lines += ["Each is a one-page PDF in this folder called 'GUESS', then the guess, then its page number. "
                  "Open it; if you know whose it is, move it into that child's folder. Nothing was filed under "
                  "a guess.", ""]
    if problems:
        lines += ["Page numbers to check"]
        for child in problems:
            lines.append(f"- {child}: {'; '.join(problems[child])}. None of {child}'s pages were filed; all "
                         f"{len(per_child[child])} are in this folder, called '{CHECK_PAGES} {child}', so a "
                         f"person can see which page is missing or doubled.")
        lines.append("")
    if per_child:
        lines += ["Pages per child (packet page numbers in brackets)"]
        for child in sorted(per_child, key=lambda c: norm(c)):
            got = per_child[child]
            lines.append(f"- {child}: {len(got)} page{'' if len(got) == 1 else 's'} "
                         f"({', '.join(str(p) for p in got)})")
        counts = {}
        for got in per_child.values():
            counts[len(got)] = counts.get(len(got), 0) + 1
        usual = max(sorted(counts), key=lambda c: counts[c])
        odd = [c for c in sorted(per_child, key=lambda c: norm(c)) if len(per_child[c]) != usual]
        clear = sum(1 for v in counts.values() if v == counts[usual]) == 1      # one count is the most common
        if len(per_child) > 1 and odd and clear:
            lines += ["", "Children with a different number of pages from most"]
            for c in odd:
                k = len(per_child[c])
                lines.append(f"- {c} has {k} page{'' if k == 1 else 's'}; most children have {usual}.")
        lines.append("")
    none = [c for c in roster if c not in per_child]
    if none:
        lines += ["Children on the class list with no pages in this packet: " + ", ".join(none) + ".", ""]
    lines += ["You can delete this note when you are done.", ""]
    return "\n".join(lines)


def packet_text(packet_name, results, unsorted_name, note_name):
    """The one line in the log for a packet, like batch_text for a photo."""
    n = len(results)
    filed = sum(1 for r in results if r["status"] == "confident")
    kids = len({r["name"] for r in results if r["status"] == "confident"})
    again = sum(1 for r in results if r.get("already"))
    went = sum(1 for r in results if r["status"] == "confident" and r.get("follows"))
    more = (f"; {went} of the filed pages have no name sticker and went with the page before" if went else "")
    more += (f"; {again} of them were already in the children's folders from an earlier sort and were not "
             f"filed a second time" if again else "")
    return (f"{packet_name}: {n} page{'' if n == 1 else 's'}, {filed} filed for {kids} "
            f"child{'' if kids == 1 else 'ren'}, {n - filed} to '{unsorted_name}'{more}. "
            f"See the note '{note_name}' there")


def process_packet(path, roster, out_dir, project, log=print, grade="", sorted_dir=None, unsorted_dir=None):
    """Sort one PDF packet, in a scratch folder of its own that is taken away
    again whether the packet was sorted or could not be."""
    tmpdir = scratch_folder(out_dir)
    try:
        return sort_packet(path, roster, out_dir, project, tmpdir, log, grade, sorted_dir, unsorted_dir)
    finally:
        drop_scratch(tmpdir)


def sort_packet(path, roster, out_dir, project, tmpdir, log=print, grade="", sorted_dir=None, unsorted_dir=None):
    pdfium, pypdf = pdf_parts()
    packet_name = os.path.basename(path)
    stem = os.path.splitext(packet_name)[0]
    project = project or ""
    with open(path, "rb") as f:         # read whole and closed: a Windows PC cannot move an open file
        data = f.read()
    key = hashlib.sha1(data).hexdigest()[:16]       # the same fingerprint a photo gets (photo_key)
    try:
        doc = pdfium.PdfDocument(data)
    except Exception as e:
        locked = "password" in str(e).lower()
        raise PacketError(PACKET_BAD, PACKET_LOCKED_WHY if locked else PACKET_BAD_WHY) from e
    try:
        try:
            reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
            if reader.is_encrypted:
                reader.decrypt("")
            count = len(reader.pages)
        except Exception as e:
            raise PacketError(PACKET_BAD, PACKET_BAD_WHY) from e
        if not len(doc) or count != len(doc):
            raise PacketError(PACKET_BAD, PACKET_EMPTY_WHY if not len(doc) else PACKET_BAD_WHY)
        log(f"{packet_name}: a PDF packet of {count} page{'' if count == 1 else 's'}")
        not_pages = grade_written_with_a_slash(grade)       # "1/2" in a 1-2 class is the grade, not a page number
        reads = []
        for i in range(count):
            page = doc[i]
            try:
                r = read_packet_page(pdfium, page, roster, tmpdir, i + 1, not_pages)
            except pdfium.PdfiumError as e:     # one page that cannot be drawn: a person looks at it
                # nobody knows whether it has a name sticker, so the pages after it are not assumed
                r = {"m": {"name": None, "score": 0.0, "margin": 0.0, "text": None, "box": None,
                           "status": "no text read"}, "number": None, "how": f"could not be read ({e})",
                     "sticker": True}
            finally:
                page.close()
            reads.append(r)
            m = r["m"]
            num = f" (page {r['number'][0]} of {r['number'][1]})" if r["number"] else ""
            log(f"  page {i + 1}: {m['status']:12s} {m['name'] or '-':12s} read '{m['text'] or ''}' "
                f"score {m['score']} from the {r['how']}{num}")

        # names: whose page each one is. A name read for certain, or, for a
        # page with no name sticker, the child named on the page before it
        # (rule 4 above). follows: {such a page: the page that carries the name}
        names = [r["m"]["name"] if r["m"]["status"] == "confident" else None for r in reads]
        follows, owner, lead = {}, None, None
        for i, r in enumerate(reads):
            if names[i]:
                owner, lead = names[i], i + 1
            elif r.get("sticker"):
                owner = None        # a sticker that was not read: the pages after it are nobody's until a name is
            elif owner:
                names[i] = owner
                follows[i + 1] = lead
                log(f"  page {i + 1}: no name sticker; it goes with page {lead} ({owner})")
        per_child = {}
        for i, child in enumerate(names):
            if child:
                per_child.setdefault(child, []).append(i + 1)

        def numbered(got):
            """[(packet page, its page number)] for one child's pages. A page
            with no sticker takes the number after the page before it."""
            out = []
            for p in got:
                n = reads[p - 1]["number"]
                if p in follows and out and out[-1][1]:
                    n = (out[-1][1][0] + 1, out[-1][1][1])
                out.append((p, n))
            return out

        problems = {}
        for child, got in per_child.items():
            probs = page_number_problems(child, numbered(got), follows)
            if probs:
                # before a child's pages go to a person, the page numbers the
                # reader read are looked at again, closer (closer_page_number)
                looked = False
                for p in got:
                    if reads[p - 1]["how"] != "reader":
                        continue
                    page = doc[p - 1]
                    try:
                        again = closer_page_number(page, reads[p - 1], tmpdir, p, not_pages=not_pages)
                    except pdfium.PdfiumError:
                        again = None
                    finally:
                        page.close()
                    if again and again != reads[p - 1]["number"]:
                        log(f"  page {p}: looked closer; the page number is {again[0]} of {again[1]}")
                        reads[p - 1]["number"] = again
                        looked = True
                if looked:
                    probs = page_number_problems(child, numbered(got), follows)
            if probs:
                problems[child] = probs
        for got in per_child.values():
            for p, n in numbered(got):
                reads[p - 1]["number"] = n
    finally:
        doc.close()

    results = [None] * count
    sroot = sorted_root(out_dir, sorted_dir)

    def shown(dest, filed):
        rel = (sorted_dir and filed) or (unsorted_dir and not filed)
        return dest if rel else os.path.relpath(dest, out_dir)

    for child, got in per_child.items():
        if child in problems:
            continue
        dest_dir = os.path.join(sroot, safe_folder(child), safe_folder(project))
        make_inside(sorted_dir, dest_dir)       # the child's folder, never the class folder itself
        have = packet_pages_filed(pypdf, dest_dir, key)
        new = [p - 1 for p in got if p not in have]
        dest = None
        if new:
            dest = os.path.join(dest_dir, piece_name(project, grade, dest_dir, ".pdf"))
            write_whole(pdf_of_pages(pypdf, reader, new, packet_mark(key, new)), dest)
        for p in got:
            m = reads[p - 1]["m"]
            if p in follows:        # no name was read on it: it went with the page before
                m = {**m, "name": child, "status": "confident", "text": None, "box": None, "follows": follows[p]}
            results[p - 1] = {"piece": p, "page": p, "packet": packet_name, "file": shown(have.get(p) or dest, True),
                              "bbox": None, "turned": 0, "already": p in have, "number": reads[p - 1]["number"],
                              **m}

    udir = unsorted_root(out_dir, unsorted_dir)
    make_inside(held_by(unsorted_dir, sorted_dir), udir)    # made when needed, the class folder around it never
    for i in range(count):
        if results[i] is not None:
            continue
        m = dict(reads[i]["m"])
        if names[i]:            # read for certain; that child's set of pages is not whole
            m.update(name=names[i], status="unsure", reason=PAGES, why="; ".join(problems[names[i]]))
            lead, guess = CHECK_PAGES, safe_folder(names[i])
        elif not reads[i].get("sticker"):
            # no name sticker, and no page before it whose name was read for certain
            m.update(name=None, nosticker=True)
            lead, guess = "GUESS", "no-name"
        else:
            # a name too far from every child's to be a guess is not given as one
            lead, guess = "GUESS", (safe_folder(m["name"]) if m["name"] and m["status"] == "unsure" else "no-name")
        # the packet's fingerprint is in the name: scanners reuse names like "Scan.pdf",
        # and a second packet of that name must never overwrite the first one's pages
        base = safe_folder(f"{lead} {guess} - {project} {grade} - {stem} {key[:6]} page {i + 1:03d}") + ".pdf"
        dest = os.path.join(udir, base)
        write_whole(pdf_of_pages(pypdf, reader, [i], packet_mark(key, [i])), dest)
        results[i] = {"piece": i + 1, "page": i + 1, "packet": packet_name, "file": shown(dest, False),
                      "bbox": None, "turned": 0, "already": False, "number": reads[i]["number"], **m}

    # The same packet sorted again (dropped in again after a class list was
    # put right, or after a newer version of this tool): a page that went to a
    # person last time and is filed now would leave its old one-page copy
    # behind in Unsorted, still asking for a person. The tool takes away its
    # own copy, and only that: a PDF in Unsorted that says, in its own
    # properties, that it is this page of this packet.
    cleared = 0
    try:
        waiting = os.listdir(udir)
    except OSError:
        waiting = []
    for i in range(count):
        if results[i]["status"] != "confident":
            continue
        tail = f" page {i + 1:03d}.pdf"
        for n in waiting:
            if n.endswith(tail) and (n.startswith("GUESS ") or n.startswith(CHECK_PAGES + " ")):
                old = os.path.join(udir, n)
                if read_packet_mark(pypdf, old) == (key, {i + 1}):
                    try:
                        os.remove(old)
                        cleared += 1
                    except OSError:
                        pass
    if cleared:
        log(f"{packet_name}: {cleared} page{'' if cleared == 1 else 's'} that waited for a person after an earlier "
            f"sort {'is' if cleared == 1 else 'are'} filed now; the old cop{'y was' if cleared == 1 else 'ies were'} "
            f"taken out of '{os.path.basename(os.path.normpath(udir))}'")

    unsorted_name = os.path.basename(os.path.normpath(udir))
    note = os.path.join(udir, safe_folder(f"{PACKET_NOTE} - {project} - {stem} {key[:6]}") + ".txt")
    try:
        with open(note, "w", encoding="utf-8") as f:
            f.write(packet_note(packet_name, project, results, names, per_child, problems, roster, unsorted_name))
    except OSError as e:
        log(f"{packet_name}: the note for the teacher could not be written ({e})")
    for child, probs in problems.items():
        log(f"{packet_name}: {child}'s pages were not filed, because {'; '.join(probs)}. They are in "
            f"'{unsorted_name}', called '{CHECK_PAGES} {child}'")
    log(packet_text(packet_name, results, unsorted_name, os.path.basename(note)))
    return results


def build_docx(child_dir, child, docx_path=None):
    """One .docx per child: a page per piece, newest last, with a caption.
    Written directly as a Word zip so the images are embedded."""
    import zipfile
    from xml.sax.saxutils import escape
    pieces = []  # (relative path, caption)
    for sub in sorted(os.listdir(child_dir)):
        d = os.path.join(child_dir, sub)
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.lower().endswith((".jpg", ".jpeg", ".png")):
                    pieces.append((os.path.join(sub, f), f"{child}, {os.path.splitext(f)[0]}"))
    if not pieces:
        return None
    docx_path = docx_path or os.path.join(child_dir, f"{child} - work.docx")
    EMU = 914400
    page_w, page_h = 6.5 * EMU, 8.6 * EMU     # letter, 1in margins, room for a caption
    body, rels, types = [], [], []
    for n, (rel, caption) in enumerate(pieces, 1):
        fname = f"image{n}" + os.path.splitext(rel)[1].lower()
        with Image.open(os.path.join(child_dir, rel)) as im:     # for its size only, and closed again
            wide, high = im.size
        scale = min(page_w / wide, page_h / high)
        cx, cy = int(wide * scale), int(high * scale)
        rid = f"rIdImg{n}"
        ext = os.path.splitext(fname)[1].lower().lstrip(".")
        ext = "jpeg" if ext == "jpg" else ext
        rels.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{fname}"/>')
        types.append(ext)
        body.append(
            f'<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{n}" name="{escape(fname)}"/>'
            f'<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="{n}" name="{escape(fname)}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
            f'</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
            f'<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:sz w:val="22"/></w:rPr><w:t>{escape(caption)}</w:t></w:r></w:p>'
            + ('<w:p><w:r><w:br w:type="page"/></w:r></w:p>' if n < len(pieces) else ''))
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
           'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
           '<w:body>' + "".join(body) +
           '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
           '</w:body></w:document>')
    ctypes = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="xml" ContentType="application/xml"/>'
              + "".join(f'<Default Extension="{e}" ContentType="image/{e}"/>' for e in sorted(set(types)))
              + '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
              '</Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + "".join(rels) + '</Relationships>')
    with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("word/document.xml", doc)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        for n, (rel, _) in enumerate(pieces, 1):
            z.write(os.path.join(child_dir, rel), f"word/media/image{n}" + os.path.splitext(rel)[1].lower())
    return docx_path


def build_all_docx(out_dir, sorted_dir=None, skip=()):
    sd = sorted_root(out_dir, sorted_dir)
    made = []
    if os.path.isdir(sd):
        for child in sorted(os.listdir(sd)):
            d = os.path.join(sd, child)
            if os.path.isdir(d) and is_child_folder(child, skip):
                p = build_docx(d, child)
                if p:
                    made.append(p)
    return made


def write_report(out_dir, photo, results):
    path = os.path.join(out_dir, "run-report.md")
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write("# Baggage Claim, run report\n\n")
        f.write(f"## {dt.datetime.now():%b %d %Y %I:%M %p}, {os.path.basename(photo)}\n\n")
        f.write("| piece | result | child | text read | score | saved as |\n|---|---|---|---|---|---|\n")
        for r in results:
            was_there = " (already there from an earlier try, not filed again)" if r.get("already") else ""
            result = ("name read, check the picture" if r.get("reason") == EDGES else
                      "name read, check the page numbers" if r.get("reason") == PAGES else
                      f"no name sticker, filed with page {r['follows']}"
                      if r.get("follows") and r["status"] == "confident" else r["status"])
            piece = f"page {r['piece']}" if r.get("packet") else r["piece"]
            f.write(f"| {piece} | {result} | {r['name'] or ''} | {r['text'] or ''} | "
                    f"{r['score']} | {r['file']}{was_there} |\n")
        f.write("\n")


# ------------------------------------------------- more than one computer ---
#
# Two computers may watch the same class (a teacher's classroom PC and a
# helper's Mac, say). Both see the same Google Drive folder, seconds to a
# couple of minutes apart. If both sorted the same photo, every child would
# get the piece twice. So each watcher writes its own small status file in
# "<class folder>/Watcher status/<computer name>.txt", once a minute at most
# (Drive uploads every change), and reads everybody else's. Among the
# computers heard from in the last STALE_SECONDS, the one with the lowest
# priority number does the sorting; the others stand by and keep writing
# their status. One file per computer means Drive never has to merge two
# writers. A teacher can open the folder and read the files as they are.
#
# Clock skew. Two computers can disagree about the time by minutes. The rule:
# a file is judged stale by comparing the time WRITTEN INSIDE it (the
# writer's clock, as seconds since 1970, so time zones do not matter) against
# the READER's clock only, never against the file's modification time, which
# Drive rewrites on sync. STALE_SECONDS is generous (5 minutes against a
# 60-second write rhythm) so a clock a few minutes off changes nothing; a
# file dated in the future counts as fresh, because a running computer with
# a fast clock is still a running computer. Computers that set their clock
# from the network (the default on macOS and Windows) agree to the second.
#
# Nothing here needs fcntl or any other Mac-only or Windows-only module:
# plain files, os.path, and platform.node(), which is sanitised because a
# computer name can hold characters Windows will not put in a file name.

STATUS_FOLDER = "Watcher status"
STALE_SECONDS = 300      # a computer not heard from for this long is treated as off
GRACE_SECONDS = 90       # a watcher that has just started waits this long before sorting
WAKE_GAP_SECONDS = 120   # a gap this long between two looks at the inbox means this computer was asleep
STATUS_EVERY = 60        # seconds between status writes, at most
# A computer that cannot write its status file, and whose last good one is
# this old, stops sorting: well before the STALE_SECONDS at which another
# computer decides this one is off and starts sorting itself.
STATUS_LOST_SECONDS = 180
STATUS_LOST_TEXT = ("standing by: this computer cannot write its status file, so the other computers cannot tell "
                    "that it is on, and one of them may be sorting this class. So that no child gets the same "
                    "piece twice, this computer sorts nothing until the file can be written again; then it carries "
                    "on by itself. New photos wait in Arrivals until then. Check that Google Drive is signed in "
                    "and running on this computer, and that its disk is not full.")
STATUS_BACK_TEXT = ("this computer's status file can be written again; standing by for {grace} seconds so the "
                    "other computers can see that it is on, then checking who should sort")
DEFAULT_PRIORITY = 50    # lower number sorts first; a helper's Mac might use 90
# A computer running a version of this tool from before status files existed
# sorts every photo it sees and never says so. When this computer notices one
# (see silent_sorter below), it stands by this long, so no child gets a piece twice.
OLD_VERSION_STANDBY_SECONDS = 8 * 3600
OLD_VERSION_NAME = "a computer running an older version of Baggage Claim"
RECENT_SECONDS = 600     # how long to watch a folder this computer just filed into for a second copy arriving
# What this computer can honestly say when it finds no other status file: that
# nobody has reported in, not that nobody is on. The log, the self-check and
# Check Setup all say the second sentence with it, so a person is never told
# the other computer is off when it is only silent.
ALONE_TEXT = "no other computer has reported in"
UNSEEN_TEXT = ("A computer with an older version of Baggage Claim never reports in, even when it is on and sorting. "
               "If another computer is a control tower for this class too, stop one of the two until that computer has this "
               "version, or a child can get the same piece twice.")
# A class is "shared" when its settings file says so: another computer watches
# it as well. While that computer has never written a status file, this one
# cannot tell whether it is switched off or is sorting with a version from
# before status files. So it leaves each new photo in the inbox for that
# computer for SHARED_WAIT_SECONDS and sorts the photo itself only if it is
# still there afterwards. Waiting costs minutes; sorting at once costs every
# child a second copy of the piece.
SHARED_WAIT_SECONDS = 600
SHARED_TEXT = ("The settings file says another computer watches this class too, and that computer has never "
               "reported in. It is switched off, or it has an older version of Baggage Claim and sorts without "
               "saying so. So that no child gets the same piece twice, this computer leaves each new photo for "
               "that computer for {wait}, and sorts it only if it is still in Arrivals after that. "
               "The wait ends for good when that computer has this version.")
VERSION_DATE = "2026-09-26"
# Folders inside the class folder that are not a child's folder.
NOT_CHILD_FOLDERS = {STATUS_FOLDER, "Unsorted - needs a person", "Wall Inbox", "Arrivals", "done", "failed", "name-strips"}


def is_child_folder(name, skip=()):
    """Is this folder inside the class folder one of the children's? `skip`
    holds the names this class gives its inbox and its unsorted folder, which
    a teacher may rename ("Arrivals" for "Wall Inbox", October 5, 2026)."""
    return not name.startswith(".") and name not in NOT_CHILD_FOLDERS and name not in skip


def own_folders(a):
    """The names of this class's inbox and unsorted folder, whatever they are called."""
    return {os.path.basename(os.path.normpath(p)) for p in (a.inbox, getattr(a, "unsorted_dir", None)) if p}


def machine_name(raw=None):
    """This computer's name as a file name that is legal on a Mac and on
    Windows. A name such as 'Room 3: Torres/PC' cannot be a Windows file name
    as it is; the characters Windows refuses are dropped."""
    raw = platform.node() if raw is None else raw
    name = safe_folder(raw)
    return "unnamed-computer" if name == "unknown" else name


def status_dir(sorted_dir):
    return os.path.join(sorted_dir, STATUS_FOLDER)


def platform_label():
    if IS_MAC:
        return "Mac"
    if IS_WIN:
        return "Windows PC"
    return sys.platform


def ago_text(seconds):
    """'just now', '2 minutes ago', '3 hours ago', '2 days ago'."""
    s = int(seconds)
    if s < 45:
        return "just now"
    if s < 90:
        return "1 minute ago"
    if s < 3600:
        return f"{s // 60} minutes ago"
    if s < 7200:
        return "1 hour ago"
    if s < 86400:
        return f"{s // 3600} hours ago"
    return "1 day ago" if s < 172800 else f"{s // 86400} days ago"


def format_status(machine, now, role, priority, leader=None, waiting=0, last_batch="none yet",
                  started=None, system=None, note=None, failed=0):
    """The text of a status file: plain English a teacher can read, plus a few
    machine-readable lines at the bottom that the other watchers use. `failed`
    is how many photos are in 'failed' inside Wall Inbox (photos_in_failed);
    the line is only there when there are some."""
    when = dt.datetime.fromtimestamp(now).strftime("%b %d %Y %I:%M:%S %p")
    if role == "watching":
        role_text = "the control tower for this class (sorting new photos)"
    elif role == "starting":
        role_text = "just started; standing by for a moment in case another computer is mid-photo"
    else:
        role_text = f"standing by; {leader} is the control tower for this class" if leader else "standing by"
    lines = [
        "Baggage Claim control tower status (this file is rewritten about once a minute while the control tower runs)",
        "",
        f"Computer: {machine}",
        f"System: {system or platform_label()}",
        f"Last checked at: {when} (this computer's clock)",
        f"Role: {role_text}",
        f"Priority: {priority} (the lowest number among the computers that are on does the sorting)",
        f"Photos waiting in Arrivals: {waiting}",
        f"Last batch: {last_batch}",
        f"Tool version: {VERSION_DATE}",
    ]
    if failed:
        lines.insert(lines.index(f"Last batch: {last_batch}"),
                     f"Photos that could not be sorted: {failed} (in '{FAILED_FOLDER}' inside Arrivals; the notes "
                     f"called '{COULD_NOT_SORT}' in the folder for doubtful pieces say why, and what to do)")
    if note:
        lines.insert(lines.index(f"Role: {role_text}") + 1, f"Note: {note}")
    if started is not None:
        lines.append(f"Watcher started: {dt.datetime.fromtimestamp(started):%b %d %Y %I:%M %p}")
    lines += [
        "",
        "If 'Last checked at' is more than five minutes old, this computer is off, asleep, or not signed in to Drive.",
        "",
        "-- for the other watchers, please leave as is --",
        f"checked-at-epoch: {int(now)}",
        f"priority: {int(priority)}",
        f"machine: {machine}",
        f"role: {role}",
    ]
    return "\n".join(lines) + "\n"


def parse_status(text):
    """Read the machine lines back. Returns dict(machine, epoch, priority,
    role) or None if the file is not one of ours or is half-written."""
    out = {}
    for ln in text.splitlines():
        if ":" not in ln:
            continue
        k, v = ln.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        try:
            if k == "checked-at-epoch":
                out["epoch"] = int(v)
            elif k == "priority" and "epoch" in out:
                out["priority"] = int(v)
            elif k == "machine" and "epoch" in out:
                out["machine"] = v
            elif k == "role" and "epoch" in out:
                out["role"] = v
        except ValueError:
            return None
    if "epoch" not in out or "machine" not in out:
        return None
    out.setdefault("priority", DEFAULT_PRIORITY)
    out.setdefault("role", "")
    return out


def read_statuses(sdir):
    """Every status file in the folder, parsed. Unreadable files are skipped;
    a missing folder means no other computer has ever written one."""
    out = []
    try:
        names = os.listdir(sdir)
    except OSError:
        return out
    for n in sorted(names):
        if not n.lower().endswith(".txt") or n.startswith("."):
            continue
        try:
            with open(os.path.join(sdir, n), encoding="utf-8", errors="replace") as f:
                st = parse_status(f.read())
        except OSError:
            continue
        if st:
            st["file"] = n
            out.append(st)
    return out


def write_status(sdir, machine, now, role, priority, **kw):
    """Write this computer's own status file. Returns its path. Raises OSError
    if the class folder is not reachable (the caller decides what to say).
    'Watcher status' is made when it is missing; the class folder that holds
    it never is (make_inside)."""
    make_inside(holder_of(sdir), sdir)
    path = os.path.join(sdir, machine + ".txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(format_status(machine, now, role, priority, **kw))
    return path


def is_fresh(status, now, stale=STALE_SECONDS):
    """Fresh means written less than `stale` seconds before the reader's clock
    says now. A time in the future is fresh (see the clock-skew note above)."""
    return now - status["epoch"] < status.get("stale", stale)


def choose_leader(statuses, me, now, stale=STALE_SECONDS):
    """Who sorts: among the fresh status files plus this computer, the lowest
    priority number; the same number is settled by computer name, so both
    machines reach the same answer from the same files. Returns the name."""
    cands = [s for s in statuses if s["machine"] != me["machine"] and is_fresh(s, now, stale)]
    cands.append({"machine": me["machine"], "priority": me["priority"]})
    return min(cands, key=lambda s: (int(s["priority"]), s["machine"]))["machine"]


def in_grace(started, now, grace=GRACE_SECONDS):
    """True during the first `grace` seconds after this watcher started."""
    return now - started < grace


def slept_since(last_look, now, gap=WAKE_GAP_SECONDS):
    """Seconds this computer was asleep between two looks at the inbox, or 0.
    The watch loop looks every few seconds, so a gap of minutes means the lid
    was closed or the computer slept. Right after it wakes, its copy of the
    class folder is as old as the sleep, until Google Drive reconnects: the
    other computer's status file still carries a time from before the sleep
    (so it looks off) and the inbox still lists photos that computer sorted
    hours ago. Sorting from that view files every child's piece a second
    time. So a wake-up re-enters the grace period (see decide_role) and lets
    Drive catch up first. `last_look` is None before the first look."""
    if last_look is None or now - last_look <= gap:
        return 0
    return now - last_look


def decide_role(statuses, me, now, started, stale=None, grace=None):
    """Pure decision: dict(role, leader, reason). role is 'watching',
    'standing by' or 'starting' (the grace period). reason is a plain
    sentence for the log."""
    stale = STALE_SECONDS if stale is None else stale
    grace = GRACE_SECONDS if grace is None else grace
    leader = choose_leader(statuses, me, now, stale)
    if in_grace(started, now, grace):
        left = int(grace - (now - started)) + 1
        return {"role": "starting", "leader": leader,
                "reason": f"just started: standing by for another {left} seconds in case another computer "
                          f"is in the middle of a photo, then checking who should sort"}
    if leader == me["machine"]:
        others = [s["machine"] for s in statuses if s["machine"] != me["machine"] and is_fresh(s, now, stale)]
        # "No status file" is not "no computer": a version from before status
        # files sorts every photo and writes none, so never say nobody is on.
        why = f" ({', '.join(others)} standing by)" if others else f" ({ALONE_TEXT}). {UNSEEN_TEXT}"
        return {"role": "watching", "leader": leader, "reason": "this computer is the control tower for this class" + why}
    return {"role": "standing by", "leader": leader,
            "reason": f"standing by, {leader} is the control tower for this class"}


def should_write_status(last_written, now, force=False, every=STATUS_EVERY):
    """At most one write a minute, unless a batch just finished."""
    return force or last_written is None or now - last_written >= every


def status_lost(last_written, now, limit=STATUS_LOST_SECONDS):
    """Asked when a status write has just failed: is the last good file too
    old to go on sorting? One failed write is nothing (the file the others
    hold is a minute old). After `limit` seconds of failures the others are
    about to decide this computer is off, and one of them will sort. A
    computer that has never managed to write one cannot be seen at all."""
    return last_written is None or now - last_written >= limit


def keep_status(state, sdir, me, decision, say, force=False, **kw):
    """Write this computer's status file if one is due, or at once with
    `force`. The time written is the time it is now, not the time the loop
    last looked, so a file written after a long batch is not old already.
    `state` is the watch loop's record: last (when the file was last written,
    None if never), err (the last error said in the log) and lost (True while
    the file cannot be written and the last good one is too old, see
    status_lost). Returns True when this computer may sort, because the other
    computers can see that it is on."""
    now = time.time()
    if should_write_status(state["last"], now, force):
        try:
            write_status(sdir, me["machine"], now, decision["role"], me["priority"], leader=decision["leader"], **kw)
        except OSError as e:
            if str(e) != state["err"]:
                say(f"could not write this computer's status file in '{STATUS_FOLDER}' ({e}); "
                    "other computers cannot see this one is on")
                state["err"] = str(e)
            state["lost"] = status_lost(state["last"], now)
        else:
            state.update(last=now, err=None, lost=False)
    return not state["lost"]


def describe_statuses(statuses, now, me=None):
    """Lines for the self-check and the Check Setup scripts: one per computer,
    freshest first, as a person would say it."""
    if not statuses:
        return ["    no computer has written a status file yet (the control tower writes one within a minute of starting)"]
    lines = []
    for s in sorted(statuses, key=lambda s: -s["epoch"]):
        age = now - s["epoch"]
        alive = is_fresh(s, now)
        state = {"watching": "watching", "standing by": "standing by", "starting": "just started"}.get(s["role"], s["role"] or "?")
        note = "" if alive else "; OFF or asleep (not heard from for over 5 minutes)"
        you = "  <- this computer" if me and s["machine"] == me else ""
        lines.append(f"    {s['machine']}: last checked {ago_text(max(0, age))}, {state}, priority {s['priority']}{note}{you}")
    return lines


def silent_sorter(seen_at):
    """Stands in for a computer that is sorting this class without writing a
    status file: one running a version of this tool from before status files
    existed, which sorts every photo it sees. It cannot be heard from, so it
    is given the lowest priority of all and stays "fresh" for
    OLD_VERSION_STANDBY_SECONDS after it was last caught at it, and the normal
    election makes this computer stand by for that long."""
    return {"machine": OLD_VERSION_NAME, "priority": -1, "epoch": int(seen_at), "role": "watching",
            "stale": OLD_VERSION_STANDBY_SECONDS}


def others_fresh(statuses, me, now, stale=None):
    """Has any other computer written a status file recently?"""
    stale = STALE_SECONDS if stale is None else stale
    return any(s["machine"] != me["machine"] and is_fresh(s, now, stale) for s in statuses)


def minutes_text(seconds):
    """'10 minutes', '1 minute': a wait as a person says it."""
    n = max(1, int(round(seconds / 60)))
    return "1 minute" if n == 1 else f"{n} minutes"


def shared_text(wait=None):
    """SHARED_TEXT with the wait in whole minutes."""
    return SHARED_TEXT.format(wait=minutes_text(SHARED_WAIT_SECONDS if wait is None else wait))


def is_yes(value):
    """A yes-or-no line in a settings file: true, 1, "yes", "true" and "on" are
    yes; false, 0, "no", nothing at all and anything else are no."""
    if isinstance(value, str):
        return value.strip().lower() in ("yes", "true", "on", "1", "y")
    return bool(value)


def never_reported_in(statuses, me):
    """Has no other computer ever written a status file for this class? An old
    file counts as having reported in: that computer has this version and is
    switched off, which the election already covers. No file at all is the
    case the election cannot see: a computer that is off, or one with an older
    version that sorts every photo and writes nothing."""
    return not any(s["machine"] != me["machine"] for s in statuses)


def leave_for_the_other(first_seen, src, now, log=print, wait=None):
    """Should this photo stay in the inbox for now, for the other computer of a
    shared class that has never reported in? True for the first `wait` seconds
    after this computer first saw the photo, False after that. The time is
    counted from when this watcher first saw the photo, not from the photo's
    own date, which is when the picture was taken. `first_seen` is the
    watcher's memory, {photo path: [first seen, said it is sorting]}; both
    sentences are said once per photo."""
    wait = SHARED_WAIT_SECONDS if wait is None else wait
    p = os.path.basename(src)
    if src not in first_seen:
        first_seen[src] = [now, False]
        log(f"{p}: new photo, left in Arrivals for the other computer. This computer sorts it in "
            f"{minutes_text(wait)} if it is still there.")
    seen = first_seen[src]
    if now - seen[0] < wait:
        return True
    if not seen[1]:
        seen[1] = True
        log(f"{p}: still in Arrivals after {minutes_text(wait)}, so the other computer is not sorting. "
            f"This computer is sorting it now.")
    return False


def forget_gone(first_seen, log=print):
    """Drop the photos that are no longer in the inbox from the watcher's
    memory. One that left while this computer was still leaving it alone was
    taken by the other computer (or by a person), which is what the wait is
    for; say so once. Returns the names of those."""
    taken = []
    for src in list(first_seen):
        if os.path.exists(src):
            continue
        if not first_seen[src][1]:
            taken.append(os.path.basename(src))
            log(f"{taken[-1]}: gone from Arrivals. The other computer took it, so this computer leaves it alone.")
        del first_seen[src]
    return taken


def files_in(folder):
    """The image files and PDFs in a folder, by name; an unreadable folder counts as empty."""
    try:
        return {f for f in os.listdir(folder) if os.path.splitext(f)[1].lower() in INBOX_EXT and not f.startswith(".")}
    except OSError:
        return set()


def note_saved(recent, results, out_dir, now):
    """Remember the folders this computer has just saved pieces into and what
    they held at that moment, so a copy from another computer can be noticed."""
    for r in results:
        f = r.get("file")
        if not f:
            continue
        folder = os.path.dirname(f if os.path.isabs(f) else os.path.join(out_dir, f))
        recent[folder] = (now, files_in(folder))


def new_arrivals(recent, now, window=RECENT_SECONDS):
    """Image files that have appeared, since this computer last saved there, in a
    folder it filed into within the last `window` seconds. Only this computer
    puts pieces into those folders, so a new file there that it did not save
    means another computer is sorting the same class. Returns
    [(folder, [file names])] and forgets folders once checked or aged out."""
    found = []
    for folder, (when, seen) in list(recent.items()):
        if now - when > window:
            del recent[folder]
            continue
        extra = sorted(files_in(folder) - seen)
        if extra:
            found.append((folder, extra))
            del recent[folder]
    return found


def old_version_warning(what):
    """The log line for a computer sorting this class without a status file."""
    hours = OLD_VERSION_STANDBY_SECONDS // 3600
    return (f"{what}, and no other computer has written a status file. Another computer is sorting this class "
            f"with an older version of Baggage Claim, which does not know how to share a class, so a child can get "
            f"the same piece twice. This computer is standing by for the next {hours} hours so that stops. To fix "
            f"it for good, install this version on the other computer, or stop its control tower. To make this computer "
            f"sort again sooner, restart its control tower.")


CLEANED_SAID = set()    # project names this watcher has already said it cleaned


def clean_project(name):
    """The project name as the tool uses it everywhere: the folder inside each
    child's folder, the file names, the GUESS names and the done folder. It is
    safe_folder's rule, applied once where the name comes in (a folder inside
    the inbox, --project, or the settings file). No name at all stays as it is."""
    return safe_folder(str(name)) if name else name


def say_cleaned(given, used, log=print, where=""):
    """Say once, in plain words, that a project name was changed so that it
    works on every computer. An accent stored the Mac's way, or extra spaces,
    is not worth a line in the log; a character that was taken out is."""
    given = str(given)
    if not used or re.sub(r"\s+", " ", unicodedata.normalize("NFC", given)).strip() == used:
        return False
    if (where, given) in CLEANED_SAID:
        return False
    CLEANED_SAID.add((where, given))
    log(f"the project name '{given}' has a character that a Windows computer cannot use in a file name "
        f"(such as ? : \" / or a full stop at the end), so this work is filed as '{used}'. Nothing is lost. "
        f"For new projects, use letters, numbers, spaces and dashes in the name.")
    return True


def old_heic_copy(name, folder, *kept):
    """True for the JPEG copy that an OLDER version of this tool wrote beside
    an iPhone photo: 'IMG_1234.HEIC.jpg' next to 'IMG_1234.HEIC'. This version
    writes that copy into its own scratch folder (see open_photo), but a
    computer that still has the older version writes it into the Wall Inbox,
    and Google Drive brings it to this computer, where it would be sorted as a
    second photo of the same wall.

    Only a copy whose own iPhone photo can still be found counts: in the same
    folder (being sorted right now, or left behind when that computer was
    stopped), or in one of the `kept` folders (done, failed). A photo that
    merely has such a name, with no iPhone photo to go with it, is a photo
    like any other and is sorted."""
    first, ext = os.path.splitext(name)
    if ext.lower() != ".jpg" or os.path.splitext(first)[1].lower() not in (".heic", ".heif"):
        return False
    return any(os.path.exists(os.path.join(d, first)) for d in (folder,) + kept)


def inbox_jobs(inbox, project):
    """Photos waiting in the inbox as (photo path, project, done folder). A
    PDF packet is taken exactly like a photo (see "PDF packets").
    Photos straight in the inbox use the default project. A teacher can also
    make a folder inside the inbox named for the project ("Fall Leaves") and
    drop photos there; the folder name becomes the project.

    The folder name is cleaned here, once (clean_project), so the project
    folder, every file name, the GUESS names in Unsorted and the done folder
    all use the same name, and it is a name both a Mac and a Windows PC can
    hold: a phone or a Mac will happily make a folder called 'Who Am I?'."""
    done = os.path.join(inbox, "done")
    failed = os.path.join(inbox, "failed")
    try:
        listing = os.listdir(inbox)
    except PermissionError:
        raise PermissionError(f"macOS is not letting this program read the inbox folder. If macOS asked whether "
                              f"Baggage Claim may access Google Drive, click Allow. Otherwise open System Settings > "
                              f"Privacy & Security > Files and Folders (or Full Disk Access), find Baggage Claim, "
                              f"and turn Google Drive on. Folder: {inbox}")
    jobs = []
    for p in sorted(listing):
        full = os.path.join(inbox, p)
        if p.startswith(".") or p in ("done", "failed"):
            continue
        if os.path.isdir(full):
            try:
                inner = sorted(os.listdir(full))
            except OSError:
                continue
            for q in inner:
                if os.path.splitext(q)[1].lower() in INBOX_EXT and not q.startswith("."):
                    # the older version kept the folder's name as it was typed
                    if old_heic_copy(q, full, os.path.join(done, clean_project(p)), os.path.join(done, p), failed):
                        continue
                    jobs.append((os.path.join(full, q), clean_project(p), os.path.join(done, clean_project(p))))
        elif os.path.splitext(p)[1].lower() in INBOX_EXT:
            if old_heic_copy(p, inbox, done, failed):
                continue
            jobs.append((full, project, done))
    return jobs


# ------------------------------------------- a photo that was not finished ---
#
# Sorting a photo takes about ten seconds, and the computer can stop anywhere
# in them: Stop Watcher, a restart after a crash, taskkill on Windows, a power
# cut. The photo is claimed (moved to done) before it is cut, so a watcher that
# comes back never sorts it a second time by itself and no child gets the
# piece twice. What is left is to SAY SO. Before the claim this computer
# writes a small marker in its own output folder (never in the inbox, which
# Drive shares with every other computer) and removes it when the photo is
# finished. A marker still there at the next start means the photo was not
# finished: the log says so, and a note in plain English goes into the
# doubtful-pieces folder, which is where the teacher already looks.

IN_PROGRESS_FOLDER = ".in-progress"


def class_key(inbox):
    """The inbox as '<class folder>/<inbox folder>', lower case. Several classes
    on one computer share one output folder, so a marker has to say whose it
    is. The last two folder names stay the same when Google Drive's "My Drive"
    moves (a new drive letter on Windows); the full path does not."""
    parts = os.path.normpath(os.path.abspath(inbox)).replace("\\", "/").split("/")
    return "/".join(parts[-2:]).lower()


def mark_started(out_dir, inbox, src, claimed, project):
    """Write the marker for a photo this computer is about to claim and sort.
    Returns the marker's path, for clear_marker."""
    import hashlib
    done_rel = os.path.relpath(claimed, inbox).replace("\\", "/")
    back = os.path.relpath(os.path.dirname(src), inbox).replace("\\", "/")
    info = {"machine": machine_name(), "class": class_key(inbox), "photo": os.path.basename(src),
            "project": project, "done": done_rel, "back": "" if back == "." else back,
            "size": os.path.getsize(src), "started": f"{dt.datetime.now():%b %d %I:%M %p}"}
    tag = hashlib.sha1(f"{info['class']}|{done_rel}".encode("utf-8")).hexdigest()[:12]
    path = os.path.join(out_dir, IN_PROGRESS_FOLDER, f"{info['machine']} {tag}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump(info, f)
        f.flush()
        os.fsync(f.fileno())    # a power cut is one of the ways a photo is left unfinished
    os.replace(path + ".part", path)
    return path


def clear_marker(path):
    """The photo is finished (or was never started): remove its marker, and the
    marker folder when that was the last one."""
    for target, remove in ((path, os.remove), (os.path.dirname(path), os.rmdir)):
        try:
            remove(target)
        except OSError:
            pass


def unfinished_photos(out_dir, inbox):
    """Markers this computer left behind for this class, as [(marker path, what
    it says)]. Another class's markers, another computer's, and a file that
    cannot be read are left alone."""
    folder = os.path.join(out_dir, IN_PROGRESS_FOLDER)
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    found = []
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, n), encoding="utf-8") as f:
                info = json.load(f)
            mine = (info["machine"] == machine_name() and info["class"] == class_key(inbox)
                    and bool(info["photo"]) and bool(info["done"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if mine:
            found.append((os.path.join(folder, n), info))
    return found


def unfinished_note(info, inbox_name):
    """The note for the teacher, in plain words. It names the photo and the
    folders, never a child."""
    done_folder = "/".join([inbox_name] + info["done"].split("/")[:-1])
    back_folder = "/".join([inbox_name] + ([info["back"]] if info.get("back") else []))
    return (f"Baggage Claim did not finish this photo.\n\n"
            f"Photo:    {info['photo']}\n"
            f"Project:  {info.get('project') or ''}\n"
            f"Started:  {info.get('started') or 'not known'}, on the computer called {info['machine']}\n"
            f"The photo is now in:  {done_folder}\n\n"
            f"What happened\n"
            f"The computer stopped partway through sorting it: it was switched off, it lost power, or the "
            f"control tower was stopped. Some children may have their piece from this photo and others may not. "
            f"The photo was not sorted a second time, so nobody was given the same piece twice.\n\n"
            f"What to do\n"
            f"1. Open the children's folders and see who is missing the piece.\n"
            f"2. If nobody is missing it, there is nothing to do.\n"
            f"3. If some children are missing it, move the photo from '{done_folder}' back into "
            f"'{back_folder}'. It will be sorted again. A child who already has the piece from this photo "
            f"keeps it and is not given a second copy; only the missing pieces are filed.\n\n"
            f"You can delete this note when you are done.\n")


def tell_unfinished(inbox, out_dir, log=print, unsorted_dir=None, sorted_dir=None):
    """Say, once, which photos this computer was in the middle of when it last
    stopped. Nothing is sorted again here. Returns the names of those photos.
    `sorted_dir` is the class folder, which is never made for the note's sake."""
    told = []
    inbox_name = os.path.basename(os.path.normpath(inbox))
    for marker, info in unfinished_photos(out_dir, inbox):
        photo = os.path.join(inbox, *info["done"].split("/"))
        waiting = os.path.join(inbox, *([info["back"]] if info.get("back") else []), info["photo"])
        try:
            same = os.path.getsize(photo) == info.get("size")
        except OSError:
            same = False
        # Still waiting in the inbox: it was never claimed, and it is sorted in
        # the ordinary way now. Not in done, or a different photo of the same
        # name there: a person or another computer has dealt with it.
        if same and not os.path.exists(waiting):
            note_dir = unsorted_root(out_dir, unsorted_dir)
            note = os.path.join(note_dir, safe_folder(f"NOT FINISHED - {info.get('project') or ''} - "
                                                      f"{info['photo']}") + ".txt")
            try:
                make_inside(held_by(unsorted_dir, sorted_dir or holder_of(inbox)), note_dir)
                with open(note, "w", encoding="utf-8") as f:
                    f.write(unfinished_note(info, inbox_name))
                where = f"A note that says this is in '{os.path.basename(os.path.normpath(note_dir))}'."
            except OSError as e:
                where = f"A note for the teacher could not be written ({e})."
            done_folder = "/".join([inbox_name] + info["done"].split("/")[:-1])
            back_folder = "/".join([inbox_name] + ([info["back"]] if info.get("back") else []))
            log(f"{info['photo']}: this computer stopped partway through sorting this photo (started "
                f"{info.get('started') or 'earlier'}), so it was not finished and some children may be missing "
                f"their piece. It has NOT been sorted again, so nobody gets a piece twice. To finish it, move the "
                f"photo from '{done_folder}' back into '{back_folder}': only the missing pieces are filed then. "
                f"{where}")
            told.append(info["photo"])
        clear_marker(marker)
    return told


# ---------------------------------------- a photo that could not be sorted ---
#
# A photo the tool cannot open, read or save from is moved to 'failed' inside
# Wall Inbox, so that it does not hold up the photos behind it. The teacher
# sees a folder called 'failed' appear in Drive with her photo in it. Until
# this was written nothing told her why, or what to do: the reason was one
# line in the log on the watching computer, in the program's own words, and
# the status file went on showing the batch before. Now it is said in plain
# words in three places:
#   - a note in the doubtful-pieces folder, 'COULD NOT SORT - <project> -
#     <photo>.txt', beside the NOT FINISHED and CHECK PICTURE notes;
#   - this computer's status file: the 'Last batch' line, and a line that
#     counts the photos in 'failed' for as long as they are there, so it is
#     still said after the next batch and after the watcher is started again;
#   - the log, which also keeps the program's own words for whoever set the
#     computer up.
# The note and the status file name the photo and the folders, never a child,
# and never carry the program's own error text, which can hold a path.
#
# Shared by the Mac and Windows watchers; nothing here is Mac-only or
# Windows-only.

COULD_NOT_SORT = "COULD NOT SORT"
FAILED_FOLDER = "failed"


def why_not_sorted(error):
    """What stopped a photo, as (kind, the reason in plain words). The kind
    decides what the teacher is asked to do: 'photo' (the file itself is no
    good: share it again), 'computer' (this computer could not save or could
    not find a folder: the photo is fine), 'reader' (the name reader did not
    work) or 'unknown'."""
    text = str(error).lower()
    if isinstance(error, PacketError):
        return error.kind, error.why
    if isinstance(error, (FileNotFoundError, PermissionError)) or (
            isinstance(error, OSError) and error.errno is not None):
        return "computer", ("this computer could not save the pieces, or could not find a folder it needs. Its "
                            "disk may be full, or Google Drive may be signed out, closed or still catching up")
    if isinstance(error, RuntimeError) and ("vision" in text or "reader" in text):
        return "reader", "the part of this computer that reads the names did not work"
    # Pillow says OSError with no number for a file that is cut short or is
    # not a picture, and SyntaxError or EOFError for some broken ones
    if isinstance(error, (OSError, SyntaxError, EOFError)) or "could not convert" in text:
        return "photo", ("the file could not be opened as a picture. It is damaged, or it did not finish arriving "
                         "from the phone, or it is not a photo")
    return "unknown", "something went wrong that the tool was not ready for"


def what_to_do(kind, failed_folder, back_folder, machine, thing="photo"):
    """The steps for the teacher, one to a line, for each kind of reason.
    `thing` is 'photo' or 'packet' (a PDF packet)."""
    has = "their pages from this packet keeps them" if thing == "packet" else "their piece from this photo keeps it"
    again = (f"Move the {thing} from '{failed_folder}' back into '{back_folder}'. It is sorted again. A child who "
             f"already has {has} and is not given a second copy.")
    if kind == PACKET_BAD:
        return [f"Save or scan the packet again as a PDF and put the new file into '{back_folder}'.",
                f"Then delete the file in '{failed_folder}'. It cannot be used."]
    if kind == PACKET_PARTS:
        return [f"Nothing is known to be wrong with the packet. Tell the person who set Baggage Claim up on the "
                f"computer called {machine}: install the newest Baggage Claim there, or run "
                f"'pip install pypdfium2 pypdf'. Photos are sorted as usual meanwhile.",
                again]
    if kind == "photo":
        return [f"Share the photo to '{back_folder}' again, from the phone it was taken with.",
                "If the photo is no longer on the phone, photograph the wall again and share the new photo.",
                f"Then delete the photo in '{failed_folder}'. It cannot be used."]
    if kind == "computer":
        return [f"Nothing is wrong with the photo. On the computer called {machine}, see that Google Drive is "
                f"signed in and that the disk is not full.",
                again]
    return [f"Nothing is known to be wrong with the {thing}. " + again,
            f"If the {thing} comes back to '{failed_folder}', tell the person who set Baggage Claim up on the "
            f"computer called {machine}, and leave the {thing} where it is. The log on that computer says more."]


def could_not_sort_note(photo_name, project, kind, why, failed_folder, back_folder, machine, when, thing="photo"):
    """The note for the teacher, in plain words. It names the photo and the
    folders, never a child."""
    steps = "\n".join(f"{i}. {s}" for i, s in
                      enumerate(what_to_do(kind, failed_folder, back_folder, machine, thing), 1))
    return (f"Baggage Claim could not sort this {thing}.\n\n"
            f"{thing.capitalize() + ':':<10}{photo_name}\n"
            f"Project:  {project or ''}\n"
            f"When:     {when}, on the computer called {machine}\n"
            f"The {thing} is now in:  {failed_folder}\n\n"
            f"What happened\n"
            f"{why[0].upper()}{why[1:]}. The {thing} was put in '{failed_folder}' so that it does not hold up the "
            f"photos and packets after it. Those are sorted in the usual way.\n\n"
            f"What to do\n"
            f"{steps}\n\n"
            f"You can delete this note when you are done.\n")


def tell_could_not_sort(photo_name, project, error, inbox, back_dir, out_dir, log=print, unsorted_dir=None,
                        sorted_dir=None):
    """Say why a photo is in 'failed' and what to do about it: a note in the
    doubtful-pieces folder and one line in the log. `back_dir` is the folder
    the photo was shared to (the inbox, or a project folder inside it).
    Returns what the watch loop needs for the status file."""
    kind, why = why_not_sorted(error)
    thing = "packet" if is_packet(photo_name) else "photo"
    machine = machine_name()
    inbox_name = os.path.basename(os.path.normpath(inbox))
    failed_folder = f"{inbox_name}/{FAILED_FOLDER}"
    back = os.path.relpath(back_dir, inbox).replace("\\", "/")
    back_folder = inbox_name if back == "." else f"{inbox_name}/{back}"
    note_dir = unsorted_root(out_dir, unsorted_dir)
    folder = os.path.basename(os.path.normpath(note_dir))
    note = os.path.join(note_dir, safe_folder(f"{COULD_NOT_SORT} - {project or ''} - {photo_name}") + ".txt")
    try:
        make_inside(held_by(unsorted_dir, sorted_dir or holder_of(inbox)), note_dir)
        with open(note, "w", encoding="utf-8") as f:
            f.write(could_not_sort_note(photo_name, project, kind, why, failed_folder, back_folder, machine,
                                        f"{dt.datetime.now():%b %d %I:%M %p}", thing))
        where = f"A note that says this, and what to do, is in '{folder}'."
    except OSError as e:
        note, where = None, f"A note for the teacher could not be written ({e})."
    log(f"{photo_name}: this {thing} could not be sorted, because {why}. It was moved to inbox/failed (the folder "
        f"'{failed_folder}'), so the photos and packets after it are not held up. What to do: "
        f"{' '.join(what_to_do(kind, failed_folder, back_folder, machine, thing))} {where} For the person who set this "
        f"computer up, the program's own words were: {type(error).__name__}: {error}")
    return {"photo": photo_name, "project": project, "kind": kind, "why": why, "note": note}


def failed_text(could_not, unsorted_name="unsorted"):
    """'1 photo could not be sorted ...', for the log and the 'Last batch' line
    of the status file, which is all a person looking from somewhere else has
    to go on. Empty when every photo was sorted."""
    if not could_not:
        return ""
    n = len(could_not)
    each = "; ".join(f"'{c['photo']}': {c['why']}" for c in could_not[:3])
    more = f"; and {n - 3} more" if n > 3 else ""
    return (f"{n} photo{'' if n == 1 else 's'} could not be sorted and {'is' if n == 1 else 'are'} in "
            f"'{FAILED_FOLDER}' inside Arrivals ({each}{more}). See the note{'' if n == 1 else 's'} called "
            f"'{COULD_NOT_SORT}' in '{unsorted_name}' for what to do")


def photos_in_failed(inbox):
    """How many photos are in 'failed' inside the inbox now. It is counted
    from the folder, not remembered, so it is right after a restart and goes
    back to 0 by itself when a person has moved or deleted the photos."""
    try:
        names = os.listdir(os.path.join(inbox, FAILED_FOLDER))
    except OSError:
        return 0
    return sum(1 for n in names if not n.startswith(".") and os.path.splitext(n)[1].lower() in INBOX_EXT)


def run_inbox(inbox, roster, out_dir, project, grid=None, log=print, grade="", sorted_dir=None, unsorted_dir=None,
              taken=None, hold=None, beat=None, folders=None, could_not=None):
    """Sort every photo waiting in the inbox. `taken`, when given, is a list
    that receives the name of each photo another computer took first.
    `could_not`, when given, is a list that receives what is known about each
    photo that could not be sorted and went to 'failed' (see
    tell_could_not_sort), so the status file can say so. `hold`,
    when given, is asked about each photo and answers True for one that must
    stay in the inbox for now (see leave_for_the_other). `beat`, when given,
    is called before each photo so this computer's status file stays fresh
    through a long batch; it answers False when the file cannot be written
    and the rest of the photos must stay in the inbox (see keep_status).
    `folders`, when given, is the watcher's memory of the children it has made
    folders for, so a folder a teacher deleted is not made again on every look
    (see make_new_child_folders); without it, once through, every child on the
    class list gets a folder.

    The inbox is a person's folder and is never made here, and neither is a
    class folder the settings name: when one of them is not there, nothing is
    made or sorted and FileNotFoundError says why (see make_inside)."""
    done = os.path.join(inbox, "done")
    make_inside(inbox, done)
    if folders is None:
        make_child_folders(roster, out_dir, project, sorted_dir)
    else:
        make_new_child_folders(roster, out_dir, project, sorted_dir, folders)
    gone = folders_gone(inbox, sorted_dir)
    if gone:
        raise FileNotFoundError(gone_text(gone[0]))
    jobs = inbox_jobs(inbox, project)
    # A photo this computer was in the middle of when it last stopped is in
    # done already and is not sorted again; say so before starting on new ones.
    tell_unfinished(inbox, out_dir, log, unsorted_dir, sorted_dir)
    summary = []
    taken = [] if taken is None else taken
    for src, proj, done_dir in jobs:
        p = os.path.basename(src)
        # Five photos can take longer than the five minutes after which the
        # other computers decide this one is off. So the status file is kept
        # fresh between photos, and if it cannot be written any more, another
        # computer may be about to sort: stop here, before claiming the photo.
        if beat is not None and beat() is False:
            log(f"{p}: left in Arrivals for now, because this computer cannot write its status file and "
                f"another computer may be sorting")
            break
        # A shared class whose other computer has never reported in: the photo
        # is that computer's for the first minutes. Nothing is claimed, cut or
        # saved, and if it leaves the inbox meanwhile that is not an alarm.
        if hold is not None and hold(src):
            continue
        # A folder renamed in the middle of a batch: stop here, before the
        # photo is claimed, and do not mistake it for another computer's work.
        gone = folders_gone(inbox, sorted_dir)
        if gone:
            raise FileNotFoundError(gone_text(gone[0]))
        # Another computer watching the same folder may have taken this photo
        # since the folder was listed: look again right before starting.
        if not os.path.exists(src):
            log(f"{p}: gone from the inbox before this computer started on it (another computer took it); skipped")
            taken.append(p)
            continue
        if not is_settled(src):
            log(f"{p}: still arriving, will try again")
            continue
        # A project folder made on a phone or a Mac can hold characters a
        # Windows PC cannot ('Who Am I?'). inbox_jobs cleaned the name; say so
        # once, the first time a photo from that folder is sorted.
        held_in = os.path.dirname(src)
        if os.path.normpath(held_in) != os.path.normpath(inbox):
            say_cleaned(os.path.basename(held_in), proj, log, os.path.normpath(inbox))
        # Claim the photo BEFORE cutting it: move it to done first, then sort it
        # from there. A computer that loses this race has saved nothing, and
        # the winner's move reaches the other computer's Drive while that one
        # is still waiting for the photo to settle. (Cutting first and moving
        # afterwards protected only the count in the log; every child's folder
        # already held both copies by the time the move failed.)
        make_inside(inbox, done_dir)
        # never over an earlier file of the same name: a scanner names every packet "Scan.pdf"
        claimed = free_path(os.path.join(done_dir, p))
        # The marker goes down before the claim and comes up when the photo is
        # finished. If this computer is stopped anywhere in between (no
        # "finally" here on purpose: Ctrl+C is one of the ways of stopping),
        # the marker is what lets the next start say the photo was not finished.
        try:
            marker = mark_started(out_dir, inbox, src, claimed, proj)
        except FileNotFoundError:
            marker = None       # the photo left the inbox this instant; the claim below says so
        try:
            shutil.move(src, claimed)
        except (FileNotFoundError, OSError) as e:
            if marker:
                clear_marker(marker)
            if os.path.exists(src):
                raise
            log(f"{p}: another computer finished this photo first; nothing filed twice ({e})")
            taken.append(p)
            continue
        try:
            if is_packet(claimed):      # a PDF packet: every page to its child (see "PDF packets")
                results = process_packet(claimed, roster, out_dir, proj, log, grade, sorted_dir, unsorted_dir)
            else:
                results = process_photo(claimed, roster, out_dir, proj, grid, log, grade, sorted_dir, unsorted_dir)
        except Exception as e:  # one bad photo must not stop the watcher
            if not os.path.exists(claimed):
                log(f"{p}: vanished while it was being sorted; nothing counted")
                if marker:
                    clear_marker(marker)
                continue
            failed = os.path.join(inbox, FAILED_FOLDER)
            try:
                make_inside(inbox, failed)
                shutil.move(claimed, os.path.join(failed, p))
            except OSError as stuck:
                log(f"{p}: this photo could not be sorted, because {why_not_sorted(e)[1]}. It could not be moved "
                    f"to inbox/failed either ({stuck}), so it is still in the folder 'done'. The program's own "
                    f"words were: {type(e).__name__}: {e}")
                raise
            # Say why, and what to do, where the teacher and a person looking
            # from somewhere else will see it (see tell_could_not_sort).
            told = tell_could_not_sort(p, proj, e, inbox, held_in, out_dir, log, unsorted_dir, sorted_dir)
            if could_not is not None:
                could_not.append(told)
            if marker:
                clear_marker(marker)
            continue
        write_report(out_dir, claimed, results)
        if marker:
            clear_marker(marker)
        summary.extend(results)
    return summary


def my_drive_candidates():
    """Places Google Drive for desktop puts "My Drive" on this machine."""
    home = os.path.expanduser("~")
    cands = []
    if IS_WIN:
        cands.append(os.path.join(home, "My Drive"))                 # Mirror files
        for letter in "GHIJKLMNOPQRSTUVWXYZDEF":                     # Stream files: a drive letter
            cands.append(f"{letter}:\\My Drive")
        cands.append(os.path.join(home, "Google Drive", "My Drive"))  # older installs
    else:
        import glob
        cands += sorted(glob.glob(os.path.join(home, "Library", "CloudStorage", "GoogleDrive-*", "My Drive")))
        cands.append(os.path.join(home, "Google Drive", "My Drive"))
    return cands


# ------------------- a folder name that ends with a space or a full stop ---
#
# A Mac, a phone and Google Drive in a browser keep a folder name exactly as
# it was typed, so a class folder called "Kindergarten - Room 3 " (a space at
# the end) is a name like any other there. Windows cannot open a folder whose
# name ends with a space or a full stop: it takes them off the names it makes
# and File Explorer cannot show them. So a settings file written on a Mac can
# name a folder that a classroom PC has under a different name, or does not
# have at all. safe_folder already knows this for the folders the tool makes;
# these are for the folders a person made and the settings file names.
#   - bad_endings says which names in a path end that way, for the self-check,
#     the log and the class tool;
#   - as_found_here gives the path as this computer has it, so the day the
#     folder is renamed in Google Drive the settings file on every computer
#     still leads to it and nobody has to edit one.
# Nothing here is Mac-only or Windows-only.

def bad_endings(path):
    """The folder names in a path that end with a space or a full stop, each once."""
    out = []
    for part in re.split(r"[\\/]+", str(path or "")):
        if part.strip(" .") and part != part.rstrip(" .") and part not in out:
            out.append(part)
    return out


def without_bad_endings(path):
    """The same path with the spaces and full stops taken off the end of every name in it."""
    parts = re.split(r"([\\/]+)", str(path))
    return "".join(p.rstrip(" .") if i % 2 == 0 and p.strip(" .") else p for i, p in enumerate(parts))


def as_found_here(path):
    """The path as this computer has it. On Windows a name cannot end with a
    space or a full stop, so the name without them is the only one there can
    be. Anywhere else the path is used as written when it is there, and
    without the endings when only that one is there (the folder was renamed)."""
    clean = without_bad_endings(path)
    if clean == path:
        return path
    if IS_WIN:
        return clean
    return clean if os.path.exists(clean) and not os.path.exists(path) else path


def ending_word(name):
    return "a space" if name.endswith(" ") else "a full stop"


def name_ending_lines(raw, st):
    """What the self-check says about names in the settings file that end with
    a space or a full stop, as (kind, [lines]) with kind "ok", "WARN" or "FAIL"."""
    found, said = [], set()
    for k in ("sorted", "inbox", "unsorted", "roster"):
        given, used = raw.get(k), st.get(k)
        if not isinstance(given, str) or not isinstance(used, str):
            continue
        for name in bad_endings(given):
            if name in said:
                continue
            said.add(name)
            clean, what = name.rstrip(" ."), ending_word(name)
            rename = (f"In Google Drive (drive.google.com), rename the folder to '{clean}': the same name "
                      f"without {what} at the end.")
            if not os.path.exists(used):
                found.append(("FAIL", [
                    f"the name '{name}' in the settings file ends with {what}, and this computer cannot find "
                    f"the folder under that name or as '{clean}'.",
                    f"A Windows PC cannot open a folder whose name ends with a space or a full stop. {rename}",
                    "Wait a minute for the change to arrive on this computer, then run this check again."]))
            elif name in bad_endings(used):
                found.append(("WARN", [
                    f"the folder name '{name}' ends with {what}. This computer can open it, but a Windows PC "
                    f"cannot: Windows does not allow {what} at the end of a folder name.",
                    "A classroom PC that watches this class may never find the folder, or may make a second "
                    "class folder beside it.",
                    rename,
                    "Then double-click Setup again on every computer that watches this class. "
                    "The settings file can stay as it is."]))
            else:
                found.append(("ok", [
                    f"the settings file says '{name}', with {what} at the end; on this computer the folder "
                    f"is '{clean}', and that is the one used.",
                    f"If the folder in Google Drive still has {what} at the end of its name, take it off there too."]))
    return found


def name_ending_note(raw, used):
    """One sentence for the watcher's log, or None: the settings file names a
    folder that ends with a space or a full stop, and the folders this
    computer is using (or cannot find) are spelled that way."""
    for k in ("sorted", "inbox", "unsorted", "roster"):
        given = raw.get(k) if raw else None
        if not isinstance(given, str):
            continue
        for name in bad_endings(given):
            if all(os.path.exists(p) and name not in bad_endings(p) for p in used if p):
                continue        # found under the name without the ending: nothing to say
            clean, what = name.rstrip(" ."), ending_word(name)
            return (f"the folder name '{name}' in the settings file ends with {what}. A Windows PC cannot open "
                    f"a folder whose name ends with a space or a full stop. In Google Drive (drive.google.com), "
                    f"rename the folder to '{clean}', the same name without {what} at the end, then double-click "
                    f"Setup again on every computer that watches this class. The settings file can stay as it is.")
    return None


def own_separators(path, sep=os.sep):
    """The same path written with this computer's own separator. A settings
    file is written once and copied to every computer that watches the class,
    so it says '{DRIVE}/Room 3/Wall Inbox' with forward slashes on a Windows
    PC too. Windows opens such a path, but it then printed and compared it as
    'C:\\...\\Room 3/Wall Inbox', half one way and half the other. On Windows a
    forward slash can never be part of a name, so turning each into a
    backslash loses nothing. On a Mac nothing is changed: a backslash there
    can be part of a name."""
    return path.replace("/", "\\") if sep == "\\" and isinstance(path, str) else path


def expand_path(v):
    """~, environment variables, and the token {DRIVE} for wherever Google
    Drive's "My Drive" is on this machine (checked against the rest of the
    path, so a Mac with two accounts picks the one that has the folder).
    A name that ends with a space or a full stop is looked for both ways
    (as_found_here). The path comes back with this computer's own separators
    (own_separators)."""
    v = own_separators(os.path.expanduser(os.path.expandvars(v)))
    if "{DRIVE}" in v:
        rest = v.split("{DRIVE}", 1)[1].lstrip("/\\")
        cands = my_drive_candidates()
        for c in cands:
            if os.path.isdir(c) and (not rest or os.path.exists(as_found_here(os.path.join(c, rest)))):
                return as_found_here(os.path.join(c, rest)) if rest else c
        for c in cands:
            if os.path.isdir(c):
                return as_found_here(os.path.join(c, rest)) if rest else c
        return as_found_here(os.path.join(cands[0], rest)) if rest else cands[0]
    return as_found_here(v)


def load_raw_settings(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolve_paths(a, raw_settings, given):
    """Work out the folders in the settings file again, for the watcher:
    Drive's "My Drive" may appear, move, or switch between a mirrored folder
    and a drive letter while the watcher runs. What was given on the command
    line is left as it was."""
    for key, attr in (("inbox", "inbox"), ("sorted", "sorted_dir"), ("unsorted", "unsorted_dir"),
                      ("roster", "roster"), ("out", "out")):
        if key in raw_settings and key not in given and isinstance(raw_settings[key], str):
            setattr(a, attr, expand_path(raw_settings[key]))


def load_settings(path):
    """settings.local.json: inbox, sorted, unsorted, roster, project, grade,
    interval. Paths may use ~, %USERPROFILE%-style variables, and {DRIVE}."""
    raw = load_raw_settings(path)
    out = {}
    for k, v in raw.items():
        if isinstance(v, str) and k in ("inbox", "sorted", "unsorted", "roster", "out"):
            v = expand_path(v)
        out[k] = v
    return out


# A watcher reads the settings file and the program once, when it starts, and
# works that way until it is started again. So a repair that is already on this
# computer's disk (a new version of the program, or "shared": true and a new
# priority in the settings file) changes nothing until then. The self-check
# reads the settings file too, so it described the watcher the settings ask
# for, not the one that was running: it said "this computer leaves each new
# photo for that computer for 10 minutes" about a watcher that sorted every
# photo at once. watcher_behind finds that out from this computer's own status
# file, and the check says so with the one thing to do. Nothing in it is
# Mac-only or Windows-only.
BEHIND_TEXT = ("the control tower that is running on this computer is still working the old way. A control tower reads the "
               "settings file and the program once, when it starts, and nobody has started it again since they "
               "changed.")
RESTART_TEXT = ("Double-click Setup (Setup.command on a Mac, Setup.bat on a Windows PC): it starts the control tower "
                "again, and from then on it works the new way. Photos in Arrivals wait and are sorted "
                "afterwards; nothing is lost. If Setup is what you are running now, it does that next.")
STARTED_FORMAT = "%b %d %Y %I:%M %p"    # the 'Watcher started' line of a status file, to the minute


def started_at(text):
    """When the watcher that wrote this status file started, from its 'Watcher
    started' line (that computer's own clock, to the minute). None when the
    file has no such line or it cannot be read as a time."""
    for ln in text.splitlines():
        if ln.lower().startswith("watcher started:"):
            try:
                return dt.datetime.strptime(ln.split(":", 1)[1].strip(), STARTED_FORMAT).timestamp()
            except (ValueError, OverflowError, OSError):
                return None
    return None


def program_files():
    """The files a watcher on this computer runs: the program itself, and on a
    Windows PC the windowless watcher beside it."""
    if getattr(sys, "frozen", False):
        files = [os.path.abspath(sys.executable), os.path.join(HERE, "BaggageClaimWatcher.exe")]
    else:
        files = [os.path.abspath(__file__)]
    return [f for f in files if os.path.exists(f)]


def changed_at(paths):
    """The last time any of these files was changed or put in place, or None
    when none of them can be found. Unzipping a new version keeps the date the
    program was built, which can be days old, so the time the file arrived on
    this disk counts as well."""
    times = []
    for p in paths:
        try:
            s = os.stat(p)
        except (OSError, TypeError):
            continue
        times.append(max(s.st_mtime, s.st_ctime))
    return max(times) if times else None


def watcher_behind(sdir, machine, st, settings_path, now=None, program=None):
    """Is the watcher that is running on this computer still working the way
    it started, although the settings file or the program has changed since?
    Returns the reasons as plain sentences; [] when it is up to date, and when
    no watcher is running here (its status file is missing or old)."""
    now = time.time() if now is None else now
    try:
        with open(os.path.join(sdir, machine + ".txt"), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    mine = parse_status(text)
    if not mine or not is_fresh(mine, now):
        return []
    why = []
    try:
        wanted = int(st.get("priority", DEFAULT_PRIORITY))
    except (TypeError, ValueError):
        wanted = DEFAULT_PRIORITY
    if int(mine["priority"]) != wanted:
        why.append(f"It sorts with priority {mine['priority']}; the settings file says {wanted}.")
    told = any(ln.lower().startswith("note:") for ln in text.splitlines())
    if (is_yes(st.get("shared")) and mine["role"] == "watching" and not told
            and never_reported_in(read_statuses(sdir), {"machine": machine})):
        why.append("The settings file says another computer is a control tower for this class too. The control tower that is running "
                   "does not know that: it sorts each new photo at once and does not leave it for the other "
                   "computer first, so a child can get the same piece twice.")
    started = started_at(text)
    if started is not None:
        said = lambda t: f"{dt.datetime.fromtimestamp(t):%b %d %I:%M %p}"      # noqa: E731
        for what, paths in (("settings file", [settings_path]),
                            ("program", program_files() if program is None else program)):
            t = changed_at(paths)
            if t is not None and t > started + 60:
                why.append(f"The {what} was changed at {said(t)}, after the control tower started ({said(started)}).")
    return why


def self_check(settings_path=None):
    """Prove the machine can do the job: reader present, a rendered word read
    back, HEIC support, folders reachable. Prints a report; returns 0 or 1.
    Checks the settings file given on the command line, else the
    settings.local.json beside the program (the teacher's case).

    The word is drawn upright and read with one look, the picture as it is
    (AS_IT_IS), and the line printed is the one line that holds the word. A
    Windows PC otherwise reads every picture four ways up and at several
    sizes, and the check printed all of it run together: the word, and the
    nonsense the reader makes of the same word seen sideways and upside
    down. That was harmless and looked like a fault."""
    from PIL import ImageDraw, ImageFont
    ok = True
    print(f"platform: {sys.platform}   reader: {backend_name()}")
    if not backend_ready():
        print("  FAIL: reader not available"
              + ("; run: pip install winsdk" if IS_WIN else "; run: swiftc -O vision.swift -o vision"))
        return 1
    img = Image.new("RGB", (900, 300), "white")
    d = ImageDraw.Draw(img)
    font = None
    for cand in ("arial.ttf", "Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
                 "C:/Windows/Fonts/arial.ttf", "/Library/Fonts/Arial.ttf"):
        try:
            font = ImageFont.truetype(cand, 120)
            break
        except OSError:
            continue
    d.text((40, 80), "Baggage 42", fill="black", font=font)
    # In a scratch folder of its own, like every photo (see scratch_folder). It
    # used to be one fixed file, <tool folder>/.selfcheck.png: two checks at
    # the same time, one per class, wrote and deleted the same file, and the
    # slower one stopped with "No such file or directory".
    tmpdir = scratch_folder(HERE)
    tmp = os.path.join(tmpdir, "selfcheck.png")
    try:
        img.save(tmp)
        lines = [t["text"].strip() for t in run_vision("text", tmp, AS_IT_IS)]
    finally:
        drop_scratch(tmpdir)
    got = next((t for t in lines if "baggage" in norm(t)), " ".join(lines))
    if "baggage" in norm(got):
        print(f"  ok: reader read back '{got}'")
    else:
        print(f"  FAIL: reader returned '{got}' for 'Baggage 42'")
        ok = False
    try:
        import pillow_heif  # noqa: F401
        print("  ok: HEIC (iPhone photos) via pillow-heif")
    except ImportError:
        print("  ok: HEIC via macOS sips" if IS_MAC else "  WARN: no HEIC support; run: pip install pillow-heif")
    # PDF packets need two more parts; without them photos are sorted as usual,
    # so this is a warning and never a reason for NOT READY
    print(f"  {pdf_parts_text()}")
    found = [c for c in my_drive_candidates() if os.path.isdir(c)]
    print(f"  {'ok' if found else 'WARN'}: Google Drive 'My Drive' folder "
          + (f"found at {found[0]}" if found else "not found (is Google Drive for desktop installed and signed in?)"))
    sp = settings_path or os.path.join(HERE, "settings.local.json")
    if os.path.exists(sp):
        st = load_settings(sp)
        for k in ("inbox", "sorted", "unsorted"):
            p = st.get(k)
            if p:
                print(f"  {'ok' if os.path.isdir(p) else 'FAIL'}: {k} folder {p}")
                ok = ok and os.path.isdir(p)
        if not all(os.path.isdir(st.get(k, "")) for k in ("inbox", "sorted", "unsorted")):
            print("  hint: a class folder shared with you is in 'Shared with me', which Drive for desktop does not sync.")
            print("        On drive.google.com: Shared with me > right-click the class folder > Organize > Add shortcut > My Drive.")
            print("        Then wait a minute for it to sync and run this check again.")
        # a folder name that ends with a space or a full stop: fine on a Mac,
        # impossible on a Windows PC (see bad_endings)
        for kind, lines in name_ending_lines(load_raw_settings(sp), st):
            print(f"  {kind}: {lines[0]}")
            for more in lines[1:]:
                print(f"        {more}")
            ok = ok and kind != "FAIL"
        r = st.get("roster")
        if r:
            try:
                n = len(load_roster(r)) if os.path.exists(r) else 0
            except (OSError, UnicodeError) as e:
                n = 0
                print(f"  FAIL: the class list cannot be read: {e}")
            print(f"  {'ok' if n else 'FAIL'}: roster {r} ({n} children)")
            ok = ok and n > 0
        if st.get("sorted") and os.path.isdir(st["sorted"]):
            print(f"  control towers for this class (from '{STATUS_FOLDER}' in the class folder; "
                  f"this computer is {machine_name()}, priority {st.get('priority', DEFAULT_PRIORITY)}):")
            for line in describe_statuses(read_statuses(status_dir(st["sorted"])), time.time(), me=machine_name()):
                print(line)
            print(f"    not in this list: {UNSEEN_TEXT[0].lower()}{UNSEEN_TEXT[1:]}")
            # The settings file says what the watcher is asked to do. The
            # watcher that is running may have started before the file, or the
            # program, was changed (see watcher_behind), and then the check
            # must not say it does what the file asks.
            behind = watcher_behind(status_dir(st["sorted"]), machine_name(), st, sp)
            if is_yes(st.get("shared")):
                me = {"machine": machine_name()}
                if behind:
                    print("    this class is shared, the settings file says. The control tower that is running on this "
                          "computer started before that was written; see the WARN below.")
                elif never_reported_in(read_statuses(status_dir(st["sorted"])), me):
                    print(f"    this class is shared: {shared_text()}")
                else:
                    print("    this class is shared, and the other computer has reported in, so the two take turns "
                          "and no photo is kept waiting.")
            # READY is kept: this computer can do the job, and Setup, which
            # starts the watcher again, must not be stopped by its own check.
            if behind:
                print(f"  WARN: {BEHIND_TEXT}")
                for line in behind + [RESTART_TEXT]:
                    print(f"        {line}")
    else:
        print(f"  FAIL: {os.path.basename(sp)} is missing from {os.path.dirname(sp) or 'this folder'}. It names the class folder to watch.")
        print("        Copy it from the class's Drive folder, or from the zip you downloaded, into this folder.")
        ok = False
    print("READY" if ok else "NOT READY")
    return 0 if ok else 1


def fetch_cloud_files(libc=None):
    """Tell macOS this program may fetch a file Google Drive has listed but not
    yet downloaded. A program started in the background (the watcher, under
    launchd) is not allowed to by default: reading such a file fails with
    "Resource deadlock avoided" for as long as nobody else opens it, so a new
    photo sat in Wall Inbox as "still arriving" until a person happened to
    open it. Found October 2, 2026, the day after the photo of October 1 was
    blamed on Drive being slow. Returns the policy now in force (2 is "may
    fetch"), or None where there is nothing to set."""
    if sys.platform != "darwin":
        return None
    try:
        import ctypes
        libc = libc or ctypes.CDLL(None)
        # IOPOL_TYPE_VFS_MATERIALIZE_DATALESS_FILES = 3, IOPOL_SCOPE_PROCESS = 0, ..._ON = 2
        libc.setiopolicy_np(3, 0, 2)
        return libc.getiopolicy_np(3, 0)
    except Exception:
        return None


def keep_awake(popen=None, pid=None):
    """Ask the computer not to doze while the watcher runs. A dozing computer
    sees no new photo, and after it wakes the watcher stands by for 90 seconds
    more. The screen may still go dark, and a closed lid still sleeps: the
    watching computer is left on with its lid open. Returns what was started,
    or None when this computer has no way to be asked."""
    try:
        if IS_WIN:
            import ctypes
            # ES_CONTINUOUS | ES_SYSTEM_REQUIRED: holds for as long as this program runs
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
            return "windows"
        if sys.platform == "darwin":
            # caffeinate ends by itself when the watcher does (-w)
            return (popen or subprocess.Popen)(["/usr/bin/caffeinate", "-i", "-w", str(pid or os.getpid())],
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return None


def watch_lock_path(log=None, out=None):
    """Where the one-watcher-per-class lock lives: next to the log file when
    there is one (each class has its own log), else in the output folder."""
    if log:
        return os.path.abspath(log) + ".lock"
    return os.path.join(out or HERE, ".watch-lock")


def claim_watch_lock(path):
    """Only one watcher may run for a class on one machine; two would race for
    the same photos. Returns (open lock file, None) when this process now holds
    the lock: keep the file open for as long as the watcher runs. Returns
    (None, other process id or "") when a live watcher already holds it. The
    lock is held by the operating system, not by the file's contents, so a lock
    left behind by a crashed or killed watcher is free and is simply taken over."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    f = open(path, "a+", encoding="utf-8")
    try:
        f.seek(0)
        if IS_WIN:
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        if e.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK, errno.EDEADLK):
            return f, None          # this disk cannot lock files (some network drives); run without the guard
        try:
            f.seek(0)
            other = f.read().strip()
        except OSError:
            other = ""              # Windows will not let us read a locked byte
        f.close()
        return None, other
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    return f, None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Baggage Claim: photograph the wall of student work, get one folder per child.")
    ap.add_argument("--settings", help="settings.local.json holding inbox, sorted, unsorted, roster, project, grade")
    ap.add_argument("--check", action="store_true", help="test that this machine can read names and reach its folders")
    ap.add_argument("--log", help="append progress to this file (for the background watcher)")
    ap.add_argument("photos", nargs="*", help="photo files; default: everything in inbox/")
    ap.add_argument("--inbox", default=os.path.join(HERE, "inbox"))
    ap.add_argument("--out", default=HERE, help="folder holding sorted/ and unsorted/")
    ap.add_argument("--sorted", dest="sorted_dir", default=None,
                    help="put the per-child folders here instead of out/sorted, e.g. a Google Drive folder")
    ap.add_argument("--unsorted", dest="unsorted_dir", default=None,
                    help="put doubtful pieces here instead of out/unsorted, e.g. a Drive folder the teacher can see")
    ap.add_argument("--roster", default=os.path.join(HERE, "roster.txt"))
    ap.add_argument("--project", default="Artwork", help="what the work is, used as the folder and file name, e.g. Self-Portrait")
    ap.add_argument("--grade", default="", help="grade level added to the file name, e.g. Kindergarten")
    ap.add_argument("--grid", help="manual override, e.g. 2x4 (rows x columns)")
    ap.add_argument("--watch", action="store_true", help="keep running; sort new photos as they land in inbox/")
    ap.add_argument("--docx", action="store_true", help="also build one .docx per child with a page per piece")
    ap.add_argument("--interval", type=float, default=5.0, help="seconds between looks at the inbox in --watch mode")
    ap.add_argument("--priority", type=int, default=DEFAULT_PRIORITY,
                    help="when more than one computer watches the same class, the lowest number sorts (default 50)")
    ap.add_argument("--shared", action="store_true", default=False,
                    help="another computer watches this class too; until it has reported in, each new photo is "
                         "left for it for 10 minutes before this computer sorts it")
    a = ap.parse_args(argv)
    if a.check:
        return self_check(a.settings)
    if a.settings:
        st = load_settings(a.settings)
        given = {x.lstrip("-").split("=")[0] for x in (argv if argv is not None else sys.argv[1:]) if x.startswith("--")}
        for key, attr in (("inbox", "inbox"), ("out", "out"), ("sorted", "sorted_dir"), ("unsorted", "unsorted_dir"),
                          ("roster", "roster"), ("project", "project"), ("grade", "grade"), ("interval", "interval"),
                          ("priority", "priority"), ("shared", "shared")):
            if key in st and key not in given:
                setattr(a, attr, st[key])
        a.shared = is_yes(a.shared)
        set_also_called(st.get("also_called"))
        try:
            a.priority = int(a.priority)
        except (TypeError, ValueError):
            print(f"priority in the settings file should be a whole number; using {DEFAULT_PRIORITY}", flush=True)
            a.priority = DEFAULT_PRIORITY
    if a.log:
        os.makedirs(os.path.dirname(os.path.abspath(a.log)), exist_ok=True)
        logf = open(a.log, "a", encoding="utf-8", buffering=1)

        class Tee:
            # A watcher with no window (BaggageClaimWatcher.exe, or pythonw)
            # has no console: sys.__stdout__ is None there. Writing to it
            # stopped the watcher at its first line, before the line reached
            # the log. With no console the log is the only place, and enough.
            def write(self, x):
                if sys.__stdout__ is not None:
                    sys.__stdout__.write(x)
                logf.write(x)

            def flush(self):
                if sys.__stdout__ is not None:
                    sys.__stdout__.flush()
                logf.flush()
        sys.stdout = Tee()

    # The project from --project or the settings file is cleaned once, here,
    # so the folder, the file names and the GUESS names agree on every computer.
    given_project, a.project = a.project, clean_project(a.project)
    say_cleaned(given_project, a.project, lambda m: print(f"{dt.datetime.now():%b %d %I:%M %p}: {m}", flush=True),
                "--project")

    if a.watch:
        # One watcher per class on this machine. A second one (started by hand
        # while launchd's is running, or the other way round) says so and
        # closes; launchd waits 30 seconds before trying again.
        watch_lock, other = claim_watch_lock(watch_lock_path(a.log, a.out))
        if watch_lock is None:
            who = f" (process {other})" if other else ""
            print(f"{dt.datetime.now():%b %d %I:%M %p}: another control tower is already running for this class{who}, "
                  "so this one is closing. Two control towers would fight over the same photos.", flush=True)
            return 0
        # A watcher must never die because a folder is not there yet: Drive may
        # not have synced, or the class folder is still in "Shared with me"
        # without a shortcut in My Drive. Say so, once a minute, and wait.
        said = None
        raw_settings = load_raw_settings(a.settings) if a.settings else None
        while True:
            if raw_settings:
                # Re-resolve every time: Drive's "My Drive" may appear, move, or
                # switch between a mirrored folder and a drive letter after login.
                resolve_paths(a, raw_settings, given)
            missing = [x for x in (a.roster, a.inbox) if not os.path.exists(x)]
            unreadable = None
            if not missing:
                try:
                    roster = load_roster(a.roster)
                except (OSError, UnicodeError) as e:
                    # a class list saved in a way this program cannot read
                    # must not end the watcher: launchd and Task Scheduler
                    # would start it again every 30 to 60 seconds for ever
                    roster, unreadable = [], str(e)
                if roster:
                    break
                missing = [f"{a.roster} (empty)"]
            found = [c for c in my_drive_candidates() if os.path.isdir(c)]
            msg = ("waiting: cannot find " + "; ".join(missing)
                   + f". My Drive folders seen on this machine: {found or 'none'}"
                   + ". Is Google Drive signed in and synced? A folder shared with you must be added to My Drive "
                     "(drive.google.com > Shared with me > right-click > Organize > Add shortcut > My Drive).")
            ending = name_ending_note(raw_settings, [a.inbox, a.roster])
            if ending:
                msg += " Also: " + ending
            if unreadable:
                msg = (f"waiting: the class list cannot be read: {unreadable}. The file is "
                       f"'{os.path.basename(a.roster)}' in the class folder. Nothing is sorted until then; "
                       "the control tower starts by itself within a minute of the list being saved again.")
            if msg != said:
                print(f"{dt.datetime.now():%b %d %I:%M %p}: {msg}", flush=True)
                said = msg
            time.sleep(60)
    else:
        try:
            roster = load_roster(a.roster)
        except UnicodeError as e:
            sys.exit(f"the class list cannot be read: {e}. The file is {a.roster}")
        if not roster:
            sys.exit(f"roster is empty: {a.roster}")
    grid = tuple(int(x) for x in a.grid.lower().split("x")) if a.grid else None

    os.makedirs(a.out, exist_ok=True)
    make_child_folders(roster, a.out, a.project, a.sorted_dir)
    if a.photos:
        for p in a.photos:
            if is_packet(p):
                write_report(a.out, p, process_packet(p, roster, a.out, a.project, grade=a.grade,
                                                      sorted_dir=a.sorted_dir, unsorted_dir=a.unsorted_dir))
                continue
            write_report(a.out, p, process_photo(p, roster, a.out, a.project, grid, grade=a.grade,
                                                 sorted_dir=a.sorted_dir, unsorted_dir=a.unsorted_dir))
        if a.docx:
            build_all_docx(a.out, a.sorted_dir, own_folders(a))
        return 0
    if a.watch:
        me = {"machine": machine_name(), "priority": a.priority}
        sdir = status_dir(sorted_root(a.out, a.sorted_dir))
        keep_awake()
        policy = fetch_cloud_files()
        if policy is not None and policy != 2:
            print(f"{dt.datetime.now():%b %d %I:%M %p}: macOS would not let this program fetch files Google Drive has "
                  f"not downloaded yet (policy {policy}); a new photo may wait until someone opens it", flush=True)
        print(f"control tower for {a.inbox} (Ctrl+C to stop)", flush=True)
        print(f"this computer is called {me['machine']} (priority {me['priority']}); its status file is in "
              f"'{STATUS_FOLDER}' inside the class folder", flush=True)
        ending = name_ending_note(raw_settings, [a.inbox, a.sorted_dir])
        if ending:
            print(f"{dt.datetime.now():%b %d %I:%M %p}: {ending}", flush=True)
        # Was this computer stopped in the middle of a photo last time? Say so
        # now, whether or not it is the one that sorts today.
        tell_unfinished(a.inbox, a.out, lambda m: print(f"{dt.datetime.now():%b %d %I:%M %p}: {m}", flush=True),
                        a.unsorted_dir, a.sorted_dir)
        last_err = None
        started = time.time()
        grace_from = started    # the grace period runs from here; a wake from sleep moves it to now
        last_look = None        # when this loop last looked at the inbox, to notice a sleep
        said_role = None
        status = {"last": None, "err": None, "lost": False}     # see keep_status
        last_batch = "none yet"
        in_failed = 0           # photos in 'failed' inside Wall Inbox, for the status file (see photos_in_failed)
        silent_seen = None      # when another computer was last caught sorting without a status file
        recent = {}             # folders this computer just filed into, to notice a second copy arriving
        roster_seen = {}        # what refresh_roster remembers about the class list file
        # Every child on the list got a folder a moment ago, at start. From
        # here on only a child who is new on the list gets one, so a folder
        # the teacher deletes stays deleted (see make_new_child_folders).
        folders_made = {}
        make_new_child_folders(roster, a.out, a.project, a.sorted_dir, folders_made)
        first_seen = {}         # shared class: photos being left for a computer that has never reported in
        said_shared = False
        said_gone = None        # what the log last said about a folder that is not where it was
        say = lambda m: print(f"{dt.datetime.now():%b %d %I:%M %p}: {m}", flush=True)   # noqa: E731
        while True:
            now = time.time()
            # Are 'Wall Inbox' and the class folder still where they were? A
            # teacher can rename one, and Google Drive can sign out. This is
            # looked at first, on every look, because everything below reads
            # from the two folders or makes something in them. When one is
            # gone the paths are worked out again (Drive's "My Drive" may have
            # moved); if it is still gone, the log says so once, this
            # computer's status file says so for as long as the class folder
            # is there to hold it, and nothing is made, read or sorted.
            gone = folders_gone(a.inbox, a.sorted_dir)
            moved = False
            if gone and raw_settings:
                resolve_paths(a, raw_settings, given)
                sdir = status_dir(sorted_root(a.out, a.sorted_dir))
                gone = folders_gone(a.inbox, a.sorted_dir)
                moved = not gone        # found in another place: "My Drive" moved, or an ending was taken off
            if gone:
                msg = " Also: ".join(gone_text(g) for g in gone)
                first = msg != said_gone
                if first and msg != last_err:       # not twice, when a look had already begun and said it
                    say(msg)
                said_gone = msg
                if os.path.isdir(holder_of(sdir)):
                    keep_status(status, sdir, me, {"role": "standing by", "leader": None}, say, force=first,
                                waiting="not known, because the folder cannot be found", last_batch=last_batch,
                                started=started, note=GONE_NOTE.format(name=os.path.basename(gone[0])))
                last_look = time.time()
                time.sleep(a.interval)
                continue
            came_back = moved or said_gone is not None
            if came_back:
                # Back. If Google Drive was away, this computer's copy of the
                # class folder is as old as the absence for a moment, the same
                # as after a sleep: give Drive the grace period first. A photo
                # that was being left for the other computer and went away
                # with the folder was not taken by that computer: forget it
                # without saying so.
                said_gone = None
                grace_from = now
                said_role = "starting"
                for src in [s for s in first_seen if not os.path.exists(s)]:
                    del first_seen[src]
                say(BACK_TEXT.format(inbox=a.inbox, grace=int(GRACE_SECONDS)))
            # The class list is read again whenever the file has changed, so a
            # child added in October is known on the next photo, not after
            # somebody restarts this watcher.
            roster = refresh_roster(a.roster, roster, roster_seen,
                                    lambda m: print(f"{dt.datetime.now():%b %d %I:%M %p}: {m}", flush=True))
            # Was this computer asleep? Then what it sees in the class folder
            # is as old as the sleep until Google Drive reconnects, so it must
            # not sort from that view (see slept_since). Start the grace period
            # again, say so once, and let the end of the grace announce the role.
            slept = slept_since(last_look, now)
            woke = slept > 0
            if woke:
                grace_from = now
                said_role = "starting"
                print(f"{dt.datetime.now():%b %d %I:%M %p}: this computer was asleep for "
                      f"{max(1, int(round(slept / 60)))} minutes; standing by for {int(GRACE_SECONDS)} seconds "
                      f"while Google Drive catches up, then checking who should sort", flush=True)
            # Who sorts? Read the other computers' status files, decide, and
            # say so when the answer changes. See "more than one computer".
            statuses = read_statuses(sdir)          # the files really in the folder
            heard = others_fresh(statuses, me, now)
            if silent_seen is not None and heard:
                silent_seen = None      # it has a status file after all; the election covers it
            seen = statuses + ([silent_sorter(silent_seen)] if silent_seen is not None else [])
            decision = decide_role(seen, me, now, grace_from)
            # A computer that cannot write its status file cannot be seen by
            # the others: to them it is off, and one of them sorts. So it
            # stands by, whatever the election says, until the file is back.
            if status["lost"]:
                decision = {"role": "standing by", "leader": None, "reason": STATUS_LOST_TEXT}
            role_key = decision["role"] if decision["role"] == "starting" else (decision["role"], decision["leader"])
            role_changed = role_key != said_role
            if role_changed:              # once per change, not every five seconds
                print(f"{dt.datetime.now():%b %d %I:%M %p}: {decision['reason']}", flush=True)
                said_role = role_key
            # A shared class whose other computer has never reported in: this
            # computer does not know whether that one is sorting, so it gives
            # it the first minutes with every photo (see SHARED_WAIT_SECONDS).
            unheard = a.shared and never_reported_in(statuses, me)
            holding = unheard and decision["role"] == "watching"
            if holding and not said_shared:
                say(shared_text())
                said_shared = True
            if said_shared and not unheard:
                say("the other computer has reported in, so it has this version. The two computers take turns "
                    "from now on and no photo is kept waiting.")
                said_shared = False
                first_seen.clear()
            hold = (lambda src, now=now: leave_for_the_other(first_seen, src, now, say)) if holding else None
            res = []
            waiting = 0
            taken = []
            could_not = []      # photos of this look that could not be sorted and went to 'failed'
            note = (("this class is shared with a computer that has never reported in, so each "
                     f"new photo is left for that computer for {minutes_text(SHARED_WAIT_SECONDS)} "
                     "before this computer sorts it") if holding else None)

            def tell(force=False):
                return keep_status(status, sdir, me, decision, say, force=force, waiting=waiting,
                                   last_batch=last_batch, started=started, note=note, failed=in_failed)
            try:
                # The status file is written BEFORE any sorting, never after:
                # the other computers must be able to see this one is on
                # before it touches a photo, or they sort the same photos.
                due = should_write_status(status["last"], now, force=role_changed or woke or came_back)
                if due:
                    waiting = len(inbox_jobs(a.inbox, a.project))
                    in_failed = photos_in_failed(a.inbox)
                was_lost = status["lost"]
                may_sort = tell(force=due)
                if was_lost and may_sort:
                    # The file is back. Another computer may have taken over
                    # meanwhile and be in the middle of a photo: give it the
                    # same grace as after a start, and say so in the file.
                    grace_from = now
                    decision = decide_role(seen, me, now, grace_from)
                    said_role = "starting"
                    say(STATUS_BACK_TEXT.format(grace=int(GRACE_SECONDS)))
                    tell(force=True)
                if decision["role"] == "watching" and may_sort:
                    res = run_inbox(a.inbox, roster, a.out, a.project, grid, grade=a.grade, sorted_dir=a.sorted_dir,
                                    unsorted_dir=a.unsorted_dir, taken=taken, hold=hold, beat=tell,
                                    folders=folders_made, could_not=could_not)
                    forget_gone(first_seen, say)
                    waiting = len(inbox_jobs(a.inbox, a.project))
                    in_failed = photos_in_failed(a.inbox)
            except (PermissionError, OSError) as e:
                # the folder is unreachable (permission not granted yet, Drive not
                # mounted yet after login): say so once a minute and keep waiting
                if str(e) != last_err:
                    print(f"{dt.datetime.now():%b %d %I:%M %p}: {e}", flush=True)
                    last_err = str(e)
                last_look = time.time()
                time.sleep(max(a.interval, 60))
                continue
            last_err = None
            if res or could_not:
                # A photo that could not be sorted is part of what this look
                # did, and the status file is where a person who is not at
                # this computer reads it.
                doubtful = os.path.basename(os.path.normpath(unsorted_root(a.out, a.unsorted_dir)))
                said = ". Also: ".join(t for t in (batch_text(res, doubtful) if res else "",
                                                   failed_text(could_not, doubtful)) if t)
                print(f"{dt.datetime.now():%b %d %I:%M %p}: {said}", flush=True)
                last_batch = f"{dt.datetime.now():%b %d %I:%M %p}: {said}"
            if res:
                if a.docx:
                    build_all_docx(a.out, a.sorted_dir, own_folders(a))
                note_saved(recent, res, a.out, now)
            # A computer running an older version of this tool sorts every photo
            # and writes no status file, so the election cannot see it. Two
            # things give it away: a photo taken from the inbox by nobody we
            # know, or a piece appearing in a folder this computer just filed
            # into. Either one, with no other status file fresh, means stand by.
            evidence = [f"{p} was taken from the inbox by another computer" for p in taken]
            evidence += [f"'{names[0]}' appeared in a folder this computer had just filed into"
                         for _, names in new_arrivals(recent, now)]
            if evidence and not heard:
                silent_seen = now
                print(f"{dt.datetime.now():%b %d %I:%M %p}: {old_version_warning(evidence[0])}", flush=True)
                said_role = None      # so the next tick says plainly that this computer is standing by
            # The status file again, right after a batch (or if the batch took
            # over a minute), so the other computers and a person can see what
            # this one just did. The write that matters came before the sorting.
            tell(force=bool(res or could_not))
            try:
                with open(os.path.join(a.out, ".watch-heartbeat"), "w") as f:
                    f.write(dt.datetime.now().isoformat())
            except OSError:
                pass
            last_look = time.time()     # set after the work, so a long batch is not mistaken for a sleep
            time.sleep(a.interval)
    # Once through, with a person at the keyboard. The tool's own inbox, next
    # to the program, is made the first time; any other inbox is a person's
    # folder and has to be there.
    if os.path.normpath(a.inbox) == os.path.normpath(os.path.join(HERE, "inbox")):
        os.makedirs(a.inbox, exist_ok=True)
    if not os.path.isdir(a.inbox):
        sys.exit(f"cannot find the inbox folder, so nothing was sorted: {a.inbox}. It may have been renamed, moved "
                 f"or deleted, or Google Drive may be signed out on this computer.")
    res = run_inbox(a.inbox, roster, a.out, a.project, grid, grade=a.grade, sorted_dir=a.sorted_dir,
                    unsorted_dir=a.unsorted_dir)
    conf = sum(1 for r in res if r["status"] == "confident")
    print(f"\n{len(res)} pieces: {conf} filed, {len(res) - conf} in unsorted/")
    if edges_guessed(res):
        print(f"On {len(edges_guessed(res))} of the pieces in unsorted the name was read, and the picture is what "
              f"a person has to check: the tool could not find the edges of the papers for certain "
              f"({EDGES_CAUSE}). "
              f"See the note in '{os.path.basename(os.path.normpath(unsorted_root(a.out, a.unsorted_dir)))}'.")
    if a.docx:
        for p in build_all_docx(a.out, a.sorted_dir, own_folders(a)):
            print(f"  docx: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

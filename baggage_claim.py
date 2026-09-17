#!/usr/bin/env python3
"""
Baggage Claim. Every piece of work returned to its owner.

Drop photos of the classroom wall into inbox/. Each piece of student work is
found, straightened, cropped, its teacher-written name read with Apple's
on-device text recognition, matched against roster.txt, and saved into
sorted/<Child>/. Anything the tool is not sure about goes to unsorted/ with its
best guess, plus a small strip showing only the name so a person (or Claude
Code, if you choose) can decide without ever seeing the artwork.

Nothing leaves the laptop. There is no network code in this file.
"""
import argparse
import datetime as dt
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata

import numpy as np
from PIL import Image, ImageOps
from scipy import ndimage

# When bundled into a single Windows program, "here" is the folder the .exe
# sits in (where settings.local.json and logs live), not the temp unpack dir.
HERE = (os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__)))
VISION = os.path.join(HERE, "vision")
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff"}

CONFIDENT_SCORE = 0.80   # how close the read text must be to a roster name
CONFIDENT_MARGIN = 0.10  # how far ahead of the next-best child it must be
WEAK_SCORE = 0.55        # below this we say "no name read" rather than guess
EDGE_BAND = 0.22         # top/bottom share of the page where a teacher writes the name
EDGE_BONUS = 0.04        # a name at the edge beats the same name in the body
BODY_PENALTY = 0.25      # a name inside a child's own writing is probably a character in the story
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


def run_vision(mode, path, *extra):
    """Read text or find paper rectangles with the machine's own on-device
    reader. Mac: the compiled Swift helper. Windows: the built-in Windows
    reader (no rectangle detector; returns [] for rects). Returns a list of dicts."""
    if IS_WIN:
        import vision_windows
        if not vision_windows.available():
            raise RuntimeError("Windows reader not available; run: pip install winsdk")
        if not os.path.exists(path):
            raise RuntimeError(f"vision {mode} failed: no such file {path}")
        return vision_windows.read_text(path) if mode == "text" else vision_windows.read_rects(path)
    if not IS_MAC:
        raise RuntimeError("Baggage Claim runs on macOS or Windows")
    if not os.path.exists(VISION):
        raise RuntimeError("vision helper not built; run: swiftc -O vision.swift -o vision")
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
    """Construction paper is coloured; a classroom wall is white or cream.
    Mask the saturated pixels, join them into blobs, box the blobs.
    Returns [] when the saturated part looks like the wall itself (most of
    the frame), so it never takes over on a beige wall with white paper."""
    small = img.resize((max(1, img.width // 8), max(1, img.height // 8)))
    a = np.asarray(small, dtype=float) / 255.0
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    mask = (sat > sat_min) & (mx > 0.15)
    if mask.mean() > 0.85:
        return []
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
        for x0, y0, x1, y1 in split_by_hue(blob, hue):
            # a sheet of paper is a solid rectangle; a coloured drawing on a
            # pale sheet is not, and must not be mistaken for the paper
            part = blob[y0:y1 + 1, x0:x1 + 1]
            if part.mean() < 0.45:      # a sparse blob is a drawing, not a sheet
                continue
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


def detect_pieces(img, path):
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
    if len(colors) >= 2 and agree >= max(2, 0.5 * len(colors)):
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


def load_roster(path):
    """One child per line: 'Maya' or 'Maya R.' Blank lines and # comments ignored."""
    names = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                names.append(line)
    return names


def roster_forms(name):
    """Strings a roster entry may appear as on the paper."""
    n = norm(name)
    forms = {n}
    parts = n.split()
    if parts:
        forms.add(parts[0])
    return forms


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
        for p, pen in pieces:
            n = norm(p)
            if len(n) < max(2, min(3, shortest)) or n in STOPWORDS:
                continue
            candidates.append((n, t, pen))

    best = {}  # roster name -> (score, text dict, piece)
    for n, t, pen in candidates:
        for name in roster:
            for form in roster_forms(name):
                score = difflib.SequenceMatcher(None, n, form).ratio() - pen
                # a whole-line match is worth a little more than a fragment
                if n == norm(t["text"]):
                    score = min(1.0, score + 0.02)
                # written work: the teacher's name sits at the top or bottom
                # edge; the same name in the middle is a character in the story
                ry = t.get("rel_y")
                if ry is not None:
                    if ry <= EDGE_BAND or ry >= 1 - EDGE_BAND:
                        score = min(1.0, score + EDGE_BONUS)
                    else:
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
    if top_score >= CONFIDENT_SCORE and margin >= CONFIDENT_MARGIN:
        status = "confident"
    elif top_score >= WEAK_SCORE:
        status = "unsure"
    else:
        status = "no name read"
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
    for t in run_vision("text", tmp):
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


def read_piece(tmp_path, crop):
    """Read one straightened piece. If the plain read finds nothing, try
    again at double size and with the reader's spelling correction on."""
    texts = run_vision("text", tmp_path)
    for t in texts:
        t["rel_y"] = (t["y"] + t["h"] / 2) / max(1, crop.height)
    if not texts:
        up = tmp_path + ".up.png"
        crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS).save(up)
        for t in run_vision("text", up, "corrected"):
            texts.append({**t, "x": t["x"] // 2, "y": t["y"] // 2, "w": t["w"] // 2, "h": t["h"] // 2,
                          "rel_y": (t["y"] + t["h"] / 2) / max(1, crop.height * 2)})
        os.remove(up)
    return texts


def safe_folder(name):
    """A folder name that is the same on a Mac and a PC. Windows silently
    drops a trailing period ("Maya R." becomes "Maya R"), so it is dropped
    everywhere; otherwise two machines watching one Drive would make two
    folders for one child."""
    return re.sub(r"[^A-Za-z0-9 _.\-]", "", name).strip().rstrip(". ") or "unknown"


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
    for the same child becomes 'Self-Portrait Kindergarten 2.jpg'."""
    base = f"{project} {grade}".strip()
    cand = base + ext
    n = 2
    while os.path.exists(os.path.join(folder, cand)):
        cand = f"{base} {n}{ext}"
        n += 1
    return cand


def sorted_root(out_dir, sorted_dir=None):
    """Where the per-child folders live: sorted/ inside out_dir unless a
    separate folder (for example inside Google Drive) is given."""
    return sorted_dir or os.path.join(out_dir, "sorted")


def make_child_folders(roster, out_dir, project=None, sorted_dir=None):
    """Every child on the roster gets a folder, even before any work is filed;
    with a project, the project subfolder too."""
    root = sorted_root(out_dir, sorted_dir)
    for name in roster:
        d = os.path.join(root, safe_folder(name))
        if project:
            d = os.path.join(d, safe_folder(project))
        os.makedirs(d, exist_ok=True)


def open_photo(path):
    """Open a photo the reader can use. iPhones save HEIC, which plain Pillow
    cannot read. On a Mac, macOS's own `sips` converts it to JPEG locally;
    anywhere, the `pillow-heif` package does the same in process. Returns
    (PIL image, path of a readable file, temp path to delete or None)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".heic", ".heif"):
        tmp = path + ".jpg"
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
            ImageOps.exif_transpose(Image.open(path)).convert("RGB").save(tmp, quality=95)
        except ImportError:
            if not IS_MAC:
                raise RuntimeError("HEIC photo but pillow-heif is not installed; run: pip install pillow-heif")
            res = subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "95", path, "--out", tmp],
                                 capture_output=True, text=True)
            if res.returncode != 0 or not os.path.exists(tmp):
                raise RuntimeError(f"could not convert {os.path.basename(path)}: {res.stderr.strip()}")
        return ImageOps.exif_transpose(Image.open(tmp)).convert("RGB"), tmp, tmp
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB"), path, None


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
        with open(path, "rb") as f:
            f.read(16)
        return True
    except OSError:
        return False


def unsorted_root(out_dir, unsorted_dir=None):
    return unsorted_dir or os.path.join(out_dir, "unsorted")


def process_photo(path, roster, out_dir, project, grid=None, log=print, grade="", sorted_dir=None, unsorted_dir=None):
    img, path, tmp_photo = open_photo(path)
    area = img.width * img.height
    if grid:
        quads, how = grid_boxes(img, *grid), f"grid {grid[0]}x{grid[1]}"
    else:
        quads, how = detect_pieces(img, path), "detectors"
    log(f"{os.path.basename(path)}: found {len(quads)} pieces ({how})")

    results = []
    tmpdir = os.path.join(out_dir, ".tmp")
    os.makedirs(tmpdir, exist_ok=True)
    # Second, independent reader: the whole photo at once. Its lines are
    # handed to whichever piece they sit inside. Two readers disagree in
    # useful ways; the union is matched and the best evidence wins.
    # Pass 1: read every piece on its own, and read the wall around it.
    # Pass 2: every line read near the pieces goes to exactly one piece, the
    # one it sits inside or the nearest one. A label pinned beside a paper
    # must never count for the neighbour as well.
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
        m = match_name(texts, roster)
        if m["status"] == "confident":
            dest_dir = os.path.join(sorted_root(out_dir, sorted_dir), safe_folder(m["name"]), safe_folder(project))
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, piece_name(project, grade, dest_dir))
            crop.save(dest, quality=92)
        else:
            guess = safe_folder(m["name"]) if m["name"] else "no-name"
            dest_dir = unsorted_root(out_dir, unsorted_dir)
            os.makedirs(os.path.join(dest_dir, "name-strips"), exist_ok=True)
            photo_id = os.path.splitext(os.path.basename(path))[0]
            base = f"GUESS {guess} - {project} {grade} - {photo_id} {i:02d}.jpg".replace("  ", " ")
            dest = os.path.join(dest_dir, base)
            crop.save(dest, quality=92)
            name_strip(crop, m["box"]).save(os.path.join(dest_dir, "name-strips", base), quality=92)
        os.remove(tmp)
        rel = (sorted_dir and m["status"] == "confident") or (unsorted_dir and m["status"] != "confident")
        results.append({"piece": i, "file": dest if rel else os.path.relpath(dest, out_dir),
                        "bbox": quad_bbox(q), **m})
        log(f"  piece {i}: {m['status']:12s} {m['name'] or '-':12s} "
            f"read '{m['text'] or ''}' score {m['score']}")
    shutil.rmtree(tmpdir, ignore_errors=True)
    if tmp_photo:
        os.remove(tmp_photo)
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
        im = Image.open(os.path.join(child_dir, rel))
        scale = min(page_w / im.width, page_h / im.height)
        cx, cy = int(im.width * scale), int(im.height * scale)
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


def build_all_docx(out_dir, sorted_dir=None):
    sd = sorted_root(out_dir, sorted_dir)
    made = []
    if os.path.isdir(sd):
        for child in sorted(os.listdir(sd)):
            d = os.path.join(sd, child)
            if os.path.isdir(d):
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
            f.write(f"| {r['piece']} | {r['status']} | {r['name'] or ''} | {r['text'] or ''} | "
                    f"{r['score']} | {r['file']} |\n")
        f.write("\n")


def run_inbox(inbox, roster, out_dir, project, grid=None, log=print, grade="", sorted_dir=None, unsorted_dir=None):
    done = os.path.join(inbox, "done")
    os.makedirs(done, exist_ok=True)
    make_child_folders(roster, out_dir, project, sorted_dir)
    try:
        listing = os.listdir(inbox)
    except PermissionError:
        raise PermissionError(f"macOS is not letting this program read the inbox folder. Give it access in "
                              f"System Settings > Privacy & Security > Full Disk Access, or start it from "
                              f"'Start Watcher.command' instead. Folder: {inbox}")
    # Photos straight in the inbox use the default project. A teacher can
    # also make a folder inside the inbox named for the project ("Fall
    # Leaves") and drop photos there; the folder name becomes the project.
    jobs = []  # (photo path, project, done folder)
    for p in sorted(listing):
        full = os.path.join(inbox, p)
        if p.startswith(".") or p in ("done", "failed"):
            continue
        if os.path.isdir(full):
            for q in sorted(os.listdir(full)):
                if os.path.splitext(q)[1].lower() in IMAGE_EXT and not q.startswith("."):
                    jobs.append((os.path.join(full, q), p, os.path.join(done, p)))
        elif os.path.splitext(p)[1].lower() in IMAGE_EXT:
            jobs.append((full, project, done))
    summary = []
    for src, proj, done_dir in jobs:
        p = os.path.basename(src)
        if not is_settled(src):
            log(f"{p}: still arriving, will try again")
            continue
        try:
            results = process_photo(src, roster, out_dir, proj, grid, log, grade, sorted_dir, unsorted_dir)
        except Exception as e:  # one bad photo must not stop the watcher
            log(f"{p}: could not process ({e}); moved to inbox/failed")
            failed = os.path.join(inbox, "failed")
            os.makedirs(failed, exist_ok=True)
            shutil.move(src, os.path.join(failed, p))
            continue
        write_report(out_dir, src, results)
        os.makedirs(done_dir, exist_ok=True)
        shutil.move(src, os.path.join(done_dir, p))
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


def expand_path(v):
    """~, environment variables, and the token {DRIVE} for wherever Google
    Drive's "My Drive" is on this machine (checked against the rest of the
    path, so a Mac with two accounts picks the one that has the folder)."""
    v = os.path.expanduser(os.path.expandvars(v))
    if "{DRIVE}" in v:
        rest = v.split("{DRIVE}", 1)[1].lstrip("/\\")
        cands = my_drive_candidates()
        for c in cands:
            if os.path.isdir(c) and (not rest or os.path.exists(os.path.join(c, rest))):
                return os.path.join(c, rest) if rest else c
        for c in cands:
            if os.path.isdir(c):
                return os.path.join(c, rest) if rest else c
        return os.path.join(cands[0], rest) if rest else cands[0]
    return v


def load_settings(path):
    """settings.local.json: inbox, sorted, unsorted, roster, project, grade,
    interval. Paths may use ~, %USERPROFILE%-style variables, and {DRIVE}."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for k, v in raw.items():
        if isinstance(v, str) and k in ("inbox", "sorted", "unsorted", "roster", "out"):
            v = expand_path(v)
        out[k] = v
    return out


def self_check():
    """Prove the machine can do the job: reader present, a rendered word read
    back, HEIC support, folders reachable. Prints a report; returns 0 or 1."""
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
    tmp = os.path.join(HERE, ".selfcheck.png")
    img.save(tmp)
    try:
        got = " ".join(t["text"] for t in run_vision("text", tmp))
    finally:
        os.remove(tmp)
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
    found = [c for c in my_drive_candidates() if os.path.isdir(c)]
    print(f"  {'ok' if found else 'WARN'}: Google Drive 'My Drive' folder "
          + (f"found at {found[0]}" if found else "not found (is Google Drive for desktop installed and signed in?)"))
    sp = os.path.join(HERE, "settings.local.json")
    if os.path.exists(sp):
        st = load_settings(sp)
        for k in ("inbox", "sorted", "unsorted"):
            p = st.get(k)
            if p:
                print(f"  {'ok' if os.path.isdir(p) else 'FAIL'}: {k} folder {p}")
                ok = ok and os.path.isdir(p)
        r = st.get("roster")
        if r:
            n = len(load_roster(r)) if os.path.exists(r) else 0
            print(f"  {'ok' if n else 'FAIL'}: roster {r} ({n} children)")
            ok = ok and n > 0
    else:
        print("  note: no settings.local.json yet (copy settings.example.json and edit it)")
    print("READY" if ok else "NOT READY")
    return 0 if ok else 1


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
    a = ap.parse_args(argv)
    if a.check:
        return self_check()
    if a.settings:
        st = load_settings(a.settings)
        given = {x.lstrip("-").split("=")[0] for x in (argv if argv is not None else sys.argv[1:]) if x.startswith("--")}
        for key, attr in (("inbox", "inbox"), ("out", "out"), ("sorted", "sorted_dir"), ("unsorted", "unsorted_dir"),
                          ("roster", "roster"), ("project", "project"), ("grade", "grade"), ("interval", "interval")):
            if key in st and key not in given:
                setattr(a, attr, st[key])
    if a.log:
        os.makedirs(os.path.dirname(os.path.abspath(a.log)), exist_ok=True)
        logf = open(a.log, "a", encoding="utf-8", buffering=1)

        class Tee:
            def write(self, x):
                sys.__stdout__.write(x)
                logf.write(x)

            def flush(self):
                sys.__stdout__.flush()
                logf.flush()
        sys.stdout = Tee()

    roster = load_roster(a.roster)
    if not roster:
        sys.exit(f"roster is empty: {a.roster}")
    grid = tuple(int(x) for x in a.grid.lower().split("x")) if a.grid else None

    os.makedirs(a.out, exist_ok=True)
    make_child_folders(roster, a.out, a.project, a.sorted_dir)
    if a.photos:
        for p in a.photos:
            write_report(a.out, p, process_photo(p, roster, a.out, a.project, grid, grade=a.grade,
                                                 sorted_dir=a.sorted_dir, unsorted_dir=a.unsorted_dir))
        if a.docx:
            build_all_docx(a.out, a.sorted_dir)
        return 0
    if a.watch:
        print(f"watching {a.inbox} (Ctrl+C to stop)", flush=True)
        last_err = None
        while True:
            try:
                res = run_inbox(a.inbox, roster, a.out, a.project, grid, grade=a.grade, sorted_dir=a.sorted_dir,
                                unsorted_dir=a.unsorted_dir)
            except (PermissionError, OSError) as e:
                # the folder is unreachable (permission not granted yet, Drive not
                # mounted yet after login): say so once a minute and keep waiting
                if str(e) != last_err:
                    print(f"{dt.datetime.now():%b %d %I:%M %p}: {e}", flush=True)
                    last_err = str(e)
                time.sleep(max(a.interval, 60))
                continue
            last_err = None
            if res:
                conf = sum(1 for r in res if r["status"] == "confident")
                print(f"{dt.datetime.now():%b %d %I:%M %p}: {len(res)} pieces, {conf} filed, "
                      f"{len(res) - conf} to unsorted", flush=True)
                if a.docx:
                    build_all_docx(a.out, a.sorted_dir)
            try:
                with open(os.path.join(a.out, ".watch-heartbeat"), "w") as f:
                    f.write(dt.datetime.now().isoformat())
            except OSError:
                pass
            time.sleep(a.interval)
    res = run_inbox(a.inbox, roster, a.out, a.project, grid, grade=a.grade, sorted_dir=a.sorted_dir,
                    unsorted_dir=a.unsorted_dir)
    conf = sum(1 for r in res if r["status"] == "confident")
    print(f"\n{len(res)} pieces: {conf} filed, {len(res) - conf} in unsorted/")
    if a.docx:
        for p in build_all_docx(a.out, a.sorted_dir):
            print(f"  docx: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

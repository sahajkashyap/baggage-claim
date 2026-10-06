"""Walls that follow the teacher's rules, for the contract check.

The rules a teacher is given: the work is mounted against a DARK background,
the WHOLE paper is in the frame, and the child's name is TYPED in a CORNER of
the paper. Every wall built here follows them. Invented names only."""
import os
import random
from PIL import Image, ImageDraw, ImageFont

MAC_FONTS = os.path.join(os.sep, "System", "Library", "Fonts", "Supplemental")
WINDOWS_FONTS = os.path.join(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or "C:\\Windows", "Fonts")
# Each font has a list of places; the first one that exists on this computer is used.
FONTS = {
    "arial": [os.path.join(MAC_FONTS, "Arial.ttf"), os.path.join(WINDOWS_FONTS, "arial.ttf")],
    "arial-bold": [os.path.join(MAC_FONTS, "Arial Bold.ttf"), os.path.join(WINDOWS_FONTS, "arialbd.ttf")],
    "times": [os.path.join(MAC_FONTS, "Times New Roman.ttf"), os.path.join(WINDOWS_FONTS, "times.ttf")],
    "verdana": [os.path.join(MAC_FONTS, "Verdana.ttf"), os.path.join(WINDOWS_FONTS, "verdana.ttf")],
}
DARK = {"black": (24, 24, 26), "navy": (22, 30, 62), "maroon": (70, 14, 24), "green": (18, 52, 36)}
# A real classroom wall is not always dark: a display board painted a middle
# blue, under a band of cream wall, is "dark enough" for white paper and is
# what the wall of October 1, 2026 looked like (5 of its 20 papers were found).
WALLS = dict(DARK, **{"mid-blue": (112, 160, 205)})
BAND = (226, 204, 168)
PAPER = {"white": (252, 252, 250), "cream": (255, 246, 214), "yellow": (250, 226, 110), "blue": (150, 190, 235)}
NAMES = ["Maya Torres", "Jonah Reyes", "Sofia Lund", "Elijah Park", "Priya", "Marcus", "Lily", "Theo",
         "Nadia", "Oscar", "Hazel", "Felix", "Ingrid", "Caleb", "Wren", "Dmitri", "Paloma", "Gideon",
         "Tessa", "Rafael", "Juniper", "Anders", "Bridget", "Bashir", "Clementine"]
TYPED_LINES = ["This practice sheet carries two typed lines", "so the reader meets more than a name"]


class FontNotFound(OSError):
    """None of the places a font is kept holds it on this computer."""


def font_file(font):
    """The first place on this computer that holds the font."""
    places = FONTS[font]
    for place in places:
        if os.path.isfile(place):
            return place
    raise FontNotFound(f"The practice walls are typed in the font '{font}', and this computer does not have it. "
                       f"Looked in: {'; '.join(places)}")


def contract_wall(names, rows, cols, size=(4032, 3024), bg="black", paper="white", corner="br",
                  font="arial-bold", label_pt=None, sentences=False, portrait_paper=False, seed=1, tilt=2.0,
                  touching=False, band=0.0, blank=False):
    """touching: the papers in each row hang edge to edge, with no wall
    showing between them; a sheet's own edge (a thin shadow line) is all
    that separates two children's work.
    band: this much more photo, as a fraction of its height, is added above
    the papers and shows a paler wall of another colour, with no papers on it.
    blank: the child has not drawn anything yet; the paper carries its name
    sticker and nothing else."""
    rnd = random.Random(seed)
    wall = WALLS[bg]
    img = Image.new("RGB", size, wall)
    d = ImageDraw.Draw(img)
    for _ in range(3000):
        x, y = rnd.randrange(size[0]), rnd.randrange(size[1])
        d.point((x, y), tuple(max(0, min(255, v + rnd.randint(-5, 5))) for v in wall))
    cw, ch = size[0] // cols, size[1] // rows
    truth, idx = [], 0
    for r in range(rows):
        for c in range(cols):
            if idx >= len(names):
                break
            name = names[idx]
            pw, ph = int(cw * 0.80), int(ch * 0.78)
            if touching:
                pw = cw
            if portrait_paper:
                pw = min(pw, int(ph * 0.77))
            pt = label_pt or max(26, min(70, int(min(pw, ph) * 0.085)))
            f = ImageFont.truetype(font_file(font), pt)
            p = Image.new("RGB", (pw, ph), PAPER[paper])
            pd = ImageDraw.Draw(p)
            for _ in range(0 if blank else 8):   # the child's drawing, kept out of the corners
                col = tuple(rnd.randint(0, 200) for _ in range(3))
                x0, y0 = rnd.randrange(int(pw * .2), int(pw * .7)), rnd.randrange(int(ph * .3), int(ph * .6))
                pd.ellipse((x0, y0, x0 + rnd.randint(40, int(pw * .2)), y0 + rnd.randint(40, int(ph * .2))),
                           outline=col, width=max(4, pt // 8))
                pd.line((x0, y0, rnd.randrange(int(pw * .2), int(pw * .8)), rnd.randrange(int(ph * .3), int(ph * .7))),
                        fill=col, width=max(4, pt // 7))
            tw = int(pd.textlength(name, font=f))
            lw, lh = tw + pt, int(pt * 1.7)
            m = int(pt * 0.5)
            lx = m if corner in ("tl", "bl") else pw - lw - m
            ly = m if corner in ("tl", "tr") else ph - lh - m
            if sentences:    # typed sentences along the opposite edge, as on a sheet that carries writing as well as a drawing
                sf = ImageFont.truetype(font_file("arial"), max(20, int(pt * 0.7)))
                sy = ph - int(pt * 2.6) if corner in ("tl", "tr") else int(pt * 0.6)
                for k, line in enumerate(TYPED_LINES):
                    pd.text((m * 2, sy + k * int(pt * 1.0)), line, fill=(20, 20, 30), font=sf)
            pd.rectangle((lx, ly, lx + lw, ly + lh), fill=(255, 255, 255), outline=(60, 60, 60), width=2)
            pd.text((lx + pt // 2, ly + int(pt * 0.25)), name, fill=(10, 10, 20), font=f)
            if touching:
                # the sheet's own edge: a thin shadow where it meets its neighbour
                pd.rectangle((0, 0, pw - 1, ph - 1), outline=(150, 150, 150), width=max(2, pw // 300))
                x = int(size[0] * 0.06) + c * int(size[0] * 0.88 / cols)
                y = r * ch + (ch - ph) // 2
                p = p.resize((int(size[0] * 0.88 / cols), ph))
                img.paste(p, (x, y))
                truth.append({"name": name, "box": (x, y, x + p.width, y + p.height), "landscape": p.width > ph,
                              "paper": p.copy()})
                idx += 1
                continue
            flat = p.copy()      # the paper's own picture: upright, before it is tilted or hung
            if tilt:
                p = p.rotate(rnd.uniform(-tilt, tilt), expand=True, fillcolor=wall)
            x = c * cw + (cw - p.width) // 2 + rnd.randint(-cw // 40, cw // 40)
            y = r * ch + (ch - p.height) // 2 + rnd.randint(-ch // 40, ch // 40)
            img.paste(p, (x, y))
            truth.append({"name": name, "box": (x, y, x + p.width, y + p.height), "landscape": pw > ph,
                          "paper": flat})
            idx += 1
    if band:
        up = int(size[1] * band)
        whole = Image.new("RGB", (size[0], size[1] + up), BAND)
        whole.paste(img, (0, up))
        img = whole
        for t in truth:
            x0, y0, x1, y1 = t["box"]
            t["box"] = (x0, y0 + up, x1, y1 + up)
    return img, truth


def from_the_side(img, strength=0.12, side="left", bg=(24, 24, 26)):
    """The same wall photographed from one side: the far edge is smaller."""
    w, h = img.size
    dy = int(h * strength)
    if side == "left":    # standing to the left: the right edge is farther away
        quad = (0, 0, 0, h, w, h + dy, w, -dy)
    else:
        quad = (0, -dy, 0, h + dy, w, h, w, 0)
    pad = Image.new("RGB", (w, h + 2 * dy), bg)
    pad.paste(img, (0, dy))
    quad = tuple(v + (dy if i % 2 else 0) for i, v in enumerate(quad))
    return pad.transform((w, h), Image.QUAD, quad, Image.BICUBIC, fillcolor=bg)

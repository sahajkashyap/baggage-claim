"""Build a fake photo of an art wall for tests: papers on a wall, scribbles,
names typed by the teacher, as the rule asks. Returns the image and the
truth: which name is on which paper, in reading order."""
import random
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import os
# The rule a teacher is given says the name is TYPED. So the practice walls
# are typed, in the same plain face on every computer (Arial, which a Mac and
# a Windows PC both have), and a Mac and a Windows PC are tested on the same
# promise. Until September 28, 2026 the names were drawn in a hand-printed
# face (Bradley Hand on a Mac, Comic Sans on Windows): a harder test than the
# rule, and a different test on each computer. HAND_FONT keeps that face for
# anyone who wants to see how a reader does beyond the rule: make_wall(hand=True).
MAC_FONTS = "/System/Library/Fonts/Supplemental"
WINDOWS_FONTS = os.path.join(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or "C:\\Windows", "Fonts")


def first_font(*places):
    return next((f for f in places if os.path.exists(f)), None)


FONT = first_font(os.path.join(MAC_FONTS, "Arial.ttf"), os.path.join(WINDOWS_FONTS, "arial.ttf"),
                  "/Library/Fonts/Arial.ttf")
HAND_FONT = first_font(os.path.join(MAC_FONTS, "Bradley Hand Bold.ttf"), os.path.join(WINDOWS_FONTS, "comic.ttf"),
                       os.path.join(WINDOWS_FONTS, "segoepr.ttf")) or FONT


STORY = ["Last summer I went to the beach", "with my friend {other}.", "We built a big",
         "sand castle and then the", "waves came and {other} laughed", "so hard. It was the best day."]


CONSTRUCTION = [(70, 110, 190), (200, 60, 60), (240, 170, 190), (60, 140, 90), (140, 100, 180), (235, 205, 90)]


def make_wall(names, rows=2, cols=4, size=(3200, 2400), seed=1, tilt=True,
              unnamed=(), blurred=(), wall=(214, 205, 190), writing=False,
              colored=False, labels_outside=(), cards=False, touching=False, hand=False):
    """hand: the names in a hand-printed face instead of a typed one (beyond
    the rule a teacher is given; no test asks for it, the reader probe does);
    colored: saturated construction paper on a white wall (the real case);
    labels_outside: indexes whose name is printed on a white label pinned on
    the wall just above the paper instead of on it; cards: a row of small
    white alphabet cards under the display; touching: rows placed with no gap."""
    if colored:
        wall = (246, 244, 238)
    white_on_color = (not colored) and max(wall) - min(wall) > 60   # white paper on a coloured wall
    rnd = random.Random(seed)
    img = Image.new("RGB", size, wall)
    d = ImageDraw.Draw(img)
    # a little wall texture so it is not a perfectly flat field
    for _ in range(4000):
        x, y = rnd.randrange(size[0]), rnd.randrange(size[1])
        c = tuple(max(0, min(255, v + rnd.randint(-6, 6))) for v in wall)
        d.point((x, y), c)
    face = HAND_FONT if hand else FONT
    font = ImageFont.truetype(face, 70)
    cw, ch = size[0] // cols, size[1] // rows
    truth = []
    idx = 0
    for r in range(rows):
        for c in range(cols):
            if idx >= len(names):
                break
            name = names[idx]
            pw, ph = int(cw * 0.72), int(ch * 0.74)
            if touching:
                pw, ph = int(cw * 0.72), int(ch * 0.98)
            paper_color = (CONSTRUCTION[idx % len(CONSTRUCTION)] if colored
                           else (252, 252, 250) if white_on_color
                           else rnd.choice([(250, 250, 245), (255, 248, 220), (235, 245, 255)]))
            paper = Image.new("RGB", (pw, ph), paper_color)
            pd = ImageDraw.Draw(paper)
            if writing:
                # ruled paper with a story that mentions ANOTHER child's name
                other = names[(idx + 1) % len(names)]
                small = ImageFont.truetype(face, 34)
                for k, line in enumerate(STORY):
                    yy = int(ph * 0.22) + k * 60
                    pd.line((20, yy + 44, pw - 20, yy + 44), fill=(170, 190, 220), width=2)
                    pd.text((40, yy), line.format(other=other), fill=(30, 30, 90), font=small)
            for _ in range(0 if writing else 9):  # child's drawing
                col = tuple(rnd.randint(0, 200) for _ in range(3))
                x0, y0 = rnd.randrange(pw), rnd.randrange(int(ph * 0.15), int(ph * 0.8))
                x1, y1 = rnd.randrange(pw), rnd.randrange(int(ph * 0.15), int(ph * 0.8))
                pd.line((x0, y0, x1, y1), fill=col, width=rnd.randint(6, 18))
                pd.ellipse((x0, y0, x0 + rnd.randint(40, 200), y0 + rnd.randint(40, 200)), outline=col, width=8)
            if colored:
                # a painted face with yarn hair, like a self-portrait
                fx, fy = pw // 2, int(ph * 0.55)
                pd.ellipse((fx - pw // 4, fy - ph // 4, fx + pw // 4, fy + ph // 4), fill=(190, 140, 100))
                for _ in range(40):
                    x0 = rnd.randrange(fx - pw // 4, fx + pw // 4)
                    pd.line((x0, fy - ph // 4 - rnd.randint(0, 40), x0 + rnd.randint(-30, 30), fy), fill=(60, 35, 20), width=6)
            if idx not in unnamed and idx not in labels_outside:
                where = rnd.choice(["top-left", "bottom-right"])
                tw = pd.textlength(name, font=font)
                pos = (30, 20) if where == "top-left" else (pw - tw - 40, ph - 110)
                if colored:
                    # a white typed label stuck on the paper, as a teacher does
                    lf = ImageFont.truetype(face, 40)
                    lw = int(pd.textlength(name, font=lf)) + 40
                    label = Image.new("RGB", (lw, 70), (255, 255, 255))
                    ImageDraw.Draw(label).text((20, 8), name, fill=(20, 20, 40), font=lf)
                    paper.paste(label, (30, 20) if where == "top-left" else (pw - lw - 30, 20))
                else:
                    pd.text(pos, name, fill=(20, 20, 40), font=font)
            if idx in blurred:
                paper = paper.filter(ImageFilter.GaussianBlur(9))
            if tilt and not touching:
                paper = paper.rotate(rnd.uniform(-4, 4), expand=True, fillcolor=wall)
            x = c * cw + (cw - paper.width) // 2 + (0 if touching else rnd.randint(-30, 30))
            y = r * ch + (ch - paper.height) // 2 + (0 if touching else rnd.randint(-30, 30))
            if idx in labels_outside and idx not in unnamed:
                # white label pinned on the wall just above the paper's top-right corner
                lw = int(pd.textlength(name, font=font) * 0.6) + 40
                label = Image.new("RGB", (lw, 70), (255, 255, 255))
                ImageDraw.Draw(label).text((20, 8), name, fill=(20, 20, 40), font=ImageFont.truetype(face, 40))
                img.paste(label, (min(x + paper.width - lw + 30, size[0] - lw), max(0, y - 60)))
            # soft shadow
            sh = Image.new("RGB", paper.size, tuple(max(0, v - 40) for v in wall))
            img.paste(sh, (x + 10, y + 12))
            img.paste(paper, (x, y))
            truth.append({"name": name if idx not in unnamed else None,
                          "box": (x, y, x + paper.width, y + paper.height)})
            idx += 1
    if cards:
        cf = ImageFont.truetype(face, 90)
        y = size[1] - 260
        for k, letter in enumerate("ABCDEFGHIJ"):
            card = Image.new("RGB", (240, 240), (255, 255, 255))
            ImageDraw.Draw(card).text((40, 40), f"{letter}{letter.lower()}", fill=(20, 20, 20), font=cf)
            img.paste(card, (40 + k * 300, y))
    return img, truth


if __name__ == "__main__":
    import sys
    names = ["Maya", "Jonah", "Sofia", "Elijah", "Priya", "Marcus", "Lily", "Theo"]
    img, truth = make_wall(names)
    img.save(sys.argv[1] if len(sys.argv) > 1 else "wall.jpg", quality=90)
    print([t["name"] for t in truth])

"""Practice PDF packets that follow the teacher's rule for packets.

The rule: the child's name is TYPED in a corner of the FIRST page of that
child's work; the pages after it need no name (a page with no name sticker
goes with the page before it). A name on every page also follows the rule.
"page X of Y" beside the name is optional. Two kinds of packet are made here,
both US Letter:

- DIGITAL: made on a computer (reportlab). The name is real text in the PDF.
- SCANNED: every page is a picture (Pillow), saved as an image-only PDF, the
  way a scanner makes one: the name drawn in Arial Bold, a little noise, and
  up to 1.5 degrees of skew. There is no text in the file at all.

Each page also carries a few lines of body text and a drawing, both different
on every page, so every page of a packet is a different page and the check
can tell them apart (page_fingerprint). Invented names only (contract_wall)."""
import hashlib
import os
import random

from PIL import Image, ImageDraw, ImageFont

try:
    from contract_wall import font_file, NAMES
except ImportError:                                     # imported from the repository root
    from tests.contract_wall import font_file, NAMES    # noqa: F401

LETTER = (612.0, 792.0)        # points
SCAN_DPI = 150
BODY = ["This practice sheet carries a few typed lines",
        "so the reader meets more than a name",
        "The river bent around the hill near the old bridge",
        "Green leaves turned orange in the cool autumn air",
        "We counted twelve blue shells along the sandy shore",
        "A small boat drifted past the quiet harbour wall",
        "The kite rose high above the windy playground",
        "Seven apples sat in a basket on the kitchen table"]
NUMBER_FORMS = {"page": "page {x} of {y}", "of": "{x} of {y}", "slash": "{x}/{y}"}


def packet_pages(names, per_child, corner="br", numbers=True, form="page", mixed=False, seed=1, corners=None,
                 first_only=False):
    """The list of pages for a packet: one dict per page with name, corner,
    number (x, y) or None and the number form. `per_child` is a count, or a
    list of counts used in turn. `mixed` shuffles the pages so one child's
    pages are not next to each other; `corners` gives each page a corner at
    random from that list. `first_only` puts the name (and the page number)
    on the first page of each child's work only: the pages after it carry no
    name, and 'child' says whose they are. Never with `mixed`."""
    assert not (first_only and mixed), "pages with no name must follow their child's first page"
    rnd = random.Random(seed)
    counts = per_child if isinstance(per_child, (list, tuple)) else [per_child]
    pages = []
    for k, name in enumerate(names):
        total = counts[k % len(counts)]
        for x in range(1, total + 1):
            named = x == 1 or not first_only
            pages.append({"name": name if named else None, "child": name,
                          "corner": rnd.choice(corners) if corners else corner,
                          "number": (x, total) if numbers and named else None, "form": form})
    if mixed:
        rnd.shuffle(pages)
    return pages


def _corner_xy(corner, page_w, page_h, text_w, margin, line_h, pt_scale):
    x = margin if corner in ("tl", "bl") else page_w - margin - text_w
    y = margin if corner in ("tl", "tr") else page_h - margin - line_h
    return x, y


def make_digital(path, pages, landscape=False, seed=1):
    """A PDF made on a computer: the name and the page number are real text."""
    from reportlab.pdfgen import canvas
    rnd = random.Random(seed)
    w, h = (LETTER[1], LETTER[0]) if landscape else LETTER
    c = canvas.Canvas(path, pagesize=(w, h))
    c.setTitle("practice packet")
    for n, pg in enumerate(pages, 1):
        _digital_body(c, w, h, rnd, n)
        if pg.get("name"):
            label = pg["name"]
            c.setFont("Helvetica-Bold", 16)
            nw = c.stringWidth(label, "Helvetica-Bold", 16)
            num = NUMBER_FORMS[pg.get("form") or "page"].format(x=pg["number"][0], y=pg["number"][1]) \
                if pg.get("number") else ""
            numw = c.stringWidth(num, "Helvetica", 11) if num else 0
            gap = 18 if num else 0
            total = nw + gap + numw
            margin = 36
            left = margin if pg["corner"] in ("tl", "bl") else w - margin - total
            base = h - margin - 14 if pg["corner"] in ("tl", "tr") else margin
            c.drawString(left, base, label)
            if num:
                c.setFont("Helvetica", 11)
                c.drawString(left + nw + gap, base + 1, num)
        c.showPage()
    c.save()
    return path


def _digital_body(c, w, h, rnd, n):
    c.setFont("Helvetica-Bold", 14)
    c.drawString(w * 0.30, h * 0.72, "Practice sheet")
    c.setFont("Helvetica", 12)
    lines = rnd.sample(BODY, 3)
    for k, line in enumerate(lines):
        c.drawString(w * 0.15, h * 0.64 - k * 20, line)
    c.setLineWidth(3)
    for _ in range(6):           # the drawing, kept away from the corners
        c.setStrokeColorRGB(rnd.random() * 0.7, rnd.random() * 0.7, rnd.random() * 0.7)
        x, y = rnd.uniform(w * 0.25, w * 0.65), rnd.uniform(h * 0.25, h * 0.45)
        c.circle(x, y, rnd.uniform(15, 60))
        c.line(x, y, rnd.uniform(w * 0.2, w * 0.8), rnd.uniform(h * 0.25, h * 0.5))
    c.setStrokeColorRGB(0, 0, 0)
    c.setFont("Helvetica", 9)
    c.drawString(w * 0.45, h * 0.18, "#" * (n % 5 + 1))    # a small mark that differs from page to page


def make_scanned(path, pages, landscape=False, seed=1, skew=1.5, noise=True):
    """An image-only PDF, the way a scanner makes one: no text in the file."""
    rnd = random.Random(seed)
    w, h = int(8.5 * SCAN_DPI), int(11 * SCAN_DPI)
    if landscape:
        w, h = h, w
    name_font = ImageFont.truetype(font_file("arial-bold"), int(16 / 72 * SCAN_DPI))
    small = ImageFont.truetype(font_file("arial"), int(11 / 72 * SCAN_DPI))
    body_font = ImageFont.truetype(font_file("arial"), int(12 / 72 * SCAN_DPI))
    title_font = ImageFont.truetype(font_file("arial-bold"), int(14 / 72 * SCAN_DPI))
    images = []
    for n, pg in enumerate(pages, 1):
        img = Image.new("RGB", (w, h), (250, 250, 247))
        d = ImageDraw.Draw(img)
        d.text((w * 0.30, h * 0.26), "Practice sheet", fill=(20, 20, 20), font=title_font)
        for k, line in enumerate(rnd.sample(BODY, 3)):
            d.text((w * 0.15, h * 0.34 + k * 42), line, fill=(30, 30, 30), font=body_font)
        for _ in range(6):
            col = tuple(rnd.randint(0, 180) for _ in range(3))
            x, y = rnd.uniform(w * 0.25, w * 0.65), rnd.uniform(h * 0.55, h * 0.75)
            r = rnd.uniform(30, 120)
            d.ellipse((x - r, y - r, x + r, y + r), outline=col, width=5)
            d.line((x, y, rnd.uniform(w * 0.2, w * 0.8), rnd.uniform(h * 0.5, h * 0.75)), fill=col, width=5)
        if pg.get("name"):
            label = pg["name"]
            num = NUMBER_FORMS[pg.get("form") or "page"].format(x=pg["number"][0], y=pg["number"][1]) \
                if pg.get("number") else ""
            nw = d.textlength(label, font=name_font)
            numw = d.textlength(num, font=small) if num else 0
            gap = 38 if num else 0
            margin = int(0.5 * SCAN_DPI)
            total = nw + gap + numw
            left = margin if pg["corner"] in ("tl", "bl") else w - margin - total
            top = margin if pg["corner"] in ("tl", "tr") else h - margin - name_font.size
            d.text((left, top), label, fill=(10, 10, 10), font=name_font)
            if num:
                d.text((left + nw + gap, top + name_font.size - small.size), num, fill=(10, 10, 10), font=small)
        if noise:
            for _ in range(1500):
                x, y = rnd.randrange(w), rnd.randrange(h)
                v = rnd.randint(150, 230)
                d.point((x, y), fill=(v, v, v))
        if skew:
            img = img.rotate(rnd.uniform(-skew, skew), resample=Image.BICUBIC, fillcolor=(250, 250, 247))
        images.append(img.convert("L"))
    images[0].save(path, "PDF", save_all=True, append_images=images[1:], resolution=SCAN_DPI)
    return path


def make_packet(path, pages, kind="digital", landscape=False, seed=1):
    if kind == "digital":
        return make_digital(path, pages, landscape, seed)
    return make_scanned(path, pages, landscape, seed)


def page_fingerprint(page):
    """What a page IS, from a pypdf page: its drawing instructions and every
    picture in it. A page copied from the packet into a child's PDF keeps the
    same fingerprint, so the check can tell which packet page it was."""
    h = hashlib.sha1()
    contents = page.get_contents()
    if contents is not None:
        h.update(contents.get_data())
    res = page.get("/Resources")
    res = res.get_object() if res is not None else {}
    xo = res.get("/XObject") if hasattr(res, "get") else None
    if xo is not None:
        xo = xo.get_object()
        for k in sorted(xo):
            h.update(xo[k].get_object().get_data())
    return h.hexdigest()


def fingerprints(path):
    import pypdf
    return [page_fingerprint(p) for p in pypdf.PdfReader(path).pages]

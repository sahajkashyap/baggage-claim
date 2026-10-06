"""Which way is up.

Every source photo of the September 26 walls carried the phone's orientation
tag a quarter turn wrong (the phone was tilted while shooting from the side),
so every crop was filed on its side. The name still matched, because Apple's
reader reads text at any rotation; the tell was the label's box, tall and
thin instead of wide. The rule now: the typed name label decides which way is
up, for the whole photo and for each paper, whatever way the phone was held
and whatever the tag says.

These tests build a fake wall (invented names only), turn it 90, 180 and 270
degrees, as raw pixels and as an upright file with a WRONG orientation tag,
and check that every filed crop reads upright and lands in the right child's
folder. One test hangs a single paper sideways on an otherwise upright wall.
The pure decision functions (majority angle; the arithmetic of the Windows
reading) are tested with fake reader output, and everything the Windows
reading does around its reader is run here with a pretend reader, and with
Apple's reader made to behave as the Windows reader does, in its place.

Run:  python3 -m unittest tests.test_orientation
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import baggage_claim as sw  # noqa: E402
import vision_windows as vw  # noqa: E402
from make_wall import make_wall  # noqa: E402

NAMES = ["Maya Torres", "Jonah Reyes", "Sofia Lund", "Elijah Park"]
HAVE_VISION = sw.backend_ready()


def T(text, angle=0, **kw):
    return {"text": text, "conf": 1.0, "x": 0, "y": 0, "w": 10, "h": 10, "angle": angle, **kw}


class MajorityAngleTests(unittest.TestCase):
    def test_labels_vote_first(self):
        texts = [T("Maya Torres", 90), T("Jonah Reyes", 90), T("we went to the beach", 0),
                 T("and then", 0), T("it rained", 0)]
        self.assertEqual(sw.majority_angle(texts, NAMES), 90)

    def test_all_lines_vote_when_no_label_read(self):
        texts = [T("we went", 180), T("to the", 180), T("beach", 0)]
        self.assertEqual(sw.majority_angle(texts, NAMES), 180)
        self.assertEqual(sw.majority_angle(texts), 180)

    def test_tie_goes_to_the_smaller_turn_so_zero_wins(self):
        self.assertEqual(sw.majority_angle([T("Maya Torres", 270), T("Jonah Reyes", 0)], NAMES), 0)
        self.assertEqual(sw.majority_angle([T("a b", 270), T("c d", 90)]), 90)

    def test_empty_is_zero(self):
        self.assertEqual(sw.majority_angle([], NAMES), 0)

    def test_missing_or_broken_angle_reads_as_zero(self):
        t = {"text": "Maya Torres", "conf": 1.0, "x": 0, "y": 0, "w": 10, "h": 10}
        self.assertEqual(sw.text_angle(t), 0)
        self.assertEqual(sw.text_angle({**t, "angle": "sideways"}), 0)
        self.assertEqual(sw.text_angle({**t, "angle": 450}), 90)

    def test_turn_upright_swaps_the_sides_for_a_quarter_turn(self):
        im = Image.new("RGB", (40, 20), "white")
        self.assertEqual(sw.turn_upright(im, 90).size, (20, 40))
        self.assertEqual(sw.turn_upright(im, 180).size, (40, 20))
        self.assertIs(sw.turn_upright(im, 0), im)
        self.assertIs(sw.turn_upright(im, 360), im)

    def test_decided_angle_follows_the_line_that_matched(self):
        texts = [T("Maya Torres", 90, x=5, y=6, w=50, h=12), T("scribble", 0), T("more", 0)]
        m = sw.match_name(texts, NAMES)
        self.assertEqual(m["name"], "Maya Torres")
        self.assertEqual(sw.decided_angle(texts, m, NAMES), 90)

    def test_decided_angle_falls_back_to_the_majority(self):
        texts = [T("nothing here", 180), T("at all", 180)]
        m = sw.match_name(texts, NAMES)
        self.assertIsNone(m["text"]) if m["name"] is None else None
        self.assertEqual(sw.decided_angle(texts, {"text": None, "box": None}, NAMES), 180)


class WindowsDecisionTests(unittest.TestCase):
    """The arithmetic of the Windows reading: no reader is needed for it."""

    def lines(self, *texts, angle=0, box=(1, 2, 30, 10)):
        return [{"text": t, "conf": 1.0, "x": box[0], "y": box[1], "w": box[2], "h": box[3], "angle": angle}
                for t in texts]

    def test_strength_counts_letters_in_real_words(self):
        self.assertEqual(vw.text_strength(self.lines("Maya Torres")), 10)
        self.assertEqual(vw.text_strength(self.lines("l | . 7")), 0)
        self.assertEqual(vw.text_strength([]), 0)

    def test_a_picture_is_read_at_its_own_size_then_smaller_and_doubled_when_it_is_small(self):
        self.assertEqual(vw.scales_for(740, 610), [1.0, 0.5, 2.0])          # one paper cut from a photo
        self.assertEqual(vw.scales_for(2400, 2400), [1.0, 0.5, 0.25])       # a tile of a whole wall
        self.assertEqual(vw.scales_for(900, 300), [1.0, 0.5, 0.25, 2.0])
        self.assertEqual(vw.scales_for(100, 30), [1.0, 2.0])                # too small to shrink
        self.assertEqual(vw.scales_for(1300, 900, room=2520), [1.0, 0.5, 0.25])   # doubled, it would not fit

    def test_a_large_picture_is_read_in_full_size_tiles_that_cover_it_and_overlap(self):
        self.assertEqual(vw.tile_boxes(2600, 900, 2600, 400), [(0, 0, 2600, 900)])
        boxes = vw.tile_boxes(4112, 3104, 2600, 400)
        self.assertEqual(len(boxes), 4)
        for x0, y0, x1, y1 in boxes:
            self.assertLessEqual(x1 - x0, 2600)
            self.assertLessEqual(y1 - y0, 2600)
        for x in range(0, 4112, 97):
            for y in range(0, 3104, 89):
                self.assertTrue(any(b[0] <= x < b[2] and b[1] <= y < b[3] for b in boxes), (x, y))
        xs = sorted({(b[0], b[2]) for b in boxes})
        self.assertGreaterEqual(xs[0][1] - xs[1][0], 400, "two tiles side by side share a label's width")
        many = vw.tile_boxes(9000, 2000, 2600, 400)
        self.assertEqual([b[0] for b in many], [0, 2200, 4400, 6400])
        self.assertEqual(many[-1][2], 9000)

    def test_a_line_is_its_words_joined_and_says_when_they_run_right_to_left(self):
        line = vw.line_of("Maya Torres", [("Maya", 10, 20, 40, 12), ("Torres", 60, 18, 70, 16)])
        self.assertEqual(line["box"], (10, 18, 120, 16))
        self.assertFalse(line["backwards"])
        line = vw.line_of("Maya Torres", [("Maya", 90, 20, 40, 12), ("Torres", 10, 18, 70, 16)])
        self.assertTrue(line["backwards"])
        self.assertFalse(vw.line_of("Maya", [("Maya", 90, 20, 40, 12)])["backwards"], "one word cannot say")
        self.assertIsNone(vw.line_of("Maya", []))
        self.assertIsNone(vw.line_of("  ", [("", 1, 1, 5, 5)]))
        self.assertIsNone(vw.line_of("Maya", [("Maya", 1, 1, 0, 0)]))

    def test_the_readers_word_for_the_turn_is_taken_to_the_nearest_quarter(self):
        for said, turn in ((None, 0), (0.0, 0), (3.7, 0), (-4.0, 0), (44.0, 0), (91.2, 90), (179.4, 180),
                           (-180.0, 180), (-90.0, 270), (268.0, 270), (358.0, 0), ("sideways", 0),
                           (float("nan"), 0), (float("inf"), 0)):
            self.assertEqual(vw.quarter(said), turn, said)

    def test_a_box_from_the_straightened_frame_is_put_back_where_it_is(self):
        self.assertEqual(vw.untilt((10, 20, 30, 8), None, 400, 300), (10, 20, 30, 8))
        self.assertEqual(vw.untilt((10, 20, 30, 8), 0.0, 400, 300), (10, 20, 30, 8))
        self.assertEqual(vw.untilt((10, 20, 30, 8), float("nan"), 400, 300), (10, 20, 30, 8))
        x, y, w, h = vw.untilt((10, 20, 30, 8), 180.0, 400, 300)
        self.assertEqual((round(x), round(y), w, h), vw.mirrored((10, 20, 30, 8), 400, 300))
        # a quarter turn clockwise about the centre: what was above the centre is to its right
        x, y, w, h = vw.untilt((190, 40, 20, 10), 90.0, 400, 300)
        self.assertEqual((round(x + w / 2), round(y + h / 2), w, h), (305, 150, 10, 20))
        # a tilt of a few degrees moves the box a little and keeps its size
        x, y, w, h = vw.untilt((350, 140, 40, 20), 4.0, 400, 300)
        self.assertEqual((w, h), (40, 20))
        self.assertAlmostEqual(x + w / 2, 200 + 170 * 0.99756, places=1)
        self.assertAlmostEqual(y + h / 2, 150 + 170 * 0.06976, places=1)

    def picture_with_a_label(self, at=(30, 20, 120, 30)):
        im = Image.new("L", (400, 300), 245)
        x, y, w, h = at
        for k in range(0, w, 8):
            im.paste(20, (x + k, y, x + k + 4, y + h))      # stripes: light and dark, as letters are
        return im

    def test_ink_is_where_the_letters_are(self):
        im = self.picture_with_a_label()
        self.assertGreater(vw.ink(im, (30, 20, 120, 30)), 50)
        self.assertLess(vw.ink(im, (250, 250, 120, 30)), vw.BLANK)
        self.assertEqual(vw.ink(im, (500, 500, 10, 10)), 0.0)
        self.assertEqual(vw.ink(im, (30, 20, 0, 0)), 0.0)

    def test_three_things_can_say_a_line_was_read_upside_down(self):
        im = self.picture_with_a_label()
        here, there = (30, 20, 120, 30), vw.mirrored((30, 20, 120, 30), 400, 300)
        line = {"text": "Maya Torres", "box": here, "backwards": False}

        def place(line, said, picture=im):
            box, turn = vw.place(line, said, picture)
            return tuple(round(v) for v in box), turn
        self.assertEqual(place(line, None), (here, 0))
        self.assertEqual(place(line, 0.0), (here, 0))
        # 1. the reader says so, and gives the box in the frame of the picture turned straight
        self.assertEqual(place({**line, "box": there}, 180.0), (here, 180))
        #    (and if it gave the box in the picture's own frame after all, the ink says which)
        self.assertEqual(place(line, 180.0), (here, 180))
        # 2. the words run right to left
        self.assertEqual(place({**line, "backwards": True}, None), (here, 180))
        # 3. the box is empty and the same box in the picture turned over is not
        self.assertEqual(place({**line, "box": there}, None), (here, 180))
        # an empty box with nothing opposite either says nothing
        self.assertEqual(place(line, None, Image.new("L", (400, 300), 245)), (here, 0))

    def test_the_same_words_in_the_same_place_are_kept_once(self):
        a = self.lines("Maya Torres", box=(100, 50, 220, 44))
        b = self.lines("Maya Torres", box=(102, 52, 216, 40))       # the same label, read at half size
        c = self.lines("Maya Torres", box=(900, 50, 220, 44))       # the same name on another paper
        d = self.lines("Maya Torrcs", box=(101, 51, 218, 42))       # read a little differently: the program chooses
        self.assertEqual(vw.merge(a + b + c + d), a + c + d)
        self.assertEqual(vw.merge([]), [])

    def test_a_turned_line_that_is_the_shadow_of_a_good_upright_line_is_dropped(self):
        good = self.lines("Maya Torres", box=(100, 50, 220, 44))
        shadow = self.lines("saj eW", angle=180, box=(100, 50, 220, 44))
        self.assertEqual(vw.merge(good + shadow), good)
        # never the other way round: an upright line stays, whatever is read over it
        name = self.lines("Jonah Reyes", angle=180, box=(100, 50, 220, 44))
        junk = self.lines("sa", box=(100, 50, 220, 44))
        self.assertEqual(vw.merge(junk + name), junk + name)
        # as many letters both ways: both stay, and the program chooses by the name
        twin = self.lines("yeuor", angle=180, box=(100, 50, 220, 44))
        real = self.lines("Jonah", box=(100, 50, 220, 44))
        self.assertEqual(vw.merge(real + twin), real + twin)
        # a turned line somewhere else is nobody's shadow
        away = self.lines("ab", angle=90, box=(700, 500, 40, 200))
        self.assertEqual(vw.merge(good + away), good + away)

    def test_boxes_map_back_to_the_original_frame(self):
        # a 40x20 image; a line at the top-left of the turned image
        for angle in (90, 180, 270):
            turned = Image.new("RGB", (40, 20)).rotate(angle, expand=True)
            tw, th = turned.size
            x, y, w, h = vw.box_back((0, 0, 8, 4), angle, 40, 20)
            self.assertTrue(0 <= x and 0 <= y and x + w <= 40 and y + h <= 20, (angle, x, y, w, h))
            self.assertEqual((w, h), (4, 8) if angle in (90, 270) else (8, 4))
            self.assertEqual((tw, th), (20, 40) if angle in (90, 270) else (40, 20))
        self.assertEqual(vw.box_back((0, 0, 8, 4), 0, 40, 20), (0, 0, 8, 4))
        # the top-left of an image turned 90 counter-clockwise was its top-right
        self.assertEqual(vw.box_back((0, 0, 8, 4), 90, 40, 20), (36, 0, 4, 8))


class PretendReader:
    """Stands where the Windows reader stands (vision_windows.recognize) and
    reads one thing: a drawn 'label', a dark bar whose left end is mid-tone. It
    reads the label as 'Maya Torres' only when the label is the right way up
    in the picture it is handed (wide, mid-tone end on the left), as a reader
    that reads upright text only would. It answers in the reader's own form,
    and remembers every picture it was handed."""

    def __init__(self):
        self.seen = []

    def __call__(self, path):
        with Image.open(path) as im:
            self.seen.append((path, im.size))
            tones = im.convert("L")
        dark = tones.point(lambda v: 255 if v < 70 else 0).getbbox()
        mid = tones.point(lambda v: 255 if 100 <= v <= 150 else 0).getbbox()
        if not dark or not mid:
            return [], None
        wide = max(dark[2], mid[2]) - min(dark[0], mid[0]) > 2 * (max(dark[3], mid[3]) - min(dark[1], mid[1]))
        if not wide or (mid[0] + mid[2]) / 2 > (dark[0] + dark[2]) / 2:
            return [], None
        words = [("Maya", mid[0], mid[1], mid[2] - mid[0], mid[3] - mid[1]),
                 ("Torres", dark[0], dark[1], dark[2] - dark[0], dark[3] - dark[1])]
        return [("Maya Torres", words)], None


class WindowsReadingTests(unittest.TestCase):
    """Everything vision_windows does around the reader, with a pretend
    reader in the reader's place: every way up, several sizes, tiles, the
    margin, the orientation tag, and where the scratch pictures go."""
    LABEL = (300, 120, 240, 40)      # x, y, w, h in the upright picture

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.real = (vw.recognize, vw.longest_side)
        self.reader = vw.recognize = PretendReader()
        vw.longest_side = lambda: vw.LIMIT       # the same arithmetic on every computer

    def tearDown(self):
        vw.recognize, vw.longest_side = self.real
        shutil.rmtree(self.tmp, ignore_errors=True)

    def picture(self, size=(1200, 800), label=None):
        x, y, w, h = label or self.LABEL
        im = Image.new("RGB", size, (236, 236, 232))
        im.paste((125, 125, 125), (x, y, x + w // 4, y + h))
        im.paste((20, 20, 30), (x + w // 4, y, x + w, y + h))
        return im

    def save(self, im, name="p.png", **kw):
        path = os.path.join(self.tmp, name)
        im.save(path, **kw)
        return path

    def assert_box(self, t, box, slack=6):
        for got, want in zip((t["x"], t["y"], t["w"], t["h"]), box):
            self.assertLessEqual(abs(got - want), slack, (t, box))

    def test_an_upright_label_is_read_once_where_it_is(self):
        got = vw.read_text(self.save(self.picture()))
        self.assertEqual([(t["text"], t["angle"], t["conf"]) for t in got], [("Maya Torres", 0, 1.0)])
        self.assert_box(got[0], self.LABEL)
        self.assertTrue(all(isinstance(got[0][k], int) for k in "xywh"))

    def test_a_picture_turned_any_way_gives_the_label_the_turn_that_rights_it(self):
        x, y, w, h = self.LABEL
        for turned in (90, 180, 270):
            with self.subTest(turned=turned):
                got = vw.read_text(self.save(self.picture().rotate(turned, expand=True)))
                self.assertEqual([(t["text"], t["angle"]) for t in got], [("Maya Torres", (360 - turned) % 360)])
                self.assert_box(got[0], {90: (y, 1200 - x - w, h, w), 180: (1200 - x - w, 800 - y - h, w, h),
                                         270: (800 - y - h, x, h, w)}[turned])

    def test_the_orientation_tag_sets_the_frame_as_it_does_on_a_mac(self):
        # pixels upright, tag 6 says 'turn me a quarter clockwise': a person, open_photo and
        # the Mac reader all see the picture on its side, 800 wide and 1200 high
        exif = Image.Exif()
        exif[0x0112] = 6
        got = vw.read_text(self.save(self.picture(), "tagged.jpg", quality=95, exif=exif))
        self.assertEqual([(t["text"], t["angle"]) for t in got], [("Maya Torres", 90)])
        x, y, w, h = self.LABEL
        self.assert_box(got[0], (800 - y - h, x, h, w))

    def test_every_way_up_at_every_size_and_one_way_only_when_asked(self):
        path = self.save(self.picture())
        vw.read_text(path)
        sizes = len(vw.scales_for(1200, 800))
        self.assertEqual(sizes, 4)
        self.assertEqual(len(self.reader.seen), 4 * sizes)
        self.assertEqual(sorted({n["turn"] for n in vw.LAST_READS}), [0, 90, 180, 270])
        self.assertEqual(sorted({n["scale"] for n in vw.LAST_READS}), [0.25, 0.5, 1.0, 2.0])
        del self.reader.seen[:]
        got = vw.read_text(path, as_it_is=True)
        self.assertEqual(len(self.reader.seen), sizes)
        self.assertEqual([(t["text"], t["angle"]) for t in got], [("Maya Torres", 0)])
        self.assertEqual({n["turn"] for n in vw.LAST_READS}, {0})
        # one way only, and the picture is upside down: this reader reads nothing, and says nothing
        self.assertEqual(vw.read_text(self.save(self.picture().rotate(180), "down.png"), as_it_is=True), [])
        # the word the program passes on
        self.assertEqual(vw.run("text", path, "corrected", vw.AS_IT_IS), got)
        self.assertEqual(sw.AS_IT_IS, vw.AS_IT_IS)
        self.assertEqual(len(vw.run("text", path)), 1)
        self.assertEqual(vw.run("rects", path), [])

    def test_a_margin_goes_around_every_picture_and_is_taken_off_the_boxes(self):
        label = (2, 3, 240, 40)                  # in the very corner
        got = vw.read_text(self.save(self.picture(label=label)), as_it_is=True)
        self.assertEqual(len(got), 1)
        self.assert_box(got[0], label)
        own = [size for _, size in self.reader.seen if size == (1200 + 2 * vw.BORDER, 800 + 2 * vw.BORDER)]
        self.assertEqual(len(own), 1)

    def test_a_picture_larger_than_the_reader_takes_is_read_in_tiles_never_shrunk_to_fit(self):
        label = (2500, 1700, 240, 40)            # on the seam between tiles
        path = self.save(self.picture(size=(4032, 3024), label=label), "wall.jpg", quality=90)
        got = vw.read_text(path, as_it_is=True)
        self.assertEqual([(t["text"], t["angle"]) for t in got], [("Maya Torres", 0)])
        self.assert_box(got[0], label)
        full = [n for n in vw.LAST_READS if n["scale"] == 1.0]
        self.assertEqual(len(full), 4)
        for _, (w, h) in self.reader.seen:
            self.assertLessEqual(max(w, h), vw.LIMIT)
        self.assertEqual(sorted({n["scale"] for n in vw.LAST_READS}), [0.25, 0.5, 1.0])

    def test_scratch_pictures_never_sit_beside_the_photo_and_are_gone_afterwards(self):
        inbox = os.path.join(self.tmp, "Wall Inbox")
        os.makedirs(inbox)
        path = os.path.join(inbox, "IMG_1234.jpg")
        self.picture().save(path, quality=90)
        vw.read_text(path)
        self.assertEqual(os.listdir(inbox), ["IMG_1234.jpg"])
        folders = {os.path.dirname(p) for p, _ in self.reader.seen}
        self.assertEqual(len(folders), 1)
        scratch = folders.pop()
        self.assertFalse(os.path.abspath(scratch).startswith(os.path.abspath(self.tmp)))
        self.assertFalse(os.path.exists(scratch))

    def test_a_reader_that_stops_leaves_nothing_behind(self):
        seen = []

        def stops(path):
            seen.append(path)
            raise RuntimeError("the reader stopped")
        vw.recognize = stops
        with self.assertRaises(RuntimeError):
            vw.read_text(self.save(self.picture()))
        self.assertEqual(len(seen), 1)
        self.assertFalse(os.path.exists(os.path.dirname(seen[0])))

    def test_a_reader_that_reads_upside_down_and_says_so_is_believed(self):
        """The Windows reader gives text_angle, and its boxes in the frame of
        the picture turned straight. Here the pretend reader reads the label
        upside down as well, and says 180."""
        plain = self.reader

        def says(path):
            lines, _ = plain(path)
            if lines:
                return lines, 0.0
            with Image.open(path) as im:
                over = os.path.join(os.path.dirname(path), "over.png")
                im.rotate(180).save(over)
            return plain(over)[0], 180.0          # boxes in the frame of the picture turned straight
        vw.recognize = says
        x, y, w, h = self.LABEL
        got = vw.read_text(self.save(self.picture().rotate(180)), as_it_is=True)
        self.assertEqual([(t["text"], t["angle"]) for t in got], [("Maya Torres", 180)])
        self.assert_box(got[0], (1200 - x - w, 800 - y - h, w, h))
        # every way up: the same label, the same turn, from two reads; reported once
        got = vw.read_text(self.save(self.picture().rotate(180)))
        self.assertEqual([(t["text"], t["angle"]) for t in got], [("Maya Torres", 180)])
        got = vw.read_text(self.save(self.picture()))
        self.assertEqual([(t["text"], t["angle"]) for t in got], [("Maya Torres", 0)])

    def test_a_reader_that_reads_upside_down_and_does_not_say_so_is_found_out(self):
        plain = self.reader

        def silent(own_frame):
            def read(path):
                lines, _ = plain(path)
                if lines:
                    return lines, None
                with Image.open(path) as im:
                    width, height = im.size
                    over = os.path.join(os.path.dirname(path), "over.png")
                    im.rotate(180).save(over)
                lines, _ = plain(over)
                if own_frame:       # boxes where the ink is: the first word is on the right
                    lines = [(t, [(wd, width - x - w, height - y - h, w, h) for wd, x, y, w, h in ws])
                             for t, ws in lines]
                return lines, None
            return read
        x, y, w, h = self.LABEL
        for own_frame in (True, False):
            with self.subTest(own_frame=own_frame):
                vw.recognize = silent(own_frame)
                got = vw.read_text(self.save(self.picture().rotate(180)), as_it_is=True)
                self.assertEqual([(t["text"], t["angle"]) for t in got], [("Maya Torres", 180)])
                self.assert_box(got[0], (1200 - x - w, 800 - y - h, w, h))
                got = vw.read_text(self.save(self.picture()))
                self.assertEqual([(t["text"], t["angle"]) for t in got], [("Maya Torres", 0)])

    def test_the_reader_is_asked_for_its_longest_side_and_2600_stands_in(self):
        asked = self.real[1]()
        self.assertGreater(asked, 0)
        if not sw.IS_WIN:
            self.assertEqual(asked, vw.LIMIT)               # no Windows reader on this computer
        self.assertEqual(vw.read_rects("anything"), [])
        self.assertEqual(vw.read_plain(self.save(self.picture())), self.reader(self.save(self.picture())))


@unittest.skipUnless(HAVE_VISION, "vision helper not built")
class UprightFilingTests(unittest.TestCase):
    """Real reader, fake wall. Each filed crop must read upright: the child's
    label a wide box with angle 0, and in the right child's folder."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inbox = os.path.join(self.tmp, "inbox")
        os.makedirs(self.inbox)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wall(self, **kw):
        # typed white labels on coloured paper, as a teacher does it
        return make_wall(NAMES, rows=2, cols=2, size=(2000, 1600), colored=True, seed=5, **kw)

    def read_label(self, crop_path, name):
        """The label line for this child on a filed crop, or None."""
        texts = sw.run_vision("text", crop_path)
        hits = sw.label_hits(texts, [name])     # fuzzy, as the tool itself matches ("Elyjah" is Elijah)
        return hits[0] if hits else None

    def check_upright(self, results, expect_turned=None):
        filed = [r for r in results if r["status"] == "confident"]
        self.assertEqual(len(results), len(NAMES), results)
        self.assertGreaterEqual(len(filed), len(NAMES) - 1, [(r["name"], r["status"], r["text"]) for r in results])
        for r in filed:
            self.assertTrue(os.path.exists(r["file"]) or os.path.exists(os.path.join(self.tmp, r["file"])), r["file"])
            path = r["file"] if os.path.isabs(r["file"]) else os.path.join(self.tmp, r["file"])
            self.assertIn(os.sep + r["name"] + os.sep, path, "filed in the wrong child's folder")
            lab = self.read_label(path, r["name"])
            self.assertIsNotNone(lab, f"{r['name']}: label not read on the filed crop")
            self.assertEqual(lab["angle"], 0, f"{r['name']}: label does not read upright ({lab})")
            self.assertGreater(lab["w"], lab["h"] * 1.5, f"{r['name']}: label box is not wide ({lab})")
            if expect_turned is not None:
                self.assertEqual(r["turned"], expect_turned, f"{r['name']}: turned {r['turned']}")
        # every child's folder holds exactly one piece, never a stranger's
        for name in NAMES:
            d = os.path.join(self.tmp, "sorted", name, "Art")
            files = [f for f in os.listdir(d) if f.endswith(".jpg")] if os.path.isdir(d) else []
            self.assertLessEqual(len(files), 1, (name, files))

    def run_photo(self, filename):
        logged = []
        res = sw.process_photo(os.path.join(self.inbox, filename), NAMES, self.tmp, "Art", log=logged.append)
        return res, logged

    def test_upright_wall_is_left_alone(self):
        img, _ = self.wall()
        img.save(os.path.join(self.inbox, "wall.jpg"), quality=90)
        res, logged = self.run_photo("wall.jpg")
        self.check_upright(res, expect_turned=0)
        self.assertFalse(any("turned it upright" in ln for ln in logged))

    def test_wall_turned_90_180_270_as_raw_pixels_files_upright(self):
        img, _ = self.wall()
        for angle in (90, 180, 270):
            with self.subTest(angle=angle):
                shutil.rmtree(os.path.join(self.tmp, "sorted"), ignore_errors=True)
                fn = f"wall{angle}.jpg"
                img.rotate(angle, expand=True).save(os.path.join(self.inbox, fn), quality=90)
                res, logged = self.run_photo(fn)
                self.assertTrue(any("turned it upright using the name labels" in ln for ln in logged), logged)
                self.check_upright(res, expect_turned=(360 - angle) % 360)

    def test_wrong_orientation_tag_is_overruled_by_the_labels(self):
        """Pixels upright, tag says 'turn me': exactly today's bug, the other
        way round. The tag must lose to the labels."""
        img, _ = self.wall()
        for tag, angle in ((6, 270), (8, 90), (3, 180)):
            with self.subTest(tag=tag):
                shutil.rmtree(os.path.join(self.tmp, "sorted"), ignore_errors=True)
                fn = f"tagged{tag}.jpg"
                exif = Image.Exif()
                exif[0x0112] = tag
                img.save(os.path.join(self.inbox, fn), quality=90, exif=exif)
                # sanity: the tag alone would put this photo on its side (or on its head)
                seen = ImageOps.exif_transpose(Image.open(os.path.join(self.inbox, fn)))
                self.assertEqual(seen.size, img.rotate(angle, expand=True).size)
                res, logged = self.run_photo(fn)
                self.assertTrue(any("turned it upright" in ln for ln in logged), logged)
                self.check_upright(res)

    def test_one_paper_hung_sideways_comes_out_upright(self):
        img, truth = self.wall(tilt=False)
        x0, y0, x1, y1 = truth[1]["box"]
        paper = img.crop((x0, y0, x1, y1)).rotate(90, expand=True)
        wall_color = img.getpixel((5, 5))
        img.paste(Image.new("RGB", (x1 - x0 + 14, y1 - y0 + 16), wall_color), (x0, y0))  # covers the shadow too
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        img.paste(paper, (cx - paper.width // 2, cy - paper.height // 2))
        img.save(os.path.join(self.inbox, "one.jpg"), quality=90)
        res, logged = self.run_photo("one.jpg")
        self.assertFalse(any("photo was on its side" in ln for ln in logged), logged)
        self.check_upright(res)
        side = [r for r in res if r["name"] == truth[1]["name"]]
        self.assertEqual(len(side), 1, res)
        self.assertEqual(side[0]["turned"], 270, side[0])
        others = [r for r in res if r["name"] != truth[1]["name"] and r["status"] == "confident"]
        self.assertTrue(all(r["turned"] == 0 for r in others), others)

    def test_unsure_pieces_get_the_same_turn(self):
        """A GUESS file and its name strip are turned by the same rule as a
        filed piece, so a person sees it upright too."""
        img, _ = make_wall(NAMES, rows=2, cols=2, size=(2000, 1600), colored=True, seed=5, blurred=(3,))
        img.rotate(90, expand=True).save(os.path.join(self.inbox, "blur.jpg"), quality=90)
        res, _ = self.run_photo("blur.jpg")
        self.assertEqual(len(res), 4)
        self.assertTrue(all(r["turned"] == 270 for r in res), [(r["name"], r["turned"]) for r in res])
        for r in res:
            path = r["file"] if os.path.isabs(r["file"]) else os.path.join(self.tmp, r["file"])
            with Image.open(path) as im:
                self.assertGreater(im.width, im.height, f"piece {r['piece']} is on its side")
        strips = os.path.join(self.tmp, "unsorted", "name-strips")
        if os.path.isdir(strips):
            for f in os.listdir(strips):
                with Image.open(os.path.join(strips, f)) as im:
                    self.assertGreater(im.width, im.height, f"strip {f} is on its side")


class OneLookWordTests(unittest.TestCase):
    """The program asks for one look at a paper (AS_IT_IS). A Windows PC
    reads the picture one way up instead of four; a Mac, whose reader sees
    every way up in one look, is handed exactly what it was handed before."""

    def setUp(self):
        self.saved = (sw.IS_WIN, sw.IS_MAC, sw.VISION, sw.subprocess.run, vw.available, vw.recognize)
        self.tmp = tempfile.mkdtemp()
        self.png = os.path.join(self.tmp, "paper.png")
        Image.new("RGB", (300, 200), "white").save(self.png)

    def tearDown(self):
        sw.IS_WIN, sw.IS_MAC, sw.VISION, sw.subprocess.run, vw.available, vw.recognize = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_on_a_mac_the_word_is_taken_out_before_the_helper_is_called(self):
        handed = []

        class Done:
            returncode, stdout, stderr = 0, '[{"text": "Maya Torres", "angle": 0}]', ""

        def run(args, **kw):
            handed.append(args)
            return Done()
        sw.IS_WIN, sw.IS_MAC, sw.VISION, sw.subprocess.run = False, True, self.png, run
        self.assertEqual(sw.run_vision("text", self.png, sw.AS_IT_IS)[0]["text"], "Maya Torres")
        sw.run_vision("text", self.png, "corrected", sw.AS_IT_IS)
        sw.run_vision("text", self.png)
        self.assertEqual(handed, [[self.png, "text", self.png], [self.png, "text", self.png, "corrected"],
                                  [self.png, "text", self.png]])

    def test_on_windows_the_word_means_one_way_up_and_without_it_every_way(self):
        looks = []

        def reader(path):
            looks.append(path)
            return [], None
        sw.IS_WIN, sw.IS_MAC, vw.available, vw.recognize = True, False, (lambda: True), reader
        sizes = len(vw.scales_for(300, 200, vw.longest_side() - vw.SHY_OF_LIMIT - 2 * vw.BORDER))
        self.assertEqual(sw.run_vision("text", self.png, sw.AS_IT_IS), [])
        self.assertEqual(len(looks), sizes)
        self.assertEqual(sw.run_vision("text", self.png), [])
        self.assertEqual(len(looks), sizes + 4 * sizes)
        self.assertEqual(sw.run_vision("rects", self.png), [])
        with self.assertRaises(RuntimeError):
            sw.run_vision("text", os.path.join(self.tmp, "not-there.png"))

    def test_a_paper_and_the_wall_around_it_are_read_with_one_look_and_a_whole_photo_every_way(self):
        asked = []

        def reader(mode, path, *extra):
            asked.append((os.path.basename(path), extra))
            return []
        real, sw.run_vision = sw.run_vision, reader
        try:
            crop = Image.new("RGB", (300, 200), "white")
            sw.read_piece(self.png, crop)
            q = {"tl": [10, 10], "tr": [200, 10], "br": [200, 150], "bl": [10, 150]}
            sw.read_neighborhood(crop, q, [], self.tmp, 1)
            sw.read_photo_text(crop, self.png, self.tmp)
        finally:
            sw.run_vision = real
        self.assertEqual(asked, [("paper.png", (sw.AS_IT_IS,)), ("paper.png.up.png", ("corrected", sw.AS_IT_IS)),
                                 ("near-1.png", (sw.AS_IT_IS,)), ("paper.png", ())])


class SecondLookTests(unittest.TestCase):
    """A reader that looks one way up at a time may read a one-word name
    upside down and call it upright. The paper is looked at turned over as
    well; these are the answers that look can give, with no reader."""

    def turned_over(self, text="Theo", angle=0, on_the_paper=True, status="confident", name="Theo"):
        line = T(text, angle, **({"rel_y": 0.1} if on_the_paper else {}))
        return lambda: ([line], {"status": status, "name": name, "text": text, "score": 1.0})

    def test_only_the_same_name_read_for_certain_and_called_upright_leaves_the_way_up_unknown(self):
        self.assertTrue(sw.second_look("Theo", self.turned_over()))

    def test_every_other_answer_leaves_the_first_look_standing(self):
        self.assertFalse(sw.second_look("Theo", self.turned_over(angle=180)), "the reader says it is upside down")
        self.assertFalse(sw.second_look("Theo", self.turned_over(angle=90)), "the reader says it is on its side")
        self.assertFalse(sw.second_look("Theo", self.turned_over(status="unsure")), "not read for certain")
        self.assertFalse(sw.second_look("Theo", self.turned_over("Wren", name="Wren")), "another child's name")
        self.assertFalse(sw.second_look("Theo", self.turned_over(on_the_paper=False)), "read beside the paper")
        nothing = lambda: ([], {"status": "no text read", "name": None, "text": None, "score": 0.0})  # noqa: E731
        self.assertFalse(sw.second_look("Theo", nothing))

    def test_only_a_reader_that_looks_one_way_at_a_time_is_asked_twice(self):
        self.assertEqual(sw.ONE_LOOK, sw.IS_WIN)

    def test_the_log_says_which_pieces_and_what_to_do_in_plain_words(self):
        said = []
        filed = {"status": "confident", "name": "Theo"}
        self.assertIsNone(sw.tell_way_up("wall.jpg", [{**filed, "piece": 1}], said.append))
        self.assertEqual(said, [])
        one = sw.tell_way_up("wall.jpg", [{**filed, "piece": 1},
                                          {**filed, "piece": 2, "way_up": sw.EITHER_WAY_UP}], said.append)
        self.assertEqual(said, [one])
        self.assertTrue(one.startswith("wall.jpg: the name was read on piece 2, and it is in the child's folder."))
        self.assertIn("which way up that paper hangs", one)
        self.assertIn("open the picture and turn it round", one)
        many = sw.tell_way_up("wall.jpg", [{**filed, "piece": n, "way_up": sw.EITHER_WAY_UP} for n in (2, 5, 6)],
                              said.append)
        self.assertIn("on pieces 2, 5 and 6, and each is in its child's folder", many)
        self.assertIn("which way up those papers hang", many)
        self.assertEqual(len(said), 2)
        for line in said:
            self.assertNotIn("Theo", line, "the log line names pieces by number")
            for word in ("OCR", "angle", "confident", "one-look", "ONE_LOOK", "AS_IT_IS", "either"):
                self.assertNotIn(word, line)


class CheckSetupReadsOneWordBackTests(unittest.TestCase):
    """Check Setup draws 'Baggage 42' and prints what the reader read back.
    It is read with one look, and the line printed is the line that holds
    the word, whatever else the reader made of the picture."""

    def setUp(self):
        self.saved = (sw.run_vision, sw.backend_ready)
        self.tmp = tempfile.mkdtemp()
        self.asked = []
        sw.backend_ready = lambda: True

    def tearDown(self):
        sw.run_vision, sw.backend_ready = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self, *read):
        def reader(mode, path, *extra):
            self.asked.append((mode, os.path.basename(path), extra))
            return [T(text) for text in read]
        sw.run_vision = reader
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            sw.self_check(os.path.join(self.tmp, "no-settings-here.json"))
        return [ln for ln in out.getvalue().splitlines() if "reader re" in ln]

    def test_the_word_is_read_with_one_look_and_printed_clean(self):
        self.assertEqual(self.check("Baggage 42"), ["  ok: reader read back 'Baggage 42'"])
        self.assertEqual(self.asked, [("text", "selfcheck.png", (sw.AS_IT_IS,))])

    def test_what_else_the_reader_made_of_the_picture_is_not_printed_with_it(self):
        # what a Windows PC handed back when the word was read every way up
        self.assertEqual(self.check("24 EGAGGAb", " Baggage 42 ", "Baggage 4 2"),
                         ["  ok: reader read back 'Baggage 42'"])

    def test_a_reader_that_did_not_read_the_word_still_fails_and_shows_all_it_read(self):
        self.assertEqual(self.check("EGAGGAb", "24"), ["  FAIL: reader returned 'EGAGGAb 24' for 'Baggage 42'"])
        self.assertEqual(self.check(), ["  FAIL: reader returned '' for 'Baggage 42'"])


class WhatIsWrittenDownIsWhatTheProgramDoesTests(unittest.TestCase):
    """The read-me said the practice walls were in a handwriting-style font
    after they had been typed, and the notes described, as how Windows
    decides which way is up, a rule that had been taken out."""

    def written(self, name):
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            return " ".join(f.read().split())

    def test_the_read_me_says_the_practice_walls_are_typed_and_they_are(self):
        import make_wall as mw
        said = self.written("README.md")
        self.assertIn("names typed in Arial, as the rule a teacher is given asks", said)
        self.assertNotIn("names in a handwriting-style font", said)
        self.assertIn("`make_wall(hand=True)` still draws them that way", said)
        self.assertIn("arial", os.path.basename(mw.FONT).lower())
        self.assertNotEqual(mw.HAND_FONT, None)
        self.assertIn("hand", mw.make_wall.__code__.co_varnames)

    def test_the_notes_describe_the_windows_reading_there_is(self):
        said = self.written("ENGINEERING-NOTES.md")
        # the rule that was taken out is told as what it was, and is not in the helper
        self.assertNotIn("so there the helper reads the picture as it is and, if that found hardly any letters", said)
        self.assertIn("That is gone.", said)
        for gone in ("needs_retry", "pick_rotation", "with_angle", "RETRY_TURNS", "WEAK_LETTERS"):
            self.assertFalse(hasattr(vw, gone), gone)
            self.assertNotIn(gone, said)
        # what the notes name is there
        self.assertIn("It reads every picture four ways up, always", said)
        self.assertEqual(sorted(vw.TURNS), [0, 90, 180, 270])
        for named in ("`place`", "`text_angle`", "`AS_IT_IS`", "`second_look`", "`tests/reader_probe.py`",
                      "`reader-probe-on-build-machine.txt`"):
            self.assertIn(named, said)
        self.assertTrue(callable(vw.place) and callable(vw.quarter) and callable(sw.second_look))
        self.assertEqual(vw.AS_IT_IS, sw.AS_IT_IS)
        self.assertTrue(os.path.isfile(os.path.join(HERE, "reader_probe.py")))


def apple_reader(mode, path, *extra):
    """Apple's reader and nothing else, whatever computer the program has
    been told it is on."""
    res = subprocess.run([sw.VISION, mode, path], capture_output=True, text=True)
    lines = [ln for ln in res.stdout.splitlines() if ln.startswith("[")]
    return json.loads(lines[-1] if lines else "[]")


class AppleReaderAsWindows:
    """Apple's reader, made to answer the way the Windows reader does, put
    where the Windows reader stands (vision_windows.recognize). Nobody here
    can run Windows; this runs the whole Windows reading path, on real
    practice walls, on a Mac. What it cannot show is how well the Windows
    reader itself reads: the reader probe on the build machine shows that.

    upside_down says what this reader does with text that is upside down in
    the picture it is handed (text on its side is never read: the build of
    September 28, 2026 read hardly a letter of a wall on its side):
      "nonsense"  reads it as nonsense with as many letters, and says nothing
      "says"      reads it, says text_angle 180, boxes in the straightened frame
      "silent"    reads it, says nothing, boxes where the ink is
    """

    def __init__(self, apple, upside_down="nonsense"):
        self.apple, self.upside_down, self.reads = apple, upside_down, 0

    @staticmethod
    def words(t, right_to_left=False):
        words = t["text"].split()
        room = sum(len(w) for w in words) + len(words) - 1
        unit = t["w"] / max(1, room)
        out, at = [], 0
        for w in words:
            x = t["x"] + t["w"] - (at + len(w)) * unit if right_to_left else t["x"] + at * unit
            out.append((w, x, t["y"], len(w) * unit, t["h"]))
            at += len(w) + 1
        return out

    def __call__(self, path):
        self.reads += 1
        with Image.open(path) as im:
            width, height = im.size
        seen = [t for t in self.apple("text", path) if t["text"].strip()]
        up = [t for t in seen if t.get("angle", 0) == 0]
        down = [t for t in seen if t.get("angle", 0) == 180]
        if self.upside_down == "nonsense":
            lines = [(t["text"], self.words(t)) for t in up]
            lines += [(t["text"][::-1].swapcase(), self.words({**t, "text": t["text"][::-1]})) for t in down]
            return lines, None
        if self.upside_down == "says" and len(down) > len(up):
            return [(t["text"], self.words({**t, "x": width - t["x"] - t["w"], "y": height - t["y"] - t["h"]}))
                    for t in down], 180.0
        if self.upside_down == "says":
            return [(t["text"], self.words(t)) for t in up], 0.0
        return ([(t["text"], self.words(t)) for t in up]
                + [(t["text"], self.words(t, right_to_left=True)) for t in down]), None


@unittest.skipUnless(sw.IS_MAC and HAVE_VISION, "needs Apple's reader to stand in for the Windows reader")
class UprightFilingTheWindowsWayTests(UprightFilingTests):
    """Every wall of UprightFilingTests again, read the way a Windows PC
    reads it: through vision_windows, with no paper-outline detector, the
    reader reading upright text only and making nonsense of the rest. Each
    picture is read at its own size only, to keep the run short; the sizes
    have a test of their own below."""
    UPSIDE_DOWN = "nonsense"
    SMALLER, LARGER = (), 1000.0

    def setUp(self):
        super().setUp()
        self.saved = (sw.run_vision, vw.recognize, vw.SMALLER, vw.LARGER, sw.ONE_LOOK)
        self.reader = AppleReaderAsWindows(apple_reader, self.UPSIDE_DOWN)
        vw.recognize, vw.SMALLER, vw.LARGER = self.reader, self.SMALLER, self.LARGER
        sw.run_vision = vw.run
        sw.ONE_LOOK = True          # as on a Windows PC: a name read on a paper is looked at turned over too

    def tearDown(self):
        sw.run_vision, vw.recognize, vw.SMALLER, vw.LARGER, sw.ONE_LOOK = self.saved
        super().tearDown()


@unittest.skipUnless(sw.IS_MAC and HAVE_VISION, "needs Apple's reader to stand in for the Windows reader")
class AReaderThatReadsUpsideDownTests(UprightFilingTheWindowsWayTests):
    """The Windows reader may read upside-down text as well as upright (the
    build of September 28, 2026 points that way and does not settle it).
    Whether it says so or not, a wall photographed upside down or on its
    side must come out upright."""
    UPSIDE_DOWN = "says"
    # these three are run once, by the class above (None takes a test out of a class)
    test_one_paper_hung_sideways_comes_out_upright = None
    test_unsure_pieces_get_the_same_turn = None
    test_wrong_orientation_tag_is_overruled_by_the_labels = None

    def test_a_reader_that_does_not_say_so(self):
        self.reader.upside_down = "silent"
        self.test_wall_turned_90_180_270_as_raw_pixels_files_upright()


ONE_WORD = ["Maya", "Jonah", "Sofia", "Elijah"]


@unittest.skipUnless(sw.IS_MAC and HAVE_VISION, "needs Apple's reader to stand in for the Windows reader")
class OneWordNameTheWindowsWayTests(unittest.TestCase):
    """A name of one word, on a computer whose reader looks one way up at a
    time. Two words read upside down run right to left and give themselves
    away; one word cannot. Before, a paper whose one-word name read for
    certain on the first look was filed as it was, with nothing checked: a
    paper hung upside down was filed upside down and nothing said so. Now
    the paper is looked at turned over as well. The three readers the
    Windows reader may turn out to be are each tried here."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inbox = os.path.join(self.tmp, "inbox")
        os.makedirs(self.inbox)
        self.saved = (sw.run_vision, vw.recognize, vw.SMALLER, vw.LARGER, sw.ONE_LOOK)
        vw.SMALLER, vw.LARGER = (), 1000.0           # each picture at its own size only, to keep the run short
        sw.run_vision, sw.ONE_LOOK = vw.run, True

    def tearDown(self):
        sw.run_vision, vw.recognize, vw.SMALLER, vw.LARGER, sw.ONE_LOOK = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sort_wall(self, reader, upside_down=None):
        """The wall, with one paper hung upside down if asked, sorted with
        the reader asked for. Returns (results by child, log lines)."""
        vw.recognize = AppleReaderAsWindows(apple_reader, reader)
        img, truth = make_wall(ONE_WORD, rows=2, cols=2, size=(2000, 1600), colored=True, seed=5, tilt=False)
        if upside_down is not None:
            box = truth[upside_down]["box"]
            img.paste(img.crop(box).rotate(180), box[:2])
        img.save(os.path.join(self.inbox, "wall.jpg"), quality=90)
        logged = []
        res = sw.process_photo(os.path.join(self.inbox, "wall.jpg"), ONE_WORD, self.tmp, "Art", log=logged.append)
        self.assertEqual(sorted(r["name"] for r in res if r["status"] == "confident"), sorted(ONE_WORD),
                         [(r["name"], r["status"], r["text"]) for r in res])
        return {r["name"]: r for r in res}, logged

    def way_up(self, r):
        """Which way the name faces on the filed picture, by Apple's own reader: 0 is upright."""
        path = r["file"] if os.path.isabs(r["file"]) else os.path.join(self.tmp, r["file"])
        self.assertIn(os.sep + r["name"] + os.sep, path, "filed in the wrong child's folder")
        hits = sw.label_hits(apple_reader("text", path), [r["name"]])
        self.assertTrue(hits, f"{r['name']}: label not read on the filed picture")
        return hits[0]["angle"]

    def about_way_up(self, logged):
        return [ln for ln in logged if "which way up" in ln]

    def test_a_reader_that_reads_upright_text_only_turns_the_paper_and_has_no_doubt(self):
        by_child, logged = self.sort_wall("nonsense", upside_down=1)
        self.assertEqual({n: (r["turned"], self.way_up(r)) for n, r in by_child.items()},
                         {n: (180 if n == ONE_WORD[1] else 0, 0) for n in ONE_WORD})
        self.assertFalse([r for r in by_child.values() if "way_up" in r])
        self.assertEqual(self.about_way_up(logged), [])

    def test_a_reader_that_says_upside_down_turns_the_paper_and_has_no_doubt(self):
        by_child, logged = self.sort_wall("says", upside_down=1)
        self.assertEqual({n: (r["turned"], self.way_up(r)) for n, r in by_child.items()},
                         {n: (180 if n == ONE_WORD[1] else 0, 0) for n in ONE_WORD})
        self.assertFalse([r for r in by_child.values() if "way_up" in r])
        self.assertEqual(self.about_way_up(logged), [])

    def test_a_reader_that_reads_both_ways_and_does_not_say_which_is_never_believed_in_silence(self):
        # every paper the right way up: all filed the right way up, and the log says what was not checked
        by_child, logged = self.sort_wall("silent")
        self.assertEqual({n: (r["turned"], self.way_up(r)) for n, r in by_child.items()},
                         {n: (0, 0) for n in ONE_WORD})
        self.assertEqual({r.get("way_up") for r in by_child.values()}, {sw.EITHER_WAY_UP})
        self.assertEqual(len(self.about_way_up(logged)), 1, logged)
        self.assertIn("on pieces 1, 2, 3 and 4", self.about_way_up(logged)[0])
        # one paper hung upside down: nothing this reader gives can tell it from the others. It is
        # in the right child's folder, and the log has told the teacher it may be upside down there.
        shutil.rmtree(os.path.join(self.tmp, "sorted"), ignore_errors=True)
        by_child, logged = self.sort_wall("silent", upside_down=1)
        self.assertEqual(by_child[ONE_WORD[1]].get("way_up"), sw.EITHER_WAY_UP)
        self.assertEqual(len(self.about_way_up(logged)), 1, logged)
        self.assertIn("on pieces 1, 2, 3 and 4", self.about_way_up(logged)[0])
        self.assertEqual([self.way_up(by_child[n]) for n in ONE_WORD if n != ONE_WORD[1]], [0, 0, 0])

    def test_a_name_of_two_words_gives_itself_away_and_is_turned_whatever_the_reader_says(self):
        vw.recognize = AppleReaderAsWindows(apple_reader, "silent")
        img, truth = make_wall(NAMES, rows=2, cols=2, size=(2000, 1600), colored=True, seed=5, tilt=False)
        box = truth[1]["box"]
        img.paste(img.crop(box).rotate(180), box[:2])
        img.save(os.path.join(self.inbox, "two.jpg"), quality=90)
        logged = []
        res = sw.process_photo(os.path.join(self.inbox, "two.jpg"), NAMES, self.tmp, "Art", log=logged.append)
        self.assertEqual([(r["name"], r["status"], r["turned"], self.way_up(r)) for r in res],
                         [(t["name"], "confident", 180 if k == 1 else 0, 0) for k, t in enumerate(truth)])
        self.assertFalse([r for r in res if "way_up" in r])
        self.assertEqual(self.about_way_up(logged), [])


@unittest.skipUnless(sw.IS_MAC and HAVE_VISION, "needs Apple's reader to stand in for the Windows reader")
class EverySizeTheWindowsWayTests(UprightFilingTheWindowsWayTests):
    """One wall on its side, every picture read at every size."""
    SMALLER, LARGER = vw.SMALLER, vw.LARGER
    # the other walls are run at one size, by the class above (None takes a test out of a class)
    test_one_paper_hung_sideways_comes_out_upright = None
    test_unsure_pieces_get_the_same_turn = None
    test_wrong_orientation_tag_is_overruled_by_the_labels = None
    test_upright_wall_is_left_alone = None

    def test_wall_turned_90_180_270_as_raw_pixels_files_upright(self):
        img, _ = self.wall()
        img.rotate(90, expand=True).save(os.path.join(self.inbox, "wall90.jpg"), quality=90)
        res, logged = self.run_photo("wall90.jpg")
        self.assertTrue(any("turned it upright using the name labels" in ln for ln in logged), logged)
        self.check_upright(res, expect_turned=270)


@unittest.skipUnless(sw.IS_MAC and HAVE_VISION, "the build runs the whole probe on a Windows PC; this is its dry run")
class ReaderProbeTests(unittest.TestCase):
    """tests/reader_probe.py is the only evidence the next Windows build
    leaves about its reader, and it cannot be tried on Windows first. So it
    is run here, cut short: once as it runs on a Mac, and once the way it
    runs on a Windows PC, with Apple's reader standing where the Windows
    reader stands. It must print every kind of line and never stop."""

    def setUp(self):
        import reader_probe
        self.probe = reader_probe
        self.saved = (reader_probe.FACES, reader_probe.HEIGHTS, reader_probe.TURNS, reader_probe.ALONE_NAMES,
                      sw.IS_WIN, sw.IS_MAC, vw.recognize, vw.available)
        reader_probe.FACES, reader_probe.HEIGHTS = reader_probe.FACES[:1], [40, 80]
        reader_probe.TURNS, reader_probe.ALONE_NAMES = [0, 180], ["Maya Torres"]

    def tearDown(self):
        (self.probe.FACES, self.probe.HEIGHTS, self.probe.TURNS, self.probe.ALONE_NAMES,
         sw.IS_WIN, sw.IS_MAC, vw.recognize, vw.available) = self.saved

    def run_probe(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.probe.main(), 0)
        return out.getvalue().splitlines()

    def test_on_a_mac_it_prints_one_line_for_each_label(self):
        lines = self.run_probe()
        self.assertFalse([ln for ln in lines if "stopped" in ln], lines)
        alone = [ln for ln in lines if ln.startswith("alone ") and "asked" in ln]
        self.assertEqual(len(alone), 4, lines)             # two heights, two turns
        for ln in alone:
            for word in ("asked 'Maya Torres'", "read 'Maya Torres'", "box (", "angle ", "s  ok"):
                self.assertIn(word, ln)
        self.assertEqual(len([ln for ln in lines if ln.startswith("wall ") and "asked" in ln]), 4, lines)
        self.assertEqual(len([ln for ln in lines if ln.startswith("tilted ") and "asked" in ln]), 4, lines)
        self.assertEqual(len([ln for ln in lines if ln.startswith("row ") and "asked" in ln]), 8, lines)
        # a one-word name on a paper hung upside down, sorted by the program: Apple's reader says which way up
        pieces = [ln for ln in lines if ln.startswith("paper ") and "filed as" in ln]
        self.assertEqual(len(pieces), 8, lines)
        self.assertTrue(all(ln.endswith(" ok") for ln in pieces), pieces)
        self.assertEqual(len([ln for ln in pieces if "turned 180  right turn 180" in ln]), 1, pieces)
        self.assertTrue(any(ln.startswith("           log:   piece 2: confident") for ln in lines), lines)
        self.assertEqual(len([ln for ln in lines if "4 pieces, 4 filed, every child once" in ln]), 2, lines)
        self.assertEqual(len([ln for ln in lines if ln.startswith("beside ") and "one look read" in ln]), 4, lines)
        self.assertTrue(any(ln.startswith("reader probe done") for ln in lines))

    def test_a_reader_that_cannot_say_which_way_up_is_written_down_as_that(self):
        sw.IS_WIN, sw.IS_MAC, vw.available = True, False, lambda: True
        vw.recognize = AppleReaderAsWindows(apple_reader, "silent")
        self.probe.FACES = []                   # the papers only: they need no typed face of the probe's own
        saved, sw.ONE_LOOK = sw.ONE_LOOK, True
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                work = tempfile.mkdtemp()
                try:
                    self.probe.paper(work)
                finally:
                    shutil.rmtree(work, ignore_errors=True)
        finally:
            sw.ONE_LOOK = saved
        lines = out.getvalue().splitlines()
        self.assertFalse([ln for ln in lines if "stopped" in ln], lines)
        pieces = [ln for ln in lines if ln.startswith("paper ") and "filed as" in ln]
        self.assertEqual(len(pieces), 8, lines)
        self.assertTrue(all(ln.endswith("(the program said it could not tell which way up)") for ln in pieces), pieces)
        self.assertTrue(all("  ok  (" in ln for ln in pieces[:4]), "papers the right way up are filed that way")
        self.assertEqual(len([ln for ln in lines if "log:" in ln and "which way up" in ln]), 2, lines)
        self.assertEqual(len([ln for ln in lines if "4 pieces, 4 filed, every child once" in ln]), 2, lines)

    def test_the_build_runs_the_probe_on_both_machines_and_keeps_what_it_prints(self):
        with open(os.path.join(ROOT, ".github", "workflows", "build-windows.yml"), encoding="utf-8") as f:
            windows, mac = f.read().split("\n  build-mac:\n", 1)
        for job, kept in ((windows, "Move-Item reader-probe-on-build-machine.txt dist\\"),
                          (mac, "mv reader-probe-on-build-machine.txt dist/")):
            self.assertEqual(job.count("python tests/reader_probe.py 2>&1"), 1)
            self.assertIn(kept, job)
            step = job.split("- name: Reader probe on the build machine (informational)\n", 1)[1]
            self.assertTrue(step.lstrip().startswith("continue-on-error: true"), "the probe never stops a build")
            # before the programs are built, and before the bundle is put together
            self.assertLess(job.index("python tests/reader_probe.py"), job.index("run: pyinstaller"))
            self.assertLess(job.index("python tests/reader_probe.py"), job.index(kept))
        self.assertTrue(os.path.isfile(os.path.join(HERE, "reader_probe.py")))

    def test_the_way_it_runs_on_a_windows_pc(self):
        sw.IS_WIN, sw.IS_MAC, vw.available = True, False, lambda: True
        vw.recognize = AppleReaderAsWindows(apple_reader, "says")
        lines = self.run_probe()
        self.assertFalse([ln for ln in lines if "stopped" in ln], lines)
        alone = [ln for ln in lines if ln.startswith("alone ") and "asked" in ln]
        self.assertEqual(len(alone), 4, lines)
        self.assertTrue(all(ln.endswith(" ok") for ln in alone), alone)
        self.assertTrue(any("longest side the reader takes" in ln for ln in lines))
        self.assertTrue(any("NAME turned" in ln and "reader said turn 180.0" in ln for ln in lines), lines)
        self.assertTrue(any("plain look: read 'Maya Torres'" in ln and "words 'Maya'@(" in ln for ln in lines), lines)
        self.assertTrue(any("tile " in ln and "reader said turn" in ln for ln in lines), lines)

    def test_a_computer_with_no_reader_says_so_and_stops_there(self):
        sw.IS_WIN, sw.IS_MAC = False, False
        lines = self.run_probe()
        self.assertEqual(lines[1:], ["no reader on this computer, so there is nothing to record"])

    def test_a_case_that_goes_wrong_is_written_down_and_the_next_one_runs(self):
        real = sw.run_vision
        calls = []

        def breaks_once(mode, path, *extra):
            calls.append(path)
            if len(calls) == 1:
                raise RuntimeError("the reader stopped")
            return real(mode, path, *extra)
        sw.run_vision = breaks_once
        try:
            lines = self.run_probe()
        finally:
            sw.run_vision = real
        self.assertEqual(len([ln for ln in lines if "stopped: RuntimeError: the reader stopped" in ln]), 1, lines)
        self.assertEqual(len([ln for ln in lines if ln.startswith("alone ") and ln.endswith(" ok")]), 3, lines)
        self.assertTrue(any(ln.startswith("reader probe done") for ln in lines))


if __name__ == "__main__":
    unittest.main()

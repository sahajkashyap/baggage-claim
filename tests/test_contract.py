"""The contract, as tests.

The rules a teacher is given: the work is against a dark background, the
whole paper is in the frame, and the child's name is typed in a corner of the
paper. When she follows them, every piece lands upright in the right child's
folder. These tests hold the tool to that on a core set of walls; the whole
grid of sixty is `python3 tests/contract_check.py`, and its required score is
100%. Invented names only.

Found on September 26, 2026 by the first run of the grid, and fixed:
  - one paper whose edges were not found sent the WHOLE photo to a person
  - a paper whose edges were not found was never looked for against the
    dark background around its name label
  - a single paper filling the photo found nothing at all
  - the reader took one upright label for upside-down nonsense, and the
    piece was turned on the strength of that nonsense

Found on September 28, 2026 in the records of the build machines, and fixed:
  - the check itself asked the reader which way up a filed piece was, so a
    piece filed correctly was called a miss on a computer whose reader could
    not read it a second time. The check now compares pixels with the paper
    it made itself; what the reader says is printed as information
  - the practice walls named the Mac's font files only, so no wall could be
    made on Windows
  - the HEIC wall was written by the Mac's sips only
"""
import os
import shutil
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import baggage_claim as sw  # noqa: E402
import contract_check as cc  # noqa: E402
import contract_wall as cw  # noqa: E402
from contract_wall import contract_wall, from_the_side, NAMES, DARK, PAPER  # noqa: E402

HAVE = sw.backend_ready()
CORE = ["pieces-1", "pieces-2", "pieces-25", "corner-tl rot270", "corner-br rot90", "bg-navy paper-white",
        "side-left-0.12", "wrong-tag-6", "sentences corner-tl rot90", "portrait-paper rot270", "heic",
        "touching-6", "touching-6 rot90"]


def T(text, x, y, w=300, h=60, angle=0, own=True):
    t = {"text": text, "conf": 1.0, "x": x, "y": y, "w": w, "h": h, "angle": angle}
    if own:
        t["rel_y"] = 0.9
    return t


@unittest.skipUnless(HAVE, "needs the on-device reader")
class CoreWalls(unittest.TestCase):
    def test_every_core_wall_is_perfect(self):
        todo = [c for c in cc.cases() if c["case"] in CORE]
        self.assertEqual(len(todo), len(CORE))
        for c in todo:
            work = tempfile.mkdtemp(prefix="contract-")
            try:
                r = cc.run_case(c, work)
            finally:
                shutil.rmtree(work, ignore_errors=True)
            with self.subTest(wall=c["case"]):
                if r.get("skipped"):     # a wall this computer cannot write is not a miss and not a pass
                    self.skipTest(f"{c['case']}: {r['skipped']}")
                self.assertEqual(r["problems"], [])
                self.assertEqual(r["right"], r["pieces"])

    def test_what_the_reader_says_is_never_a_reason_for_a_miss(self):
        """On the build machine's Mac the tool filed two pieces correctly and
        the check called them misses, because the reader could not read the
        filed pieces a second time."""
        real = cc.reader_says
        cc.reader_says = lambda path, name: "label not read"
        work = tempfile.mkdtemp(prefix="contract-")
        try:
            c = [c for c in cc.cases() if c["case"] == "corner-tl rot270"][0]
            r = cc.run_case(c, work)
        finally:
            cc.reader_says = real
            shutil.rmtree(work, ignore_errors=True)
        self.assertEqual(r["problems"], [])
        self.assertEqual(r["right"], r["pieces"])
        self.assertIn("read 0 of 6 labels upright", r["info"]["reader"])
        self.assertIn("Jonah Reyes: label not read", r["info"]["reader"])

    def test_the_grid_has_seventy_five_walls_and_every_one_follows_the_rules(self):
        all_cases = cc.cases()
        self.assertEqual(len(all_cases), 75)
        self.assertEqual(len({c["case"] for c in all_cases}), 75)

    def test_main_reports_a_perfect_score_and_a_miss(self):
        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cc.main(["wrong-tag-3", "--json"])
        self.assertEqual(code, 0)
        self.assertIn("1 of 1 walls perfect, 6 of 6 pieces right (100.0%)", out.getvalue())
        real = cc.run_case
        cc.run_case = lambda c, work: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cc.main(["wrong-tag-3"])
        finally:
            cc.run_case = real
        self.assertEqual(code, 1)
        self.assertIn("MISS", out.getvalue())
        self.assertIn("crashed: RuntimeError: boom", out.getvalue())


class DarkWall(unittest.TestCase):
    def wall(self, bg, paper=(250, 250, 248), box=(300, 200, 1300, 900), size=(1600, 1200)):
        img = Image.new("RGB", size, bg)
        ImageDraw.Draw(img).rectangle(box, fill=paper)
        return img

    def test_a_dark_wall_is_dark_and_a_pale_wall_is_not(self):
        self.assertTrue(sw.wall_is_dark(self.wall((25, 25, 28))))
        self.assertTrue(sw.wall_is_dark(self.wall((70, 14, 24))))
        self.assertFalse(sw.wall_is_dark(self.wall((240, 238, 230))))

    def test_the_paper_is_found_around_its_label(self):
        img = self.wall((25, 25, 28))
        lab = T("Maya Torres", 900, 800)
        q = sw.paper_around_label(img, lab, [sw.centre(lab)])
        self.assertIsNotNone(q)
        x0, y0, x1, y1 = sw.quad_bbox(q)
        for got, want in zip((x0, y0, x1, y1), (300, 200, 1300, 900)):
            self.assertLess(abs(got - want), 12)
        self.assertNotIn("label", q)

    def test_no_paper_on_a_pale_wall(self):
        img = self.wall((240, 238, 230))
        lab = T("Maya Torres", 900, 800)
        self.assertIsNone(sw.paper_around_label(img, lab, [sw.centre(lab)]))

    def test_no_paper_when_it_runs_off_the_photo(self):
        img = self.wall((25, 25, 28), box=(0, 200, 1000, 900))
        lab = T("Maya Torres", 600, 800)
        self.assertIsNone(sw.paper_around_label(img, lab, [sw.centre(lab)]))

    def test_no_paper_when_two_labels_share_one_patch(self):
        img = self.wall((25, 25, 28))
        a, b = T("Maya Torres", 350, 800), T("Jonah Reyes", 950, 800)
        self.assertIsNone(sw.paper_around_label(img, a, [sw.centre(a), sw.centre(b)]))

    def test_no_paper_when_the_patch_is_not_a_sheet(self):
        img = Image.new("RGB", (1600, 1200), (25, 25, 28))
        d = ImageDraw.Draw(img)
        d.rectangle((300, 850, 1300, 950), fill=(250, 250, 248))     # an L, not a sheet
        d.rectangle((300, 200, 400, 950), fill=(250, 250, 248))
        lab = T("Maya Torres", 900, 870)
        self.assertIsNone(sw.paper_around_label(img, lab, [sw.centre(lab)]))

    def test_no_paper_when_the_label_is_on_the_wall(self):
        img = self.wall((25, 25, 28))
        lab = T("Maya Torres", 1320, 1000, w=200, h=40)
        self.assertIsNone(sw.paper_around_label(img, lab, [sw.centre(lab)]))

    def test_no_paper_when_the_patch_is_hardly_bigger_than_the_label(self):
        img = self.wall((25, 25, 28), box=(880, 790, 1230, 880))
        lab = T("Maya Torres", 900, 800)
        self.assertIsNone(sw.paper_around_label(img, lab, [sw.centre(lab)]))


class FoundEdges(unittest.TestCase):
    def quad(self, x0, y0, x1, y1, **kw):
        return {"conf": 1.0, "tl": [x0, y0], "tr": [x1, y0], "br": [x1, y1], "bl": [x0, y1], **kw}

    def setUp(self):
        self.img = Image.new("RGB", (2400, 1200), (25, 25, 28))
        d = ImageDraw.Draw(self.img)
        self.papers = [(100, 200, 700, 1000), (900, 200, 1500, 1000), (1700, 200, 2300, 1000)]
        for b in self.papers:
            d.rectangle(b, fill=(250, 250, 248))
        self.labels = [T("Maya Torres", 380, 900, own=False), T("Jonah Reyes", 1180, 900, own=False),
                       T("Sofia Lund", 1980, 900, own=False)]
        self.guesses = [self.quad(t["x"] - 200, t["y"] - 200, t["x"] + 500, t["y"] + 200, label=t) for t in self.labels]

    def test_a_found_paper_is_used_and_a_missing_one_is_looked_for(self):
        found = [self.quad(*self.papers[0]), self.quad(*self.papers[1])]      # the third was missed
        out = sw.with_found_edges(self.img, self.guesses, found)
        self.assertEqual(len(out), 3)
        self.assertEqual([("label" in q) for q in out], [False, False, False])
        self.assertEqual(sw.quad_bbox(out[0]), self.papers[0])
        self.assertEqual(out[2].get("edges"), "background")

    def test_one_found_paper_holding_two_labels_is_not_trusted(self):
        img = Image.new("RGB", (2400, 1200), (25, 25, 28))
        ImageDraw.Draw(img).rectangle((100, 200, 1500, 1000), fill=(250, 250, 248))   # two papers touching
        found = [self.quad(100, 200, 1500, 1000)]
        out = sw.with_found_edges(img, self.guesses[:2], found)
        self.assertEqual([("label" in q) for q in out], [True, True])

    def test_a_found_paper_far_bigger_than_the_rest_is_not_trusted(self):
        small = [self.quad(100 + k * 350, 20, 400 + k * 350, 320) for k in range(3)]     # three papers of the usual size
        found = small + [self.quad(*self.papers[2])]                                      # and one five times as big
        blank = Image.new("RGB", (2400, 1200), (25, 25, 28))
        out = sw.with_found_edges(blank, self.guesses[2:], found)
        self.assertIn("label", out[0])

    def test_on_a_pale_wall_every_piece_stays_a_guess(self):
        pale = Image.new("RGB", (2400, 1200), (240, 238, 230))
        found = [self.quad(*b) for b in self.papers]
        self.assertEqual(sw.with_found_edges(pale, self.guesses, found), self.guesses)
        self.assertEqual(sw.add_missing_papers(pale, self.labels, ["Maya Torres"], found), found)

    def test_a_missed_paper_is_added_and_a_found_one_is_left_alone(self):
        found = [self.quad(*self.papers[0])]
        roster = ["Maya Torres", "Jonah Reyes", "Sofia Lund"]
        was, sw.LAST_DETECTOR = sw.LAST_DETECTOR, "rectangles"     # a found box is kept only with the rectangle finder
        self.addCleanup(setattr, sw, "LAST_DETECTOR", was)
        out = sw.add_missing_papers(self.img, self.labels, roster, found)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0], found[0])
        self.assertEqual(sw.add_missing_papers(self.img, self.labels, roster, out), out)

    def test_the_same_label_read_twice_counts_once(self):
        twice = self.labels + [T("Maya Torres", 384, 903, own=False)]
        self.assertEqual(len(sw.label_list(self.img, twice, ["Maya Torres", "Jonah Reyes", "Sofia Lund"])), 3)


class WithoutTheRectangleFinder(unittest.TestCase):
    """A Windows PC has no rectangle finder: a found box is a texture or colour
    guess. On a dark wall the paper found from the background around the label
    is exact and replaces the guess. Found by the first Windows build of
    September 28, 2026, where five dark-wall walls with coloured paper missed."""

    def quad(self, x0, y0, x1, y1, **kw):
        return {"conf": 1.0, "tl": [x0, y0], "tr": [x1, y0], "br": [x1, y1], "bl": [x0, y1], **kw}

    def setUp(self):
        self.img = Image.new("RGB", (2400, 1200), (22, 30, 62))
        d = ImageDraw.Draw(self.img)
        self.papers = [(100, 200, 700, 1000), (900, 200, 1500, 1000)]
        for b in self.papers:
            d.rectangle(b, fill=(250, 226, 110))
        self.roster = ["Maya Torres", "Jonah Reyes"]
        # the reader read the second label twice, with two spellings, a few pixels apart
        self.whole = [T("Maya Torres", 380, 900, own=False), T("lonah Reyes", 1180, 900, own=False),
                      T("Jonah Re", 1170, 902, w=220, own=False)]
        self.was = sw.LAST_DETECTOR

    def tearDown(self):
        sw.LAST_DETECTOR = self.was

    def test_two_readings_of_one_label_are_one_label(self):
        self.assertEqual(len(sw.label_list(self.img, self.whole, self.roster)), 2)

    def test_a_colour_guess_around_a_label_is_replaced_by_the_paper(self):
        sw.LAST_DETECTOR = "colour"
        guesses = [self.quad(340, 880, 720, 960), self.quad(1150, 880, 1450, 960)]   # the label strips, not the papers
        out = sw.add_missing_papers(self.img, self.whole, self.roster, guesses)
        self.assertEqual(len(out), 2)
        for q, want in zip(out, self.papers):
            self.assertEqual(q.get("edges"), "background")
            got = sw.quad_bbox(q)
            for a, b in zip(got, want):
                self.assertLess(abs(a - b), 12)

    def test_with_the_rectangle_finder_a_found_box_is_kept(self):
        sw.LAST_DETECTOR = "rectangles"
        found = [self.quad(*self.papers[0]), self.quad(*self.papers[1])]
        out = sw.add_missing_papers(self.img, self.whole, self.roster, found)
        self.assertEqual(out, found)


class WhatThePCReaderGetsWrong(unittest.TestCase):
    """Two things the reader of a PC did on the Windows build of September 28,
    2026 that Apple's reader does not: a garbled second reading of one child's
    name on another child's paper, and a label read on the whole photo but not
    again on the piece. Each cost one piece on one practice wall."""

    def test_a_garbled_second_reading_is_dropped_and_a_clean_one_kept(self):
        roster = ["Lily", "Theo", "Maya Torres"]
        lines = [T("Lily", 100, 100, own=False), T("09 LIL", 900, 100, own=False),
                 T("Theo", 900, 400, own=False)]
        kept = sw.one_label_per_child(lines, roster)
        self.assertEqual([t["text"] for t in kept], ["Lily", "Theo"])
        two_clean = [T("Lily", 100, 100, own=False), T("Lily", 900, 100, own=False)]
        self.assertEqual(len(sw.one_label_per_child(two_clean, roster)), 2, "a child may have two papers")
        self.assertEqual(sw.one_label_per_child(lines, None), lines)

    def test_strength_of_a_reading(self):
        roster = ["Lily", "Maya Torres"]
        self.assertEqual(sw.label_strength(T("Maya Torres", 0, 0), roster), 1.0)
        self.assertLess(sw.label_strength(T("09 LIL", 0, 0), roster), sw.CLEAN_READ)
        self.assertEqual(sw.label_strength(T("", 0, 0), roster), 0.0)

    @unittest.skipUnless(HAVE, "needs the on-device reader")
    def test_a_paper_found_from_its_label_files_even_when_the_close_read_misses(self):
        from contract_wall import contract_wall, NAMES
        names = NAMES[:6]
        img, truth = contract_wall(names, 2, 3, bg="navy", paper="yellow", seed=5)
        work = tempfile.mkdtemp(prefix="missed-label-")
        self.addCleanup(shutil.rmtree, work, True)
        photo = os.path.join(work, "wall.jpg"); img.save(photo, quality=92)
        real_rv, real_rp, real_rn = sw.run_vision, sw.read_piece, sw.read_neighborhood
        blind = lambda lines: [t for t in lines if "priya" not in sw.norm(t.get("text", ""))]
        sw.run_vision = lambda mode, path, *e: [] if mode == "rects" else real_rv(mode, path, *e)
        sw.read_piece = lambda tmp, crop: blind(real_rp(tmp, crop))
        sw.read_neighborhood = lambda *a, **k: blind(real_rn(*a, **k))
        try:
            res = sw.process_photo(photo, names, os.path.join(work, "out"), "Contract", log=lambda s: None, grade="K")
        finally:
            sw.run_vision, sw.read_piece, sw.read_neighborhood = real_rv, real_rp, real_rn
        filed = sorted(r["name"] for r in res if r["status"] == "confident")
        self.assertEqual(filed, sorted(names), "every child filed, the one whose close read was missed included")


class ASentenceSplitByTheReader(unittest.TestCase):
    """The reader of a PC can return "with my friend Theo." as two lines, and
    "Theo." alone looks exactly like a name label on the wrong child's page.
    Found on the Windows build of September 28, 2026 as one piece filed under
    a friend's name on a page of writing. Lines on one row that nearly touch
    are joined back into one line (join_rows) before any name is looked for."""

    def test_a_split_sentence_is_one_line_again(self):
        a = {"text": "with my friend", "conf": 1.0, "x": 100, "y": 500, "w": 300, "h": 40, "angle": 0}
        b = {"text": "Theo.", "conf": 0.9, "x": 410, "y": 502, "w": 90, "h": 40, "angle": 0}
        out = sw.join_rows([b, a])
        self.assertEqual([t["text"] for t in out], ["with my friend Theo."])
        self.assertEqual((out[0]["x"], out[0]["w"], out[0]["conf"]), (100, 400, 0.9))

    def test_a_fragment_a_tile_edge_cut_off_is_not_a_line_of_its_own(self):
        whole = {"text": "waves came and Theo laughed", "conf": 1.0, "x": 1778, "y": 1796, "w": 472, "h": 35, "angle": 0}
        cut = {"text": "Theo", "conf": 1.0, "x": 2043, "y": 1797, "w": 76, "h": 32, "angle": 0}
        tail = {"text": "o laughed", "conf": 1.0, "x": 2102, "y": 1803, "w": 148, "h": 35, "angle": 0}
        label = {"text": "Lily", "conf": 1.0, "x": 2153, "y": 2157, "w": 102, "h": 67, "angle": 0}
        upside = {"text": "peq6nel", "conf": 1.0, "x": 2102, "y": 1803, "w": 148, "h": 35, "angle": 180}
        out = sw.join_rows([whole, cut, tail, label, upside])
        self.assertEqual(sorted(t["text"] for t in out), sorted(["waves came and Theo laughed", "Lily", "peq6nel"]))
        self.assertEqual(sw.label_hits([whole, cut, tail, label], ["Lily", "Theo"])[0]["text"], "Lily")
        self.assertEqual(len(sw.label_hits([whole, cut, tail, label], ["Lily", "Theo"])), 1)

    @unittest.skipUnless(HAVE, "needs the on-device reader")
    def test_a_wall_read_in_tiles_is_never_cut_by_a_fragment(self):
        """Replays what the Windows build of September 29, 2026 showed: every
        sentence that names a friend also comes back as a separate fragment
        holding just the name. Without the fix this wall came out as 16
        pieces with 8 under the wrong child."""
        from make_wall import make_wall
        names = ["Maya", "Jonah", "Sofia", "Elijah", "Priya", "Marcus", "Lily", "Theo"]
        real = sw.read_photo_text
        def with_fragments(*a, **k):
            out = list(real(*a, **k))
            for t in list(out):
                words = t.get("text", "").split()
                for i, word in enumerate(words):
                    if word.strip(".") in names and len(words) > 2:
                        n = max(1, len(t["text"]))
                        x = t["x"] + int(t["w"] * sum(len(v) + 1 for v in words[:i]) / n)
                        out.append({**t, "text": word.strip("."), "x": x, "w": int(t["w"] * len(word) / n)})
            return out
        img, truth = make_wall(names, writing=True, wall=(190, 60, 60), seed=6)
        work = tempfile.mkdtemp(prefix="tiles-")
        self.addCleanup(shutil.rmtree, work, True)
        inbox = os.path.join(work, "inbox"); os.makedirs(inbox)
        img.save(os.path.join(inbox, "wall.jpg"), quality=90)
        sw.read_photo_text = with_fragments
        try:
            res = sw.run_inbox(inbox, names, work, "W", log=lambda *a: None, grade="K")
        finally:
            sw.read_photo_text = real
        self.assertEqual(len(res), 8)
        for r in res:
            paper = max(truth, key=lambda t: sw.bbox_overlap(t["box"], r["bbox"]))
            self.assertEqual((r["status"], r["name"]), ("confident", paper["name"]), f"piece {r['piece']}")

    def test_a_word_read_twice_by_two_tiles_leaves_no_lone_name(self):
        """The exact lines the Windows reader returned at noon on September 29,
        2026: two tiles read the last word of "with my friend Lily." as "Lily."
        and as a garbled "LAY,". One joined the sentence; the other was left
        alone and taken for a label, which filed a page under the friend."""
        near = [{"text": "with my friend", "x": 949, "y": 1628, "w": 221, "h": 40, "angle": 0},
                {"text": "Lily.", "x": 1170, "y": 1628, "w": 56, "h": 40, "angle": 0},
                {"text": "LAY,", "x": 1168, "y": 1640, "w": 60, "h": 32, "angle": 0},
                {"text": "E", "x": 1021, "y": 1634, "w": 25, "h": 20, "angle": 90}]
        out = sw.join_rows(near)
        self.assertFalse([t for t in out if sw.norm(t["text"]) in ("lily", "lay")])
        self.assertEqual(sw.label_hits(near, ["Lily", "Theo"]), [])

    def test_lines_that_do_not_belong_together_stay_apart(self):
        label = {"text": "Maya Torres", "conf": 1.0, "x": 900, "y": 80, "w": 300, "h": 50, "angle": 0}
        far = {"text": "Jonah Reyes", "conf": 1.0, "x": 1600, "y": 82, "w": 300, "h": 50, "angle": 0}
        below = {"text": "we went", "conf": 1.0, "x": 900, "y": 200, "w": 200, "h": 50, "angle": 0}
        turned = {"text": "Theo", "conf": 1.0, "x": 1210, "y": 80, "w": 100, "h": 50, "angle": 180}
        tall = {"text": "BIG", "conf": 1.0, "x": 1205, "y": 60, "w": 100, "h": 120, "angle": 0}
        for other in (far, below, turned, tall):
            self.assertEqual(len(sw.join_rows([label, other])), 2)
        self.assertEqual(sw.join_rows([]), [])

    @unittest.skipUnless(HAVE, "needs the on-device reader")
    def test_a_page_of_writing_is_never_filed_under_the_friend_in_the_story(self):
        from make_wall import make_wall
        names = ["Maya", "Jonah", "Sofia", "Elijah", "Priya", "Marcus", "Lily", "Theo"]
        real = sw.run_vision
        def split(lines):
            out = []
            for t in lines:
                w = t.get("text", "").split()
                if len(w) >= 3 and sw.norm(w[-1]) in [n.lower() for n in names]:
                    cut = int(t["w"] * 0.8)
                    out += [{**t, "text": " ".join(w[:-1]), "w": cut}, {**t, "text": w[-1], "x": t["x"] + cut, "w": t["w"] - cut}]
                else:
                    out.append(t)
            return out
        img, truth = make_wall(names, writing=True, wall=(190, 60, 60), seed=6)
        work = tempfile.mkdtemp(prefix="split-")
        self.addCleanup(shutil.rmtree, work, True)
        inbox = os.path.join(work, "inbox"); os.makedirs(inbox)
        img.save(os.path.join(inbox, "wall.jpg"), quality=90)
        sw.run_vision = lambda m, p, *e: [] if m == "rects" else split(real(m, p, *e))
        try:
            from test_baggage_claim import ReaderEvidence
            with ReaderEvidence("split sentences, red wall") as ev:
                res = sw.run_inbox(inbox, names, work, "W", log=lambda *a: None, grade="K")
            ev.report(res, truth)
        finally:
            sw.run_vision = real
        for r in res:
            if r["status"] == "confident":
                paper = max(truth, key=lambda t: sw.bbox_overlap(t["box"], r["bbox"]))
                self.assertEqual(r["name"], paper["name"], f"piece {r['piece']} filed under the wrong child")


class OnlyTheNameDecides(unittest.TestCase):
    def test_the_name_read_on_the_piece(self):
        texts = [T("scribble", 10, 10, angle=180), T("Maya Torres", 50, 900, angle=90)]
        self.assertEqual(sw.name_line(texts, {"text": "Maya Torres"}), ("own", 90))

    def test_the_name_read_on_the_wall_around_it(self):
        texts = [T("slayy", 10, 10, angle=180), T("Maya Torres", 50, 900, angle=0, own=False)]
        self.assertEqual(sw.name_line(texts, {"text": "Maya Torres"}), ("wall", 0))

    def test_no_line_is_the_name(self):
        texts = [T("slayy", 10, 10, angle=180)]
        self.assertEqual(sw.name_line(texts, {"text": "Maya Torres"}), (None, 0))
        self.assertEqual(sw.name_line(texts, {"text": None}), (None, 0))

    def test_a_scribble_is_a_hint_and_nothing_more(self):
        texts = [T("slayy", 10, 10, angle=180), T("Maya Torres", 50, 900, angle=0, own=False)]
        self.assertEqual(sw.hint_angle(texts), 180)
        self.assertEqual(sw.hint_angle([]), 0)


class PapersHungTouching(unittest.TestCase):
    """No dark wall shows between two sheets hung edge to edge, but the
    sheet's own edge is a line, and the papers are cut there."""

    def quad(self, x0, y0, x1, y1, **kw):
        return {"conf": 1.0, "tl": [x0, y0], "tr": [x1, y0], "br": [x1, y1], "bl": [x0, y1], **kw}

    def pair(self, seam=True, size=(2400, 1200)):
        img = Image.new("RGB", size, (25, 25, 28))
        d = ImageDraw.Draw(img)
        d.rectangle((200, 200, 2199, 1000), fill=(250, 250, 248))
        if seam:
            d.line((1200, 200, 1200, 1000), fill=(150, 150, 150), width=6)
        # each child's drawing, which is not a seam: it does not run the height of the paper
        d.line((600, 400, 600, 700), fill=(40, 40, 160), width=8)
        d.line((1700, 450, 1700, 650), fill=(160, 40, 40), width=8)
        a, b = T("Maya Torres", 820, 900, own=False), T("Jonah Reyes", 1820, 900, own=False)
        return img, a, b

    def test_two_papers_are_cut_at_the_line_between_them(self):
        img, a, b = self.pair()
        cs, kids = [sw.centre(a), sw.centre(b)], ["Maya Torres", "Jonah Reyes"]
        qa = sw.paper_around_label(img, a, cs, kids=kids)
        qb = sw.paper_around_label(img, b, cs, kids=kids)
        self.assertEqual((qa["edges"], qb["edges"]), ("seam", "seam"))
        ax0, ay0, ax1, ay1 = sw.quad_bbox(qa)
        bx0, by0, bx1, by1 = sw.quad_bbox(qb)
        self.assertLess(abs(ax0 - 200), 12); self.assertLess(abs(ax1 - 1200), 14)
        self.assertLess(abs(bx0 - 1200), 14); self.assertLess(abs(bx1 - 2200), 12)
        self.assertLessEqual(ax1, bx0 + 4, "the two pieces do not share any of the wall")

    def test_no_line_between_them_means_no_cut(self):
        img, a, b = self.pair(seam=False)
        cs, kids = [sw.centre(a), sw.centre(b)], ["Maya Torres", "Jonah Reyes"]
        self.assertIsNone(sw.paper_around_label(img, a, cs, kids=kids))
        self.assertIsNone(sw.paper_around_label(img, b, cs, kids=kids))

    def test_papers_hung_one_above_the_other(self):
        img, a, b = self.pair()
        img = img.rotate(90, expand=True)           # now 1200 wide, 2400 tall; the seam runs across
        a = T("Maya Torres", 900, 2400 - 820 - 300, w=60, h=300, own=False)
        b = T("Jonah Reyes", 900, 2400 - 1820 - 300, w=60, h=300, own=False)
        cs, kids = [sw.centre(a), sw.centre(b)], ["Maya Torres", "Jonah Reyes"]
        qa = sw.paper_around_label(img, a, cs, kids=kids)
        self.assertIsNotNone(qa)
        x0, y0, x1, y1 = sw.quad_bbox(qa)
        self.assertLess(abs(y0 - 1200), 14)

    def test_the_same_child_named_twice_on_one_paper_is_one_child(self):
        img = Image.new("RGB", (1600, 1200), (25, 25, 28))
        ImageDraw.Draw(img).rectangle((300, 200, 1300, 900), fill=(250, 250, 248))
        a, b = T("Maya Torres", 900, 800, own=False), T("Maya Torres", 350, 250, own=False)
        cs, kids = [sw.centre(a), sw.centre(b)], ["Maya Torres", "Maya Torres"]
        q = sw.paper_around_label(img, a, cs, kids=kids)
        self.assertEqual(q["edges"], "background")
        guesses = [self.quad(700, 600, 1400, 1000, label=a), self.quad(300, 200, 800, 500, label=b)]
        out = sw.with_found_edges(img, guesses, [], ["Maya Torres", "Jonah Reyes"])
        self.assertEqual(len(out), 1, "one paper, one piece")
        out = sw.with_found_edges(img, guesses, [self.quad(300, 200, 1300, 900)], ["Maya Torres", "Jonah Reyes"])
        self.assertEqual(len(out), 1)

    def test_a_found_paper_holding_two_children_is_cut_in_two(self):
        img, a, b = self.pair()
        roster = ["Maya Torres", "Jonah Reyes"]
        out = sw.add_missing_papers(img, [a, b], roster, [self.quad(200, 200, 2200, 1000)])
        self.assertEqual(sorted(q["child"] for q in out), roster[::-1][::-1] if False else sorted(roster))
        img2, a2, b2 = self.pair(seam=False)
        one = [self.quad(200, 200, 2200, 1000)]
        self.assertEqual(sw.add_missing_papers(img2, [a2, b2], roster, one), one)

    def test_whose_label(self):
        roster = ["Maya Torres", "Jonah Reyes"]
        self.assertEqual(sw.whose({"text": "Jonah Reyes:"}, roster), "Jonah Reyes")
        self.assertEqual(sw.whose({"text": "MAYA"}, roster), "Maya Torres")
        self.assertIsNone(sw.whose({"text": ""}, []))

    def test_no_seam_when_the_labels_sit_side_by_side_with_nothing_between(self):
        import numpy as np
        lum = np.full((100, 100), 240.0)
        self.assertIsNone(sw.seam_between(lum, (0, 0, 99, 99), (50, 50), (51, 50), True))


class OffThePhoto(unittest.TestCase):
    def test_the_reason_is_carried_and_said_in_plain_words(self):
        img = Image.new("RGB", (1600, 1200), (25, 25, 28))
        ImageDraw.Draw(img).rectangle((300, 0, 1300, 700), fill=(250, 250, 248))
        lab = T("Maya Torres", 900, 600, own=False)
        why = []
        self.assertIsNone(sw.paper_around_label(img, lab, [sw.centre(lab)], why=why))
        self.assertEqual(why, [sw.OFF_THE_PHOTO])
        guess = {"conf": 0.6, "tl": [700, 400], "tr": [1400, 400], "br": [1400, 800], "bl": [700, 800], "label": lab}
        out = sw.with_found_edges(img, [guess], [], ["Maya Torres"])
        self.assertEqual(out[0]["why"], sw.OFF_THE_PHOTO)
        self.assertIn("label", out[0])

    def test_the_batch_line_says_so(self):
        off = [{"status": "unsure", "reason": sw.EDGES, "why": sw.OFF_THE_PHOTO}, {"status": "confident"}]
        self.assertIn("2 pieces, 1 filed, 1 to unsorted (on 1 of them the name was read, but the paper runs off "
                      "the edge of the photo", sw.batch_text(off))
        mixed = off + [{"status": "unsure", "reason": sw.EDGES}]
        self.assertIn("pale paper on a pale wall, or papers hung with no edge showing", sw.batch_text(mixed))
        self.assertEqual(sw.batch_text([{"status": "confident"}]), "1 pieces, 1 filed, 0 to unsorted")

    def test_the_log_says_so(self):
        results = [{"status": "unsure", "reason": sw.EDGES, "why": sw.OFF_THE_PHOTO, "name": "Maya Torres"},
                   {"status": "confident", "name": "Jonah Reyes"}]
        d = tempfile.mkdtemp()
        try:
            said = []
            sw.tell_edges_guessed("wall.jpg", "Maps", results, 2, 1, d, said.append)
            self.assertIn("the name was read on 2 of the 2 pieces", said[0])
            self.assertIn("where one paper begins and ends", said[0])
            self.assertIn("the paper runs off the edge of the photo", said[0])
            self.assertIn("That piece is in", said[0])
            two = results + [{"status": "unsure", "reason": sw.EDGES, "name": "Sofia Lund"}]
            said = []
            sw.tell_edges_guessed("wall.jpg", "Maps", two, 3, 1, d, said.append)
            self.assertIn("the name was read on 3 of the 3 pieces", said[0])
            self.assertIn("where 2 of the papers begin and end", said[0])
            self.assertIn("on 1 of them the paper runs off the edge of the photo", said[0])
            self.assertIn("Those 2 pieces are in", said[0])
        finally:
            shutil.rmtree(d, ignore_errors=True)


def hung(n=6, rows=2, cols=3, size=(2016, 1512), **kw):
    """A practice wall, and each paper as it hangs on it: cut from the photo
    by its own box, with the strips of wall a tilted paper leaves around it."""
    img, truth = contract_wall(NAMES[:n], rows, cols, size=size, **kw)
    return img, truth, [img.crop(t["box"]) for t in truth]


def seen_from_the_side(img, truth, strength, side, wall):
    """The same papers cut from a photo taken from one side, not
    straightened at all: harder than anything the tool files."""
    photo = from_the_side(img, strength, side, wall)
    pieces = []
    for t in truth:
        place = Image.new("RGB", img.size, (0, 0, 0))
        ImageDraw.Draw(place).rectangle(t["box"], fill=(255, 255, 255))
        box = from_the_side(place, strength, side, (0, 0, 0)).convert("L").point(lambda v: 255 if v > 128 else 0).getbbox()
        pieces.append(photo.crop(box))
    return pieces


class WhichWayUpByPixels(unittest.TestCase):
    """The check's own eyes. No reader is asked anything here, so these run
    on any computer that has the fonts."""

    def every_way(self, piece, paper, wall, what=""):
        ok, why, match = cc.upright(piece, paper, wall)
        self.assertTrue(ok, f"{what} upright: {why}")
        self.assertGreaterEqual(match[0] - max(match[90], match[180], match[270]), 2 * cc.CLEAR, f"{what} {match}")
        for turn in (90, 180, 270):
            ok, why, match = cc.upright(piece.rotate(turn, expand=True), paper, wall)
            self.assertFalse(ok, f"{what} turned {turn}: {match}")
            back = (360 - turn) % 360
            self.assertIn(f"it would be upright after a {back} degree turn", why, what)
            self.assertEqual(max(match, key=match.get), back, what)

    def test_upright_wins_clearly(self):
        img, truth, pieces = hung()
        for t, piece in zip(truth, pieces):
            ok, why, match = cc.upright(piece, t["paper"], DARK["black"])
            self.assertEqual((ok, why), (True, ""), t["name"])
            self.assertEqual(sorted(match), [0, 90, 180, 270])
            self.assertGreater(match[0], 0.8)
            self.assertGreaterEqual(match[0] - max(match[90], match[180], match[270]), 0.3, match)

    def test_each_of_the_three_turns_is_caught(self):
        img, truth, pieces = hung()
        for t, piece in zip(truth, pieces):
            self.every_way(piece, t["paper"], DARK["black"], t["name"])

    def test_a_piece_given_as_a_file(self):
        img, truth, pieces = hung()
        d = tempfile.mkdtemp()
        try:
            f = os.path.join(d, "piece.jpg")
            pieces[0].save(f, quality=92)
            self.assertTrue(cc.upright(f, truth[0]["paper"], DARK["black"])[0])
            pieces[0].rotate(180).save(f, quality=92)
            self.assertFalse(cc.upright(f, truth[0]["paper"], DARK["black"])[0])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_a_nearly_square_paper(self):
        img, truth, pieces = hung(20, 4, 5, size=(4032, 3024), seed=60)
        for t, piece in list(zip(truth, pieces))[::3]:
            w, h = t["paper"].size
            self.assertLessEqual(abs(w - h), 0.2 * max(w, h), "the paper is nearly square")
            self.every_way(piece, t["paper"], DARK["black"], t["name"])

    def test_a_paper_seen_from_the_side(self):
        img, truth, _ = hung(size=(4032, 3024))
        for side in ("left", "right"):
            for strength in (0.06, 0.12):
                for t, piece in zip(truth, seen_from_the_side(img, truth, strength, side, DARK["black"])):
                    self.every_way(piece, t["paper"], DARK["black"], f"{t['name']} from the {side} {strength}")

    def test_every_wall_colour_and_every_paper_colour(self):
        for bg in DARK:
            for paper in PAPER:
                img, truth, pieces = hung(2, 1, 2, size=(2016, 1512), bg=bg, paper=paper, seed=7)
                for t, piece in zip(truth, pieces):
                    self.every_way(piece, t["paper"], DARK[bg], f"{t['name']} {paper} on {bg}")

    def test_portrait_paper_and_a_label_in_every_corner(self):
        for corner in ("tl", "tr", "bl", "br"):
            img, truth, pieces = hung(portrait_paper=True, corner=corner, seed=9)
            self.assertLess(truth[0]["paper"].width, truth[0]["paper"].height)
            for t, piece in list(zip(truth, pieces))[:2]:
                self.every_way(piece, t["paper"], DARK["black"], f"{t['name']} {corner}")

    def test_a_badly_tilted_paper(self):
        img, truth, pieces = hung(tilt=6.0, seed=12)
        for t, piece in zip(truth, pieces):
            self.every_way(piece, t["paper"], DARK["black"], t["name"])

    def test_papers_hung_touching(self):
        img, truth, _ = hung(touching=True, seed=5)
        for t in truth:
            x0, y0, x1, y1 = t["box"]
            wide = int((x1 - x0) * 0.04)       # a cut that takes in a little of each neighbour
            self.every_way(img.crop((x0 - wide, y0, x1 + wide, y1)), t["paper"], DARK["black"], t["name"])
            self.every_way(img.crop(t["box"]), t["paper"], DARK["black"], t["name"])

    def test_wide_strips_of_wall_around_the_paper_are_left_out(self):
        img, truth, pieces = hung(bg="navy", seed=3)
        for t, piece in zip(truth, pieces):
            w, h = piece.size
            wide = Image.new("RGB", (w + w // 4, h + h // 5), DARK["navy"])
            wide.paste(piece, (w // 5, h // 20))
            self.every_way(wide, t["paper"], DARK["navy"], t["name"])
            self.assertLess(abs(cc.paper_part(wide, DARK["navy"]).width - w), w // 12)

    def test_typed_letters_are_not_taken_for_wall(self):
        img, truth, pieces = hung(1, 1, 1, size=(1600, 1200), tilt=0)
        n = cc.SMALL * cc.FINE
        rgb = cc.fine_rgb(truth[0]["paper"])
        self.assertFalse(cc.wall_at_the_edges(rgb, DARK["black"]).any(), "a paper with no wall around it")
        self.assertEqual(cc.paper_part(truth[0]["paper"], DARK["black"]).size, truth[0]["paper"].size)
        shades, counts = cc.small_shades(pieces[0], DARK["black"])
        self.assertEqual(shades.shape, (cc.SMALL, cc.SMALL))
        self.assertEqual(counts.min(), 1.0)
        self.assertEqual(n, 128)

    def test_a_piece_with_nothing_on_it_cannot_be_told(self):
        img, truth, pieces = hung()
        blank = Image.new("RGB", pieces[0].size, PAPER["white"])
        ok, why, match = cc.upright(blank, truth[0]["paper"], DARK["black"])
        self.assertFalse(ok)
        self.assertIn("cannot tell from the filed piece which way is up", why)
        all_wall = Image.new("RGB", pieces[0].size, DARK["black"])
        ok, why, match = cc.upright(all_wall, truth[0]["paper"], DARK["black"])
        self.assertFalse(ok)
        self.assertEqual(match, {0: 0.0, 90: 0.0, 180: 0.0, 270: 0.0})

    def test_each_piece_looks_most_like_its_own_paper(self):
        img, truth, pieces = hung()
        papers = {t["name"]: cc.small_shades(t["paper"])[0] for t in truth}
        for t, piece in zip(truth, pieces):
            for turn in (0, 90, 180, 270):
                whose = cc.looks_like(piece.rotate(turn, expand=True), papers, DARK["black"])
                self.assertEqual(max(whose, key=whose.get), t["name"])


class HeldAgainstTheWall(unittest.TestCase):
    """What the tool filed, held against what was on the wall. The filing is
    done here by hand, so no reader is needed."""

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="contract-")
        self.real_reader = cc.reader_says
        cc.reader_says = lambda path, name: "upright"
        # nearly square papers: a piece filed on its side is the same shape, so only the pixels can tell
        self.img, self.truth, self.pieces = hung(20, 4, 5, size=(4032, 3024), seed=60)
        self.truth, self.pieces = self.truth[:4], self.pieces[:4]
        self.names = [t["name"] for t in self.truth]

    def tearDown(self):
        cc.reader_says = self.real_reader
        shutil.rmtree(self.out, ignore_errors=True)

    def filed(self, turns=None, under=None):
        res = []
        for k, (t, piece) in enumerate(zip(self.truth, self.pieces)):
            name = (under or {}).get(t["name"], t["name"])
            rel = os.path.join("sorted", name, "Contract", "Contract K.jpg")
            os.makedirs(os.path.dirname(os.path.join(self.out, rel)), exist_ok=True)
            turn = (turns or {}).get(t["name"], 0)
            (piece.rotate(turn, expand=True) if turn else piece).save(os.path.join(self.out, rel), quality=92)
            res.append({"piece": k + 1, "file": rel, "name": name, "status": "confident", "score": 1.0, "turned": 0})
        return res

    def test_every_piece_upright_is_a_perfect_wall(self):
        right, problems, info = cc.score_wall(self.filed(), self.truth, self.names, self.out, DARK["black"])
        self.assertEqual((right, problems), (4, []))
        self.assertIn("upright by 0.", info["pixels"])
        self.assertEqual(info["reader"], "read 4 of 4 labels upright")

    def test_a_piece_filed_on_its_side_or_upside_down_is_a_miss(self):
        for turn in (90, 180, 270):
            res = self.filed(turns={"Jonah Reyes": turn})
            right, problems, info = cc.score_wall(res, self.truth, self.names, self.out, DARK["black"])
            self.assertEqual(right, 3)
            self.assertEqual(len(problems), 1)
            self.assertIn(f"Jonah Reyes: filed turned: it would be upright after a {(360 - turn) % 360} degree turn", problems[0])

    def test_a_reader_that_reads_nothing_changes_nothing(self):
        cc.reader_says = lambda path, name: "label not read" if name == "Sofia Lund" else "label read at 180 degrees"
        right, problems, info = cc.score_wall(self.filed(), self.truth, self.names, self.out, DARK["black"])
        self.assertEqual((right, problems), (4, []))
        self.assertIn("read 0 of 4 labels upright", info["reader"])
        self.assertIn("Sofia Lund: label not read", info["reader"])
        self.assertIn("Maya Torres: label read at 180 degrees", info["reader"])

    def test_a_reader_that_says_upright_does_not_excuse_a_turned_piece(self):
        res = self.filed(turns={"Maya Torres": 180})
        right, problems, info = cc.score_wall(res, self.truth, self.names, self.out, DARK["black"])
        self.assertEqual(right, 3)
        self.assertIn("Maya Torres: filed turned", problems[0])

    def test_the_reader_is_not_asked_when_told_not_to(self):
        cc.reader_says = lambda path, name: self.fail("the reader was asked")
        right, problems, info = cc.score_wall(self.filed(), self.truth, self.names, self.out, DARK["black"], ask_reader=False)
        self.assertEqual((right, problems), (4, []))
        self.assertNotIn("reader", info)

    def test_two_childrens_papers_in_each_others_folders(self):
        res = self.filed(under={"Maya Torres": "Jonah Reyes", "Jonah Reyes": "Maya Torres"})
        right, problems, info = cc.score_wall(res, self.truth, self.names, self.out, DARK["black"])
        self.assertEqual(right, 2)
        self.assertEqual(sorted(p.split(":")[0] for p in problems), ["Jonah Reyes", "Maya Torres"])

    def test_never_filed_filed_twice_and_a_file_that_is_not_there(self):
        res = self.filed()
        res[0]["status"] = "unsure"
        res.append(dict(res[1]))
        os.remove(os.path.join(self.out, res[2]["file"]))
        right, problems, info = cc.score_wall(res, self.truth, self.names, self.out, DARK["black"])
        self.assertEqual(right, 1)
        self.assertIn("Maya Torres: filed 0 times (unsure:1.0)", problems)
        self.assertIn("Jonah Reyes: filed 2 times (confident:1.0, confident:1.0)", problems)
        self.assertIn("Sofia Lund: file missing", problems)
        self.assertIn("1 duplicate filing(s)", problems)

    def test_the_reader_failing_is_said_and_is_not_a_miss(self):
        cc.reader_says = self.real_reader
        real = sw.read_piece
        sw.read_piece = lambda path, crop: (_ for _ in ()).throw(RuntimeError("no reader here"))
        try:
            right, problems, info = cc.score_wall(self.filed(), self.truth, self.names, self.out, DARK["black"])
        finally:
            sw.read_piece = real
        self.assertEqual((right, problems), (4, []))
        self.assertIn("reader failed (RuntimeError: no reader here)", info["reader"])

    def test_what_the_reader_says_in_its_own_words(self):
        cc.reader_says = self.real_reader
        res = self.filed()
        f = os.path.join(self.out, res[0]["file"])
        real = sw.read_piece
        try:
            sw.read_piece = lambda path, crop: [T("Maya Torres", 10, 10)]
            self.assertEqual(cc.reader_says(f, "Maya Torres"), "upright")
            sw.read_piece = lambda path, crop: [T("Maya Torres", 10, 10, angle=90)]
            self.assertEqual(cc.reader_says(f, "Maya Torres"), "label read at 90 degrees")
            sw.read_piece = lambda path, crop: [T("scribble", 10, 10)]
            self.assertEqual(cc.reader_says(f, "Maya Torres"), "label not read")
        finally:
            sw.read_piece = real


class OnAnyComputer(unittest.TestCase):
    """The practice walls can be made on a Mac and on Windows, and a wall
    that cannot be made is skipped out loud."""

    def case(self, name):
        return [c for c in cc.cases() if c["case"] == name][0]

    def test_every_font_is_found_on_this_computer(self):
        for font, places in cw.FONTS.items():
            self.assertGreaterEqual(len(places), 2, "a place on a Mac and a place on Windows")
            self.assertTrue(any(p.lower().endswith(("arial.ttf", "arialbd.ttf", "times.ttf", "verdana.ttf")) for p in places))
            self.assertIn(cw.font_file(font), places)
            self.assertTrue(os.path.isfile(cw.font_file(font)))

    def test_the_first_place_that_has_the_font_is_used(self):
        here = cw.font_file("arial")
        cw.FONTS["practice"] = [os.path.join(HERE, "no-such-folder", "arial.ttf"), here]
        try:
            self.assertEqual(cw.font_file("practice"), here)
        finally:
            del cw.FONTS["practice"]

    def test_a_font_that_is_nowhere_is_said_plainly_and_the_wall_is_skipped(self):
        real = cw.FONTS["arial-bold"]
        nowhere = [os.path.join(HERE, "no-such-folder", "Arial Bold.ttf"), os.path.join(HERE, "no-such-folder", "arialbd.ttf")]
        cw.FONTS["arial-bold"] = nowhere
        work = tempfile.mkdtemp(prefix="contract-")
        try:
            with self.assertRaises(cw.FontNotFound) as e:
                cw.font_file("arial-bold")
            self.assertIn("this computer does not have it", str(e.exception))
            self.assertIn(nowhere[1], str(e.exception))
            r = cc.run_case(self.case("pieces-2"), work)
            about = cc.about_this_computer()
        finally:
            cw.FONTS["arial-bold"] = real
            shutil.rmtree(work, ignore_errors=True)
        self.assertIn("this computer does not have it", r["skipped"])
        self.assertEqual((r["right"], r["problems"]), (0, []))
        self.assertTrue(any(line.startswith("font arial-bold: NOT HERE") for line in about))

    def test_the_top_of_the_record_says_which_computer_and_which_reader(self):
        about = "\n".join(cc.about_this_computer())
        for word in ("computer: ", "Python ", "Pillow ", "reader: ", "font arial: ", "font arial-bold: ", "font times: ",
                     "font verdana: ", "the HEIC wall is written by: ", "decided by its pixels"):
            self.assertIn(word, about)

    def without(self, sips=True, heif=True):
        """This computer, made to look as if it had no sips, no pillow-heif, or neither."""
        real_which, real_heif = cc.shutil.which, sys.modules.get("pillow_heif", self)
        if sips:
            cc.shutil.which = lambda name, *a, **k: None if name == "sips" else real_which(name, *a, **k)
        if heif:
            sys.modules["pillow_heif"] = None      # an import of it now fails, as where it is not installed

        def put_back():
            cc.shutil.which = real_which
            if real_heif is self:
                sys.modules.pop("pillow_heif", None)
            else:
                sys.modules["pillow_heif"] = real_heif
        self.addCleanup(put_back)

    def test_a_heic_wall_that_cannot_be_written_is_skipped_not_missed(self):
        self.without(sips=True, heif=True)
        self.assertIsNone(cc.heic_writer())
        work = tempfile.mkdtemp(prefix="contract-")
        try:
            wall = Image.new("RGB", (400, 300), DARK["black"])
            ok, why = cc.write_heic(wall, os.path.join(work, "wall.heic"))
            self.assertFalse(cc.save(wall, os.path.join(work, "wall.heic"), "heic", None))
            self.assertEqual(os.listdir(work), [])
            real = sw.process_photo
            sw.process_photo = lambda *a, **k: self.fail("the tool was given a wall that was never written")
            try:
                r = cc.run_case(self.case("heic"), work)
            finally:
                sw.process_photo = real
        finally:
            shutil.rmtree(work, ignore_errors=True)
        self.assertFalse(ok)
        self.assertEqual(why, "a HEIC photo cannot be written here: this computer has no sips, and pillow-heif is not installed")
        self.assertEqual(r["skipped"], why)
        self.assertEqual((r["right"], r["problems"]), (0, []))
        self.assertIn("nothing here can write one", "\n".join(cc.about_this_computer()))

    @unittest.skipUnless(shutil.which("sips"), "needs the Mac's sips")
    def test_on_a_mac_the_heic_wall_is_written_by_sips(self):
        work = tempfile.mkdtemp(prefix="contract-")
        try:
            f = os.path.join(work, "wall.heic")
            self.assertEqual(cc.write_heic(Image.new("RGB", (400, 300), DARK["navy"]), f), (True, "sips"))
            self.assertEqual(os.listdir(work), ["wall.heic"])
            self.assertEqual(cc.heic_writer(), "sips")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_without_sips_the_heic_wall_is_written_by_pillow_heif(self):
        try:
            import pillow_heif  # noqa: F401
        except Exception:
            self.skipTest("pillow-heif is not installed on this computer")
        self.without(sips=True, heif=False)
        work = tempfile.mkdtemp(prefix="contract-")
        try:
            f = os.path.join(work, "wall.heic")
            self.assertEqual(cc.heic_writer(), "pillow-heif")
            self.assertEqual(cc.write_heic(Image.new("RGB", (400, 300), DARK["navy"]), f), (True, "pillow-heif"))
            with Image.open(f) as im:
                self.assertEqual(im.size, (400, 300))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def main_with(self, rows, argv=()):
        import contextlib, io
        real_case, real_ready = cc.run_case, sw.backend_ready
        todo = iter(rows)
        cc.run_case = lambda c, work: next(todo)
        sw.backend_ready = lambda: True
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = cc.main(list(argv))
        finally:
            cc.run_case, sw.backend_ready = real_case, real_ready
        return code, out.getvalue()

    def test_a_skipped_wall_is_printed_as_skipped_and_counts_as_neither(self):
        rows = [{"case": "heic", "pieces": 6, "right": 0, "problems": [], "skipped": "a HEIC photo cannot be written here"},
                {"case": "png", "pieces": 6, "right": 6, "problems": [], "info": {"pixels": "upright by 0.50 or more"}}]
        code, out = self.main_with(rows, ["heic", "png"])
        self.assertEqual(code, 0)
        self.assertIn("SKIP  heic", out)
        self.assertIn("not run: a HEIC photo cannot be written here", out)
        self.assertNotIn("MISS", out)
        self.assertEqual(out.count("PASS"), 1)
        self.assertIn("CONTRACT CHECK: 1 of 1 walls perfect, 6 of 6 pieces right (100.0%), 1 wall SKIPPED (heic: "
                      "could not be written on this computer)", out)

    def test_a_skipped_wall_does_not_hide_a_miss_and_nothing_run_is_not_a_pass(self):
        rows = [{"case": "heic", "pieces": 6, "right": 0, "problems": [], "skipped": "a HEIC photo cannot be written here"},
                {"case": "png", "pieces": 6, "right": 5, "problems": ["Maya Torres: filed turned"],
                 "info": {"reader": "read 5 of 6 labels upright"}, "said": ["wall.png: found 6 pieces"]}]
        code, out = self.main_with(rows, ["heic", "png"])
        self.assertEqual(code, 1)
        self.assertIn("MISS  png", out)
        self.assertIn("problem: Maya Torres: filed turned", out)
        self.assertIn("the tool said: wall.png: found 6 pieces", out)
        self.assertIn("reader: read 5 of 6 labels upright", out)
        self.assertIn("0 of 1 walls perfect, 5 of 6 pieces right", out)
        code, out = self.main_with(rows[:1], ["heic"])
        self.assertEqual(code, 1, "a check that ran no wall has proved nothing")
        self.assertIn("0 of 0 walls perfect", out)

    def test_a_letter_the_screen_cannot_show_does_not_stop_the_record(self):
        import io

        class Narrow(io.StringIO):
            encoding = "ascii"
        real, sys.stdout = sys.stdout, Narrow()
        try:
            cc.say("filed \u2192 upright")
            said = sys.stdout.getvalue()
        finally:
            sys.stdout = real
        self.assertEqual(said, "filed ? upright\n")

    def test_without_a_reader_the_check_says_so(self):
        import contextlib, io
        real = sw.backend_ready
        sw.backend_ready = lambda: False
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = cc.main([])
        finally:
            sw.backend_ready = real
        self.assertEqual(code, 2)
        self.assertIn("The reader is not available on this computer.", out.getvalue())


if __name__ == "__main__":
    unittest.main()

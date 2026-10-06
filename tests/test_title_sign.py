"""A title sign on the wall is left out; a child's paper never is.

The wall of October 1, 2026 had twenty children's papers and two title signs.
The signs went to "Unsorted - needs a person" every time. One of them had no
words the reader could read and both were on the children's own paper, so a
sign cannot be told from a child's work that has lost its name sticker. The
teacher says which paper is the sign: a typed sticker that reads TITLE.

  - a paper with the TITLE sticker is left out: not filed, not in Unsorted;
  - a paper with no name and no TITLE sticker still goes to Unsorted;
  - a paper with a child's name sticker is filed, TITLE or no TITLE on it.

Run:  python3 -m unittest tests.test_title_sign
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import baggage_claim as sw  # noqa: E402
from make_wall import make_wall  # noqa: E402

NAMES = ["Maya", "Jonah", "Sofia", "Elijah", "Priya", "Marcus", "Lily", "Theo"]


def T(text, **kw):
    return {"text": text, "conf": 1.0, "x": 0, "y": 0, "w": 10, "h": 10, **kw}


class TheStickerTests(unittest.TestCase):
    def test_the_sticker_is_the_one_word_in_capitals(self):
        self.assertTrue(sw.is_title_sign([T("TITLE")]))
        self.assertTrue(sw.is_title_sign([T("Self-Portraits"), T(" TITLE ")]))

    def test_a_speck_beside_the_sticker_does_not_count_against_it(self):
        self.assertTrue(sw.is_title_sign([T("TITLE .")]))
        self.assertTrue(sw.is_title_sign([T("I TITLE")]))

    def test_the_word_in_a_childs_writing_is_not_the_sticker(self):
        for line in ("Title", "Title:", "title", "THE TITLE OF MY STORY", "MY TITLE", "TITLES", "TILE", "LITTLE"):
            self.assertFalse(sw.is_title_sign([T(line)]), line)

    def test_no_words_at_all_is_not_a_sign(self):
        self.assertFalse(sw.is_title_sign([]))
        self.assertFalse(sw.is_title_sign([T("")]))


@unittest.skipUnless(sw.backend_ready(), "no name reader on this machine")
class OnAWallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inbox = os.path.join(self.tmp, "inbox")
        os.makedirs(self.inbox)
        self.log = []

    def sort(self, img, roster):
        img.save(os.path.join(self.inbox, "wall.jpg"), quality=90)
        return sw.run_inbox(self.inbox, roster, self.tmp, "art", log=lambda m: self.log.append(str(m)))

    def in_unsorted(self):
        d = os.path.join(self.tmp, "unsorted")
        return [n for n in os.listdir(d) if n.endswith(".jpg")] if os.path.isdir(d) else []

    def test_a_sign_with_the_sticker_is_left_out_and_every_child_is_filed(self):
        img, _ = make_wall(NAMES[:7] + ["TITLE"])
        res = self.sort(img, NAMES[:7])
        self.assertEqual(sorted(r["name"] for r in res if r["status"] == "confident"), sorted(NAMES[:7]), self.log)
        self.assertEqual(len(res), 7, self.log)
        self.assertEqual(self.in_unsorted(), [])
        self.assertTrue([m for m in self.log if "1 title sign left out" in m], self.log)
        self.assertTrue([m for m in self.log if "7 pieces, 7 filed, 0 to unsorted" in m] or
                        sw.batch_text(res) == "7 pieces, 7 filed, 0 to unsorted")

    def test_a_paper_with_no_name_and_no_sticker_still_goes_to_a_person(self):
        img, _ = make_wall(NAMES[:6] + ["TITLE", NAMES[7]], unnamed=(7,))
        res = self.sort(img, NAMES)
        self.assertEqual(len(res), 7, self.log)
        doubtful = [r for r in res if r["status"] != "confident"]
        self.assertEqual(len(doubtful), 1, self.log)
        self.assertEqual(len(self.in_unsorted()), 1)
        self.assertEqual(sorted(r["name"] for r in res if r["status"] == "confident"), sorted(NAMES[:6]))

    def test_without_the_sticker_a_sign_goes_to_a_person_as_before(self):
        img, _ = make_wall(NAMES[:7] + ["Our Self-Portraits"])
        res = self.sort(img, NAMES[:7])
        self.assertEqual(len(res), 8, self.log)
        self.assertEqual(len(self.in_unsorted()), 1)
        self.assertFalse([m for m in self.log if "title sign" in m], self.log)

    def test_a_childs_page_that_says_title_is_filed_under_the_child(self):
        """The name sticker decides. A paper that has a child's name read for
        certain is that child's, whatever else is written on it."""
        orig = sw.read_piece
        sw.read_piece = lambda tmp, crop: orig(tmp, crop) + [T("TITLE", rel_y=0.5)]
        self.addCleanup(setattr, sw, "read_piece", orig)
        img, _ = make_wall(NAMES)
        res = self.sort(img, NAMES)
        self.assertEqual(sorted(r["name"] for r in res if r["status"] == "confident"), sorted(NAMES), self.log)
        self.assertFalse([m for m in self.log if "title sign" in m], self.log)


if __name__ == "__main__":
    unittest.main()

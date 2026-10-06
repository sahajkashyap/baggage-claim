"""A name label in the MIDDLE of an art piece must still file.

On a real wall of artwork the teacher's typed label sat in the middle band of
six papers. Each was read exactly right, yet scored 0.75 (1.0 minus the
0.25 body discount meant for names inside a child's story) and went to
"Unsorted - needs a person". A bare roster name on its own short line is a
label wherever it sits; a name inside a sentence in the body of a page of
writing is still a character in the story.

Run:  python3 -m unittest tests.test_body_label
"""
import difflib
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import baggage_claim as sw  # noqa: E402

NAMES = ["Maya", "Jonah", "Sofia", "Elijah", "Priya", "Marcus", "Lily", "Theo"]
MIDDLE = 0.5   # rel_y in the body band, between EDGE_BAND and 1 - EDGE_BAND


def T(text, **kw):
    return {"text": text, "conf": 1.0, "x": 0, "y": 0, "w": 10, "h": 10, **kw}


class BodyLabelTests(unittest.TestCase):
    def test_middle_is_inside_the_body_band(self):
        self.assertTrue(sw.EDGE_BAND < MIDDLE < 1 - sw.EDGE_BAND)

    def test_1_standalone_exact_name_in_the_middle_is_confident(self):
        m = sw.match_name([T("Jonah", rel_y=MIDDLE)], NAMES)
        self.assertEqual((m["name"], m["status"]), ("Jonah", "confident"))
        self.assertGreaterEqual(m["score"], sw.CONFIDENT_SCORE)

    def test_1b_every_roster_name_alone_in_the_middle_files(self):
        for name in NAMES:
            m = sw.match_name([T(name, rel_y=MIDDLE)], NAMES)
            self.assertEqual((m["name"], m["status"]), (name, "confident"), name)

    def test_1c_label_with_a_stray_one_letter_mark_still_files(self):
        # the reader added a look-alike letter after a typed label
        m = sw.match_name([T("Marcus м", rel_y=MIDDLE)], NAMES)
        self.assertEqual((m["name"], m["status"]), ("Marcus", "confident"))

    def test_2_same_name_inside_a_six_word_sentence_is_not_confident(self):
        m = sw.match_name([T("Jonah went to the beach today", rel_y=MIDDLE)], NAMES)
        self.assertEqual(m["name"], "Jonah")
        self.assertNotEqual(m["status"], "confident")
        self.assertLess(m["score"], sw.CONFIDENT_SCORE)

    def test_2b_with_my_friend_case_keeps_the_full_penalty(self):
        m = sw.match_name([T("with my friend Jonah", rel_y=MIDDLE)], NAMES)
        self.assertEqual((m["name"], m["status"]), ("Jonah", "unsure"))
        m = sw.match_name([T("my friend Theo", rel_y=MIDDLE)], NAMES)
        self.assertEqual((m["name"], m["status"]), ("Theo", "unsure"))

    def test_2c_label_at_the_edge_still_beats_the_friend_in_the_story(self):
        texts = [T("Lily", rel_y=0.05), T("Theo", rel_y=MIDDLE), T("with my friend Theo", rel_y=0.6)]
        m = sw.match_name(texts, NAMES)
        self.assertEqual((m["name"], m["status"]), ("Lily", "confident"))
        self.assertGreaterEqual(m["margin"], sw.CONFIDENT_MARGIN)

    def test_3_two_children_share_the_first_name_is_not_confident(self):
        roster = ["Maya R.", "Maya T.", "Theo"]
        m = sw.match_name([T("Maya", rel_y=MIDDLE)], roster)
        self.assertEqual(m["status"], "unsure")
        self.assertEqual(m["margin"], 0.0)
        # the last initial written as part of the line breaks the tie
        m = sw.match_name([T("Maya T.", rel_y=MIDDLE)], roster)
        self.assertEqual((m["name"], m["status"]), ("Maya T.", "confident"))

    def test_4_fuzzy_read_in_the_middle_stays_unsure(self):
        ratio = difflib.SequenceMatcher(None, sw.norm("ELíjak"), "elijah").ratio()
        self.assertTrue(0.80 <= ratio <= 0.90, ratio)     # a shaky read, not a clean one
        m = sw.match_name([T("ELíjak", rel_y=MIDDLE)], NAMES)
        self.assertEqual((m["name"], m["status"]), ("Elijah", "unsure"))
        self.assertLess(m["score"], sw.CONFIDENT_SCORE)
        # the same shaky read at the edge, or with no position, is confident as before
        self.assertEqual(sw.match_name([T("ELíjak", rel_y=0.05)], NAMES)["status"], "confident")
        self.assertEqual(sw.match_name([T("ELíjak")], NAMES)["status"], "confident")

    def test_penalties_are_ordered(self):
        self.assertLess(sw.BODY_LABEL_PENALTY, sw.BODY_PENALTY)
        self.assertGreaterEqual(1.0 - sw.BODY_LABEL_PENALTY, sw.CONFIDENT_SCORE)


if __name__ == "__main__":
    unittest.main()

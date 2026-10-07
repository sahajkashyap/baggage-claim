"""The wall of October 1, 2026: twenty sheets of white paper on a blue board
under a band of cream wall, one photo, put in a project folder in Wall Inbox.
Two things went wrong and both are held here.

1. Google Drive had listed the photo but not delivered it. The first bytes
   could be read, the rest failed, and the photo was moved to 'failed'.
2. The colour detector found 5 blobs, the rectangle detector 22 sheets. The
   5 agreed with rectangles, colour won, and 15 children got nothing.

Invented names only.
"""
import errno
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import baggage_claim as bc  # noqa: E402
from PIL import Image  # noqa: E402


def box(x, y, w=700, h=1000, **more):
    return dict({"conf": 0.9, "tl": [x, y], "tr": [x + w, y], "br": [x + w, y + h], "bl": [x, y + h]}, **more)


class HalfDelivered:
    """A file that hands over its first megabyte and then fails, as Google
    Drive does with a photo it has listed but not finished delivering."""
    def __init__(self):
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        self.reads += 1
        if self.reads > 1:
            raise OSError(errno.EDEADLK, "Resource deadlock avoided")
        return b"x" * 16


class PhotoStillArriving(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.dir, True)
        self.photo = os.path.join(self.dir, "wall.jpeg")
        with open(self.photo, "wb") as f:
            f.write(b"x" * 5000)

    def test_a_photo_that_reads_to_its_end_is_settled(self):
        self.assertTrue(bc.is_settled(self.photo, wait=0))

    def test_a_photo_drive_has_not_finished_delivering_is_not_settled(self):
        bc.open = lambda path, mode="r": HalfDelivered()
        self.addCleanup(delattr, bc, "open")
        self.assertFalse(bc.is_settled(self.photo, wait=0))

    def test_it_stays_in_the_inbox_and_is_tried_again(self):
        inbox, out = os.path.join(self.dir, "inbox"), os.path.join(self.dir, "out")
        os.makedirs(inbox)
        Image.new("RGB", (64, 64), (20, 20, 20)).save(os.path.join(inbox, "wall.jpg"))
        saved = bc.is_settled
        bc.is_settled = lambda p, wait=2.0: False
        self.addCleanup(setattr, bc, "is_settled", saved)
        said = []
        bc.run_inbox(inbox, ["Maya Torres"], out, "Writing", log=said.append)
        self.assertTrue(os.path.exists(os.path.join(inbox, "wall.jpg")))
        self.assertFalse(os.path.exists(os.path.join(inbox, bc.FAILED_FOLDER)))
        self.assertTrue(any("still arriving" in str(s) for s in said))


class ColourMustAccountForTheSheets(unittest.TestCase):
    """detect_pieces with the three detectors' answers put in by hand."""
    def setUp(self):
        self.saved = (bc.run_vision, bc.fallback_boxes, bc.color_boxes, bc.drop_junk)
        self.addCleanup(self.restore)
        bc.fallback_boxes = lambda img: []
        bc.drop_junk = lambda img, quads, *a, **k: quads
        self.img = Image.new("RGB", (8000, 6000), (110, 160, 205))
        self.sheets = [box(200 + 900 * c, 300 + 1300 * r) for r in range(3) for c in range(8)][:22]

    def restore(self):
        bc.run_vision, bc.fallback_boxes, bc.color_boxes, bc.drop_junk = self.saved

    def test_five_blobs_do_not_outvote_twenty_two_rectangles(self):
        bc.run_vision = lambda mode, path, *extra: [dict(q) for q in self.sheets]
        bc.color_boxes = lambda img: [dict(q, conf=0.5, fill=0.95) for q in self.sheets[:5]]
        found = bc.detect_pieces(self.img, "wall.jpg")
        self.assertEqual(len(found), 22)
        self.assertEqual(bc.LAST_DETECTOR, "rectangles")

    def test_coloured_paper_the_rectangles_agree_with_is_still_read_by_colour(self):
        bc.run_vision = lambda mode, path, *extra: [dict(q) for q in self.sheets[:8]]
        bc.color_boxes = lambda img: [dict(q, conf=0.5, fill=0.95) for q in self.sheets[:8]]
        found = bc.detect_pieces(self.img, "wall.jpg")
        self.assertEqual(len(found), 8)
        self.assertEqual(bc.LAST_DETECTOR, "colour")

    def test_colour_can_be_switched_off(self):
        bc.run_vision = lambda mode, path, *extra: [dict(q) for q in self.sheets[:8]]
        bc.color_boxes = lambda img: [dict(q, conf=0.5, fill=0.95) for q in self.sheets[:8]]
        bc.detect_pieces(self.img, "wall.jpg", allow_colour=False)
        self.assertEqual(bc.LAST_DETECTOR, "rectangles")


class LabelsAreTheSecondOpinion(unittest.TestCase):
    def test_counts_each_child_once(self):
        roster = ["Maya Torres", "Jonah Reyes", "Sofia Lund"]
        def line(text, x):
            return {"text": text, "x": x, "y": 10, "w": 80, "h": 20, "angle": 0}
        texts = [line("Maya Torres", 0), line("Maya Torres", 900), line("Jonah Reyes", 1800),
                 line("I hope to get better at writing this year", 2700)]
        self.assertEqual(bc.labelled_children(texts, roster), 2)


class TheWatcherKeepsItsComputerAwake(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin", "the Mac way of asking")
    def test_caffeinate_is_tied_to_the_watcher(self):
        asked = []
        got = bc.keep_awake(popen=lambda cmd, **k: asked.append(cmd) or "started", pid=4321)
        self.assertEqual(got, "started")
        self.assertEqual(asked, [["/usr/bin/caffeinate", "-i", "-w", "4321"]])

    @unittest.skipUnless(sys.platform == "darwin", "the Mac way of asking")
    def test_a_computer_that_cannot_be_asked_does_not_stop_the_watcher(self):
        def broken(cmd, **k):
            raise OSError("no caffeinate here")
        self.assertIsNone(bc.keep_awake(popen=broken, pid=1))


class TheWatcherMayFetchWhatDriveHasNotDownloaded(unittest.TestCase):
    """October 2, 2026: a photo listed by Drive but not downloaded stayed
    "still arriving" for ten minutes, until a person opened it."""
    @unittest.skipUnless(sys.platform == "darwin", "a macOS rule")
    def test_it_asks_macos_for_the_right_to_fetch(self):
        class Libc:
            def __init__(self):
                self.asked = []

            def setiopolicy_np(self, kind, scope, policy):
                self.asked.append((kind, scope, policy)); return 0

            def getiopolicy_np(self, kind, scope):
                return 2
        libc = Libc()
        self.assertEqual(bc.fetch_cloud_files(libc), 2)
        self.assertEqual(libc.asked, [(3, 0, 2)])

    @unittest.skipUnless(sys.platform == "darwin", "a macOS rule")
    def test_on_this_mac_the_policy_really_is_on_afterwards(self):
        self.assertEqual(bc.fetch_cloud_files(), 2)

    @unittest.skipUnless(sys.platform == "darwin", "a macOS rule")
    def test_a_mac_that_refuses_does_not_stop_the_watcher(self):
        class Broken:
            def setiopolicy_np(self, *a):
                raise OSError("no such call")
        self.assertIsNone(bc.fetch_cloud_files(Broken()))


class AnInboxMayBeRenamed(unittest.TestCase):
    """October 5, 2026: a class renamed its Wall Inbox to "Arrivals"."""
    def test_the_renamed_inbox_is_not_a_child(self):
        # "Arrivals" is every class's inbox since October 5, 2026; any other name a class picks is
        # told to the check by the class's settings
        self.assertFalse(bc.is_child_folder("Arrivals"))
        self.assertFalse(bc.is_child_folder("Wall Inbox"))
        self.assertTrue(bc.is_child_folder("Gate 12"))
        self.assertFalse(bc.is_child_folder("Gate 12", {"Gate 12"}))

    def test_own_folders_are_read_from_the_settings(self):
        class A:
            inbox = "/Drive/Rock Walkers/Arrivals/"
            unsorted_dir = "/Drive/Rock Walkers/Needs a person"
        self.assertEqual(bc.own_folders(A()), {"Arrivals", "Needs a person"})

    def test_no_document_is_made_for_the_inbox(self):
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        for f in ("Arrivals/Writing", "Maya Torres/Writing"):
            os.makedirs(os.path.join(d, f))
            Image.new("RGB", (40, 50), (200, 200, 200)).save(os.path.join(d, f, "piece.jpg"))
        made = bc.build_all_docx(d, d, {"Arrivals"})
        self.assertEqual([os.path.basename(os.path.dirname(m)) for m in made], ["Maya Torres"])


class ALastNameFirstClassList(unittest.TestCase):
    """October 6, 2026: a class whose files are named "Doe, Jane"."""
    def test_the_paper_may_say_the_first_name_or_first_and_last(self):
        forms = bc.roster_forms("Doe, Jane")
        for f in ("jane", "jane doe", "doe jane", "doe"):
            self.assertIn(f, forms)

    def test_a_label_with_the_first_name_finds_the_child(self):
        roster = ["Doe, Jane", "Ray, Wren", "Okafor, Bea"]
        line = {"text": "Jane", "conf": 1.0, "x": 900, "y": 1200, "w": 120, "h": 40, "angle": 0}
        m = bc.match_name([line], roster)
        self.assertEqual(m["name"], "Doe, Jane")

    def test_a_list_without_commas_is_read_as_before(self):
        self.assertEqual(bc.roster_forms("Maya Torres"), {"maya torres", "maya"})


if __name__ == "__main__":
    unittest.main()

"""Regression tests for repaired defects.

Repair 1: a classroom computer running a build from before status files
existed sorts every photo and never says so, so a second computer running
this version filed every piece a second time. Two changes: a photo is now
claimed (moved to done) BEFORE it is cut, so a computer that loses the race
saves nothing; and a computer that notices a silent sorter (a photo taken by
nobody it knows, or a copy of a piece arriving in a folder it just filed
into) stands by for OLD_VERSION_STANDBY_SECONDS and says why, in plain words.

Repair 2: a laptop waking from sleep sorted photos the other computer had
already filed, from its own stale copy of the class folder, before Google
Drive had reconnected. The grace period was keyed to the process start only.
Now a gap of more than WAKE_GAP_SECONDS between two looks at the inbox counts
as a wake-up: the grace period starts again, the log says so, and nothing is
sorted until it has passed.

Repair 3: the JPEG made from an iPhone HEIC photo was written next to the
photo, inside the Drive-synced Wall Inbox, so for the seconds a photo took to
sort, Drive uploaded it everywhere and the inbox listed it as a second wall
photo; a watcher stopped mid-photo left it behind for good. It now goes into
the tool's own scratch folder (out_dir/.tmp).

Repair (class list): the class list was read once, when the watcher started,
and the same list was used for every photo until somebody restarted the
watcher. A child added to the class list in October was unknown to a watcher
started in September, so that child's work went to Unsorted or to a classmate
with a similar name. The watch loop now reads the file again whenever its size
or time of last change is different (refresh_roster) and says so once.

Everything runs against temporary folders and invented names (Maya Torres).
No real photo is opened; process_photo and run_inbox are replaced by fakes,
and the only image is a synthetic wall from make_wall.py.
Run:  python3 -m unittest tests.test_repairs
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import baggage_claim as bc  # noqa: E402

sys.path.insert(0, HERE)
from test_baggage_claim import assert_safe_outside_the_contract  # noqa: E402

NOW = 1_800_000_000.0
LONG_AGO = NOW - 3600
MAC = {"machine": "Helpers-MacBook", "priority": 90}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class ClaimBeforeCutTests(unittest.TestCase):
    """The photo is moved to done first and cut from there."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inbox = os.path.join(self.tmp, "Wall Inbox")
        os.makedirs(self.inbox)
        self.cls = os.path.join(self.tmp, "Class")
        os.makedirs(self.cls)
        self.photo = os.path.join(self.inbox, "wall.jpg")
        with open(self.photo, "wb") as f:
            f.write(b"\xff\xd8 not really a jpeg")
        self.log = []
        self.saved = (bc.is_settled, bc.process_photo)
        bc.is_settled = lambda p, wait=0: True

    def tearDown(self):
        bc.is_settled, bc.process_photo = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def result(self, n=1):
        return [{"piece": i, "status": "confident", "name": "Maya Torres", "text": "Maya", "score": 1.0,
                 "margin": 1.0, "box": None, "file": "x", "bbox": (0, 0, 1, 1)} for i in range(1, n + 1)]

    def test_photo_is_in_done_and_gone_from_the_inbox_before_cutting_starts(self):
        seen = {}

        def cut(path, *a, **k):
            seen["path"] = path
            seen["inbox_still_has_it"] = os.path.exists(self.photo)
            seen["done_has_it"] = os.path.isfile(path)
            return self.result(2)
        bc.process_photo = cut
        res = bc.run_inbox(self.inbox, ["Maya Torres"], self.tmp, "Leaves", log=self.log.append, sorted_dir=self.cls)
        self.assertEqual(len(res), 2)
        self.assertEqual(seen["path"], os.path.join(self.inbox, "done", "wall.jpg"))
        self.assertFalse(seen["inbox_still_has_it"])
        self.assertTrue(seen["done_has_it"])
        self.assertEqual(os.listdir(os.path.join(self.inbox, "done")), ["wall.jpg"])

    def test_project_folder_photo_is_claimed_into_its_own_done_folder(self):
        proj = os.path.join(self.inbox, "Fall Leaves")
        os.makedirs(proj)
        os.rename(self.photo, os.path.join(proj, "b.jpg"))
        paths = []
        bc.process_photo = lambda path, *a, **k: paths.append(path) or self.result(1)
        bc.run_inbox(self.inbox, ["Maya Torres"], self.tmp, "Art", log=self.log.append, sorted_dir=self.cls)
        self.assertEqual(paths, [os.path.join(self.inbox, "done", "Fall Leaves", "b.jpg")])

    def test_losing_the_race_cuts_nothing_and_reports_the_photo_as_taken(self):
        calls = []
        bc.process_photo = lambda *a, **k: calls.append(1) or self.result(3)
        real_move = bc.shutil.move

        def other_computer_moved_it_first(src, dst):
            os.remove(src)
            return real_move(src, dst)
        bc.shutil.move = other_computer_moved_it_first
        try:
            taken = []
            res = bc.run_inbox(self.inbox, ["Maya Torres"], self.tmp, "Leaves", log=self.log.append,
                               sorted_dir=self.cls, taken=taken)
        finally:
            bc.shutil.move = real_move
        self.assertEqual((res, calls, taken), ([], [], ["wall.jpg"]))
        self.assertTrue(any("nothing filed twice" in m for m in self.log), self.log)

    def test_photo_gone_before_the_claim_is_reported_as_taken(self):
        os.remove(self.photo)
        saved = bc.inbox_jobs
        bc.inbox_jobs = lambda inbox, project: [(self.photo, project, os.path.join(inbox, "done"))]
        bc.process_photo = lambda *a, **k: self.fail("must not cut a photo that is gone")
        try:
            taken = []
            res = bc.run_inbox(self.inbox, ["Maya Torres"], self.tmp, "Leaves", log=self.log.append,
                               sorted_dir=self.cls, taken=taken)
        finally:
            bc.inbox_jobs = saved
        self.assertEqual((res, taken), ([], ["wall.jpg"]))

    def test_a_photo_that_cannot_be_read_goes_from_done_to_failed(self):
        def bad(path, *a, **k):
            raise ValueError("not an image")
        bc.process_photo = bad
        res = bc.run_inbox(self.inbox, ["Maya Torres"], self.tmp, "Leaves", log=self.log.append, sorted_dir=self.cls)
        self.assertEqual(res, [])
        self.assertEqual(os.listdir(os.path.join(self.inbox, "done")), [])
        self.assertEqual(os.listdir(os.path.join(self.inbox, "failed")), ["wall.jpg"])
        self.assertTrue(any("moved to inbox/failed" in m for m in self.log), self.log)

    def test_taken_list_is_optional(self):
        bc.process_photo = lambda *a, **k: self.result(1)
        self.assertEqual(len(bc.run_inbox(self.inbox, ["Maya Torres"], self.tmp, "Leaves", log=self.log.append,
                                          sorted_dir=self.cls)), 1)


class SilentSorterTests(unittest.TestCase):
    """A computer sorting without a status file is stood in for by a phantom
    with the lowest priority, fresh for eight hours."""

    def test_phantom_makes_a_lone_computer_stand_by_for_eight_hours(self):
        ghost = bc.silent_sorter(NOW)
        d = bc.decide_role([ghost], MAC, NOW + 60, started=LONG_AGO)
        self.assertEqual(d["role"], "standing by")
        self.assertEqual(d["reason"], "standing by, a computer running an older version of Baggage Claim is the control tower for this class")
        self.assertEqual(bc.decide_role([ghost], MAC, NOW + bc.OLD_VERSION_STANDBY_SECONDS - 1, started=LONG_AGO)["role"], "standing by")
        self.assertEqual(bc.decide_role([ghost], MAC, NOW + bc.OLD_VERSION_STANDBY_SECONDS, started=LONG_AGO)["role"], "watching")
        self.assertEqual(bc.OLD_VERSION_STANDBY_SECONDS, 8 * 3600)

    def test_phantom_outranks_every_real_priority_and_a_plain_file_still_goes_stale_at_five_minutes(self):
        self.assertTrue(bc.is_fresh(bc.silent_sorter(NOW), NOW + 3600))
        self.assertFalse(bc.is_fresh({"machine": "PC", "priority": 0, "epoch": int(NOW)}, NOW + 3600))
        self.assertEqual(bc.choose_leader([bc.silent_sorter(NOW)], {"machine": "PC", "priority": 0}, NOW), bc.OLD_VERSION_NAME)

    def test_others_fresh(self):
        pc = {"machine": "CLASSROOM-PC", "priority": 50, "epoch": int(NOW)}
        self.assertTrue(bc.others_fresh([pc], MAC, NOW + 10))
        self.assertFalse(bc.others_fresh([pc], MAC, NOW + bc.STALE_SECONDS + 1))
        self.assertFalse(bc.others_fresh([{**pc, "machine": MAC["machine"]}], MAC, NOW))
        self.assertFalse(bc.others_fresh([], MAC, NOW))

    def test_status_file_text_names_the_older_version_in_plain_words(self):
        text = bc.format_status("Helpers-MacBook", NOW, "standing by", 90, leader=bc.OLD_VERSION_NAME)
        self.assertIn("standing by; a computer running an older version of Baggage Claim is the control tower for this class", text)

    def test_warning_is_plain_english_and_says_what_to_do(self):
        w = bc.old_version_warning("wall.jpg was taken from the inbox by another computer")
        for phrase in ("wall.jpg was taken", "no other computer has written a status file", "older version of Baggage Claim",
                       "the same piece twice", "standing by for the next 8 hours", "install this version on the other computer",
                       "restart its control tower"):
            self.assertIn(phrase, w)


class ArrivalTests(unittest.TestCase):
    """A copy arriving in a folder this computer just filed into."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.folder = os.path.join(self.tmp, "Class", "Maya Torres", "Self-Portrait")
        os.makedirs(self.folder)
        self.mine = os.path.join(self.folder, "Self-Portrait Kindergarten.jpg")
        open(self.mine, "w").close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_files_in_lists_images_only_and_survives_a_missing_folder(self):
        open(os.path.join(self.folder, "notes.txt"), "w").close()
        open(os.path.join(self.folder, ".hidden.jpg"), "w").close()
        self.assertEqual(bc.files_in(self.folder), {"Self-Portrait Kindergarten.jpg"})
        self.assertEqual(bc.files_in(os.path.join(self.tmp, "nowhere")), set())

    def test_note_saved_snapshots_the_folder_using_absolute_or_relative_paths(self):
        recent = {}
        bc.note_saved(recent, [{"file": self.mine}, {"status": "unsure"}], self.tmp, NOW)
        self.assertEqual(recent, {self.folder: (NOW, {"Self-Portrait Kindergarten.jpg"})})
        recent = {}
        bc.note_saved(recent, [{"file": os.path.relpath(self.mine, self.tmp)}], self.tmp, NOW)
        self.assertIn(self.folder, recent)

    def test_own_files_are_not_arrivals_but_a_drive_copy_is(self):
        recent = {}
        bc.note_saved(recent, [{"file": self.mine}], self.tmp, NOW)
        self.assertEqual(bc.new_arrivals(recent, NOW + 5), [])
        open(os.path.join(self.folder, "Self-Portrait Kindergarten (1).jpg"), "w").close()
        self.assertEqual(bc.new_arrivals(recent, NOW + 10), [(self.folder, ["Self-Portrait Kindergarten (1).jpg"])])
        self.assertEqual(recent, {})                         # said once
        bc.note_saved(recent, [{"file": self.mine}], self.tmp, NOW)
        open(os.path.join(self.folder, "Self-Portrait Kindergarten 2.jpg"), "w").close()
        self.assertEqual(bc.new_arrivals(recent, NOW + bc.RECENT_SECONDS + 1), [])   # too old to judge
        self.assertEqual(recent, {})


class WatchLoopRepairTests(unittest.TestCase):
    """The --watch loop notices a silent sorter and stands by, in the log and in
    its status file; a real status file from that computer clears the alarm."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Class")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.roster = os.path.join(self.cls, "Class list.txt")
        with open(self.roster, "w") as f:
            f.write("Maya Torres\n")
        self.settings = os.path.join(self.tmp, "settings.json")
        with open(self.settings, "w") as f:
            json.dump({"inbox": self.inbox, "sorted": self.cls, "unsorted": os.path.join(self.cls, "Unsorted - needs a person"),
                       "roster": self.roster, "project": "Self-Portrait", "grade": "Kindergarten", "interval": 1,
                       "priority": 90}, f)
        self.piece_dir = os.path.join(self.cls, "Maya Torres", "Self-Portrait")
        self.saved = (bc.time.sleep, bc.run_inbox, bc.GRACE_SECONDS)
        bc.GRACE_SECONDS = 0
        self.ticks = []
        self.calls = []

    def tearDown(self):
        bc.time.sleep, bc.run_inbox, bc.GRACE_SECONDS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_main(self, on_sleep, stop_after):
        def fake_sleep(s):
            self.ticks.append(s)
            on_sleep(len(self.ticks))
            if len(self.ticks) >= stop_after:
                raise KeyboardInterrupt
        bc.time.sleep = fake_sleep
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                bc.main(["--watch", "--settings", self.settings, "--out", self.tmp])
        return buf.getvalue()

    def status_text(self):
        return read(os.path.join(self.cls, "Watcher status", bc.machine_name() + ".txt"))

    def test_a_copy_arriving_in_a_folder_just_filed_into_puts_this_computer_on_standby(self):
        mine = os.path.join(self.piece_dir, "Self-Portrait Kindergarten.jpg")

        def fake_run_inbox(*a, **k):
            self.calls.append(1)
            if len(self.calls) == 1:
                os.makedirs(self.piece_dir, exist_ok=True)
                open(mine, "w").close()
                return [{"status": "confident", "file": mine}]
            return []
        bc.run_inbox = fake_run_inbox

        def on_sleep(n):
            if n == 1:      # the other computer's copy of the same piece syncs in
                open(os.path.join(self.piece_dir, "Self-Portrait Kindergarten (1).jpg"), "w").close()
        out = self.run_main(on_sleep, stop_after=3)
        self.assertEqual(len(self.calls), 2)      # tick 1 sorted, tick 2 noticed, tick 3 stood by
        self.assertIn("'Self-Portrait Kindergarten (1).jpg' appeared in a folder this computer had just filed into", out)
        self.assertIn("older version of Baggage Claim", out)
        self.assertIn("standing by, a computer running an older version of Baggage Claim is the control tower for this class", out)
        self.assertNotIn("Maya Torres", out.split("appeared in a folder")[1].split("\n")[0])   # no child's name in that line
        self.assertIn("standing by; a computer running an older version of Baggage Claim is the control tower for this class",
                      self.status_text())

    def test_a_photo_taken_by_an_unknown_computer_puts_this_computer_on_standby(self):
        def fake_run_inbox(*a, **k):
            self.calls.append(1)
            k["taken"].append("wall.jpg")
            return []
        bc.run_inbox = fake_run_inbox
        out = self.run_main(lambda n: None, stop_after=2)
        self.assertEqual(len(self.calls), 1)
        self.assertIn("wall.jpg was taken from the inbox by another computer, and no other computer has written a status file", out)
        self.assertIn("standing by, a computer running an older version of Baggage Claim", out)

    def test_a_real_status_file_from_the_other_computer_clears_the_alarm(self):
        def fake_run_inbox(*a, **k):
            self.calls.append(1)
            if len(self.calls) == 1:
                k["taken"].append("wall.jpg")
            return []
        bc.run_inbox = fake_run_inbox

        def on_sleep(n):
            if n == 1:      # the other computer turns out to run this version after all
                bc.write_status(bc.status_dir(self.cls), "CLASSROOM-PC", bc.time.time(), "watching", 50)
        out = self.run_main(on_sleep, stop_after=2)
        self.assertIn("older version of Baggage Claim, which does not know", out)
        self.assertIn("standing by, CLASSROOM-PC is the control tower for this class", out)
        self.assertNotIn("standing by, a computer running an older version", out)

    def test_a_known_computer_taking_a_photo_is_not_an_alarm(self):
        bc.write_status(bc.status_dir(self.cls), "CLASSROOM-PC", bc.time.time(), "watching", 95)   # it stands by to us

        def fake_run_inbox(*a, **k):
            self.calls.append(1)
            k["taken"].append("wall.jpg")
            return []
        bc.run_inbox = fake_run_inbox
        out = self.run_main(lambda n: None, stop_after=2)
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn("older version", out)


class WakeFromSleepTests(unittest.TestCase):
    """Repair 2: a computer waking from sleep must not sort from its stale view
    of the class folder. The clock is faked so a "sleep" is a jump of hours
    between two ticks of the watch loop; nothing really waits."""

    HOURS_ASLEEP = 3

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Class")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.roster = os.path.join(self.cls, "Class list.txt")
        with open(self.roster, "w") as f:
            f.write("Maya Torres\n")
        self.settings = os.path.join(self.tmp, "settings.json")
        with open(self.settings, "w") as f:
            json.dump({"inbox": self.inbox, "sorted": self.cls, "unsorted": os.path.join(self.cls, "Unsorted - needs a person"),
                       "roster": self.roster, "project": "Self-Portrait", "grade": "Kindergarten", "interval": 5,
                       "priority": 90}, f)
        self.saved = (bc.time.time, bc.time.sleep, bc.run_inbox)
        real_time = self.saved[0]
        self.offset = 0.0                       # seconds the fake clock is ahead of the real one
        bc.time.time = lambda: real_time() + self.offset
        self.ticks = []
        self.calls = []
        self.status_at = {}

    def tearDown(self):
        bc.time.time, bc.time.sleep, bc.run_inbox = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_main(self, advance, stop_after):
        """advance: {tick: seconds the clock jumps during that sleep}; other
        sleeps advance the clock by the seconds asked for."""
        def fake_sleep(s):
            self.ticks.append(s)
            n = len(self.ticks)
            self.status_at[n] = self.status_text()
            self.offset += advance.get(n, s)
            if n >= stop_after:
                raise KeyboardInterrupt
        bc.time.sleep = fake_sleep
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                bc.main(["--watch", "--settings", self.settings, "--out", self.tmp])
        return buf.getvalue()

    def status_text(self):
        try:
            return read(os.path.join(self.cls, "Watcher status", bc.machine_name() + ".txt"))
        except OSError:
            return ""

    def test_slept_since_is_zero_for_a_normal_tick_and_the_gap_after_a_sleep(self):
        self.assertEqual(bc.slept_since(None, NOW), 0)                       # before the first look
        self.assertEqual(bc.slept_since(NOW - 5, NOW), 0)                    # an ordinary five-second tick
        self.assertEqual(bc.slept_since(NOW - bc.WAKE_GAP_SECONDS, NOW), 0)  # right at the edge: not a sleep
        self.assertEqual(bc.slept_since(NOW - 3 * 3600, NOW), 3 * 3600)      # the lid was closed for three hours

    def test_the_reported_repro_is_what_the_pure_decision_says_and_the_loop_no_longer_trusts_it(self):
        # The report: an 8-hour-old status file from the PC, a Mac started days ago.
        # decide_role alone says "watching"; that is correct for a computer that has
        # really been awake all that time. The loop is what must notice the sleep.
        pc = {"machine": "CLASSROOM-PC", "priority": 50, "epoch": int(NOW - 8 * 3600), "role": "watching"}
        me = {"machine": "Helpers-MacBook", "priority": 50}
        self.assertEqual(bc.decide_role([pc], me, NOW, NOW - 3 * 86400)["role"], "watching")
        # With the grace period restarted at the moment of waking, it stands by.
        d = bc.decide_role([pc], me, NOW, NOW)
        self.assertEqual(d["role"], "starting")

    def test_a_computer_waking_from_sleep_stands_by_while_drive_catches_up(self):
        # Before the sleep the classroom PC is watching and its status file is fresh.
        bc.write_status(bc.status_dir(self.cls), "CLASSROOM-PC", bc.time.time(), "watching", 50)

        def fake_run_inbox(*a, **k):
            self.calls.append(len(self.ticks) + 1)     # which tick sorted
            return []
        bc.run_inbox = fake_run_inbox
        grace = bc.GRACE_SECONDS
        # tick 1: just started. tick 2: PC fresh, standing by. Then the lid closes for hours.
        # tick 3: awake; the PC's file still carries its pre-sleep time, so it LOOKS off.
        # tick 4: five seconds later, still in the new grace period.
        # tick 5: grace over and the PC still not heard from: now, and only now, sort.
        out = self.run_main({1: grace + 10, 2: self.HOURS_ASLEEP * 3600, 4: grace + 10}, stop_after=5)
        self.assertEqual(self.calls, [5], f"sorted on ticks {self.calls}; log:\n{out}")
        self.assertIn(f"this computer was asleep for {self.HOURS_ASLEEP * 60} minutes; standing by for {int(grace)} seconds "
                      "while Google Drive catches up, then checking who should sort", out)
        before, after = out.split("was asleep for")
        self.assertIn("standing by, CLASSROOM-PC is the control tower for this class", before)
        self.assertNotIn("this computer is the control tower for this class", before)
        self.assertIn("this computer is the control tower for this class", after)
        self.assertEqual(out.count("just started"), 1)          # the wake-up line replaces a second "just started"
        self.assertIn("just started; standing by for a moment", self.status_at[3])   # the status file says so at once
        self.assertIn("Role: the control tower", self.status_at[5])

    def test_a_long_batch_is_not_mistaken_for_a_sleep(self):
        def fake_run_inbox(*a, **k):
            self.calls.append(len(self.ticks) + 1)
            self.offset += 3 * 60                       # cutting a big wall takes three minutes
            return []
        bc.run_inbox = fake_run_inbox
        out = self.run_main({1: bc.GRACE_SECONDS + 10}, stop_after=4)
        self.assertEqual(self.calls, [2, 3, 4], out)
        self.assertNotIn("asleep", out)


if __name__ == "__main__":
    unittest.main()


class HeicTempFileTests(unittest.TestCase):
    """Repair 3: the JPEG made from an iPhone HEIC photo used to be written
    right next to the photo, inside the Drive-synced Wall Inbox, and removed
    only when the photo was finished. For those seconds Google Drive uploaded
    it to every other computer, and inbox_jobs listed it as a second wall
    photo; a watcher stopped mid-photo left it behind for good. The JPEG now
    goes into the tool's own scratch folder (out_dir/.tmp, or the computer's
    temp folder), never beside the photo."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inbox = os.path.join(self.tmp, "Wall Inbox")
        os.makedirs(self.inbox)
        self.out = os.path.join(self.tmp, "Class")
        os.makedirs(self.out)
        sys.path.insert(0, HERE)
        from make_wall import make_wall
        img, _ = make_wall(["Maya Torres", "Priya Nair"], rows=1, cols=2, size=(800, 400))
        self.size = img.size
        self.heic = os.path.join(self.inbox, "IMG_0001.HEIC")
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
            img.save(self.heic, quality=90)
        except ImportError:
            if not bc.IS_MAC:
                self.skipTest("HEIC test image needs pillow-heif or macOS sips")
            jpg = os.path.join(self.tmp, "wall.jpg")
            img.save(jpg, quality=90)
            r = bc.subprocess.run(["sips", "-s", "format", "heic", jpg, "--out", self.heic], capture_output=True)
            if r.returncode != 0 or not os.path.exists(self.heic):
                self.skipTest("sips cannot write HEIC on this Mac")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_converted_jpeg_goes_into_the_scratch_folder_and_the_inbox_lists_one_photo(self):
        scratch = os.path.join(self.out, ".tmp")
        os.makedirs(scratch)
        img, path, tmp = bc.open_photo(self.heic, scratch)
        self.assertEqual(os.listdir(self.inbox), ["IMG_0001.HEIC"], "nothing may be written into the inbox")
        self.assertEqual([os.path.basename(j[0]) for j in bc.inbox_jobs(self.inbox, "Art")], ["IMG_0001.HEIC"])
        self.assertEqual(os.path.dirname(tmp), scratch)
        self.assertEqual(path, tmp)
        self.assertTrue(os.path.exists(tmp))
        self.assertEqual(img.size, self.size)

    def test_without_a_scratch_folder_the_jpeg_still_stays_out_of_the_inbox(self):
        img, path, tmp = bc.open_photo(self.heic)
        try:
            self.assertEqual(os.listdir(self.inbox), ["IMG_0001.HEIC"])
            self.assertNotEqual(os.path.dirname(tmp), self.inbox)
            self.assertEqual(img.size, self.size)
        finally:
            os.remove(tmp)

    def test_process_photo_leaves_no_temp_file_anywhere(self):
        """Whole run with the readers and detectors faked: the HEIC is the only
        file left in the inbox, and the scratch folder is gone with the JPEG."""
        saved = (bc.read_photo_text, bc.detect_pieces, bc.pieces_from_labels)
        bc.read_photo_text = lambda img, path, tmpdir, **k: []
        bc.detect_pieces = lambda img, path: []
        bc.pieces_from_labels = lambda *a, **k: None
        try:
            results = bc.process_photo(self.heic, ["Maya Torres", "Priya Nair"], self.out, "Art", log=lambda *a: None)
        finally:
            bc.read_photo_text, bc.detect_pieces, bc.pieces_from_labels = saved
        self.assertEqual(results, [])
        self.assertEqual(os.listdir(self.inbox), ["IMG_0001.HEIC"])
        self.assertFalse(os.path.exists(os.path.join(self.out, ".tmp")))
        leftovers = [f for top in (self.inbox, self.out) for _, _, fs in os.walk(top) for f in fs
                     if f.lower().endswith(".jpg")]
        self.assertEqual(leftovers, [])


class StoppedMidPhotoTests(unittest.TestCase):
    """Repair: a watcher stopped partway through a photo (Stop Watcher, a
    restart after a crash, taskkill on Windows, a power cut) used to find the
    photo still in the inbox when it came back, sort it again, and give every
    child on that wall a second copy ('... 2.jpg'), without a word to anyone.

    Two halves. The photo is claimed (moved to done) before it is cut, so the
    restart has nothing to sort twice. And a marker in the tool's own output
    folder, written before the claim and removed when the photo is finished,
    lets the next start SAY the photo was not finished: one line in the log
    and a plain-English note in the doubtful-pieces folder.

    "The process dies" is a KeyboardInterrupt raised from inside the work: it
    is not an Exception, so nothing in run_inbox catches it or tidies up after
    it, which is what being killed looks like from the files' point of view."""

    ROSTER = ["Maya Torres", "Priya Nair", "Jonah Reed", "Sofia Marsh"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Drive", "Room 3")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.unsorted = os.path.join(self.cls, "Unsorted - needs a person")
        self.out = os.path.join(self.tmp, "tool")
        os.makedirs(self.out)
        self.photo = os.path.join(self.inbox, "wall.jpg")
        with open(self.photo, "wb") as f:
            f.write(b"\xff\xd8 a wall photo, as far as these tests care")
        self.log = []
        self.cuts = []
        self.saved = (bc.is_settled, bc.process_photo, bc.write_report, bc.shutil.move, bc.machine_name,
                      bc.time.sleep, bc.run_inbox)
        bc.is_settled = lambda p, wait=0: True

    def tearDown(self):
        (bc.is_settled, bc.process_photo, bc.write_report, bc.shutil.move, bc.machine_name,
         bc.time.sleep, bc.run_inbox) = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ---------------------------------------------------------
    def filing(self, die_after=None):
        """A stand-in for process_photo that files one piece per child with the
        tool's own naming rule, and dies after `die_after` pieces."""
        def cut(path, roster, out_dir, project, grid=None, log=print, grade="", sorted_dir=None, unsorted_dir=None):
            self.cuts.append(path)
            results = []
            for i, name in enumerate(roster, 1):
                if die_after is not None and i > die_after:
                    raise KeyboardInterrupt
                d = os.path.join(bc.sorted_root(out_dir, sorted_dir), bc.safe_folder(name), bc.safe_folder(project))
                os.makedirs(d, exist_ok=True)
                dest = os.path.join(d, bc.piece_name(project, grade, d))
                with open(dest, "wb") as f:
                    f.write(b"a piece")
                results.append({"piece": i, "status": "confident", "name": name, "text": name, "score": 1.0,
                                "margin": 1.0, "box": None, "file": dest, "bbox": (0, 0, 1, 1)})
            return results
        return cut

    def sort(self, project="Self-Portrait", inbox=None):
        return bc.run_inbox(inbox or self.inbox, self.ROSTER, self.out, project, log=self.log.append,
                            grade="K", sorted_dir=self.cls, unsorted_dir=self.unsorted)

    def pieces(self, project="Self-Portrait"):
        folders = {n: os.path.join(self.cls, n, project) for n in self.ROSTER}
        return {n: sorted(os.listdir(d)) if os.path.isdir(d) else [] for n, d in folders.items()}

    def markers(self):
        d = os.path.join(self.out, bc.IN_PROGRESS_FOLDER)
        return sorted(os.listdir(d)) if os.path.isdir(d) else None

    def notes(self):
        return sorted(f for f in os.listdir(self.unsorted) if f.endswith(".txt")) if os.path.isdir(self.unsorted) else []

    def die_while(self, **kw):
        with self.assertRaises(KeyboardInterrupt):
            self.sort(**kw)

    # -- the reported defect ---------------------------------------------
    def test_stopped_after_every_piece_was_filed_the_restart_files_nothing_twice(self):
        bc.process_photo = self.filing()

        def dies(*a, **k):
            raise KeyboardInterrupt
        bc.write_report = dies                      # every piece saved, then the process is killed
        self.die_while()
        self.assertEqual(self.pieces(), {n: ["Self-Portrait K.jpg"] for n in self.ROSTER})
        self.assertEqual(len(self.markers()), 1)

        bc.write_report = self.saved[2]             # the watcher comes back
        self.log.clear()
        res = self.sort()
        self.assertEqual(res, [])
        self.assertEqual(len(self.cuts), 1, "the photo must not be cut a second time")
        self.assertEqual(self.pieces(), {n: ["Self-Portrait K.jpg"] for n in self.ROSTER})
        self.assertEqual(os.listdir(os.path.join(self.inbox, "done")), ["wall.jpg"])
        self.assertFalse(os.path.exists(self.photo))

    def test_the_repro_as_reported_a_kill_at_the_move_sorts_the_photo_once(self):
        """The report's own steps: shutil.move raises KeyboardInterrupt, then the
        watcher runs again. The move is now the FIRST thing that happens to a
        photo, so a kill there has saved nothing and the restart sorts it once."""
        bc.process_photo = self.filing()

        def dies(src, dst):
            raise KeyboardInterrupt
        bc.shutil.move = dies
        self.die_while()
        self.assertEqual(self.cuts, [])
        self.assertTrue(os.path.exists(self.photo))

        bc.shutil.move = self.saved[3]
        self.log.clear()
        res = self.sort()
        self.assertEqual(len(res), 4)
        self.assertEqual(self.pieces(), {n: ["Self-Portrait K.jpg"] for n in self.ROSTER})
        self.assertFalse(any("not finished" in m for m in self.log), self.log)   # it was never started
        self.assertEqual(self.notes(), [])
        self.assertIsNone(self.markers())

    def test_stopped_halfway_is_not_sorted_again_and_somebody_is_told(self):
        bc.process_photo = self.filing(die_after=2)
        self.die_while()
        bc.process_photo = self.filing()
        self.log.clear()
        self.assertEqual(self.sort(), [])
        got = self.pieces()
        self.assertEqual([got[n] for n in self.ROSTER], [["Self-Portrait K.jpg"], ["Self-Portrait K.jpg"], [], []])
        self.assertEqual(len(self.cuts), 1)
        said = [m for m in self.log if "wall.jpg" in m]
        self.assertEqual(len(said), 1, self.log)
        for words in ("stopped partway through sorting this photo", "was not finished",
                      "some children may be missing their piece", "NOT been sorted again",
                      "move the photo from 'Wall Inbox/done' back into 'Wall Inbox'",
                      "A note that says this is in 'Unsorted - needs a person'"):
            self.assertIn(words, said[0])
        for name in self.ROSTER:                    # the photo and the folders, never a child
            self.assertNotIn(name, said[0])
        self.assertEqual(self.notes(), ["NOT FINISHED - Self-Portrait - wall.jpg.txt"])
        note = read(os.path.join(self.unsorted, self.notes()[0]))
        for words in ("Baggage Claim did not finish this photo.", "Photo:    wall.jpg", "Project:  Self-Portrait",
                      "on the computer called " + bc.machine_name(), "The photo is now in:  Wall Inbox/done",
                      "nobody was given the same piece twice",
                      "move the photo from 'Wall Inbox/done' back into 'Wall Inbox'",
                      "You can delete this note when you are done."):
            self.assertIn(words, note)
        for name in self.ROSTER:
            self.assertNotIn(name, note)
        self.assertIsNone(self.markers(), "the marker is removed once the photo has been reported")

    def test_it_is_said_once_not_every_five_seconds(self):
        bc.process_photo = self.filing(die_after=1)
        self.die_while()
        bc.process_photo = self.filing()
        self.sort()
        self.log.clear()
        self.sort()
        self.sort()
        self.assertEqual(self.log, [])

    def test_a_teacher_who_moves_the_photo_back_gets_it_sorted(self):
        bc.process_photo = self.filing(die_after=2)
        self.die_while()
        bc.process_photo = self.filing()
        self.sort()
        shutil.move(os.path.join(self.inbox, "done", "wall.jpg"), self.photo)   # what the note says to do
        self.log.clear()
        self.assertEqual(len(self.sort()), 4)
        got = self.pieces()
        self.assertEqual(got["Jonah Reed"], ["Self-Portrait K.jpg"])
        self.assertEqual(got["Maya Torres"], ["Self-Portrait K 2.jpg", "Self-Portrait K.jpg"])
        self.assertFalse(any("not finished" in m for m in self.log), self.log)

    def test_a_photo_in_a_project_folder_names_the_project_folder_to_move_it_back_to(self):
        proj = os.path.join(self.inbox, "Fall Leaves")
        os.makedirs(proj)
        os.rename(self.photo, os.path.join(proj, "leaves.jpg"))
        bc.process_photo = self.filing(die_after=1)
        self.die_while()
        bc.process_photo = self.filing()
        self.log.clear()
        self.assertEqual(self.sort(), [])
        self.assertEqual(self.pieces("Fall Leaves")["Priya Nair"], [])
        self.assertIn("move the photo from 'Wall Inbox/done/Fall Leaves' back into 'Wall Inbox/Fall Leaves'",
                      " ".join(self.log))
        self.assertEqual(self.notes(), ["NOT FINISHED - Fall Leaves - leaves.jpg.txt"])
        self.assertIn("The photo is now in:  Wall Inbox/done/Fall Leaves", read(os.path.join(self.unsorted, self.notes()[0])))

    # -- the marker itself -----------------------------------------------
    def test_the_marker_is_there_while_the_photo_is_cut_and_gone_when_it_is_finished(self):
        seen = {}
        real = self.filing()

        def cut(path, *a, **k):
            seen["markers"] = self.markers()
            seen["inbox"] = sorted(os.listdir(self.inbox))
            return real(path, *a, **k)
        bc.process_photo = cut
        self.assertEqual(len(self.sort()), 4)
        self.assertEqual(len(seen["markers"]), 1)
        self.assertTrue(seen["markers"][0].startswith(bc.machine_name() + " "))
        self.assertEqual(seen["inbox"], ["done"], "the marker must never be written into the shared inbox")
        self.assertIsNone(self.markers())
        self.assertEqual(self.notes(), [])
        self.assertFalse(any("not finished" in m for m in self.log), self.log)

    def test_a_bad_photo_and_a_lost_race_leave_no_marker_behind(self):
        def bad(path, *a, **k):
            raise ValueError("not an image")
        bc.process_photo = bad
        self.sort()
        self.assertEqual(os.listdir(os.path.join(self.inbox, "failed")), ["wall.jpg"])
        self.assertIsNone(self.markers())

        with open(self.photo, "wb") as f:
            f.write(b"\xff\xd8 another wall")
        real_move = self.saved[3]

        def other_computer_moved_it_first(src, dst):
            os.remove(src)
            return real_move(src, dst)
        bc.shutil.move = other_computer_moved_it_first
        self.sort()
        bc.shutil.move = real_move
        self.assertIsNone(self.markers())

        with open(self.photo, "wb") as f:
            f.write(b"\xff\xd8 a third wall")

        def vanishes(path, *a, **k):
            os.remove(path)
            raise OSError("the photo is gone")
        bc.process_photo = vanishes
        self.sort()
        self.assertIsNone(self.markers())
        self.sort()
        self.assertFalse(any("not finished" in m for m in self.log), self.log)
        # the bad photo has a note of its own since the repair further down (COULD NOT SORT);
        # what must not be here is a note that says a photo was left unfinished
        self.assertEqual([n for n in self.notes() if not n.startswith(bc.COULD_NOT_SORT)], [])
        self.assertEqual(self.notes(), ["COULD NOT SORT - Self-Portrait - wall.jpg.txt"])

    def test_a_photo_that_leaves_the_inbox_at_the_last_instant_is_reported_as_taken(self):
        real_size = bc.os.path.getsize
        saved_mark = bc.mark_started

        def gone(out_dir, inbox, src, claimed, project):
            os.remove(src)                          # the other computer's move arrives this instant
            return saved_mark(out_dir, inbox, src, claimed, project)
        bc.mark_started = gone
        bc.process_photo = self.filing()
        try:
            taken = []
            res = bc.run_inbox(self.inbox, self.ROSTER, self.out, "Self-Portrait", log=self.log.append,
                               sorted_dir=self.cls, taken=taken)
        finally:
            bc.mark_started = saved_mark
        self.assertIs(bc.os.path.getsize, real_size)
        self.assertEqual((res, taken, self.cuts), ([], ["wall.jpg"], []))
        self.assertIsNone(self.markers())

    def test_another_class_another_computer_and_a_broken_file_are_left_alone(self):
        bc.process_photo = self.filing(die_after=1)
        self.die_while()
        folder = os.path.join(self.out, bc.IN_PROGRESS_FOLDER)
        mine = self.markers()[0]
        info = json.loads(read(os.path.join(folder, mine)))
        self.assertEqual(info["class"], "room 3/wall inbox")
        self.assertEqual((info["photo"], info["done"], info["back"], info["project"]),
                         ("wall.jpg", "done/wall.jpg", "", "Self-Portrait"))
        with open(os.path.join(folder, "Classroom-PC 000000000000.json"), "w") as f:
            json.dump(dict(info, machine="Classroom-PC"), f)
        with open(os.path.join(folder, "other class.json"), "w") as f:
            json.dump(dict(info, **{"class": "room 4/wall inbox"}), f)
        with open(os.path.join(folder, "broken.json"), "w") as f:
            f.write("{ not json")
        with open(os.path.join(folder, "list.json"), "w") as f:
            f.write("[1, 2]")
        with open(os.path.join(folder, "half.json.part"), "w") as f:
            f.write("{")
        self.assertEqual([i["photo"] for _, i in bc.unfinished_photos(self.out, self.inbox)], ["wall.jpg"])
        bc.process_photo = self.filing()
        self.log.clear()
        self.sort()
        self.assertEqual(len([m for m in self.log if "not finished" in m]), 1, self.log)
        self.assertEqual(self.markers(), ["Classroom-PC 000000000000.json", "broken.json", "half.json.part",
                                          "list.json", "other class.json"])
        self.assertEqual(bc.unfinished_photos(os.path.join(self.tmp, "nowhere"), self.inbox), [])

    def test_the_class_is_known_by_its_last_two_folders_so_a_moved_drive_still_matches(self):
        self.assertEqual(bc.class_key("/Volumes/GoogleDrive/My Drive/Room 3/Wall Inbox"), "room 3/wall inbox")
        self.assertEqual(bc.class_key("/Users/helper/My Drive/Room 3/Wall Inbox/"), "room 3/wall inbox")
        self.assertNotEqual(bc.class_key("/x/My Drive/Room 4/Wall Inbox"), bc.class_key("/x/My Drive/Room 3/Wall Inbox"))

    def test_a_photo_dealt_with_by_a_person_in_the_meantime_is_not_reported(self):
        # killed between the marker and the claim, and an OLDER photo of the
        # same name already sits in done: that one was finished long ago
        os.makedirs(os.path.join(self.inbox, "done"))
        with open(os.path.join(self.inbox, "done", "wall.jpg"), "wb") as f:
            f.write(b"\xff\xd8 last week's wall, a different size")
        path = bc.mark_started(self.out, self.inbox, self.photo, os.path.join(self.inbox, "done", "wall.jpg"), "Art")
        self.assertEqual(bc.tell_unfinished(self.inbox, self.out, self.log.append, self.unsorted), [])
        self.assertFalse(os.path.exists(path))
        # the same photo, claimed, and then dropped into the inbox again by a teacher
        bc.mark_started(self.out, self.inbox, self.photo, os.path.join(self.inbox, "done", "wall.jpg"), "Art")
        shutil.copy(self.photo, os.path.join(self.inbox, "done", "wall.jpg"))
        self.assertEqual(bc.tell_unfinished(self.inbox, self.out, self.log.append, self.unsorted), [])
        # claimed, and gone from done altogether
        bc.mark_started(self.out, self.inbox, self.photo, os.path.join(self.inbox, "done", "wall.jpg"), "Art")
        os.remove(os.path.join(self.inbox, "done", "wall.jpg"))
        os.remove(self.photo)
        self.assertEqual(bc.tell_unfinished(self.inbox, self.out, self.log.append, self.unsorted), [])
        self.assertEqual((self.log, self.notes(), self.markers()), ([], [], None))

    def test_a_note_that_cannot_be_written_is_said_in_the_log_and_stops_nothing(self):
        bc.process_photo = self.filing(die_after=1)
        self.die_while()
        with open(self.unsorted, "w") as f:         # a file where the folder should be
            f.write("in the way")
        bc.process_photo = self.filing()
        self.log.clear()
        self.assertEqual(self.sort(), [])
        self.assertEqual(len(self.log), 1)
        self.assertIn("was not finished", self.log[0])
        self.assertIn("A note for the teacher could not be written", self.log[0])
        self.assertIsNone(self.markers())

    def test_an_old_marker_without_the_newer_fields_still_reads(self):
        bc.process_photo = self.filing(die_after=1)
        self.die_while()
        folder = os.path.join(self.out, bc.IN_PROGRESS_FOLDER)
        path = os.path.join(folder, self.markers()[0])
        info = json.loads(read(path))
        for k in ("started", "project", "back"):
            del info[k]
        with open(path, "w") as f:
            json.dump(info, f)
        told = bc.tell_unfinished(self.inbox, self.out, self.log.append, self.unsorted)
        self.assertEqual(told, ["wall.jpg"])
        self.assertIn("(started earlier)", self.log[0])
        self.assertIn("Started:  not known", read(os.path.join(self.unsorted, self.notes()[0])))

    # -- the watcher says it at start, whoever sorts today ------------------
    def test_the_watcher_says_so_when_it_starts_even_if_it_is_standing_by(self):
        bc.process_photo = self.filing(die_after=2)
        self.die_while()
        roster = os.path.join(self.cls, "Class list.txt")
        with open(roster, "w") as f:
            f.write("\n".join(self.ROSTER) + "\n")
        settings = os.path.join(self.tmp, "settings.json")
        with open(settings, "w") as f:
            json.dump({"inbox": self.inbox, "sorted": self.cls, "unsorted": self.unsorted, "roster": roster,
                       "project": "Self-Portrait", "grade": "K", "interval": 1, "priority": 90}, f)
        bc.write_status(bc.status_dir(self.cls), "Classroom-PC", bc.time.time(), "watching", 10)
        calls = []
        bc.run_inbox = lambda *a, **k: calls.append(1) or []

        def stop(s):
            raise KeyboardInterrupt
        bc.time.sleep = stop
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                bc.main(["--watch", "--settings", settings, "--out", self.out])
        out = buf.getvalue()
        self.assertEqual(calls, [], "this computer is standing by and must not sort")
        self.assertEqual(out.count("stopped partway through sorting this photo"), 1, out)
        self.assertRegex(out, r"(?m)^\w{3} \d\d \d\d:\d\d [AP]M: wall\.jpg: this computer stopped partway")
        self.assertEqual(self.notes(), ["NOT FINISHED - Self-Portrait - wall.jpg.txt"])
        self.assertIsNone(self.markers())
        self.assertEqual(self.pieces()["Jonah Reed"], [])


@unittest.skipUnless(bc.backend_ready(), "the name reader is not available on this machine")
class StoppedMidPhotoOnARealWallTests(unittest.TestCase):
    """The same defect end to end: a synthetic wall (make_wall.py, invented
    names), the real detectors and the real name reader, the process killed
    after the last piece was saved, and the watcher started again."""

    NAMES = ["Maya", "Jonah", "Sofia", "Elijah"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Drive", "Room 3")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.unsorted = os.path.join(self.cls, "Unsorted - needs a person")
        self.out = os.path.join(self.tmp, "tool")
        os.makedirs(self.out)
        sys.path.insert(0, HERE)
        from make_wall import make_wall
        img, _ = make_wall(self.NAMES, rows=1, cols=4, size=(2400, 700))
        img.save(os.path.join(self.inbox, "wall.jpg"), quality=90)
        self.saved = (bc.write_report, bc.is_settled)
        bc.is_settled = lambda p, wait=0: True

    def tearDown(self):
        bc.write_report, bc.is_settled = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def everything_filed(self):
        found = []
        for top in (self.cls, self.out):
            for folder, _, files in os.walk(top):
                if os.path.join(self.inbox, "") in os.path.join(folder, ""):
                    continue
                found += [os.path.relpath(os.path.join(folder, f), self.tmp) for f in files
                          if f.lower().endswith(".jpg")]
        return sorted(found)

    def test_restart_after_a_kill_files_no_second_copy(self):
        def dies(*a, **k):
            raise KeyboardInterrupt
        bc.write_report = dies
        log = []
        with self.assertRaises(KeyboardInterrupt):
            bc.run_inbox(self.inbox, self.NAMES, self.out, "Self-Portrait", log=log.append, grade="K",
                         sorted_dir=self.cls, unsorted_dir=self.unsorted)
        first = self.everything_filed()
        self.assertGreaterEqual(len([f for f in first if "Self-Portrait K.jpg" in f]), 3, first)

        bc.write_report = self.saved[0]
        log = []
        res = bc.run_inbox(self.inbox, self.NAMES, self.out, "Self-Portrait", log=log.append, grade="K",
                           sorted_dir=self.cls, unsorted_dir=self.unsorted)
        self.assertEqual(res, [])
        self.assertEqual(self.everything_filed(), first, "the restart must not file anything")
        self.assertFalse([f for f in first if f.endswith(" 2.jpg")])
        self.assertEqual(os.listdir(os.path.join(self.inbox, "done")), ["wall.jpg"])
        self.assertEqual(len([m for m in log if "was not finished" in m]), 1, log)
        self.assertTrue(os.path.exists(os.path.join(self.unsorted, "NOT FINISHED - Self-Portrait - wall.jpg.txt")))


class ClassListReloadTests(unittest.TestCase):
    """Repair (class list): refresh_roster on its own. A changed file gives
    the new list and one line in the log; a list that is missing, empty or
    unreadable for a moment never replaces a good one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "Class list - one first name per line.txt")
        self.write("Maya Torres\nJonah Reed\n")
        self.log = []
        self.seen = {}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, text, raw=None):
        with open(self.path, "wb") as f:
            f.write(raw if raw is not None else text.encode("utf-8"))

    def refresh(self, roster):
        return bc.refresh_roster(self.path, roster, self.seen, self.log.append)

    def test_a_child_added_to_the_file_is_in_the_list_on_the_next_look_and_it_is_said_once(self):
        roster = self.refresh(bc.load_roster(self.path))
        self.assertEqual(roster, ["Maya Torres", "Jonah Reed"])
        self.assertEqual(self.log, [], "the first look at an unchanged list says nothing")
        self.write("Maya Torres\nJonah Reed\nSofia Marin\n")
        roster = self.refresh(roster)
        self.assertEqual(roster, ["Maya Torres", "Jonah Reed", "Sofia Marin"])
        for _ in range(5):
            self.assertIs(self.refresh(roster), roster, "an unchanged file is not read again")
        self.assertEqual(len(self.log), 1, self.log)
        self.assertIn("class list changed: 3 children (there were 2)", self.log[0])
        self.assertIn("A new child gets a folder, and their work is filed from the next photo", self.log[0])

    def test_a_child_taken_off_the_list_is_gone_on_the_next_look(self):
        roster = self.refresh(bc.load_roster(self.path))
        self.write("Maya Torres\n")
        self.assertEqual(self.refresh(roster), ["Maya Torres"])
        self.assertIn("class list changed: 1 child (there were 2)", self.log[0])
        self.assertIn("The next photo is sorted with the new list", self.log[0])
        self.assertNotIn("new child", self.log[0])

    def test_a_file_saved_again_with_the_same_names_says_nothing(self):
        roster = self.refresh(bc.load_roster(self.path))
        self.write("# kindergarten\nMaya Torres\n\nJonah Reed\n")     # a comment and a blank line: same children
        self.assertEqual(self.refresh(roster), ["Maya Torres", "Jonah Reed"])
        self.assertEqual(self.log, [])

    def test_an_empty_list_never_replaces_a_good_one_and_the_next_good_one_is_picked_up(self):
        roster = self.refresh(bc.load_roster(self.path))
        self.write("")                                   # Drive, or an editor, in the middle of saving
        for _ in range(3):
            self.assertEqual(self.refresh(roster), ["Maya Torres", "Jonah Reed"])
        self.assertEqual(len(self.log), 1, self.log)
        self.assertIn("class list is empty; still using the list of 2 children from before", self.log[0])
        self.assertIn("Class list - one first name per line.txt", self.log[0])
        self.write("Maya Torres\nJonah Reed\nSofia Marin\n")
        self.assertEqual(len(self.refresh(roster)), 3)
        self.assertIn("class list changed: 3 children", self.log[1])

    def test_a_list_that_cannot_be_read_keeps_the_old_one_and_says_so_once(self):
        roster = self.refresh(bc.load_roster(self.path))
        self.write(None, raw=b"Maya Torres\n\xff\xfe broken\n")    # not text this program can read
        for _ in range(3):
            self.assertEqual(self.refresh(roster), ["Maya Torres", "Jonah Reed"])
        self.assertEqual(len(self.log), 1, self.log)
        self.assertIn("class list could not be read", self.log[0])
        self.assertIn("still using the list of 2 children from before", self.log[0])

    def test_a_list_that_is_not_there_for_a_moment_keeps_the_old_one_without_a_word(self):
        roster = self.refresh(bc.load_roster(self.path))
        os.remove(self.path)                             # Drive not connected for a moment
        self.assertIsNone(bc.roster_stamp(self.path))
        self.assertEqual(self.refresh(roster), ["Maya Torres", "Jonah Reed"])
        self.assertEqual(self.log, [])


class ClassListReloadInTheWatchLoopTests(unittest.TestCase):
    """Repair (class list): the --watch loop itself. run_inbox is a fake that
    writes down the list it was handed on every look at the inbox."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Class")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.roster = os.path.join(self.cls, "Class list - one first name per line.txt")
        with open(self.roster, "w", encoding="utf-8") as f:
            f.write("Maya Torres\nJonah Reed\n")
        self.settings = os.path.join(self.tmp, "settings.json")
        with open(self.settings, "w") as f:
            json.dump({"inbox": self.inbox, "sorted": self.cls,
                       "unsorted": os.path.join(self.cls, "Unsorted - needs a person"),
                       "roster": self.roster, "project": "Self-Portrait", "grade": "Kindergarten", "interval": 1,
                       "priority": 50}, f)
        self.saved = (bc.time.sleep, bc.run_inbox, bc.GRACE_SECONDS)
        bc.GRACE_SECONDS = 0
        self.ticks = []
        self.handed = []

        def fake_run_inbox(inbox, roster, *a, **k):
            self.handed.append(list(roster))
            return []
        bc.run_inbox = fake_run_inbox

    def tearDown(self):
        bc.time.sleep, bc.run_inbox, bc.GRACE_SECONDS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_main(self, on_sleep, stop_after):
        def fake_sleep(s):
            self.ticks.append(s)
            on_sleep(len(self.ticks))
            if len(self.ticks) >= stop_after:
                raise KeyboardInterrupt
        bc.time.sleep = fake_sleep
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                bc.main(["--watch", "--settings", self.settings, "--out", self.tmp])
        return buf.getvalue()

    def test_a_child_added_while_the_watcher_runs_is_on_the_list_at_the_next_look(self):
        def teacher(tick):
            if tick == 2:       # the watcher has been running; the teacher adds the new child
                with open(self.roster, "a", encoding="utf-8") as f:
                    f.write("Sofia Marin\n")
        out = self.run_main(teacher, stop_after=6)
        two, three = ["Maya Torres", "Jonah Reed"], ["Maya Torres", "Jonah Reed", "Sofia Marin"]
        self.assertEqual(self.handed, [two, two, three, three, three, three], out)
        self.assertEqual(out.count("class list changed"), 1, out)
        self.assertIn("class list changed: 3 children (there were 2)", out)

    def test_a_list_emptied_for_a_moment_does_not_stop_the_sorting(self):
        def drive(tick):
            if tick == 1:
                open(self.roster, "w").close()              # caught in the middle of being saved
            if tick == 3:
                with open(self.roster, "w", encoding="utf-8") as f:
                    f.write("Maya Torres\nJonah Reed\nSofia Marin\n")
        out = self.run_main(drive, stop_after=5)
        self.assertEqual([len(r) for r in self.handed], [2, 2, 2, 3, 3], out)
        self.assertEqual(out.count("class list is empty"), 1, out)
        self.assertEqual(out.count("class list changed"), 1, out)


class ClassListReloadOnARealWallTests(unittest.TestCase):
    """Repair (class list), the report end to end: the watcher starts with
    three children on the class list, the teacher adds a fourth, and the next
    photo has that child's labelled work on it. A synthetic wall (make_wall.py,
    invented names), the real detectors and the real name reader."""

    NAMES = ["Maya", "Jonah", "Sofia", "Elijah"]
    NEW = "Elijah"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Drive", "Room 3")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.unsorted = os.path.join(self.cls, "Unsorted - needs a person")
        self.out = os.path.join(self.tmp, "tool")
        os.makedirs(self.out)
        self.roster = os.path.join(self.cls, "Class list - one first name per line.txt")
        with open(self.roster, "w", encoding="utf-8") as f:
            f.write("".join(n + "\n" for n in self.NAMES if n != self.NEW))
        self.settings = os.path.join(self.tmp, "settings.json")
        with open(self.settings, "w") as f:
            json.dump({"inbox": self.inbox, "sorted": self.cls, "unsorted": self.unsorted, "roster": self.roster,
                       "project": "Self-Portrait", "grade": "K", "interval": 1, "priority": 50}, f)
        self.saved = (bc.time.sleep, bc.is_settled, bc.GRACE_SECONDS)
        bc.GRACE_SECONDS = 0
        bc.is_settled = lambda p, wait=0: True
        self.ticks = []

    def tearDown(self):
        bc.time.sleep, bc.is_settled, bc.GRACE_SECONDS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pieces(self, child):
        d = os.path.join(self.cls, child, "Self-Portrait")
        return sorted(os.listdir(d)) if os.path.isdir(d) else None

    def test_the_new_childs_work_is_filed_under_the_new_child_without_a_restart(self):
        def teacher(tick):
            self.ticks.append(tick)
            if len(self.ticks) == 1:
                # The watcher has looked once with three children. No folder for the fourth yet.
                self.assertIsNone(self.pieces(self.NEW))
                with open(self.roster, "a", encoding="utf-8") as f:
                    f.write(self.NEW + "\n")
                sys.path.insert(0, HERE)
                from make_wall import make_wall
                img, _ = make_wall(self.NAMES, rows=1, cols=4, size=(2400, 700))
                img.save(os.path.join(self.inbox, "wall.jpg"), quality=90)
            else:
                raise KeyboardInterrupt
        bc.time.sleep = teacher
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                bc.main(["--watch", "--settings", self.settings, "--out", self.out])
        out = buf.getvalue()
        self.assertIn("class list changed: 4 children (there were 3)", out)
        self.assertEqual(self.pieces(self.NEW), ["Self-Portrait K.jpg"], out)
        # and nobody else got that child's piece: one piece per child at most, none filed twice
        for child in self.NAMES:
            self.assertLessEqual(len(self.pieces(child) or []), 1, out)
        self.assertEqual(os.listdir(os.path.join(self.inbox, "done")), ["wall.jpg"])


class ProjectNameCleanedTests(unittest.TestCase):
    """Repair (project name): a teacher makes a folder in the Wall Inbox called
    'Who Am I?' or 'Unit 2: Leaves' from a phone. A Mac accepts the name and
    sorts the photos. The project FOLDER was cleaned ('Who Am I'), but every
    file name, every GUESS name in Unsorted and the done folder kept the ? or
    the : and a Windows PC cannot hold such a name, so Google Drive on the PC
    showed a sync error for every piece. The name is now cleaned once where it
    comes in (a folder inside the inbox, --project, the settings file), the
    file names are cleaned the same way as the folders, and the log says so
    once. Invented names only; the one image is a synthetic wall."""

    REFUSED = set('<>:"/\\|?*')
    NAMES = ["Maya", "Jonah", "Sofia", "Elijah"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Drive", "Room 3")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.unsorted = os.path.join(self.cls, "Unsorted - needs a person")
        self.out = os.path.join(self.tmp, "tool")
        os.makedirs(self.out)
        self.saved = (bc.is_settled, bc.process_photo)
        bc.is_settled = lambda p, wait=0: True
        bc.CLEANED_SAID.clear()
        self.projects = []

    def tearDown(self):
        bc.is_settled, bc.process_photo = self.saved
        bc.CLEANED_SAID.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_photo(self, folder, name):
        from PIL import Image
        os.makedirs(folder, exist_ok=True)
        Image.new("RGB", (60, 40), "white").save(os.path.join(folder, name))

    def fake_sorting(self):
        def fake(path, roster, out_dir, project, *a, **k):
            self.projects.append(project)
            return []
        bc.process_photo = fake

    def names_made(self):
        """Every file and folder name the tool made, leaving out what the
        teacher made herself (the folders waiting in the inbox)."""
        made = []
        for top in (self.cls, self.out):
            for folder, dirs, files in os.walk(top):
                if os.path.normpath(folder) == os.path.normpath(self.inbox):
                    dirs[:] = [d for d in dirs if d in ("done", "failed")]
                made += dirs + files
        return made

    def assert_every_name_works_on_windows(self):
        made = self.names_made()
        bad = [n for n in made if set(n) & self.REFUSED or n != n.rstrip(". ")]
        self.assertEqual(bad, [], "names a Windows PC cannot hold")
        return made

    def test_the_file_name_is_cleaned_the_same_way_as_the_folder(self):
        self.assertEqual(bc.piece_name("Who Am I?", "Kindergarten", self.tmp), "Who Am I Kindergarten.jpg")
        self.assertEqual(bc.piece_name("Unit 2: Leaves", "K", self.tmp), "Unit 2 Leaves K.jpg")
        self.assertEqual(bc.piece_name('The "Me" Book', "", self.tmp), "The Me Book.jpg")
        # a grade such as 5/6 must not turn into a folder that is not there
        self.assertEqual(bc.piece_name("Maps", "5/6", self.tmp), "Maps 56.jpg")
        # the second piece is still numbered, against the cleaned name
        open(os.path.join(self.tmp, "Who Am I Kindergarten.jpg"), "w").close()
        self.assertEqual(bc.piece_name("Who Am I?", "Kindergarten", self.tmp), "Who Am I Kindergarten 2.jpg")
        # and a name that was fine is the name it always was
        self.assertEqual(bc.piece_name("Self-Portrait", "Kindergarten", self.tmp), "Self-Portrait Kindergarten.jpg")
        self.assertEqual(bc.clean_project("Who Am I?"), bc.safe_folder("Who Am I?"))
        self.assertEqual(bc.clean_project(""), "")

    def test_it_is_said_once_and_only_when_a_character_was_taken_out(self):
        import unicodedata
        log = []
        self.assertTrue(bc.say_cleaned("Who Am I?", "Who Am I", log.append, "inbox"))
        self.assertFalse(bc.say_cleaned("Who Am I?", "Who Am I", log.append, "inbox"))
        self.assertFalse(bc.say_cleaned("Fall Leaves", "Fall Leaves", log.append, "inbox"))
        self.assertFalse(bc.say_cleaned("", "", log.append, "inbox"))
        # an accent stored the Mac's way is the same name, not a changed one
        self.assertFalse(bc.say_cleaned(unicodedata.normalize("NFD", "Otoño"), bc.clean_project("Otoño"),
                                        log.append, "inbox"))
        self.assertEqual(len(log), 1, log)
        self.assertIn("'Who Am I?'", log[0])
        self.assertIn("filed as 'Who Am I'", log[0])
        self.assertIn("Windows", log[0])

    @unittest.skipIf(bc.IS_WIN, "Windows cannot make the folder this test starts from")
    def test_the_inbox_folder_name_is_cleaned_where_it_comes_in(self):
        self.fake_photo(os.path.join(self.inbox, "Unit 2: Leaves"), "IMG_0001.jpg")
        self.fake_photo(os.path.join(self.inbox, "Fall Leaves"), "IMG_0002.jpg")
        jobs = bc.inbox_jobs(self.inbox, "Artwork")
        self.assertEqual(jobs, [
            (os.path.join(self.inbox, "Fall Leaves", "IMG_0002.jpg"), "Fall Leaves",
             os.path.join(self.inbox, "done", "Fall Leaves")),
            (os.path.join(self.inbox, "Unit 2: Leaves", "IMG_0001.jpg"), "Unit 2 Leaves",
             os.path.join(self.inbox, "done", "Unit 2 Leaves"))])

    @unittest.skipIf(bc.IS_WIN, "Windows cannot make the folder this test starts from")
    def test_the_done_folder_and_the_project_agree_and_the_log_says_it_once(self):
        self.fake_sorting()
        log = []
        for photo in ("IMG_0001.jpg", "IMG_0002.jpg"):
            self.fake_photo(os.path.join(self.inbox, "Unit 2: Leaves"), photo)
            self.fake_photo(self.inbox, "straight " + photo)
            bc.run_inbox(self.inbox, ["Maya Torres"], self.out, "Artwork", log=log.append, grade="K",
                         sorted_dir=self.cls, unsorted_dir=self.unsorted)
        self.assertEqual(sorted(self.projects), ["Artwork", "Artwork", "Unit 2 Leaves", "Unit 2 Leaves"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.inbox, "done"))),
                         ["Unit 2 Leaves", "straight IMG_0001.jpg", "straight IMG_0002.jpg"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.inbox, "done", "Unit 2 Leaves"))),
                         ["IMG_0001.jpg", "IMG_0002.jpg"])
        said = [m for m in log if "Unit 2: Leaves" in m]
        self.assertEqual(len(said), 1, log)
        self.assertIn("filed as 'Unit 2 Leaves'", said[0])
        self.assert_every_name_works_on_windows()

    @unittest.skipIf(bc.IS_WIN, "Windows cannot make the folder this test starts from")
    def test_a_photo_stopped_halfway_is_reported_under_the_cleaned_name(self):
        def dies(*a, **k):
            raise KeyboardInterrupt
        bc.process_photo = dies
        self.fake_photo(os.path.join(self.inbox, "Who Am I?"), "IMG_0001.jpg")
        with self.assertRaises(KeyboardInterrupt):
            bc.run_inbox(self.inbox, ["Maya Torres"], self.out, "Artwork", log=lambda m: None,
                         sorted_dir=self.cls, unsorted_dir=self.unsorted)
        log = []
        bc.tell_unfinished(self.inbox, self.out, log.append, self.unsorted)
        note = os.path.join(self.unsorted, "NOT FINISHED - Who Am I - IMG_0001.jpg.txt")
        self.assertTrue(os.path.exists(note), os.listdir(self.unsorted))
        text = read(note)
        self.assertIn("Wall Inbox/done/Who Am I\n", text)
        # the folder to move it back into is the teacher's own, under the name she gave it
        self.assertIn("back into 'Wall Inbox/Who Am I?'", text)
        self.assert_every_name_works_on_windows()

    def test_the_project_flag_and_the_settings_file_are_cleaned_too(self):
        self.fake_sorting()
        roster = os.path.join(self.tmp, "class list.txt")
        with open(roster, "w", encoding="utf-8") as f:
            f.write("Maya Torres\n")
        self.fake_photo(self.tmp, "wall.jpg")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            bc.main(["--project", "Unit 2: Leaves", "--roster", roster, "--out", self.out, "--sorted", self.cls,
                     os.path.join(self.tmp, "wall.jpg")])
        settings = os.path.join(self.tmp, "settings.json")
        with open(settings, "w", encoding="utf-8") as f:
            json.dump({"inbox": self.inbox, "sorted": self.cls, "unsorted": self.unsorted, "roster": roster,
                       "project": "Who Am I?", "grade": "K"}, f)
        with contextlib.redirect_stdout(buf):
            bc.main(["--settings", settings, "--out", self.out, os.path.join(self.tmp, "wall.jpg")])
            bc.main(["--settings", settings, "--out", self.out, "--project", "Self-Portrait",
                     os.path.join(self.tmp, "wall.jpg")])
        out = buf.getvalue()
        self.assertEqual(self.projects, ["Unit 2 Leaves", "Who Am I", "Self-Portrait"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.cls, "Maya Torres"))),
                         ["Self-Portrait", "Unit 2 Leaves", "Who Am I"])
        self.assertEqual(out.count("filed as 'Unit 2 Leaves'"), 1, out)
        self.assertEqual(out.count("filed as 'Who Am I'"), 1, out)
        self.assertNotIn("filed as 'Self-Portrait'", out)


class ProjectNameCleanedOnARealWallTests(unittest.TestCase):
    """The same defect end to end, as the teacher meets it: a folder called
    'Who Am I?' inside the Wall Inbox, a synthetic wall (make_wall.py, invented
    names, one paper with no name so that a GUESS file is made), the real
    detectors and the real name reader. Every name the tool makes has to be
    one a Windows PC can hold."""

    NAMES = ["Maya", "Jonah", "Sofia", "Elijah"]
    REFUSED = ProjectNameCleanedTests.REFUSED

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Drive", "Room 3")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        self.unsorted = os.path.join(self.cls, "Unsorted - needs a person")
        self.out = os.path.join(self.tmp, "tool")
        os.makedirs(self.out)
        self.saved = bc.is_settled
        bc.is_settled = lambda p, wait=0: True
        bc.CLEANED_SAID.clear()

    def tearDown(self):
        bc.is_settled = self.saved
        bc.CLEANED_SAID.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    @unittest.skipIf(bc.IS_WIN, "Windows cannot make the folder this test starts from")
    def test_every_piece_and_every_guess_has_a_name_a_windows_pc_can_hold(self):
        sys.path.insert(0, HERE)
        from make_wall import make_wall
        folder = os.path.join(self.inbox, "Who Am I?")
        os.makedirs(folder)
        img, _ = make_wall(self.NAMES, rows=1, cols=4, size=(2400, 700), unnamed=(3,))
        img.save(os.path.join(folder, "IMG_0001.jpg"), quality=90)
        log = []
        res = bc.run_inbox(self.inbox, self.NAMES, self.out, "Artwork", log=log.append, grade="K",
                           sorted_dir=self.cls, unsorted_dir=self.unsorted)
        self.assertEqual(len(res), 4, log)
        made = []
        for top in (self.cls, self.out):
            for where, dirs, files in os.walk(top):
                if os.path.normpath(where) == os.path.normpath(self.inbox):
                    dirs[:] = [d for d in dirs if d in ("done", "failed")]
                made += [os.path.relpath(os.path.join(where, n), self.tmp) for n in dirs + files]
        bad = [m for m in made if set(os.path.basename(m)) & self.REFUSED]
        self.assertEqual(bad, [], "names a Windows PC cannot hold")
        filed = [m for m in made if os.path.basename(m) == "Who Am I K.jpg"]
        self.assertGreaterEqual(len(filed), 3, made)
        for m in filed:
            self.assertEqual(os.path.basename(os.path.dirname(m)), "Who Am I", m)
        guesses = sorted(n for n in os.listdir(self.unsorted) if n.startswith("GUESS "))
        self.assertTrue(guesses, made)
        for g in guesses:
            self.assertIn(" - Who Am I K - IMG_0001 ", g)
            self.assertTrue(os.path.exists(os.path.join(self.unsorted, "name-strips", g)), g)
        self.assertEqual(os.listdir(os.path.join(self.inbox, "done")), ["Who Am I"])
        self.assertEqual(os.listdir(os.path.join(self.inbox, "done", "Who Am I")), ["IMG_0001.jpg"])
        self.assertEqual(len([m for m in log if "filed as 'Who Am I'" in m]), 1, log)


class WindowsVisibleWatcherTests(unittest.TestCase):
    """Repair (Windows visible watcher): "Start Watcher (visible).bat" stopped
    the background watcher (taskkill) and ran a watcher in the window instead.
    A teacher who opened it to see the tool working and then closed the window
    left the class with no watcher until her next login. It now looks first:
    when the background watcher is running it follows logs\watch.log and
    stops nothing; only when no background watcher is running does the
    watcher run in the window, and the window says so.

    A Mac cannot run a .bat file, so the file is walked line by line here by a
    small reader that knows only the few constructs the file is allowed to
    use, with the answer to "is the background watcher running?" supplied by
    the test. Anything the reader does not know fails the test, so the file
    cannot quietly grow a line these tests misread."""

    BAT = os.path.join(ROOT, "windows", "Start Watcher (visible).bat")
    WATCHER = "BaggageClaimWatcher.exe"

    def lines(self, path=None):
        with open(path or self.BAT, encoding="ascii") as f:
            return [ln.strip() for ln in f.read().splitlines()]

    def walk(self, watcher_running, path=None):
        """What the window would run and say. Returns (commands, words)."""
        lines = self.lines(path)
        labels = {ln[1:].lower(): i for i, ln in enumerate(lines) if ln.startswith(":")}
        ran, said, level, i, steps = [], [], 0, 0, 0
        while i < len(lines):
            steps += 1
            self.assertLess(steps, 500, "the file goes round in a circle")
            ln = lines[i]
            low = ln.lower()
            i += 1
            if not ln or low == "@echo off" or low.startswith(("rem ", "cd ", "title ", ":")):
                continue
            if low.startswith("echo"):
                said.append(ln[5:].strip())
                continue
            if low == "pause":
                ran.append("pause")
                continue
            if low.startswith("exit /b"):
                break
            if low.startswith("if not exist "):
                continue                    # making the logs folder and an empty log: harmless either way
            if low.startswith("if errorlevel 1 goto "):
                if level >= 1:
                    i = labels[low.rsplit(" ", 1)[1]]
                continue
            if low.startswith("goto "):
                i = labels[low.split(" ", 1)[1]]
                continue
            self.assertFalse(low.startswith(("if ", "for ", "call ", "start ", "(")), f"a line this test cannot follow: {ln}")
            ran.append(ln)
            level = 0
            if low.startswith("tasklist") and self.WATCHER.lower() in low:
                level = 0 if watcher_running else 1
        return ran, said

    def test_the_reader_itself_catches_the_old_file(self):
        old = os.path.join(tempfile.mkdtemp(), "old.bat")
        self.addCleanup(shutil.rmtree, os.path.dirname(old), True)
        with open(old, "w", encoding="ascii") as f:
            f.write('@echo off\ncd /d "%~dp0"\ntaskkill /IM BaggageClaimWatcher.exe /F >nul 2>&1\n'
                    "if not exist logs mkdir logs\n"
                    "BaggageClaim.exe --watch --settings settings.local.json --log logs\\watch.log\npause\n")
        ran, _ = self.walk(True, old)
        self.assertTrue(ran[0].startswith("taskkill"), ran)
        self.assertTrue(ran[1].startswith("BaggageClaim.exe --watch"), ran)

    def test_the_repro_opening_the_window_and_closing_it_stops_nothing(self):
        for running in (True, False):
            ran, _ = self.walk(running)
            for cmd in ran:
                self.assertNotIn("taskkill", cmd.lower(), ran)
                self.assertNotIn("stop-process", cmd.lower(), ran)
        for ln in self.lines():
            if not ln.lower().startswith("rem "):
                self.assertNotIn("taskkill", ln.lower())

    def test_it_looks_for_the_background_watcher_before_it_starts_anything(self):
        ran, _ = self.walk(True)
        self.assertTrue(ran[0].lower().startswith("tasklist"), ran)
        self.assertIn(self.WATCHER, ran[0])

    def test_with_the_background_watcher_running_it_follows_the_log_and_starts_no_second_watcher(self):
        ran, said = self.walk(True)
        follow = [c for c in ran if "Get-Content" in c]
        self.assertEqual(len(follow), 1, ran)
        self.assertIn("-Wait", follow[0])
        self.assertIn("logs\\watch.log", follow[0])
        self.assertEqual([c for c in ran if "--watch" in c], [], ran)
        words = " ".join(said)
        self.assertIn("already running in the background", words)
        self.assertIn("the watcher keeps going", words)
        self.assertIn("still running in the background", words)

    def test_with_no_background_watcher_the_watcher_runs_in_the_window_and_says_how_to_bring_it_back(self):
        ran, said = self.walk(False)
        watch = [c for c in ran if c.startswith("BaggageClaim.exe")]
        self.assertEqual(watch, ["BaggageClaim.exe --watch --settings settings.local.json --log logs\\watch.log"])
        self.assertEqual([c for c in ran if "Get-Content" in c], [], ran)
        words = " ".join(said)
        self.assertIn("Closing this window stops it", words)
        self.assertIn("double-click Setup.bat", words)
        self.assertNotIn("keeps going", words)

    def test_the_window_stays_open_at_the_end_either_way(self):
        for running in (True, False):
            ran, _ = self.walk(running)
            self.assertEqual(ran[-1], "pause", ran)

    def test_the_name_it_looks_for_is_the_program_setup_starts_and_the_build_makes(self):
        with open(os.path.join(ROOT, "windows", "Setup.bat"), encoding="ascii") as f:
            self.assertIn('start "" "%~dp0' + self.WATCHER + '"', f.read())
        with open(os.path.join(ROOT, ".github", "workflows", "build-windows.yml"), encoding="utf-8") as f:
            self.assertIn("--name " + self.WATCHER[:-4] + " ", f.read())
        self.assertLessEqual(len(self.WATCHER), 25, "tasklist cuts a longer program name short")


import threading  # noqa: E402


class TwoClassesOneToolFolder:
    """Two classes watched from one tool folder, as two threads. Class B is
    held at a known point (it has saved its first crop and is about to read
    it) while class A sorts a whole photo. Nothing is timed."""

    A_ROSTER = ["Maya", "Priya"]
    B_ROSTER = ["Jonah", "Sofia"]
    RED, BLUE = (200, 30, 30), (30, 30, 200)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, "tool")          # the one tool folder both watchers run from
        os.makedirs(self.out)
        self.cls = {k: os.path.join(self.tmp, "Drive", room) for k, room in (("a", "Room 3"), ("b", "Room 4"))}
        self.uns = {k: os.path.join(d, "Unsorted - needs a person") for k, d in self.cls.items()}
        self.wall = {k: os.path.join(d, "Wall Inbox", "done", "wall.jpg") for k, d in self.cls.items()}
        for p in self.wall.values():
            os.makedirs(os.path.dirname(p))
        self.saved = (bc.read_piece, bc.read_neighborhood, bc.read_photo_text)
        self.b_has_a_crop, self.a_is_finished = threading.Event(), threading.Event()
        self.read_from = {"a": [], "b": []}

    def tearDown(self):
        bc.read_piece, bc.read_neighborhood, bc.read_photo_text = self.saved
        self.a_is_finished.set()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def hold_b_at_its_first_crop(self, reader):
        """Wrap a name reader: class B stops right after saving its first crop,
        until class A has sorted a whole photo, and then reads that crop."""
        def read(tmp_path, crop):
            who = threading.current_thread().name
            self.read_from[who].append(tmp_path)
            if who == "b" and not self.b_has_a_crop.is_set():
                self.b_has_a_crop.set()
                if not self.a_is_finished.wait(120):
                    raise AssertionError("class A never finished")
            return reader(tmp_path, crop)
        return read

    def sort(self, who, roster, **kw):
        return bc.process_photo(self.wall[who], roster, self.out, "Self-Portrait", log=lambda *a: None, grade="K",
                                sorted_dir=self.cls[who], unsorted_dir=self.uns[who], **kw)

    def both_at_once(self, **kw):
        """Class B starts, class A sorts its whole photo while B is in the
        middle of its own, then B carries on. Returns (A's pieces, B's pieces)."""
        got, wrong = {}, {}

        def b():
            try:
                got["b"] = self.sort("b", self.B_ROSTER, **kw)
            except BaseException as e:   # noqa: B036  (reported by the test, not swallowed)
                wrong["b"] = e
        t = threading.Thread(target=b, name="b")
        threading.current_thread().name, mine = "a", threading.current_thread().name
        try:
            t.start()
            self.assertTrue(self.b_has_a_crop.wait(120), wrong)
            try:
                got["a"] = self.sort("a", self.A_ROSTER, **kw)
            finally:
                self.a_is_finished.set()
            t.join(120)
        finally:
            threading.current_thread().name = mine
        self.assertEqual(wrong, {}, "class B's photo failed because class A finished first")
        return got["a"], got["b"]

    def filed(self, who, child):
        d = os.path.join(self.cls[who], child, "Self-Portrait")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []


class OneScratchFolderPerPhotoTests(TwoClassesOneToolFolder, unittest.TestCase):
    """Repair (scratch folder): one tool folder can watch several classes, one
    watcher each, and every watcher cut its photo in the same scratch folder
    (<tool folder>/.tmp) under the same file names (crop-1.png, crop-2.png,
    upright.jpg), and deleted the whole folder when its photo was finished.
    Two teachers posting in the same ten seconds: the watcher that finished
    first deleted the other one's crops in the middle of its photo, which then
    went to 'failed' with some pieces already filed; or one watcher's crop was
    overwritten by the other's between saving it and reading the name, so the
    name of a child in the other class was read for it. Every photo now gets a
    scratch folder of its own, .tmp/<process id>-<random letters>, and only
    that folder is deleted at the end.

    Invented names and painted walls; the name reader is a fake that answers
    by the colour of the file it is handed."""

    def painted_walls(self):
        """A red wall for class A and a blue one for class B, and a name reader
        that answers by the colour of the file it is handed: whoever is handed
        the other class's crop reads the other class's child."""
        from PIL import Image
        Image.new("RGB", (400, 200), self.RED).save(self.wall["a"], quality=95)
        Image.new("RGB", (400, 200), self.BLUE).save(self.wall["b"], quality=95)

        def by_colour(tmp_path, crop):
            with Image.open(tmp_path) as im:
                r, _, b = im.convert("RGB").getpixel((im.width // 2, im.height // 2))
            return [{"text": "Maya" if r > b else "Jonah", "conf": 1.0, "x": 10, "y": 10, "w": 100, "h": 30,
                     "rel_y": 0.05, "angle": 0}]
        bc.read_piece = self.hold_b_at_its_first_crop(by_colour)
        bc.read_neighborhood = lambda *a, **k: []
        bc.read_photo_text = lambda img, path, tmpdir, **k: []

    def test_a_class_finishing_first_does_not_delete_the_other_classs_crops(self):
        self.painted_walls()
        a, b = self.both_at_once(grid=(1, 2))
        self.assertEqual([(r["status"], r["name"]) for r in a], [("confident", "Maya")] * 2)
        self.assertEqual([(r["status"], r["name"]) for r in b], [("confident", "Jonah")] * 2)
        self.assertEqual(self.filed("a", "Maya"), ["Self-Portrait K 2.jpg", "Self-Portrait K.jpg"])
        self.assertEqual(self.filed("b", "Jonah"), ["Self-Portrait K 2.jpg", "Self-Portrait K.jpg"])
        # nothing of one class reached the other class's folders, filed or doubtful
        self.assertEqual(sorted(os.listdir(self.cls["a"])), ["Maya", "Wall Inbox"])
        self.assertEqual(sorted(os.listdir(self.cls["b"])), ["Jonah", "Wall Inbox"])

    def test_no_two_photos_are_ever_handed_the_same_scratch_file(self):
        self.painted_walls()
        self.both_at_once(grid=(1, 2))
        a, b = self.read_from["a"], self.read_from["b"]
        # two pieces each, so two scratch files each. A Windows PC reads each file twice (a paper
        # whose name was read is looked at turned over as well), a Mac once: the files are counted
        self.assertEqual((len(set(a)), len(set(b))), (2, 2))
        self.assertEqual(set(a) & set(b), set(), "two classes wrote their crops to the same file")
        self.assertEqual(len({os.path.dirname(p) for p in a}), 1)
        self.assertEqual(len({os.path.dirname(p) for p in b}), 1)
        self.assertNotEqual(os.path.dirname(a[0]), os.path.dirname(b[0]))
        for p in a + b:
            self.assertEqual(os.path.dirname(os.path.dirname(p)), os.path.join(self.out, ".tmp"))

    def test_the_same_class_twice_in_a_row_gets_a_new_scratch_folder_each_time(self):
        self.painted_walls()
        bc.read_piece = self.hold_b_at_its_first_crop(lambda p, c: [])
        threading.current_thread().name, mine = "a", threading.current_thread().name
        try:
            self.sort("a", self.A_ROSTER, grid=(1, 1))
            self.sort("a", self.A_ROSTER, grid=(1, 1))
        finally:
            threading.current_thread().name = mine
        # a piece whose name was not read is read again turned the other
        # ways, so each sort reads more than once: compare the two sorts
        reads = self.read_from["a"]
        folders = list(dict.fromkeys(os.path.dirname(p) for p in reads))
        self.assertEqual(len(folders), 2, "each sort has one scratch folder of its own")
        self.assertNotEqual(folders[0], folders[1])

    def test_nothing_is_left_behind_when_both_have_finished(self):
        self.painted_walls()
        self.both_at_once(grid=(1, 2))
        self.assertEqual(os.listdir(self.out), [], "the scratch folder is gone once no photo is using it")

    def test_the_scratch_folder_stays_while_another_photo_is_still_using_it(self):
        self.painted_walls()
        seen = []
        held = self.hold_b_at_its_first_crop(lambda p, c: [])

        def read(tmp_path, crop):
            out = held(tmp_path, crop)
            if threading.current_thread().name == "b" and not seen:
                # class A has just finished and cleaned up after itself
                seen.append((os.path.isdir(os.path.dirname(tmp_path)), os.path.exists(tmp_path),
                             os.listdir(os.path.join(self.out, ".tmp"))))
            return out
        bc.read_piece = read
        self.both_at_once(grid=(1, 2))
        folder_there, crop_there, in_scratch = seen[0]
        self.assertTrue(folder_there)
        self.assertTrue(crop_there)
        self.assertEqual(len(in_scratch), 1, "only class B's own folder is left; class A took its own away")

    def test_a_photo_that_cannot_be_sorted_takes_its_scratch_folder_away_too(self):
        self.painted_walls()

        def broken(tmp_path, crop):
            raise RuntimeError("the name reader stopped")
        bc.read_piece = broken
        with self.assertRaises(RuntimeError):
            self.sort("a", self.A_ROSTER, grid=(1, 2))
        self.assertEqual(os.listdir(self.out), [])

    def test_what_a_stopped_watcher_left_behind_is_cleared_and_a_busy_one_is_left_alone(self):
        self.painted_walls()
        bc.read_piece = lambda p, c: []
        scratch = os.path.join(self.out, ".tmp")
        left, busy, loose = (os.path.join(scratch, n) for n in ("4242-left", "4343-busy", "crop-1.png"))
        for d in (left, busy):
            os.makedirs(d)
            with open(os.path.join(d, "crop-1.png"), "wb") as f:
                f.write(b"x")
        with open(loose, "wb") as f:       # from a version that wrote straight into .tmp
            f.write(b"x")
        long_ago = bc.time.time() - bc.SCRATCH_STALE_SECONDS - 60
        for p in (left, loose):
            os.utime(p, (long_ago, long_ago))
        threading.current_thread().name, mine = "a", threading.current_thread().name
        try:
            self.sort("a", self.A_ROSTER, grid=(1, 1))
        finally:
            threading.current_thread().name = mine
        self.assertEqual(os.listdir(scratch), ["4343-busy"])
        self.assertEqual(os.listdir(busy), ["crop-1.png"])

    def test_clearing_old_scratch_never_stops_a_photo(self):
        bc.clear_old_scratch(os.path.join(self.out, "not there"), None)     # no folder: nothing to do
        scratch = os.path.join(self.out, ".tmp")
        os.makedirs(os.path.join(scratch, "4242-left"))
        saved = (bc.os.path.getmtime, bc.os.remove)
        try:
            def gone(p):
                raise FileNotFoundError(p)          # its owner removed it this instant
            bc.os.path.getmtime = gone
            bc.clear_old_scratch(scratch, None)
            self.assertEqual(os.listdir(scratch), ["4242-left"])
            bc.os.path.getmtime = lambda p: 0.0
            with open(os.path.join(scratch, "crop-1.png"), "wb") as f:
                f.write(b"x")

            def refused(p):
                raise PermissionError(p)            # Windows: still open in another program
            bc.os.remove = refused
            bc.clear_old_scratch(scratch, None)
            self.assertEqual(os.listdir(scratch), ["crop-1.png"])
        finally:
            bc.os.path.getmtime, bc.os.remove = saved

    def test_the_scratch_folder_is_made_again_if_another_watcher_removed_it_that_instant(self):
        """Watcher A finishes and removes the empty .tmp between watcher B
        making sure it is there and B making its own folder inside it."""
        real, calls = bc.tempfile.mkdtemp, []

        def mkdtemp(**kw):
            calls.append(kw)
            if len(calls) == 1:
                os.rmdir(kw["dir"])
                raise FileNotFoundError(kw["dir"])
            return real(**kw)
        bc.tempfile.mkdtemp = mkdtemp
        try:
            mine = bc.scratch_folder(self.out)
        finally:
            bc.tempfile.mkdtemp = real
        self.assertEqual(len(calls), 2)
        self.assertTrue(os.path.isdir(mine))
        self.assertEqual(os.path.dirname(mine), os.path.join(self.out, ".tmp"))
        self.assertTrue(os.path.basename(mine).startswith(f"{os.getpid()}-"))

        def never(**kw):
            raise FileNotFoundError(kw["dir"])
        bc.tempfile.mkdtemp = never
        try:
            with self.assertRaises(FileNotFoundError):
                bc.scratch_folder(self.out)
        finally:
            bc.tempfile.mkdtemp = real


class OneScratchFolderPerPhotoOnARealWallTests(TwoClassesOneToolFolder, unittest.TestCase):
    """The same report end to end: two synthetic walls (make_wall.py, invented
    names), the real detectors and the real name reader, two classes sorted
    from one tool folder at the same moment."""

    def setUp(self):
        if not bc.backend_ready():
            self.skipTest("no name reader on this machine")
        super().setUp()
        sys.path.insert(0, HERE)
        from make_wall import make_wall
        self.truth = {}
        for who, names, seed in (("a", self.A_ROSTER, 1), ("b", self.B_ROSTER, 2)):
            img, self.truth[who] = make_wall(names, rows=1, cols=2, size=(1600, 700), seed=seed)
            img.save(self.wall[who], quality=90)
        bc.read_piece = self.hold_b_at_its_first_crop(self.saved[0])

    def each_piece_in_its_own_class_or_its_own_unsorted(self, got):
        """The Windows bar for these two pale walls (outside the contract):
        fail safely, and every piece, filed or not, stays in its own class.
        'Priya' on wall A was read on the build machine (Sep 28, 2026), so
        she carries the proof that a filed piece lands in its own class."""
        other = {"a": "b", "b": "a"}
        for who, res in got.items():
            assert_safe_outside_the_contract(self, res, self.truth[who], f"wall {who}")
            roster = self.A_ROSTER if who == "a" else self.B_ROSTER
            for r in res:
                if r["status"] == "confident":
                    self.assertIn(r["name"], roster)
                    self.assertEqual(self.filed(who, r["name"]), ["Self-Portrait K.jpg"])
                    self.assertEqual(self.filed(other[who], r["name"]), [])
                    self.assertTrue(r["file"].startswith(self.cls[who] + os.sep), r["file"])
                else:
                    self.assertTrue(r["file"].startswith(self.uns[who] + os.sep), r["file"])
            unsorted = [n for n in (os.listdir(self.uns[who]) if os.path.isdir(self.uns[who]) else [])
                        if n.lower().endswith(".jpg")]
            self.assertEqual(len(unsorted), sum(r["status"] != "confident" for r in res), unsorted)
        self.assertIn(("confident", "Priya"), [(r["status"], r["name"]) for r in got["a"]])
        self.assertEqual(self.filed("b", "Priya"), [])
        self.assertEqual(os.listdir(self.out), [])

    def test_two_real_walls_at_once_every_piece_in_its_own_class_under_its_own_child(self):
        a, b = self.both_at_once()
        if bc.IS_WIN:   # Windows record of Sep 28, 2026: 'Maya' not read on wall A (pale, outside the contract)
            return self.each_piece_in_its_own_class_or_its_own_unsorted({"a": a, "b": b})
        self.assertEqual(sorted((r["status"], r["name"]) for r in a), [("confident", n) for n in sorted(self.A_ROSTER)])
        self.assertEqual(sorted((r["status"], r["name"]) for r in b), [("confident", n) for n in sorted(self.B_ROSTER)])
        for child in self.A_ROSTER:
            self.assertEqual(self.filed("a", child), ["Self-Portrait K.jpg"])
            self.assertEqual(self.filed("b", child), [])
        for child in self.B_ROSTER:
            self.assertEqual(self.filed("b", child), ["Self-Portrait K.jpg"])
            self.assertEqual(self.filed("a", child), [])
        self.assertFalse(os.path.exists(self.uns["a"]))
        self.assertFalse(os.path.exists(self.uns["b"]))
        self.assertEqual(os.listdir(self.out), [])


class NoStatusFileIsNotNoComputerTests(unittest.TestCase):
    """Repair (the older version on the classroom computer): a computer running a
    version from before status files sorts every photo and writes no status
    file. A watcher that found no other status file said "no other computer is
    on", and Check Setup listed only itself, so a person was told the other
    computer was off while it was sorting the same class. The log, the
    self-check and the read-me now say what is true: nobody has reported in,
    an older version never does, and only one watcher may run until it has
    this version."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Class")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        os.makedirs(os.path.join(self.cls, "Unsorted - needs a person"))
        self.roster = os.path.join(self.cls, "Class list.txt")
        with open(self.roster, "w") as f:
            f.write("Maya Torres\n")
        self.settings = os.path.join(self.tmp, "settings.json")
        with open(self.settings, "w") as f:
            json.dump({"inbox": self.inbox, "sorted": self.cls, "unsorted": os.path.join(self.cls, "Unsorted - needs a person"),
                       "roster": self.roster, "project": "Self-Portrait", "grade": "Kindergarten", "interval": 1,
                       "priority": 90}, f)
        self.saved = (bc.time.sleep, bc.run_inbox, bc.GRACE_SECONDS)

    def tearDown(self):
        bc.time.sleep, bc.run_inbox, bc.GRACE_SECONDS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            bc.self_check(self.settings)
        return buf.getvalue()

    def test_a_computer_alone_says_nobody_has_reported_in_and_never_that_nobody_is_on(self):
        d = bc.decide_role([], MAC, NOW, started=LONG_AGO)
        self.assertEqual(d["role"], "watching")
        self.assertTrue(d["reason"].startswith("this computer is the control tower for this class (no other computer has reported in)"))
        self.assertNotIn("is on)", d["reason"])
        for phrase in ("older version of Baggage Claim never reports in", "even when it is on and sorting",
                       "stop one of the two until", "the same piece twice"):
            self.assertIn(phrase, d["reason"])

    def test_a_stale_file_from_the_other_computer_is_not_proof_that_it_is_off_either(self):
        old = {"machine": "CLASSROOM-PC", "priority": 50, "epoch": int(NOW - bc.STALE_SECONDS - 5), "role": "watching"}
        d = bc.decide_role([old], MAC, NOW, started=LONG_AGO)
        self.assertEqual(d["role"], "watching")
        self.assertIn("no other computer has reported in", d["reason"])
        self.assertNotIn("no other computer is on", d["reason"])

    def test_a_computer_that_has_reported_in_is_named_and_the_warning_is_not_said(self):
        pc = {"machine": "CLASSROOM-PC", "priority": 95, "epoch": int(NOW - 20), "role": "standing by"}
        d = bc.decide_role([pc], MAC, NOW, started=LONG_AGO)
        self.assertEqual(d["reason"], "this computer is the control tower for this class (CLASSROOM-PC standing by)")

    def test_the_program_no_longer_holds_the_old_sentence(self):
        self.assertNotIn("no other computer is on", read(os.path.join(ROOT, "baggage_claim.py")))

    def test_the_watch_log_says_it_once_and_the_computer_still_sorts(self):
        calls, ticks = [], []
        bc.run_inbox = lambda *a, **k: calls.append(1) or []
        bc.GRACE_SECONDS = 0

        def fake_sleep(s):
            ticks.append(s)
            if len(ticks) >= 3:
                raise KeyboardInterrupt
        bc.time.sleep = fake_sleep
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                bc.main(["--watch", "--settings", self.settings, "--out", self.tmp])
        out = buf.getvalue()
        self.assertEqual(len(calls), 3)
        self.assertEqual(out.count("no other computer has reported in"), 1)
        self.assertEqual(out.count("never reports in, even when it is on and sorting"), 1)
        self.assertNotIn("no other computer is on", out)

    def test_check_setup_says_who_is_missing_from_its_list_when_the_list_is_empty(self):
        if not bc.backend_ready():
            self.skipTest("no name reader on this machine")
        out = self.check()
        self.assertIn("no computer has written a status file yet", out)
        self.assertIn("not in this list: a computer with an older version of Baggage Claim never reports in, "
                      "even when it is on and sorting", out)
        self.assertIn("stop one of the two until", out)

    def test_check_setup_says_it_when_this_computer_is_the_only_one_listed(self):
        if not bc.backend_ready():
            self.skipTest("no name reader on this machine")
        bc.write_status(bc.status_dir(self.cls), bc.machine_name(), bc.time.time() - 10, "watching", 90)
        lines = self.check().splitlines()
        mine = [i for i, ln in enumerate(lines) if "<- this computer" in ln]
        self.assertEqual(len(mine), 1)
        self.assertTrue(lines[mine[0] + 1].strip().startswith("not in this list: a computer with an older version"))

    def test_the_read_me_puts_the_one_watcher_rule_before_the_two_computer_setup(self):
        text = read(os.path.join(ROOT, "README.md"))
        section = " ".join(text.split("### More than one computer")[1].split("### ")[0].split())
        rule = section.index("both must have this version")
        self.assertLess(rule, section.index("Two computers can watch the same class"))
        self.assertLess(section.index("run one control tower only"), section.index("Two computers can watch the same class"))
        for phrase in ("has a file named for it in `Watcher status/`", "every child gets the same piece twice",
                       "`Stop Watcher.command` (Mac) or `Stop Watcher.bat` (Windows)",
                       "(no other computer has reported in)"):
            self.assertIn(phrase, section)
        self.assertNotIn("no other computer is on", text)


# ---- Repair: the Mac zip for a colleague left out autostart.sh and watch.sh ----
import glob as _glob  # noqa: E402
import importlib.util as _importlib_util  # noqa: E402
import plistlib as _plistlib  # noqa: E402
import re as _re  # noqa: E402
import subprocess as _subprocess  # noqa: E402
import zipfile as _zipfile  # noqa: E402
from unittest import mock as _mock  # noqa: E402

NEW_CLASS_TOOL = os.path.join(ROOT, "tools", "new_class.py")
MAC_ZIP_TESTS_CAN_RUN = bool(os.path.exists(NEW_CLASS_TOOL) and shutil.which("zip") and shutil.which("unzip"))
ZIP_FOLDER = "Baggage Claim"


def _write(path, text, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, mode)


def _files_a_script_runs_from_its_own_folder(folder):
    """Every file a .command in this folder names as "$HERE_DIR/<file>"."""
    wanted = set()
    for script in _glob.glob(os.path.join(folder, "*.command")):
        wanted.update(_re.findall(r'"\$HERE_DIR/([^"$/]+)"', read(script)))
    return wanted


class _Built:
    pass


def _build_a_class_and_unzip_the_mac_zip():
    """Run the class tool the way the baggage-check skill does, against a build folder
    made the way the GitHub recipe makes it (the real mac/*.command, mac/autostart.sh
    and watch.sh from this folder, and pretend programs), then do what the colleague
    does: unzip the Mac zip on the Desktop. Every folder is a temporary one."""
    b = _Built()
    b.tmp = os.path.realpath(tempfile.mkdtemp())
    spec = _importlib_util.spec_from_file_location("new_class_under_test", NEW_CLASS_TOOL)
    b.nc = _importlib_util.module_from_spec(spec)
    spec.loader.exec_module(b.nc)

    mac = b.macbuild = os.path.join(b.tmp, "macbuild")
    os.makedirs(mac)
    for src in _glob.glob(os.path.join(ROOT, "mac", "*.command")) + [
            os.path.join(ROOT, "mac", "autostart.sh"), os.path.join(ROOT, "watch.sh")]:
        shutil.copy2(src, mac)
    _write(os.path.join(mac, "baggage-claim"), "#!/bin/zsh\necho '  READY (pretend check)'\nexit 0\n", 0o755)
    _write(os.path.join(mac, "Baggage Claim.app", "Contents", "MacOS", "Baggage Claim"), "#!/bin/zsh\nexit 0\n", 0o755)
    _write(os.path.join(mac, "Baggage Claim Watcher.app", "Contents", "MacOS", "Baggage Claim Watcher"),
           "#!/bin/zsh\nexit 0\n", 0o755)
    for name in ("README.md", "ENGINEERING-NOTES.md", "settings.example.json",
                 "selfcheck-on-build-machine.txt", "tests-on-build-machine.txt"):
        _write(os.path.join(mac, name), "pretend\n")

    win = os.path.join(b.tmp, "winbuild")
    os.makedirs(win)
    for src in _glob.glob(os.path.join(ROOT, "windows", "*.bat")):
        shutil.copy2(src, win)
    for name in ("BaggageClaim.exe", "BaggageClaimWatcher.exe", "SETUP-WINDOWS.md", "settings.example.json"):
        _write(os.path.join(win, name), "pretend\n")

    b.drive = os.path.join(b.tmp, "My Drive")
    os.makedirs(b.drive)
    b.tool_home = os.path.join(b.tmp, "tool home")
    os.makedirs(b.tool_home)
    roster = os.path.join(b.tmp, "roster.txt")
    _write(roster, "Maya Torres\nJordan Lum\n")
    b.class_name = "Grade 1 - Room 4"
    argv = ["new_class.py", "--class-name", b.class_name, "--roster", roster, "--drive-root", b.drive,
            "--exe-dir", win, "--mac-dir", mac]
    buf = io.StringIO()
    # ROOT is where the tool keeps classes/, .private-names and its staging folder: a temporary one here
    with _mock.patch.object(b.nc, "ROOT", b.tool_home), _mock.patch.object(sys, "argv", argv), \
            contextlib.redirect_stdout(buf):
        b.nc.main()
    b.printed = buf.getvalue()
    b.mac_zip = os.path.join(b.drive, b.class_name, "Baggage Claim for Mac.zip")
    b.win_zip = os.path.join(b.drive, b.class_name, "Baggage Claim for Windows.zip")
    b.desktop = os.path.join(b.tmp, "Desktop")
    os.makedirs(b.desktop)
    _subprocess.run(["unzip", "-q", b.mac_zip, "-d", b.desktop], check=True)
    b.folder = os.path.join(b.desktop, ZIP_FOLDER)
    return b


@unittest.skipUnless(MAC_ZIP_TESTS_CAN_RUN, "the class tool (tools/, kept off GitHub) and zip/unzip are needed")
class MacZipForAColleagueTests(unittest.TestCase):
    """The class tool builds "Baggage Claim for Mac.zip" from the GitHub Mac build.
    It kept only the .command files, the .md files, the apps and baggage-claim, so
    the zip had no autostart.sh and no watch.sh. Every .command runs autostart.sh
    from its own folder and tells the tool folder by watch.sh being in it, so on a
    colleague's Mac Setup.command took the Desktop for the tool folder and ended in
    NOT READY. The zip now holds both, and START HERE names the program macOS asks
    about ("Baggage Claim"). The class is invented; every folder is a temporary one."""

    @classmethod
    def setUpClass(cls):
        cls.built = _build_a_class_and_unzip_the_mac_zip()
        for name, value in vars(cls.built).items():
            setattr(cls, name, value)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.built.tmp, ignore_errors=True)

    def test_the_zip_holds_autostart_and_watch_next_to_setup(self):
        with _zipfile.ZipFile(self.mac_zip) as z:
            names = set(z.namelist())
        for name in ("autostart.sh", "watch.sh", "baggage-claim", "Setup.command", "Check Setup.command",
                     "Start Watcher (visible).command", "Stop Watcher.command", "settings.local.json",
                     "START HERE.txt", "Baggage Claim.app/Contents/MacOS/Baggage Claim"):
            self.assertIn(ZIP_FOLDER + "/" + name, names)
        self.assertIn("Baggage Claim for Mac.zip", self.printed)

    def test_every_file_the_four_scripts_run_is_in_the_zip(self):
        wanted = _files_a_script_runs_from_its_own_folder(self.folder)
        self.assertIn("autostart.sh", wanted)      # the scripts really do ask for it
        missing = sorted(n for n in wanted if not os.path.exists(os.path.join(self.folder, n)))
        self.assertEqual(missing, [])
        # and the file that tells each script "this folder is the tool folder"
        for script in _glob.glob(os.path.join(self.folder, "*.command")):
            if 'TOOL="$HERE_DIR"' in read(script):
                self.assertIn('[ -f "$TOOL/watch.sh" ]', read(script))
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "watch.sh")))

    def test_this_test_would_have_caught_the_old_zip(self):
        old_zip = os.path.join(self.tmp, "old.zip")
        self.nc.package(os.path.join(self.tmp, "old stage", ZIP_FOLDER), self.macbuild, {"project": "Artwork"},
                        "start here", old_zip, (".command", ".md", ".app"), keep_names=("baggage-claim",))
        where = os.path.join(self.tmp, "old desktop")
        _subprocess.run(["unzip", "-q", old_zip, "-d", where], check=True)
        old = os.path.join(where, ZIP_FOLDER)
        wanted = _files_a_script_runs_from_its_own_folder(old)
        self.assertEqual(sorted(n for n in wanted if not os.path.exists(os.path.join(old, n))), ["autostart.sh"])
        self.assertFalse(os.path.exists(os.path.join(old, "watch.sh")))

    def test_the_scripts_and_programs_can_still_be_run_after_unzipping(self):
        for name in ("autostart.sh", "watch.sh", "baggage-claim", "Setup.command", "Check Setup.command",
                     "Start Watcher (visible).command", "Stop Watcher.command",
                     os.path.join("Baggage Claim.app", "Contents", "MacOS", "Baggage Claim")):
            self.assertTrue(os.access(os.path.join(self.folder, name), os.X_OK), name)

    def test_the_settings_in_the_zip_are_this_classes(self):
        with open(os.path.join(self.folder, "settings.local.json"), encoding="utf-8") as f:
            s = json.load(f)
        self.assertEqual(s["inbox"], "{DRIVE}/" + self.class_name + "/Arrivals")
        self.assertEqual(s["roster"], "{DRIVE}/" + self.class_name + "/Class list - one first name per line.txt")

    def test_start_here_names_the_program_macos_asks_about(self):
        text = " ".join(read(os.path.join(self.folder, "START HERE.txt")).split())
        # Since September 28, 2026 START HERE names both programs macOS may ask about: the check runs
        # in Terminal before the Baggage Claim helper starts, so a new Mac asks about Terminal first.
        self.assertIn('macOS may ask a few times whether "Terminal" or "Baggage Claim" may access your Desktop folder '
                      'or files in Google Drive. Click Allow every time.', text)
        self.assertNotIn("Baggage Claim Watcher", text)
        self.assertIn("Double-click Setup.command", text)
        self.assertIn("Keep all the files in this folder together", text)
        # the name macOS shows is the helper app's, which autostart.sh writes
        self.assertIn("<key>CFBundleDisplayName</key><string>Baggage Claim</string>",
                      read(os.path.join(ROOT, "mac", "autostart.sh")))

    def test_the_help_names_what_the_mac_folder_must_hold(self):
        buf = io.StringIO()
        with _mock.patch.object(sys, "argv", ["new_class.py", "--help"]), contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit):
                self.nc.main()
        mac_help = " ".join(buf.getvalue().split()).split("--mac-dir")[-1].split("--private")[0]
        for name in ("baggage-claim", "Baggage Claim.app", "autostart.sh", "watch.sh", ".command"):
            self.assertIn(name, mac_help)
        self.assertNotIn("Baggage Claim Watcher", mac_help)

    def test_the_windows_zip_holds_what_it_did_and_nothing_from_the_mac(self):
        with _zipfile.ZipFile(self.win_zip) as z:
            names = {n.split("/", 1)[1] for n in z.namelist() if "/" in n and n.split("/", 1)[1]}
        for name in ("BaggageClaim.exe", "BaggageClaimWatcher.exe", "Setup.bat", "Check Setup.bat",
                     "Start Watcher (visible).bat", "Stop Watcher.bat", "SETUP-WINDOWS.md",
                     "settings.local.json", "START HERE.txt"):
            self.assertIn(name, names)
        self.assertEqual([n for n in names if n.endswith((".sh", ".command", ".app")) or n == "baggage-claim"], [])

    def test_the_class_tool_wrote_only_into_the_folders_it_was_given(self):
        self.assertTrue(os.path.isfile(os.path.join(self.tool_home, "classes", self.class_name + ".json")))
        self.assertIn("Maya Torres", read(os.path.join(self.tool_home, ".private-names")))
        self.assertFalse(os.path.exists(os.path.join(self.tool_home, ".stage")))
        self.assertTrue(os.path.isdir(os.path.join(self.drive, self.class_name, "Maya Torres", "Artwork")))

    def test_an_empty_class_list_stops_the_tool(self):
        empty = os.path.join(self.tmp, "empty.txt")
        _write(empty, "# nobody yet\n")
        argv = ["new_class.py", "--class-name", "Nobody", "--roster", empty, "--drive-root", self.drive]
        with _mock.patch.object(self.nc, "ROOT", self.tool_home), _mock.patch.object(sys, "argv", argv):
            with self.assertRaises(SystemExit) as stop:
                self.nc.main()
        self.assertEqual(str(stop.exception), "roster is empty")
        self.assertFalse(os.path.exists(os.path.join(self.drive, "Nobody")))


@unittest.skipUnless(MAC_ZIP_TESTS_CAN_RUN and sys.platform == "darwin", "Setup.command is a Mac matter")
class SetupFromTheMacZipTests(unittest.TestCase):
    """The report, step by step: build the zip, unzip it on the Desktop, double-click
    Setup.command. launchctl is a stub that writes down what it was asked; the launchd
    folder is a temporary one; BAGGAGE_TEST keeps Setup from stopping any real watcher."""

    def setUp(self):
        self.built = _build_a_class_and_unzip_the_mac_zip()
        self.tmp = self.built.tmp
        self.folder = self.built.folder
        self.desktop = self.built.desktop
        self.agents = os.path.join(self.tmp, "LaunchAgents")
        self.calls = os.path.join(self.tmp, "launchctl-calls.txt")
        stub = os.path.join(self.tmp, "launchctl")
        _write(stub, '#!/bin/zsh\necho "$@" >> "%s"\n'
                     'if [ "$1" = print ]; then grep -q "^bootstrap" "%s" || exit 113; '
                     'echo "\tstate = running"; echo "\tpid = 4242"; fi\nexit 0\n' % (self.calls, self.calls), 0o755)
        self.env = dict(os.environ, BAGGAGE_LAUNCH_AGENTS_DIR=self.agents, BAGGAGE_LAUNCHCTL=stub,
                        BAGGAGE_TEST="1", BAGGAGE_NONINTERACTIVE="1")
        self.plist = os.path.join(self.agents, "com.sahajkashyap.baggage-claim.plist")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_autostart_from_the_unzipped_folder_sets_up_that_folder(self):
        r = _subprocess.run([os.path.join(self.folder, "autostart.sh"), "install", self.folder],
                            capture_output=True, text=True, env=self.env, cwd=self.desktop)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(self.plist, "rb") as f:
            job = _plistlib.load(f)
        self.assertEqual(job["WorkingDirectory"], self.folder)
        self.assertEqual(job["ProgramArguments"],
                         [os.path.join(self.folder, "Baggage Claim.app", "Contents", "MacOS", "Baggage Claim"),
                          "/bin/zsh", os.path.join(self.folder, "watch.sh")])

    @unittest.skipUnless(os.path.isdir("/Applications/Google Drive.app"),
                         "without Google Drive for desktop, Setup stops to download it")
    def test_setup_double_clicked_in_the_unzipped_folder_ends_in_ready(self):
        r = _subprocess.run([os.path.join(self.folder, "Setup.command")], capture_output=True, text=True,
                            env=self.env, cwd=os.path.expanduser("~"), stdin=_subprocess.DEVNULL, timeout=120)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("READY (pretend check)", out)             # the program in the zip did the check
        self.assertIn("The watcher now starts with the Mac", out)
        self.assertIn("  READY. If macOS asks whether Terminal or Baggage Claim may access", out)
        self.assertNotIn("NOT READY", out)
        self.assertNotIn("no such file", out.lower())
        with open(self.plist, "rb") as f:
            job = _plistlib.load(f)
        self.assertEqual(job["WorkingDirectory"], self.folder)   # the folder from the zip, not the Desktop
        self.assertTrue(os.path.isdir(os.path.join(self.folder, "logs")))
        self.assertEqual(sorted(os.listdir(self.desktop)), [ZIP_FOLDER])   # nothing was written beside it
        with open(self.calls) as f:
            self.assertIn("bootstrap gui/%d %s" % (os.getuid(), self.plist), f.read().splitlines())


# ---- Repair: the read-me named Mac files that are not where it said -----------------
OLD_MAC_BULLETS = """## Phone to folders, hands off

- `mac/Setup.command`: sets the watcher up to start with the Mac.
- `Check Setup.command`: says whether the launchd job is loaded.
- `Start Watcher.command`: runs the watcher in a Terminal window.
- `Stop Watcher.command`: stops the watcher and its launchd job.
- On a Windows PC the same four are `Setup.bat`, `Check Setup.bat`,
  `Start Watcher (visible).bat` and `Stop Watcher.bat`.

## Does this already exist?
"""


def _readme_section(text, heading):
    start = text.index(heading)
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else len(text)]


def _names_in_backticks(text, ending):
    """Every `name` in the text that ends the given way. A name may wrap over two lines."""
    flat = " ".join(_re.sub(r"```.*?```", " ", text, flags=_re.S).split())
    return [n for n in _re.findall(r"`([^`]+)`", flat) if n.endswith(ending) and n != ending]


def _mac_files_in_the_bundle(root):
    """The GitHub recipe copies mac/*.command into the bundle, so these are the names a teacher sees."""
    return sorted(os.path.basename(p) for p in _glob.glob(os.path.join(root, "mac", "*.command")))


def _mac_bullet_problems(readme_text, root):
    """What is wrong with the Mac bullets under "Phone to folders", in plain words.
    Each bullet must begin with the name the teacher sees in the one-click bundle and
    say where the same file is in the source folder, and that place must be real."""
    problems, seen = [], []
    in_bundle = _mac_files_in_the_bundle(root)
    for bullet in _re.split(r"\n- ", _readme_section(readme_text, "## Phone to folders, hands off"))[1:]:
        flat = " ".join(bullet.split())
        first = _re.match(r"`([^`]+\.command)`", flat)
        if not first:
            continue
        name = first.group(1)
        seen.append(name)
        if name not in in_bundle:
            problems.append("%s is not a file in the one-click bundle" % name)
        source = _re.match(r"`[^`]+` \(from source: `([^`]+)`", flat)
        if not source:
            problems.append("%s: the bullet does not say where the file is in the source folder" % name)
        elif not os.path.isfile(os.path.join(root, *source.group(1).split("/"))):
            problems.append("%s: the source folder has no %s" % (name, source.group(1)))
    for name in in_bundle:
        if name not in seen:
            problems.append("%s is in the bundle and has no bullet" % name)
    return problems


class MacFilesAreWhereTheReadMeSaysTests(unittest.TestCase):
    """The read-me listed `mac/Setup.command` next to a bare `Check Setup.command` (which is in
    mac/ too) and `Start Watcher.command` (which the one-click bundle does not have: there it is
    `Start Watcher (visible).command`). It also described the bundle as holding a windowless
    `Baggage Claim Watcher.app`, as if that were the watcher; since the launchd change nothing
    starts that app, and the GitHub recipe still built it, so it was the one icon in the folder
    a teacher would double-click. The recipe no longer builds it, the class tool never zips it,
    and every Mac file the read-me or the log names is a file that is really there."""

    README = os.path.join(ROOT, "README.md")
    RECIPE = os.path.join(ROOT, ".github", "workflows", "build-windows.yml")

    def mac_job(self):
        return read(self.RECIPE).split("\n  build-mac:\n", 1)[1]

    def windows_job(self):
        return read(self.RECIPE).split("\n  build-mac:\n", 1)[0]

    def test_each_mac_bullet_names_the_bundle_file_and_its_real_place_in_the_source(self):
        self.assertEqual(_mac_bullet_problems(read(self.README), ROOT), [])

    def test_this_test_would_have_caught_the_old_bullets(self):
        problems = _mac_bullet_problems(OLD_MAC_BULLETS, ROOT)
        self.assertIn("mac/Setup.command is not a file in the one-click bundle", problems)
        self.assertIn("Check Setup.command: the bullet does not say where the file is in the source folder",
                      problems)
        self.assertIn("Start Watcher.command is not a file in the one-click bundle", problems)
        self.assertIn("Start Watcher (visible).command is in the bundle and has no bullet", problems)

    def test_the_bundle_has_the_four_mac_files_the_read_me_lists(self):
        self.assertEqual(_mac_files_in_the_bundle(ROOT),
                         ["Check Setup.command", "Setup.command", "Start Watcher (visible).command",
                          "Stop Watcher.command"])
        self.assertIn("cp mac/*.command mac/autostart.sh watch.sh dist/", self.mac_job())

    def test_every_command_file_the_read_me_names_is_a_real_file(self):
        names = _names_in_backticks(read(self.README), ".command")
        self.assertIn("mac/Check Setup.command", names)
        self.assertIn("Start Watcher (visible).command", names)
        for name in names:
            parts = name.split("/")
            places = [os.path.join(ROOT, *parts)]
            if len(parts) == 1:
                places.append(os.path.join(ROOT, "mac", name))      # a bare name: the bundle, or the top
            self.assertTrue(any(os.path.isfile(p) for p in places), name)

    def test_the_two_files_only_the_source_folder_has_are_said_to_be_at_the_top_of_it(self):
        section = " ".join(_readme_section(read(self.README), "## Phone to folders, hands off").split())
        self.assertIn("or `Start Watcher.command` at the top of the source folder", section)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "Start Watcher.command")))
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "Stop Watcher.command")))
        self.assertNotIn("Start Watcher.command", _mac_files_in_the_bundle(ROOT))

    def test_the_mac_recipe_no_longer_builds_the_watcher_app(self):
        job = self.mac_job()
        self.assertNotIn("Baggage Claim Watcher", job)
        self.assertNotIn("--windowed", job)
        self.assertNotIn("watcher_entry.py", job)
        # what launchd runs is still built and still copied into the bundle
        self.assertIn("zsh mac/autostart.sh build .", job)
        self.assertIn('cp -R "Baggage Claim.app" dist/', job)
        self.assertIn("pyinstaller --onefile --name baggage-claim ", job)
        self.assertIn("name: BaggageClaim-mac", job)

    def test_the_windows_recipe_still_builds_its_two_programs(self):
        job = self.windows_job()
        self.assertIn("pyinstaller --onefile --name BaggageClaim ", job)
        self.assertIn("--noconsole --name BaggageClaimWatcher ", job)
        self.assertIn("watcher_entry.py", job)
        self.assertIn("Copy-Item windows\\*.bat dist\\", job)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "watcher_entry.py")))
        self.assertIn("BaggageClaimWatcher.exe", read(os.path.join(ROOT, "windows", "Setup.bat")))

    def test_nothing_on_the_mac_starts_the_old_app(self):
        for name in _mac_files_in_the_bundle(ROOT) + ["autostart.sh"]:
            text = read(os.path.join(ROOT, "mac", name))
            self.assertNotIn("Baggage Claim Watcher.app", text, name)
            self.assertNotIn('open "', text, name)
        self.assertNotIn("Baggage Claim Watcher", read(os.path.join(ROOT, "watch.sh")))
        # Setup still stops an old one that is running, and the job runs the helper app
        autostart = read(os.path.join(ROOT, "mac", "autostart.sh"))
        self.assertIn('pkill -f "Baggage Claim Watcher"', autostart)
        self.assertIn('APP_NAME="Baggage Claim.app"', autostart)

    def test_the_read_me_says_the_old_app_is_gone_and_what_the_helper_app_is_for(self):
        text = " ".join(read(self.README).split())
        self.assertNotIn("and a windowless `Baggage Claim Watcher.app`", text)
        self.assertNotIn("both with Python and the Vision helper inside", text)
        sentences = [s for s in _re.split(r"(?<=[.;:]) ", text) if "Baggage Claim Watcher.app" in s]
        self.assertEqual(len(sentences), 2, sentences)
        self.assertIn("There is no `Baggage Claim Watcher.app` any more", sentences[0])
        self.assertIn("Bundles made before September 26, 2026 also held", sentences[1])
        self.assertIn("It is no longer built and nothing starts it.", text)
        self.assertIn("one program, `baggage-claim`, with Python and the Vision helper inside", text)
        self.assertIn("`Baggage Claim.app`. It is not for double-clicking", text)
        self.assertIn("`Setup.command` is the one to double-click", text)

    def test_the_permission_sentence_in_the_log_names_no_file_the_bundle_lacks(self):
        with _mock.patch.object(bc.os, "listdir", side_effect=PermissionError("Operation not permitted")):
            with self.assertRaises(PermissionError) as refused:
                bc.inbox_jobs(os.path.join("My Drive", "Grade 1 - Room 4", "Wall Inbox"), "Artwork")
        said = str(refused.exception)
        # Check Setup looks for these words in the log before it prints PERMISSION NEEDED
        self.assertTrue(said.startswith("macOS is not letting this program read the inbox folder."), said)
        self.assertIn("macOS is not letting this program read", read(os.path.join(ROOT, "mac", "autostart.sh")))
        self.assertNotIn("Start Watcher.command", said)
        for name in _re.findall(r"'([^']+\.command)'", said):
            self.assertIn(name, _mac_files_in_the_bundle(ROOT))
        self.assertIn("find Baggage Claim, and turn Google Drive on", said)
        self.assertTrue(said.endswith(os.path.join("Grade 1 - Room 4", "Wall Inbox")), said)


@unittest.skipUnless(MAC_ZIP_TESTS_CAN_RUN, "the class tool (tools/, kept off GitHub) and zip/unzip are needed")
class OldWatcherAppStaysOutOfTheMacZipTests(unittest.TestCase):
    """A build folder from before the change still holds the old app (the pretend build
    folder these tests use has one). The zip a teacher gets must not: the helper app is
    the only app in it, and START HERE lists only files that are in the folder."""

    @classmethod
    def setUpClass(cls):
        cls.built = _build_a_class_and_unzip_the_mac_zip()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.built.tmp, ignore_errors=True)

    def test_the_build_folder_had_the_old_app_and_the_zip_does_not(self):
        self.assertTrue(os.path.isdir(os.path.join(self.built.macbuild, "Baggage Claim Watcher.app")))
        with _zipfile.ZipFile(self.built.mac_zip) as z:
            self.assertEqual([n for n in z.namelist() if "Baggage Claim Watcher" in n], [])
        self.assertEqual(sorted(n for n in os.listdir(self.built.folder) if n.endswith(".app")),
                         ["Baggage Claim.app"])

    def test_every_command_file_start_here_names_is_in_the_folder(self):
        text = read(os.path.join(self.built.folder, "START HERE.txt"))
        named = set(_re.findall(r"(?m)^((?:Check Setup|Start Watcher \(visible\)|Stop Watcher|Setup)\.command)\s",
                                text)) | set(_re.findall(r"Double-click\s+(Setup\.command)", text))
        self.assertEqual(sorted(named), ["Check Setup.command", "Setup.command",
                                         "Start Watcher (visible).command", "Stop Watcher.command"])
        for name in named:
            self.assertTrue(os.path.isfile(os.path.join(self.built.folder, name)), name)
        self.assertNotIn("Start Watcher.command", text)
        self.assertNotIn("Baggage Claim Watcher", text)

    def test_leaving_nothing_out_would_have_put_the_old_app_in_the_zip(self):
        old_zip = os.path.join(self.built.tmp, "with the old app.zip")
        self.built.nc.package(os.path.join(self.built.tmp, "old app stage", ZIP_FOLDER), self.built.macbuild,
                              {"project": "Artwork"}, "start here", old_zip, self.built.nc.MAC_KEEP_EXTS,
                              keep_names=self.built.nc.MAC_KEEP_NAMES)
        with _zipfile.ZipFile(old_zip) as z:
            self.assertTrue([n for n in z.namelist() if "Baggage Claim Watcher.app" in n])


# ---- Repair: a second class on the same Mac was watched by a nohup line ------------
#
# The launchd job runs watch.sh, and watch.sh only ever read settings.local.json. For
# any other class the class tool printed a "nohup ... &" line: a watcher started that
# way ends when the Mac restarts, nothing starts it again, and Check Setup did not
# notice. Now every class a Mac watches has a launchd job of its own
# (autostart.sh install <tool folder> <settings file>), watch.sh takes the settings
# file and the log, Check Setup lists every class with and without a watcher, and the
# class tool prints the install line. Invented classes, temporary folders, a stub
# launchctl; nothing here touches the real LaunchAgents folder or a real watcher.

import shlex as _shlex  # noqa: E402
import time as _time  # noqa: E402

AUTOSTART_SH = os.path.join(ROOT, "mac", "autostart.sh")
WATCH_SH = os.path.join(ROOT, "watch.sh")
FIRST_LABEL = "com.sahajkashyap.baggage-claim"
IS_A_MAC = sys.platform == "darwin"


def _class_settings(class_name):
    return {"inbox": "{DRIVE}/" + class_name + "/Wall Inbox", "sorted": "{DRIVE}/" + class_name,
            "unsorted": "{DRIVE}/" + class_name + "/Unsorted - needs a person",
            "roster": "{DRIVE}/" + class_name + "/Class list - one first name per line.txt",
            "project": "Artwork", "grade": "", "interval": 5}


class _AMacWithTwoClasses:
    """A pretend Baggage Claim folder on a pretend Mac. settings.local.json is the
    kindergarten class; classes/ holds the settings the class tool wrote: the same
    kindergarten class again, and two more classes."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.tool = os.path.join(self.tmp, "Baggage Claim")
        os.makedirs(os.path.join(self.tool, "classes"))
        shutil.copy2(WATCH_SH, self.tool)
        _write(os.path.join(self.tool, "Baggage Claim.app", "Contents", "MacOS", "Baggage Claim"),
               "#!/bin/zsh\nexit 0\n", 0o755)
        _write(os.path.join(self.tool, "settings.local.json"),
               json.dumps(dict(_class_settings("Kindergarten - Room 1"), priority=90), indent=2))
        self.same_as_first = self.settings_file("Kindergarten - Room 1")
        self.room4 = self.settings_file("Grade 1 - Room 4")
        self.room7 = self.settings_file("Maya & Jordan's 5-6")
        self.agents = os.path.join(self.tmp, "LaunchAgents")
        self.calls = os.path.join(self.tmp, "launchctl-calls.txt")
        stub = os.path.join(self.tmp, "launchctl")
        # "print <job>" says loaded only when that very job was started last, not any job
        _write(stub, '#!/bin/zsh\necho "$@" >> "%(calls)s"\n'
                     'if [ "$1" = print ]; then\n'
                     '  label="${2:t}"\n'
                     '  last="$(grep -E "^(bootstrap .*/${label}\\.plist|bootout .*/${label})$" "%(calls)s" | tail -1)"\n'
                     '  [[ "$last" == bootstrap* ]] || exit 113\n'
                     '  echo "\tstate = running"; echo "\tpid = 4242"\n'
                     'fi\nexit 0\n' % {"calls": self.calls}, 0o755)
        self.env = dict(os.environ, BAGGAGE_LAUNCH_AGENTS_DIR=self.agents, BAGGAGE_LAUNCHCTL=stub,
                        BAGGAGE_TEST="1", BAGGAGE_LAUNCHD="")
        self.first_plist = os.path.join(self.agents, FIRST_LABEL + ".plist")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def settings_file(self, class_name):
        path = os.path.join(self.tool, "classes", class_name + ".json")
        _write(path, json.dumps(_class_settings(class_name), indent=2))
        return path

    def autostart(self, *args, cwd=None):
        return _subprocess.run(["/bin/zsh", AUTOSTART_SH, *args], capture_output=True, text=True,
                               env=self.env, cwd=cwd or self.tmp, timeout=60)

    def job(self, *args):
        r = self.autostart("render", self.tool, *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return _plistlib.loads(r.stdout.encode("utf-8"))

    def job_files(self):
        return sorted(os.listdir(self.agents)) if os.path.isdir(self.agents) else []

    def launchctl_calls(self):
        return read(self.calls).splitlines() if os.path.exists(self.calls) else []


@unittest.skipUnless(IS_A_MAC, "launchd jobs are a Mac matter")
class SecondClassOnTheSameMacTests(_AMacWithTwoClasses, unittest.TestCase):

    # -- the job file ------------------------------------------------------------

    def test_the_first_class_has_the_job_it_always_had(self):
        d = self.job()
        self.assertEqual(d["Label"], FIRST_LABEL)
        self.assertEqual(d["ProgramArguments"][-2:], ["/bin/zsh", os.path.join(self.tool, "watch.sh")])
        self.assertEqual(d["EnvironmentVariables"], {"BAGGAGE_LAUNCHD": "1"})
        # naming settings.local.json itself is the first class, not a second job for the same class
        self.assertEqual(self.job(os.path.join(self.tool, "settings.local.json")), d)

    def test_a_second_class_has_a_job_of_its_own_that_names_its_settings_and_its_log(self):
        d = self.job(self.room4)
        self.assertTrue(d["Label"].startswith(FIRST_LABEL + ".class.grade-1-room-4-"), d["Label"])
        self.assertEqual(d["ProgramArguments"],
                         [os.path.join(self.tool, "Baggage Claim.app", "Contents", "MacOS", "Baggage Claim"),
                          "/bin/zsh", os.path.join(self.tool, "watch.sh"),
                          self.room4, os.path.join(self.tool, "logs", "Grade 1 - Room 4.log")])
        self.assertEqual(d["WorkingDirectory"], self.tool)
        self.assertIs(d["RunAtLoad"], True)       # it starts at login
        self.assertIs(d["KeepAlive"], True)       # and is started again if it stops
        self.assertEqual(d["ThrottleInterval"], 30)
        self.assertEqual(d["EnvironmentVariables"], {"BAGGAGE_LAUNCHD": "1", "BAGGAGE_SETTINGS": self.room4})

    def test_a_class_name_with_an_ampersand_and_an_apostrophe_survives(self):
        d = self.job(self.room7)
        self.assertEqual(d["ProgramArguments"][-2:],
                         [self.room7, os.path.join(self.tool, "logs", "Maya & Jordan's 5-6.log")])
        self.assertRegex(d["Label"], r"^com\.sahajkashyap\.baggage-claim\.class\.[a-z0-9-]+$")

    def test_two_classes_never_share_a_job(self):
        labels = {self.job()["Label"], self.job(self.room4)["Label"], self.job(self.room7)["Label"],
                  self.job(self.settings_file("Grade 1 _ Room 4"))["Label"],
                  self.job(self.settings_file("Grade 1 Room 4"))["Label"]}
        self.assertEqual(len(labels), 5, labels)

    def test_a_settings_file_given_from_inside_the_folder_is_made_absolute(self):
        r = self.autostart("render", ".", "classes/Grade 1 - Room 4.json", cwd=self.tool)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(_plistlib.loads(r.stdout.encode("utf-8"))["ProgramArguments"][-2], self.room4)

    def test_a_settings_file_that_is_not_there_is_refused_in_plain_words(self):
        r = self.autostart("install", self.tool, os.path.join(self.tool, "classes", "Nobody.json"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("There is no settings file at", r.stderr)
        self.assertIn("nothing was changed", r.stderr)
        self.assertEqual(self.job_files(), [])
        self.assertEqual([c for c in self.launchctl_calls() if c.startswith("bootstrap")], [])

    # -- install -----------------------------------------------------------------

    def test_install_for_a_second_class_adds_its_job_and_leaves_the_first_alone(self):
        self.assertEqual(self.autostart("install", self.tool).returncode, 0)
        with open(self.first_plist, "rb") as f:
            first_before = f.read()
        r = self.autostart("install", self.tool, self.room4)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        label = self.job(self.room4)["Label"]
        self.assertEqual(self.job_files(), sorted([FIRST_LABEL + ".plist", label + ".plist"]))
        with open(os.path.join(self.agents, label + ".plist"), "rb") as f:
            self.assertEqual(_plistlib.load(f), self.job(self.room4))
        with open(self.first_plist, "rb") as f:
            self.assertEqual(f.read(), first_before)
        uid = os.getuid()
        calls = self.launchctl_calls()
        self.assertIn("bootstrap gui/%d %s" % (uid, os.path.join(self.agents, label + ".plist")), calls)
        self.assertEqual(calls.count("bootout gui/%d/%s" % (uid, FIRST_LABEL)), 1)   # only its own install
        self.assertIn("The watcher for the class 'Grade 1 - Room 4' now starts with the Mac", r.stdout)
        self.assertIn("logs/Grade 1 - Room 4.log", r.stdout)

    def test_a_second_watcher_for_the_class_in_settings_local_json_is_refused(self):
        r = self.autostart("install", self.tool, self.same_as_first)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("This Mac already watches that class: settings.local.json names the same Wall Inbox", r.stderr)
        self.assertIn("file every piece twice", r.stderr)
        self.assertEqual(self.job_files(), [])
        self.assertEqual(self.launchctl_calls(), [])

    def test_a_second_job_for_a_class_that_already_has_one_is_refused(self):
        self.assertEqual(self.autostart("install", self.tool, self.room4).returncode, 0)
        copy = os.path.join(self.tmp, "a copy of room 4.json")
        shutil.copy2(self.room4, copy)
        r = self.autostart("install", self.tool, copy)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("names the same Wall Inbox", r.stderr)
        self.assertEqual(len(self.job_files()), 1)
        # setting the same class up again is not a second watcher: it replaces its own job
        self.assertEqual(self.autostart("install", self.tool, self.room4).returncode, 0)
        self.assertEqual(len(self.job_files()), 1)

    # -- Check Setup ---------------------------------------------------------------

    def test_check_setup_names_the_class_nobody_watches_and_how_to_watch_it(self):
        self.autostart("install", self.tool)
        out = self.autostart("status", self.tool).stdout
        for name in ("Grade 1 - Room 4", "Maya & Jordan's 5-6"):
            self.assertIn("The class '%s' has a settings file on this Mac, and this Mac does NOT watch it" % name, out)
        self.assertIn("none starts at login", out)
        # the line it gives is the line that works: run it as printed
        line = [ln for ln in out.splitlines() if "Grade 1 - Room 4.json" in ln][0].split("run:", 1)[1]
        words = _shlex.split(line)
        self.assertEqual(words[1:], ["install", self.tool, self.room4])
        self.assertEqual(os.path.realpath(words[0]), os.path.realpath(AUTOSTART_SH))
        r = _subprocess.run(words, capture_output=True, text=True, env=self.env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.autostart("status", self.tool).stdout
        self.assertIn("This Mac also watches the class 'Grade 1 - Room 4':", out)
        self.assertNotIn("The class 'Grade 1 - Room 4' has a settings file", out)
        self.assertIn("The class 'Maya & Jordan's 5-6' has a settings file", out)

    def test_check_setup_does_not_call_the_first_class_unwatched(self):
        # classes/ holds a second settings file for the class in settings.local.json
        out = self.autostart("status", self.tool).stdout
        self.assertNotIn("Kindergarten - Room 1", out)

    def test_check_setup_says_for_each_class_whether_its_own_job_is_loaded(self):
        self.autostart("install", self.tool)
        self.autostart("install", self.tool, self.room4)
        label = self.job(self.room4)["Label"]
        os.makedirs(os.path.join(self.tool, "logs"), exist_ok=True)
        _write(os.path.join(self.tool, "logs", "Grade 1 - Room 4.log"),
               "Sep 26 03:08 PM: 8 pieces, 7 filed, 1 to unsorted\n")
        r = self.autostart("status", self.tool)
        first, second = r.stdout.split("This Mac also watches the class 'Grade 1 - Room 4':")
        self.assertIn("launchd job %s is loaded" % FIRST_LABEL, first)
        self.assertIn("launchd job %s is loaded" % label, second)
        self.assertIn("8 pieces, 7 filed", second)              # its own log, not watch.log
        self.assertNotIn("8 pieces, 7 filed", first)
        # its job is stopped behind the tool's back: the first class is still fine, this one is not
        with open(self.calls, "a") as f:
            f.write("bootout gui/%d/%s\n" % (os.getuid(), label))
        r = self.autostart("status", self.tool)
        first, second = r.stdout.split("This Mac also watches the class 'Grade 1 - Room 4':")
        self.assertIn("Starts with the Mac: yes", first)
        self.assertIn("Starts with the Mac: NO", second)
        self.assertIn("install", second)
        self.assertNotEqual(r.returncode, 0)

    def test_a_watcher_alive_for_one_class_is_not_counted_for_another(self):
        """Before, any watcher process on the Mac made Check Setup say 'Watching right
        now: yes'. Run the second class's job the way launchd does (with a pretend
        program that only waits) and ask about both classes."""
        _write(os.path.join(self.tool, "baggage-claim"), "#!/bin/zsh\nsleep 60\n", 0o755)
        self.autostart("install", self.tool, self.room4)
        self.autostart("install", self.tool, self.room7)
        args = self.job(self.room4)["ProgramArguments"][1:]      # past the helper app, which is a stub here
        watcher = _subprocess.Popen(args, cwd=self.tool, env=self.env, stdout=_subprocess.DEVNULL,
                                    stderr=_subprocess.DEVNULL)
        try:
            for _ in range(50):
                out = self.autostart("status", self.tool).stdout
                room4 = out.split("'Grade 1 - Room 4':")[1].split("This Mac also watches")[0]
                if "Watching right now: yes" in room4:
                    break
                _time.sleep(0.1)
            self.assertIn("Watching right now: yes (process %d)" % watcher.pid, room4)
            room7 = out.split("'Maya & Jordan's 5-6':")[1].split("This Mac also watches")[0]
            self.assertIn("Watching right now: NO", room7)
        finally:
            watcher.kill()
            watcher.wait()

    def test_a_watcher_started_by_hand_is_called_what_it_is(self):
        _write(os.path.join(self.tool, "baggage-claim"), "#!/bin/zsh\nsleep 60\n", 0o755)
        by_hand = _subprocess.Popen(["/bin/zsh", "./baggage-claim", "--watch", "--settings", self.room4,
                                     "--log", "logs/Grade 1 - Room 4.log"], cwd=self.tool,
                                    stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL)
        try:
            for _ in range(50):
                out = self.autostart("status", self.tool).stdout
                if "started by hand" in out:
                    break
                _time.sleep(0.1)
            self.assertIn("a watcher started by hand is running for it now (process %d)" % by_hand.pid, out)
            self.assertIn("nothing starts it again", out)
        finally:
            by_hand.kill()
            by_hand.wait()

    # -- Stop Watcher --------------------------------------------------------------

    def test_stop_watcher_stops_every_class_and_says_how_to_bring_each_back(self):
        self.autostart("install", self.tool)
        self.autostart("install", self.tool, self.room4)
        label = self.job(self.room4)["Label"]
        r = self.autostart("remove")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.job_files(), [])
        uid = os.getuid()
        self.assertIn("bootout gui/%d/%s" % (uid, label), self.launchctl_calls())
        self.assertIn("Watcher for the class 'Grade 1 - Room 4' stopped", r.stdout)
        self.assertIn("Double-click Setup.command to turn it back on", r.stdout)
        line = [ln for ln in r.stdout.splitlines() if "run:" in ln][0].split("run:", 1)[1]
        self.assertEqual(_shlex.split(line)[1:], ["install", self.tool, self.room4])
        self.assertNotEqual(self.autostart("status", self.tool).returncode, 0)

    def test_one_class_can_be_stopped_without_stopping_the_others(self):
        self.autostart("install", self.tool)
        self.autostart("install", self.tool, self.room4)
        r = self.autostart("remove", self.tool, self.room4)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.job_files(), [FIRST_LABEL + ".plist"])
        self.assertEqual(self.launchctl_calls().count("bootout gui/%d/%s" % (os.getuid(), FIRST_LABEL)), 1)
        self.assertEqual(self.autostart("loaded").returncode, 0)
        r = self.autostart("remove", self.tool, self.room7)
        self.assertIn("This Mac has no watcher job for the class 'Maya & Jordan's 5-6'", r.stdout)
        self.assertEqual(self.job_files(), [FIRST_LABEL + ".plist"])

    # -- watch.sh ------------------------------------------------------------------

    def run_the_job(self, *args):
        """watch.sh as the job runs it, with a pretend program that writes down what it was given."""
        given = os.path.join(self.tmp, "given.txt")
        _write(os.path.join(self.tool, "baggage-claim"),
               '#!/bin/zsh\nprint -rl -- "$@" > "%s"\n' % given, 0o755)
        r = _subprocess.run(["/bin/zsh", os.path.join(self.tool, "watch.sh"), *args], capture_output=True,
                            text=True, env=self.env, cwd=self.tmp, timeout=60)
        return r, (read(given).splitlines() if os.path.exists(given) else None)

    def test_the_job_for_a_second_class_watches_that_class_and_writes_its_own_log(self):
        d = self.job(self.room4)
        r, given = self.run_the_job(*d["ProgramArguments"][3:])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(given, ["--watch", "--settings", self.room4,
                                 "--log", os.path.join(self.tool, "logs", "Grade 1 - Room 4.log")])

    def test_the_first_job_still_watches_settings_local_json(self):
        r, given = self.run_the_job()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(given, ["--watch", "--settings", "settings.local.json", "--log", "logs/watch.log"])

    def test_a_missing_settings_file_is_explained_in_that_class_s_log(self):
        d = self.job(self.room4)
        os.remove(self.room4)
        r, given = self.run_the_job(*d["ProgramArguments"][3:])
        self.assertEqual(r.returncode, 1)
        self.assertIsNone(given)                                  # nothing was started
        text = read(os.path.join(self.tool, "logs", "Grade 1 - Room 4.log"))
        self.assertIn("The settings file for this class is missing, so there is nothing to watch", text)
        self.assertIn(self.room4, text)
        self.assertFalse(os.path.exists(os.path.join(self.tool, "logs", "watch.log")))

    # -- the words -----------------------------------------------------------------

    def test_the_read_me_says_which_class_the_job_covers_and_how_to_add_another(self):
        text = " ".join(read(os.path.join(ROOT, "README.md")).split())
        self.assertFalse("one machine can watch several classes" in text,
                         "the read-me still says one machine can watch several classes, with no word on how")
        section = " ".join(_readme_section(read(os.path.join(ROOT, "README.md")),
                                           "### One Mac, more than one class").split())
        self.assertIn("`Setup.command` starts one control tower, for the class in `settings.local.json`", section)
        self.assertIn("autostart.sh install", section)
        self.assertIn("`Check Setup.command`", section)
        self.assertIn("`Stop Watcher.command`", section)
        self.assertIn("ends when the Mac restarts", section)
        self.assertIn("A Windows PC watches one class", text)

    def test_no_script_tells_anyone_to_start_a_watcher_with_nohup(self):
        for path in [AUTOSTART_SH, WATCH_SH] + _glob.glob(os.path.join(ROOT, "mac", "*.command")) \
                + _glob.glob(os.path.join(ROOT, "*.command")) + _glob.glob(os.path.join(ROOT, "tools", "*.py")):
            for line in read(path).splitlines():
                if "nohup" in line and "--watch" in line:
                    self.fail("%s still gives a nohup line: %s" % (os.path.basename(path), line.strip()))


@unittest.skipUnless(IS_A_MAC and MAC_ZIP_TESTS_CAN_RUN,
                     "a Mac, the class tool (tools/, kept off GitHub) and zip/unzip are needed")
class ClassToolPrintsALineThatSurvivesARestartTests(unittest.TestCase):
    """The report, step by step: check a new class in with the class tool, do what it
    prints, and look at what this Mac will start at login."""

    def setUp(self):
        self.built = _build_a_class_and_unzip_the_mac_zip()
        self.tmp = self.built.tmp
        home = self.built.tool_home                   # the tool folder the class tool believed it was in
        shutil.copytree(os.path.join(ROOT, "mac"), os.path.join(home, "mac"))
        shutil.copy2(WATCH_SH, home)
        self.agents = os.path.join(self.tmp, "LaunchAgents")
        self.calls = os.path.join(self.tmp, "launchctl-calls.txt")
        stub = os.path.join(self.tmp, "launchctl")
        _write(stub, '#!/bin/zsh\necho "$@" >> "%s"\nexit 0\n' % self.calls, 0o755)
        self.env = dict(os.environ, BAGGAGE_LAUNCH_AGENTS_DIR=self.agents, BAGGAGE_LAUNCHCTL=stub,
                        BAGGAGE_TEST="1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_class_tool_prints_no_nohup_line(self):
        self.assertNotIn("nohup", self.built.printed)
        self.assertNotIn(" &\n", self.built.printed + "\n")
        self.assertIn("to have THIS Mac watch this class", self.built.printed)
        self.assertIn("skip that line if another computer watches this class", self.built.printed)

    def test_the_line_it_prints_gives_the_class_a_job_that_starts_at_login(self):
        lines = self.built.printed.splitlines()
        line = lines[lines.index([ln for ln in lines if ln.startswith("to have THIS Mac watch")][0]) + 1]
        words = _shlex.split(line)
        settings = os.path.join(self.built.tool_home, "classes", self.built.class_name + ".json")
        self.assertEqual(words, [os.path.join(self.built.tool_home, "mac", "autostart.sh"), "install",
                                 self.built.tool_home, settings])
        r = _subprocess.run(words, capture_output=True, text=True, env=self.env, cwd=os.path.expanduser("~"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        made = os.listdir(self.agents)
        self.assertEqual(len(made), 1, made)
        with open(os.path.join(self.agents, made[0]), "rb") as f:
            job = _plistlib.load(f)
        self.assertEqual(job["ProgramArguments"][-2:],
                         [settings, os.path.join(self.built.tool_home, "logs", self.built.class_name + ".log")])
        self.assertIs(job["RunAtLoad"], True)
        self.assertIs(job["KeepAlive"], True)
        self.assertIn("bootstrap gui/%d %s" % (os.getuid(), os.path.join(self.agents, made[0])),
                      read(self.calls).splitlines())


# ---- Repair: a class shared with a computer that has never reported in ----
class _ASharedClass:
    """A class folder watched by this computer (the helper's Mac, priority 90)
    and, the settings say, by another one. The other one is played by
    old_pc_sorts(): what a build from before status files does with a photo.
    It files the piece, moves the photo to done, and writes no status file.
    The clock is faked, so ten minutes is eleven ticks and nothing waits.
    process_photo is replaced by a fake that saves one empty file under the
    invented child; no photo is opened."""

    PIECE = "Self-Portrait Kindergarten.jpg"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Class")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        os.makedirs(os.path.join(self.cls, "Unsorted - needs a person"))
        self.roster = os.path.join(self.cls, "Class list.txt")
        with open(self.roster, "w") as f:
            f.write("Maya Torres\n")
        self.settings = os.path.join(self.tmp, "settings.json")
        self.write_settings(shared=True)
        self.child = os.path.join(self.cls, "Maya Torres", "Self-Portrait")
        self.saved = (bc.time.time, bc.time.sleep, bc.is_settled, bc.process_photo, bc.GRACE_SECONDS)
        real_time = self.saved[0]
        self.offset = 0.0
        bc.time.time = lambda: real_time() + self.offset
        bc.is_settled = lambda p, wait=0: True
        bc.GRACE_SECONDS = 0
        self.ticks = []
        self.cut_at = []        # how far the fake clock had run each time THIS computer cut a photo
        self.status_at = {}

        def fake_process_photo(path, roster, out_dir, project, grid=None, log=print, grade="", sorted_dir=None,
                               unsorted_dir=None):
            self.cut_at.append(self.offset)
            folder = os.path.join(sorted_dir, "Maya Torres", project)
            os.makedirs(folder, exist_ok=True)
            saved_as = os.path.join(folder, bc.piece_name(project, grade, folder))
            open(saved_as, "w").close()
            return [{"piece": 1, "status": "confident", "name": "Maya Torres", "text": "Maya", "score": 1.0,
                     "margin": 1.0, "box": None, "file": saved_as, "bbox": (0, 0, 1, 1)}]
        bc.process_photo = fake_process_photo

    def tearDown(self):
        bc.time.time, bc.time.sleep, bc.is_settled, bc.process_photo, bc.GRACE_SECONDS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_settings(self, **more):
        st = {"inbox": self.inbox, "sorted": self.cls, "unsorted": os.path.join(self.cls, "Unsorted - needs a person"),
              "roster": self.roster, "project": "Self-Portrait", "grade": "Kindergarten", "interval": 60,
              "priority": 90}
        st.update(more)
        with open(self.settings, "w") as f:
            json.dump(st, f)

    def drop_photo(self, name="wall.jpg"):
        with open(os.path.join(self.inbox, name), "wb") as f:
            f.write(b"\xff\xd8 not really a jpeg")

    def old_pc_sorts(self, name="wall.jpg"):
        """The classroom computer with the older version: its own copy of the
        inbox still holds the photo, so it files its piece whatever this
        computer did. It checks for a file of the same name only in its own
        copy of the folder, so both computers choose the same name and Google
        Drive keeps the second one as '... (1).jpg'. Then it moves the photo
        to done. It never writes a status file."""
        os.makedirs(self.child, exist_ok=True)
        theirs = self.PIECE if not os.path.exists(os.path.join(self.child, self.PIECE)) \
            else self.PIECE.replace(".jpg", " (1).jpg")
        open(os.path.join(self.child, theirs), "w").close()
        src = os.path.join(self.inbox, name)
        if os.path.exists(src):
            os.makedirs(os.path.join(self.inbox, "done"), exist_ok=True)
            shutil.move(src, os.path.join(self.inbox, "done", name))

    def pieces(self):
        return sorted(os.listdir(self.child)) if os.path.isdir(self.child) else []

    def status_text(self):
        try:
            return read(os.path.join(self.cls, "Watcher status", bc.machine_name() + ".txt"))
        except OSError:
            return ""

    def run_main(self, on_tick=lambda n: None, stop_after=3, more_args=()):
        def fake_sleep(s):
            self.ticks.append(s)
            n = len(self.ticks)
            self.status_at[n] = self.status_text()
            on_tick(n)
            self.offset += s
            if n >= stop_after:
                raise KeyboardInterrupt
        bc.time.sleep = fake_sleep
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                bc.main(["--watch", "--settings", self.settings, "--out", self.tmp] + list(more_args))
        return buf.getvalue()


class SharedClassWithAnOlderVersionTests(_ASharedClass, unittest.TestCase):
    """Repair: two computers sorted the same photo. The classroom computer ran
    a build from before status files, so it sorted every photo and never
    reported in; the helper's Mac found nobody in 'Watcher status', took
    itself for the only watcher and sorted too. Every child had the piece
    twice, under one name. Noticing afterwards is too late for the first
    photo of every day. Now the settings file can say the class is shared
    ("shared": true). While the other computer has never reported in, this
    one leaves each new photo for it for SHARED_WAIT_SECONDS and sorts the
    photo only if it is still in the inbox after that."""

    def test_the_repro_both_computers_on_the_child_gets_the_piece_once(self):
        self.drop_photo()
        out = self.run_main(lambda n: self.old_pc_sorts() if n == 1 else None, stop_after=3)
        self.assertEqual(self.pieces(), [self.PIECE])
        self.assertEqual(self.cut_at, [])                       # this computer cut nothing and saved nothing
        self.assertTrue(os.path.exists(os.path.join(self.inbox, "done", "wall.jpg")))
        self.assertEqual(out.count("wall.jpg: new photo, left in Arrivals for the other computer. "
                                   "This computer sorts it in 10 minutes if it is still there."), 1)
        self.assertEqual(out.count("wall.jpg: gone from Arrivals. The other computer took it"), 1)

    def test_without_the_line_in_the_settings_the_same_morning_files_it_twice(self):
        # The defect as reported, kept as a test so the one above is known to
        # be testing something: same two computers, no "shared" line.
        self.write_settings()
        self.drop_photo()
        self.run_main(lambda n: self.old_pc_sorts() if n == 1 else None, stop_after=3)
        self.assertEqual(self.pieces(), ["Self-Portrait Kindergarten (1).jpg", self.PIECE])
        self.assertEqual(len(self.cut_at), 1)

    def test_the_other_computer_taking_a_photo_left_for_it_is_not_an_alarm(self):
        self.drop_photo()
        out = self.run_main(lambda n: self.old_pc_sorts() if n == 1 else None, stop_after=4)
        self.assertNotIn("standing by for the next 8 hours", out)
        self.assertNotIn("standing by, a computer running an older version", out)
        self.assertIn("Role: the control tower for this class", self.status_text())

    def test_it_says_why_once_in_the_log_and_in_the_status_file(self):
        self.drop_photo()
        out = self.run_main(stop_after=4)
        self.assertEqual(out.count("The settings file says another computer watches this class too"), 1)
        for phrase in ("has never reported in", "switched off, or it has an older version of Baggage Claim",
                       "no child gets the same piece twice", "for 10 minutes",
                       "only if it is still in Arrivals after that",
                       "The wait ends for good when that computer has this version."):
            self.assertIn(phrase, out)
        status = self.status_text()
        self.assertIn("Note: this class is shared with a computer that has never reported in, so each new photo is "
                      "left for that computer for 10 minutes before this computer sorts it", status)
        self.assertIn("Photos waiting in Arrivals: 1", status)
        self.assertLess(status.index("Role: "), status.index("Note: "))
        self.assertLess(status.index("Note: "), status.index("Priority: "))
        self.assertIsNotNone(bc.parse_status(status))           # the other watchers can still read the file

    def test_the_other_computer_is_off_so_this_one_sorts_after_ten_minutes(self):
        self.drop_photo()
        out = self.run_main(stop_after=13)                      # 13 looks, one a minute
        self.assertEqual(self.pieces(), [self.PIECE])
        self.assertEqual(len(self.cut_at), 1)
        self.assertGreaterEqual(self.cut_at[0], bc.SHARED_WAIT_SECONDS)
        self.assertLess(self.cut_at[0], bc.SHARED_WAIT_SECONDS + 120)
        self.assertEqual(out.count("wall.jpg: still in Arrivals after 10 minutes, so the other computer is not "
                                   "sorting. This computer is sorting it now."), 1)
        self.assertEqual(out.count("left in Arrivals for the other computer"), 1)
        self.assertNotIn("The other computer took it", out)
        self.assertNotIn("asleep", out)
        self.assertIn("1 pieces, 1 filed", out)

    def test_each_photo_waits_from_when_it_was_first_seen_not_from_its_own_date(self):
        self.drop_photo("wall.jpg")
        long_ago = bc.time.time() - 7 * 86400                   # a picture taken last week, shared today
        os.utime(os.path.join(self.inbox, "wall.jpg"), (long_ago, long_ago))

        def on_tick(n):
            if n == 5:
                self.drop_photo("second wall.jpg")
        self.run_main(on_tick, stop_after=13)
        self.assertEqual(len(self.cut_at), 1)                   # the first photo only; the second has waited 8 minutes
        self.assertGreaterEqual(self.cut_at[0], bc.SHARED_WAIT_SECONDS)
        self.assertTrue(os.path.exists(os.path.join(self.inbox, "second wall.jpg")))

    def test_once_the_other_computer_has_this_version_nothing_is_kept_waiting(self):
        bc.write_status(bc.status_dir(self.cls), "CLASSROOM-PC", bc.time.time(), "standing by", 95)
        self.drop_photo()
        out = self.run_main(stop_after=2)
        self.assertEqual(self.cut_at, [0.0])                    # sorted on the first look
        self.assertNotIn("The settings file says another computer", out)
        self.assertNotIn("left in Arrivals for the other computer", out)
        self.assertNotIn("Note:", self.status_text())

    def test_a_computer_that_has_this_version_and_is_switched_off_has_reported_in(self):
        bc.write_status(bc.status_dir(self.cls), "CLASSROOM-PC", bc.time.time() - 3 * 86400, "watching", 50)
        self.drop_photo()
        out = self.run_main(stop_after=2)
        self.assertEqual(self.cut_at, [0.0])
        self.assertNotIn("left in Arrivals for the other computer", out)

    def test_the_classroom_computer_with_this_version_sorts_and_this_one_stands_by_as_before(self):
        def on_tick(n):
            bc.write_status(bc.status_dir(self.cls), "CLASSROOM-PC", bc.time.time() + 60, "watching", 50)
        on_tick(0)
        self.drop_photo()
        out = self.run_main(on_tick, stop_after=3)
        self.assertEqual(self.cut_at, [])
        self.assertIn("standing by, CLASSROOM-PC is the control tower for this class", out)
        self.assertNotIn("The settings file says another computer", out)

    def test_the_day_the_other_computer_reports_in_the_wait_ends_and_it_is_said_once(self):
        self.drop_photo()

        def on_tick(n):
            if n >= 2:      # the new zip is installed on the classroom computer; here it is the one standing by
                bc.write_status(bc.status_dir(self.cls), "CLASSROOM-PC", bc.time.time() + 60, "standing by", 95)
        out = self.run_main(on_tick, stop_after=5)
        self.assertEqual(out.count("the other computer has reported in, so it has this version"), 1)
        self.assertEqual(len(self.cut_at), 1)
        self.assertLess(self.cut_at[0], bc.SHARED_WAIT_SECONDS)     # no ten-minute wait any more
        self.assertIn("Note: this class is shared", self.status_at[2])
        self.assertNotIn("Note:", self.status_text())

    def test_the_line_in_the_settings_can_say_no_and_the_flag_says_yes(self):
        self.write_settings(shared="no")
        self.drop_photo()
        self.run_main(stop_after=2)
        self.assertEqual(self.cut_at, [0.0])
        self.drop_photo("second wall.jpg")
        self.cut_at, self.ticks = [], []
        out = self.run_main(stop_after=2, more_args=["--shared"])
        self.assertEqual(self.cut_at, [])
        self.assertIn("second wall.jpg: new photo, left in Arrivals for the other computer", out)
        for yes in (True, 1, "yes", "Yes", "true", "on"):
            self.assertTrue(bc.is_yes(yes), yes)
        for no in (False, 0, None, "", "no", "false", "off", "maybe"):
            self.assertFalse(bc.is_yes(no), no)

    def test_this_computers_own_status_file_is_not_another_computer(self):
        mine = {"machine": MAC["machine"], "priority": 90, "epoch": int(NOW), "role": "watching"}
        pc = {"machine": "CLASSROOM-PC", "priority": 50, "epoch": int(NOW - 30 * 86400), "role": "watching"}
        self.assertTrue(bc.never_reported_in([], MAC))
        self.assertTrue(bc.never_reported_in([mine], MAC))
        self.assertFalse(bc.never_reported_in([mine, pc], MAC))

    def test_the_wait_on_its_own(self):
        said, seen = [], {}
        photo = os.path.join(self.inbox, "wall.jpg")
        self.assertTrue(bc.leave_for_the_other(seen, photo, NOW, said.append))
        self.assertTrue(bc.leave_for_the_other(seen, photo, NOW + 599, said.append))
        self.assertEqual(len(said), 1)
        self.assertFalse(bc.leave_for_the_other(seen, photo, NOW + 600, said.append))
        self.assertFalse(bc.leave_for_the_other(seen, photo, NOW + 605, said.append))
        self.assertEqual(len(said), 2)
        self.assertTrue(bc.leave_for_the_other({}, photo, NOW, said.append, wait=30))
        self.assertIn("sorts it in 1 minute if it is still there", said[-1])
        self.assertEqual((bc.minutes_text(60), bc.minutes_text(600)), ("1 minute", "10 minutes"))
        for line in said:
            self.assertNotIn(self.inbox, line)                  # the photo's name, never the path of the class folder

    def test_forgetting_a_photo_says_something_only_when_the_other_computer_took_it(self):
        said = []
        held = os.path.join(self.inbox, "held.jpg")
        ours = os.path.join(self.inbox, "ours.jpg")
        self.drop_photo("still here.jpg")
        here = os.path.join(self.inbox, "still here.jpg")
        seen = {held: [NOW, False], ours: [NOW, True], here: [NOW, False]}
        self.assertEqual(bc.forget_gone(seen, said.append), ["held.jpg"])
        self.assertEqual(list(seen), [here])
        self.assertEqual(len(said), 1)
        self.assertIn("held.jpg: gone from Arrivals. The other computer took it", said[0])

    def test_a_photo_being_left_is_not_claimed_cut_or_counted_as_taken(self):
        self.drop_photo()
        taken, log = [], []
        res = bc.run_inbox(self.inbox, ["Maya Torres"], self.tmp, "Self-Portrait", log=log.append,
                           grade="Kindergarten", sorted_dir=self.cls, taken=taken, hold=lambda src: True)
        self.assertEqual((res, taken, self.cut_at, log), ([], [], [], []))
        self.assertTrue(os.path.exists(os.path.join(self.inbox, "wall.jpg")))
        self.assertFalse(os.path.exists(os.path.join(self.inbox, "done", "wall.jpg")))
        self.assertEqual(bc.unfinished_photos(self.tmp, self.inbox), [])     # and no marker was written for it
        asked = []
        res = bc.run_inbox(self.inbox, ["Maya Torres"], self.tmp, "Self-Portrait", log=log.append,
                           grade="Kindergarten", sorted_dir=self.cls, taken=taken,
                           hold=lambda src: asked.append(os.path.basename(src)) or False)
        self.assertEqual(asked, ["wall.jpg"])
        self.assertEqual(len(res), 1)
        self.assertEqual(self.pieces(), [self.PIECE])

    def test_check_setup_says_the_class_is_shared_and_what_this_computer_does_about_it(self):
        if not bc.backend_ready():
            self.skipTest("no name reader on this machine")

        def check():
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                bc.self_check(self.settings)
            return buf.getvalue()
        out = check()
        self.assertIn("this class is shared: The settings file says another computer watches this class too", out)
        self.assertIn("for 10 minutes", out)
        bc.write_status(bc.status_dir(self.cls), "CLASSROOM-PC", bc.time.time(), "watching", 50)
        out = check()
        self.assertIn("this class is shared, and the other computer has reported in", out)
        self.assertNotIn("has never reported in", out)
        self.write_settings()
        self.assertNotIn("this class is shared", check())

    def test_the_read_me_and_the_example_settings_say_how_to_share_a_class_with_an_older_version(self):
        text = read(os.path.join(ROOT, "README.md"))
        section = " ".join(text.split("### More than one computer")[1].split("### ")[0].split())
        for phrase in ('`"shared": true`', "has never reported in", "for 10 minutes",
                       "only if it is still in `Arrivals` after that", "`--shared`"):
            self.assertIn(phrase, " ".join(text.split()) if phrase == "`--shared`" else section)
        with open(os.path.join(ROOT, "settings.example.json"), encoding="utf-8") as f:
            example = json.load(f)
        self.assertIs(example["shared"], False)
        self.assertIn("10 minutes", example["_shared"])


class _ASortingComputer:
    """Repair (status before sorting). This computer is the classroom PC,
    priority 50: the one that sorts whenever it is on. The helper's Mac
    (priority 90) stands by for as long as the PC's status file is fresh, and
    takes over when that file is five minutes old. So the file is this
    computer's only way of saying "I am on, leave the photos to me", and it
    has to be said BEFORE a photo is touched and kept being said through a
    long batch. The clock is faked; nothing waits and no photo is opened."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Class")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.roster = os.path.join(self.cls, "Class list.txt")
        with open(self.roster, "w") as f:
            f.write("Maya Torres\n")
        self.settings = os.path.join(self.tmp, "settings.json")
        with open(self.settings, "w") as f:
            json.dump({"inbox": self.inbox, "sorted": self.cls,
                       "unsorted": os.path.join(self.cls, "Unsorted - needs a person"), "roster": self.roster,
                       "project": "Self-Portrait", "grade": "Kindergarten", "interval": 5, "priority": 50}, f)
        self.saved = (bc.time.time, bc.time.sleep, bc.run_inbox, bc.process_photo, bc.is_settled, bc.write_status)
        real_time, self.real_write = self.saved[0], self.saved[5]
        self.offset = 0.0                       # seconds the fake clock is ahead of the real one
        bc.time.time = lambda: real_time() + self.offset
        bc.is_settled = lambda p, wait=0: True
        self.failing = False                    # True: this computer's status file cannot be written

        def write_status(sdir, machine, *a, **k):
            if self.failing and machine == bc.machine_name():
                raise OSError(28, "No space left on device")
            return self.real_write(sdir, machine, *a, **k)
        bc.write_status = write_status
        self.ticks = []
        self.calls = []             # which tick of the loop sorted
        self.seen = []              # this computer's own status file, as it was each time sorting began
        self.status_at = {}         # the file at the end of each tick, and how old it was then
        self.age_at = {}

    def tearDown(self):
        bc.time.time, bc.time.sleep, bc.run_inbox, bc.process_photo, bc.is_settled, bc.write_status = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def status_text(self):
        try:
            return read(os.path.join(self.cls, "Watcher status", bc.machine_name() + ".txt"))
        except OSError:
            return ""

    def status_age(self, text=None):
        """How old this computer's status file is by the clock the other
        computers read it with, or None if there is no file."""
        st = bc.parse_status(self.status_text() if text is None else text)
        return None if st is None else bc.time.time() - st["epoch"]

    def fake_run_inbox(self, takes=0, result=None):
        def run_inbox(*a, **k):
            self.calls.append(len(self.ticks) + 1)
            self.seen.append((self.status_text(), self.status_age()))
            self.offset += takes
            return list(result or [])
        bc.run_inbox = run_inbox

    def drop_photos(self, *names):
        for n in names:
            with open(os.path.join(self.inbox, n), "wb") as f:
                f.write(b"\xff\xd8 not really a jpeg")

    def fake_process_photo(self, takes):
        def process_photo(path, roster, out_dir, project, grid=None, log=print, grade="", sorted_dir=None,
                          unsorted_dir=None):
            self.seen.append((os.path.basename(path), self.status_age()))
            self.offset += takes
            folder = os.path.join(sorted_dir, "Maya Torres", project)
            os.makedirs(folder, exist_ok=True)
            saved_as = os.path.join(folder, bc.piece_name(project, grade, folder))
            open(saved_as, "w").close()
            return [{"piece": 1, "status": "confident", "name": "Maya Torres", "text": "Maya", "score": 1.0,
                     "margin": 1.0, "box": None, "file": saved_as, "bbox": (0, 0, 1, 1)}]
        bc.process_photo = process_photo

    def run_main(self, step, stop_after, on_tick=lambda n: None):
        """step: {tick: seconds the clock moves during that sleep}; the other
        sleeps move it by step['else'] (or the seconds asked for)."""
        def fake_sleep(s):
            self.ticks.append(s)
            n = len(self.ticks)
            self.status_at[n] = self.status_text()
            self.age_at[n] = self.status_age()
            on_tick(n)
            self.offset += step.get(n, step.get("else", s))
            if n >= stop_after:
                raise KeyboardInterrupt
        bc.time.sleep = fake_sleep
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                bc.main(["--watch", "--settings", self.settings, "--out", self.tmp])
        return buf.getvalue()


class StatusIsWrittenBeforeSortingTests(_ASortingComputer, unittest.TestCase):
    """The status file goes first: before the first photo after a start or a
    wake-up, between the photos of a long batch, and with the time it really
    is when a batch has finished."""

    def test_the_reported_repro_a_pc_that_wakes_says_it_is_on_before_it_touches_a_photo(self):
        self.fake_run_inbox()
        minutes_asleep = 6

        def on_tick(n):
            if n == 2:      # while the PC sleeps the Mac takes over; its file is 10 seconds old when the PC wakes
                self.real_write(bc.status_dir(self.cls), "Helpers-MacBook",
                                bc.time.time() + minutes_asleep * 60 - 10, "watching", 90)
        # tick 1: just started. tick 2: sorting. Then the PC sleeps for six minutes.
        # tick 3: awake. tick 4: 50 seconds later. tick 5: the 90 seconds are over.
        out = self.run_main({1: bc.GRACE_SECONDS + 10, 2: minutes_asleep * 60, 3: 50, 4: 50}, stop_after=5,
                            on_tick=on_tick)
        self.assertGreater(minutes_asleep * 60, bc.STALE_SECONDS)       # long enough for the Mac to take over
        self.assertEqual(self.calls, [2, 5], f"sorted on ticks {self.calls}; log:\n{out}")
        self.assertIn(f"this computer was asleep for {minutes_asleep} minutes", out)
        # On waking, nothing is sorted and the file is rewritten at once, so the Mac can see the PC is back...
        self.assertIn("just started; standing by for a moment", self.status_at[3])
        self.assertLess(self.age_at[3], 2)
        # ...and each time sorting began, the file already said "watching", seconds old. (Before the repair
        # it still said "just started" and was 100 seconds old: the PC sorted first and said so afterwards.)
        for text, age in self.seen:
            self.assertIn("Role: the control tower", text)
            self.assertLess(age, 2)
        self.assertIn("this computer is the control tower for this class (Helpers-MacBook standing by)", out.split("was asleep")[1])

    def test_the_pure_decision_has_no_grace_for_a_computer_that_was_asleep_so_the_loop_supplies_it(self):
        mac = {"machine": "Helpers-MacBook", "priority": 90, "epoch": int(NOW - 10), "role": "watching"}
        me = {"machine": "CLASSROOM-PC", "priority": 50}
        self.assertEqual(bc.decide_role([mac], me, NOW, NOW - 3600)["role"], "watching")    # as reported
        self.assertEqual(bc.decide_role([mac], me, NOW, NOW)["role"], "starting")           # what the loop passes on a wake

    def test_the_file_written_after_a_long_batch_carries_the_time_it_was_written(self):
        piece = os.path.join(self.cls, "Maya Torres", "Self-Portrait", "Self-Portrait Kindergarten.jpg")
        os.makedirs(os.path.dirname(piece))
        open(piece, "w").close()
        self.fake_run_inbox(takes=4 * 60, result=[{"status": "confident", "file": piece}])
        self.run_main({1: bc.GRACE_SECONDS + 10}, stop_after=2)
        self.assertEqual(self.calls, [2])
        # Before the repair the file carried the time the loop had looked at the inbox,
        # four minutes earlier: one more minute and the Mac would have taken over.
        self.assertLess(self.age_at[2], 2)
        self.assertIn("1 pieces, 1 filed, 0 to unsorted", self.status_at[2])

    def test_a_batch_longer_than_five_minutes_never_lets_the_file_go_stale(self):
        self.drop_photos("wall 1.jpg", "wall 2.jpg", "wall 3.jpg")
        self.fake_process_photo(takes=2 * 60)               # six minutes in all
        out = self.run_main({1: bc.GRACE_SECONDS + 10}, stop_after=2)
        self.assertEqual([name for name, _ in self.seen], ["wall 1.jpg", "wall 2.jpg", "wall 3.jpg"], out)
        for name, age in self.seen:                          # as each photo was started
            self.assertLess(age, 2, f"{name}: the status file was {age:.0f} seconds old")
        self.assertIn("3 pieces, 3 filed, 0 to unsorted", out)
        self.assertEqual(sorted(os.listdir(os.path.join(self.inbox, "done"))), ["wall 1.jpg", "wall 2.jpg", "wall 3.jpg"])
        self.assertLess(self.age_at[2], 2)

    def test_run_inbox_without_a_beat_or_with_one_that_says_nothing_sorts_everything(self):
        self.fake_process_photo(takes=0)
        for beat in (None, lambda: None, lambda: True):
            self.drop_photos("wall 1.jpg", "wall 2.jpg")
            res = bc.run_inbox(self.inbox, ["Maya Torres"], self.tmp, "Self-Portrait", log=lambda m: None,
                               grade="Kindergarten", sorted_dir=self.cls, beat=beat)
            self.assertEqual(len(res), 2)
            self.assertEqual(bc.inbox_jobs(self.inbox, "Self-Portrait"), [])


class StatusFileCannotBeWrittenTests(_ASortingComputer, unittest.TestCase):
    """A sorting computer whose status file cannot be written (Drive signed
    out, disk full) looks switched off to the others, and one of them takes
    over after five minutes. It used to say so once in the log and carry on
    sorting, so both computers sorted. Now it stands by after three minutes
    without a good write, says why and what to check, and carries on by
    itself, after the usual 90 seconds, when the file can be written again."""

    def test_three_minutes_without_a_good_write_and_this_computer_stands_by_until_the_file_is_back(self):
        self.fake_run_inbox()

        def on_tick(n):
            if n == 2:
                self.failing = True         # the disk fills up
            if n == 7:
                self.failing = False        # somebody makes room
        # Seconds on the clock at each tick: 0, 100, 150, 200 ... The last good write is at 100.
        # tick 3 (150): no write due yet. ticks 4 and 5 (200, 250): the write fails, the file is
        # under three minutes old, sorting goes on. tick 6 (300): 200 seconds old, stand by.
        # tick 8 (400): the write works again, 90 seconds' grace. tick 10 (500): sorting again.
        out = self.run_main({1: 100, "else": 50}, stop_after=10, on_tick=on_tick)
        self.assertEqual(self.calls, [2, 3, 4, 5, 10], f"sorted on ticks {self.calls}; log:\n{out}")
        self.assertEqual(out.count("could not write this computer's status file in 'Watcher status'"), 1)
        self.assertEqual(out.count(bc.STATUS_LOST_TEXT), 1)
        self.assertEqual(out.count(bc.STATUS_BACK_TEXT.format(grace=int(bc.GRACE_SECONDS))), 1)
        lost, back = out.index(bc.STATUS_LOST_TEXT), out.index("status file can be written again")
        self.assertLess(out.index("could not write this computer's status file"), lost)
        self.assertLess(lost, back)
        self.assertIn("this computer is the control tower for this class", out[back:])
        self.assertEqual(out.count("just started"), 1)                  # the "written again" line stands in for it
        self.assertIn("just started; standing by for a moment", self.status_at[8])     # said in the file at once
        self.assertLess(self.age_at[8], 2)
        self.assertIn("Role: the control tower", self.status_at[10])
        for text, age in self.seen:                                     # never sorting with a file the others call off
            self.assertLess(age, bc.STATUS_LOST_SECONDS)

    def test_the_words_in_the_log_are_plain_and_say_what_to_check(self):
        for phrase in ("cannot write its status file", "no child gets the same piece twice",
                       "New photos wait in Arrivals", "Google Drive is signed in", "disk is not full"):
            self.assertIn(phrase, bc.STATUS_LOST_TEXT)
        for word in ("OSError", "errno", "stale", "leader", "heartbeat"):
            self.assertNotIn(word, bc.STATUS_LOST_TEXT + bc.STATUS_BACK_TEXT)

    def test_one_failed_write_is_not_a_reason_to_stop_and_three_minutes_of_them_is(self):
        self.assertFalse(bc.status_lost(NOW - 60, NOW))
        self.assertFalse(bc.status_lost(NOW - bc.STATUS_LOST_SECONDS + 1, NOW))
        self.assertTrue(bc.status_lost(NOW - bc.STATUS_LOST_SECONDS, NOW))
        self.assertTrue(bc.status_lost(None, NOW))                      # never written: nobody can see this computer
        # It must stop well before the others take over, not at the same moment.
        self.assertLessEqual(bc.STATUS_LOST_SECONDS + bc.STATUS_EVERY, bc.STALE_SECONDS)

    def test_a_computer_that_has_never_managed_to_write_its_file_never_sorts(self):
        self.fake_run_inbox()
        self.failing = True
        out = self.run_main({"else": 100}, stop_after=4)
        self.assertEqual(self.calls, [], out)
        self.assertEqual(out.count(bc.STATUS_LOST_TEXT), 1)
        self.assertEqual(self.status_text(), "")

    def test_a_batch_stops_between_photos_and_the_rest_stay_in_the_inbox(self):
        self.drop_photos("wall 1.jpg", "wall 2.jpg", "wall 3.jpg")
        self.fake_process_photo(takes=2 * 60)

        real_jobs = bc.inbox_jobs
        self.addCleanup(setattr, bc, "inbox_jobs", real_jobs)

        def inbox_jobs(*a, **k):        # the disk fills up as the batch begins
            jobs = real_jobs(*a, **k)
            if self.status_text():
                self.failing = "Role: the control tower" in self.status_text()
            return jobs
        bc.inbox_jobs = inbox_jobs
        out = self.run_main({1: bc.GRACE_SECONDS + 10}, stop_after=3)
        # Photo 1 starts on a fresh file. Before photo 2 the write fails, but the file is two
        # minutes old: carry on. Before photo 3 it is four minutes old: stop, leave it where it is.
        self.assertEqual([name for name, _ in self.seen], ["wall 1.jpg", "wall 2.jpg"], out)
        self.assertEqual([os.path.basename(j[0]) for j in real_jobs(self.inbox, "Self-Portrait")], ["wall 3.jpg"])
        self.assertIn("wall 3.jpg: left in Arrivals for now, because this computer cannot write its status file "
                      "and another computer may be sorting", out)
        self.assertIn("2 pieces, 2 filed, 0 to unsorted", out)
        self.assertEqual(out.count(bc.STATUS_LOST_TEXT), 1)
        self.assertEqual(len(os.listdir(os.path.join(self.cls, "Maya Torres", "Self-Portrait"))), 2)

    def test_the_read_me_says_what_a_teacher_sees(self):
        text = " ".join(read(os.path.join(ROOT, "README.md")).split())
        section = text.split("### More than one computer")[1].split("### ")[0]
        for phrase in ("before it touches a photo", "cannot write its status file",
                       "this computer's status file can be written again"):
            self.assertIn(phrase, section)


class DeletedChildFolderStaysDeletedTests(unittest.TestCase):
    """Repair (folder keeps coming back): every look at the inbox, every five
    seconds, made a folder for every child on the class list again. A teacher
    who deleted the folder of a child who had left, without taking the name
    off the class list, saw the empty folder come back within seconds. The
    watcher now remembers which children it has made folders for
    (make_new_child_folders) and makes one only for a child who is new on the
    list; a piece filed for a child still makes that child's folder. Invented
    names and temporary folders only; the one image is a synthetic wall."""

    PROJECT = "Self-Portrait"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Drive", "Room 3")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.unsorted = os.path.join(self.cls, "Unsorted - needs a person")
        self.out = os.path.join(self.tmp, "tool")
        os.makedirs(self.out)
        self.roster = os.path.join(self.cls, "Class list - one first name per line.txt")
        with open(self.roster, "w", encoding="utf-8") as f:
            f.write("Maya Torres\nJordan Lum\n")
        self.settings = os.path.join(self.tmp, "settings.json")
        with open(self.settings, "w") as f:
            json.dump({"inbox": self.inbox, "sorted": self.cls, "unsorted": self.unsorted, "roster": self.roster,
                       "project": self.PROJECT, "grade": "K", "interval": 1, "priority": 50}, f)
        self.saved = (bc.time.sleep, bc.is_settled, bc.GRACE_SECONDS, bc.make_child_folders)
        bc.GRACE_SECONDS = 0
        bc.is_settled = lambda p, wait=0: True
        self.made = {}
        self.log = []

    def tearDown(self):
        bc.time.sleep, bc.is_settled, bc.GRACE_SECONDS, bc.make_child_folders = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def folder(self, child):
        return os.path.join(self.cls, child)

    def look(self, roster, **k):
        """One look at the inbox, the way the watch loop does it."""
        return bc.run_inbox(self.inbox, roster, self.out, self.PROJECT, log=self.log.append, grade="K",
                            sorted_dir=self.cls, unsorted_dir=self.unsorted, folders=self.made, **k)

    def children(self):
        return sorted(d for d in os.listdir(self.cls)
                      if os.path.isdir(self.folder(d)) and d not in ("Wall Inbox", "Unsorted - needs a person",
                                                                     bc.STATUS_FOLDER))

    def test_a_folder_deleted_by_the_teacher_is_not_made_again_on_the_next_look(self):
        two = ["Maya Torres", "Jordan Lum"]
        self.look(two)
        self.assertEqual(self.children(), ["Jordan Lum", "Maya Torres"])
        self.assertTrue(os.path.isdir(os.path.join(self.folder("Jordan Lum"), self.PROJECT)))
        shutil.rmtree(self.folder("Jordan Lum"))         # the child has left; the name is still on the list
        for _ in range(5):
            self.look(two)
        self.assertEqual(self.children(), ["Maya Torres"], "the deleted folder came back")

    def test_a_new_child_gets_a_folder_and_the_deleted_one_still_stays_deleted(self):
        self.look(["Maya Torres", "Jordan Lum"])
        shutil.rmtree(self.folder("Jordan Lum"))
        self.look(["Maya Torres", "Jordan Lum", "Sofia Marin"])
        self.assertEqual(self.children(), ["Maya Torres", "Sofia Marin"])
        self.assertTrue(os.path.isdir(os.path.join(self.folder("Sofia Marin"), self.PROJECT)))

    def test_a_name_taken_off_the_list_and_put_back_gets_its_folder_again(self):
        self.look(["Maya Torres", "Jordan Lum"])
        shutil.rmtree(self.folder("Jordan Lum"))
        self.look(["Maya Torres"])                       # the teacher takes the name off the list
        self.assertEqual(self.children(), ["Maya Torres"])
        self.look(["Maya Torres", "Jordan Lum"])         # the child comes back in the spring
        self.assertEqual(self.children(), ["Jordan Lum", "Maya Torres"])

    def test_a_name_taken_off_the_list_leaves_the_folder_and_the_work_in_it(self):
        self.look(["Maya Torres", "Jordan Lum"])
        piece = os.path.join(self.folder("Jordan Lum"), self.PROJECT, "Self-Portrait K.jpg")
        with open(piece, "w") as f:
            f.write("a piece")
        self.look(["Maya Torres"])
        self.assertTrue(os.path.exists(piece), "the tool never takes a child's folder away")

    def test_a_spelling_fixed_in_the_list_gets_a_folder_under_the_new_spelling(self):
        self.look(["Maya Torres", "Jordon Lum"])
        self.look(["Maya Torres", "Jordan Lum"])
        self.assertEqual(self.children(), ["Jordan Lum", "Jordon Lum", "Maya Torres"])

    def test_folders_that_could_not_be_made_are_tried_again_on_the_next_look(self):
        real = bc.make_child_folders
        calls = []

        def drive_is_away_once(roster, *a, **k):
            calls.append(list(roster))
            if len(calls) == 1:
                raise OSError("Google Drive is not connected")
            return real(roster, *a, **k)
        bc.make_child_folders = drive_is_away_once
        with self.assertRaises(OSError):
            self.look(["Maya Torres", "Jordan Lum"])
        self.assertEqual(self.made, {}, "nothing is remembered as made when it was not")
        self.look(["Maya Torres", "Jordan Lum"])
        self.assertEqual(self.children(), ["Jordan Lum", "Maya Torres"])
        self.look(["Maya Torres", "Jordan Lum"])
        self.assertEqual(len(calls), 2, "an unchanged class list makes no folders")

    def test_two_classes_on_one_computer_are_remembered_apart(self):
        other = os.path.join(self.tmp, "Drive", "Room 4")
        os.makedirs(other)
        self.look(["Maya Torres", "Jordan Lum"])
        new = bc.make_new_child_folders(["Maya Torres"], self.out, self.PROJECT, other, self.made)
        self.assertEqual(new, ["Maya Torres"])
        self.assertTrue(os.path.isdir(os.path.join(other, "Maya Torres", self.PROJECT)))
        self.assertEqual(bc.make_new_child_folders(["Maya Torres"], self.out, self.PROJECT, other, self.made), [])

    def test_a_run_that_is_not_the_watcher_still_makes_every_folder(self):
        # Baggage Claim.command, once through: no memory is handed over, every child gets a folder.
        bc.run_inbox(self.inbox, ["Maya Torres", "Jordan Lum"], self.out, self.PROJECT, log=self.log.append,
                     sorted_dir=self.cls, unsorted_dir=self.unsorted)
        self.assertEqual(self.children(), ["Jordan Lum", "Maya Torres"])

    def run_main(self, on_sleep, stop_after):
        ticks = []

        def fake_sleep(s):
            ticks.append(s)
            on_sleep(len(ticks))
            if len(ticks) >= stop_after:
                raise KeyboardInterrupt
        bc.time.sleep = fake_sleep
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                bc.main(["--watch", "--settings", self.settings, "--out", self.out])
        return buf.getvalue()

    def test_the_watcher_itself_the_report_from_start_to_finish(self):
        seen = {}

        def teacher(tick):
            if tick == 1:       # the watcher has started: every child on the list has a folder
                seen["at start"] = self.children()
                shutil.rmtree(self.folder("Jordan Lum"))
            if tick == 3:       # two looks at the inbox later, ten seconds on a real computer
                seen["after the delete"] = self.children()
                with open(self.roster, "a", encoding="utf-8") as f:
                    f.write("Sofia Marin\n")
            if tick == 5:
                seen["after the new child"] = self.children()
        out = self.run_main(teacher, stop_after=7)
        self.assertEqual(seen["at start"], ["Jordan Lum", "Maya Torres"], out)
        self.assertEqual(seen["after the delete"], ["Maya Torres"], out)
        self.assertEqual(seen["after the new child"], ["Maya Torres", "Sofia Marin"], out)
        self.assertEqual(self.children(), ["Maya Torres", "Sofia Marin"], out)
        self.assertTrue(os.path.isdir(os.path.join(self.folder("Sofia Marin"), self.PROJECT)))
        self.assertEqual(out.count("class list changed: 3 children (there were 2)"), 1, out)

    def test_a_piece_filed_for_a_child_brings_that_childs_folder_back(self):
        names = ["Maya", "Jonah", "Sofia", "Elijah"]
        # Windows record of Sep 28, 2026: this pale wall is outside the contract and the Windows reader did not
        # read 'Jonah' on it (it read the other three), so on Windows the folder deleted is one whose name was read
        gone = "Sofia" if bc.IS_WIN else "Jonah"
        self.look(names)
        shutil.rmtree(self.folder(gone))                 # deleted by mistake; the child is still in the class
        self.look(names)
        self.assertNotIn(gone, self.children())
        sys.path.insert(0, HERE)
        from make_wall import make_wall
        img, truth = make_wall(names, rows=1, cols=4, size=(2400, 700))
        img.save(os.path.join(self.inbox, "wall.jpg"), quality=90)
        res = self.look(names)
        if bc.IS_WIN:
            assert_safe_outside_the_contract(self, res, truth, "row wall")
        filed = sorted(r["name"] for r in res if r["status"] == "confident")
        self.assertIn(gone, filed, res)
        self.assertEqual(os.listdir(os.path.join(self.folder(gone), self.PROJECT)), ["Self-Portrait K.jpg"])

    def test_the_read_me_says_what_a_teacher_does_when_a_child_leaves(self):
        text = " ".join(read(os.path.join(ROOT, "README.md")).split())
        section = text.split("### A child leaves the class")[1].split("### ")[0]
        for phrase in ("take the child's name off the class list", "stays deleted",
                       "never deletes a child's folder"):
            self.assertIn(phrase, section)


class ClassListSavedByAnyProgramTests(unittest.TestCase):
    """Repair (class list, how it was saved): Google Docs, Notepad and Word
    put an invisible mark (U+FEFF) at the start of a text file. The first
    child's name kept it, so the tool made a second folder for that child
    that looks the same on the screen and filed every piece into it; a first
    line that was a # comment became a folder. A list saved from Word in the
    Windows encoding with an accented name raised UnicodeDecodeError and the
    watcher was restarted every 30 to 60 seconds for ever. read_class_list now
    reads the bytes whichever way they were saved, the same on every
    computer, and when it cannot it says which line and never guesses.
    Invented names and temporary folders only."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Drive", "Room 3")
        os.makedirs(self.cls)
        self.path = os.path.join(self.cls, "Class list - one first name per line.txt")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def save(self, raw):
        with open(self.path, "wb") as f:
            f.write(raw)
        return self.path

    # -- the invisible mark ------------------------------------------------

    def test_the_mark_google_docs_and_notepad_put_first_is_not_part_of_the_first_name(self):
        self.save("Maya Torres\nJordan Lum\n".encode("utf-8-sig"))
        self.assertEqual(bc.load_roster(self.path), ["Maya Torres", "Jordan Lum"])

    def test_the_first_child_gets_one_folder_and_it_is_the_one_the_teacher_made(self):
        os.makedirs(os.path.join(self.cls, "Maya Torres"))           # made by hand, in Drive
        roster = bc.load_roster(self.save("Maya Torres\nJordan Lum\n".encode("utf-8-sig")))
        bc.make_child_folders(roster, self.tmp, "Self-Portrait", self.cls)
        children = sorted(n for n in os.listdir(self.cls) if os.path.isdir(os.path.join(self.cls, n)))
        self.assertEqual(children, ["Jordan Lum", "Maya Torres"])
        self.assertEqual([ascii(n) for n in children], ["'Jordan Lum'", "'Maya Torres'"], "no invisible twin")
        self.assertTrue(os.path.isdir(os.path.join(self.cls, "Maya Torres", "Self-Portrait")))

    def test_a_comment_on_the_first_line_is_still_a_comment(self):
        roster = bc.load_roster(self.save("# Kindergarten, first names\nMaya\nJordan\n".encode("utf-8-sig")))
        self.assertEqual(roster, ["Maya", "Jordan"])
        bc.make_child_folders(roster, self.tmp, None, self.cls)
        self.assertEqual(sorted(n for n in os.listdir(self.cls) if not n.endswith(".txt")), ["Jordan", "Maya"])

    def test_invisible_characters_tabs_and_double_spaces_anywhere_are_tidied(self):
        raw = "Maya​\tTorres\r\n﻿Jordan  Lum \r\n\r\n".encode("utf-8")
        self.assertEqual(bc.load_roster(self.save(raw)), ["Maya Torres", "Jordan Lum"])

    # -- the way the file was saved ------------------------------------------

    NAMES = ["Zoë Marin", "José Reed", "María Lum", "Raúl Torres", "Maya"]

    def test_a_list_saved_by_word_on_windows_with_accents_is_read(self):
        self.save("\r\n".join(self.NAMES + ["Aoife O’Hara", "Álvaro Reed", ""]).encode("cp1252"))
        self.assertEqual(bc.load_roster(self.path), self.NAMES + ["Aoife O’Hara", "Álvaro Reed"])

    def test_the_crash_as_reported(self):
        self.save("Zoë\nMaya\n".encode("cp1252"))
        self.assertEqual(bc.load_roster(self.path), ["Zoë", "Maya"])

    def test_a_list_saved_by_word_on_a_mac_with_accents_is_read(self):
        self.save("\r".join(self.NAMES + [""]).encode("mac_roman"))
        self.assertEqual(bc.load_roster(self.path), self.NAMES)

    def test_a_list_saved_as_unicode_by_notepad_is_read(self):
        for encoding in ("utf-16", "utf-16-le", "utf-16-be"):
            mark = {"utf-16-le": b"\xff\xfe", "utf-16-be": b"\xfe\xff"}.get(encoding, b"")
            self.save(mark + "\r\n".join(self.NAMES + [""]).encode(encoding))
            self.assertEqual(bc.load_roster(self.path), self.NAMES, encoding)

    def test_plain_utf8_is_read_as_before_whatever_the_alphabet(self):
        names = ["Zoë Marin", "Nguyễn An", "Łukasz", "Maya R."]
        self.save("\n".join(names).encode("utf-8"))
        self.assertEqual(bc.load_roster(self.path), names)

    def test_the_folder_is_the_same_however_the_list_was_saved(self):
        """Two computers watch one class; whichever reads the list, and
        however the teacher saved it, a child has one folder."""
        made = set()
        for raw in ("Zoë Marin\n".encode("utf-8"), "Zoë Marin\n".encode("utf-8-sig"),
                    "Zoë Marin\n".encode("cp1252"), "Zoë Marin\n".encode("mac_roman"),
                    "Zoë Marin\n".encode("utf-16"), "Zoë Marin\n".encode("utf-8")):
            bc.make_child_folders(bc.load_roster(self.save(raw)), self.tmp, None, self.cls)
            made |= {n for n in os.listdir(self.cls) if not n.endswith(".txt")}
        self.assertEqual({unicodedata_nfc(n) for n in made}, {"Zoë Marin"})
        self.assertEqual(len([n for n in os.listdir(self.cls) if not n.endswith(".txt")]), 1)

    def test_the_reading_does_not_depend_on_the_computer(self):
        raw = "Zoë Marin\nJosé Reed\n".encode("cp1252")
        here = bc.read_class_list(raw)
        with _mock.patch.object(sys, "platform", "win32"), \
                _mock.patch("locale.getpreferredencoding", return_value="cp437"):
            self.assertEqual(bc.read_class_list(raw), here)
        self.assertEqual(here, ["Zoë Marin", "José Reed"])

    # -- a list that cannot be read: say which line, never guess ---------------

    def unreadable(self, raw):
        with self.assertRaises(bc.ClassListError) as stop:
            bc.load_roster(self.save(raw))
        self.assertIsInstance(stop.exception, UnicodeError)      # what refresh_roster and the watcher catch
        return str(stop.exception)

    def test_a_line_that_cannot_be_read_is_named_by_its_number_and_never_by_its_words(self):
        said = self.unreadable(b"# room 3\nMaya Torres\nZo\x81 Marin\nJordan\n")
        self.assertIn("line 3 has a letter this program cannot make out", said)
        self.assertIn("choose Save As, pick 'UTF-8'", said)
        for word in ("Marin", "Zo", "Maya", "codec", "byte", "0x"):
            self.assertNotIn(word, said)

    def test_the_line_is_the_one_where_the_likelier_reading_stops(self):
        # saved on Windows: line 1 is fine in that reading, line 3 is not in either
        said = self.unreadable("José\nMaya\n".encode("cp1252") + b"\x81\x8d\n")
        self.assertIn("line 3 ", said)

    def test_two_readings_that_both_make_sense_are_not_guessed_between(self):
        # these bytes are 'Álvaro' saved by Word on a Mac and a different word saved on Windows
        said = self.unreadable("Maya\nÁlvaro\n".encode("mac_roman"))
        self.assertIn("line 2 has a letter this program cannot make out", said)

    def test_a_word_document_renamed_to_txt_is_not_a_class_list(self):
        self.assertIn("line 1 ", self.unreadable(b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00\xdf\xa4\xd2lZ\x01"))
        self.assertIn("line 2 is not text", self.unreadable(b"Maya\n\x00\x01\x02J\n"))
        self.assertIn("damaged or still being saved", self.unreadable(b"\xff\xfeM\x00a"))

    def test_a_running_watcher_keeps_its_list_and_says_which_line(self):
        log, seen = [], {}
        roster = bc.refresh_roster(self.save(b"Maya Torres\nJordan Lum\n"), ["Maya Torres", "Jordan Lum"], seen,
                                   log.append)
        self.save(b"Maya Torres\nJordan Lum\nZo\x81 Marin\n")
        for _ in range(3):
            self.assertEqual(bc.refresh_roster(self.path, roster, seen, log.append), ["Maya Torres", "Jordan Lum"])
        self.assertEqual(len(log), 1, log)
        self.assertIn("class list could not be read (line 3 has a letter", log[0])
        self.assertIn("still using the list of 2 children from before", log[0])
        self.assertNotIn("Marin", log[0])
        self.save("Maya Torres\nJordan Lum\nZoë Marin\n".encode("cp1252"))      # saved again, from Word
        self.assertEqual(bc.refresh_roster(self.path, roster, seen, log.append),
                         ["Maya Torres", "Jordan Lum", "Zoë Marin"])
        self.assertIn("class list changed: 3 children (there were 2)", log[1])

    def test_the_class_tool_and_the_self_check_say_it_in_a_sentence(self):
        self.save(b"Maya Torres\nZo\x81 Marin\n")
        with self.assertRaises(SystemExit) as stop:
            with contextlib.redirect_stdout(io.StringIO()):
                bc.main(["--roster", self.path, "--inbox", self.cls, "--out", self.tmp])
        self.assertIn("the class list cannot be read: line 2 has a letter", str(stop.exception))
        settings = os.path.join(self.tmp, "settings.json")
        with open(settings, "w") as f:
            json.dump({"inbox": self.cls, "sorted": self.cls, "unsorted": self.cls, "roster": self.path}, f)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(bc.self_check(settings), 1)
        self.assertIn("FAIL: the class list cannot be read: line 2 has a letter", buf.getvalue())
        self.assertNotIn("Traceback", buf.getvalue())

    def test_the_read_me_says_how_to_save_the_list_and_what_to_do_when_a_line_cannot_be_read(self):
        text = " ".join(read(os.path.join(ROOT, "README.md")).split())
        section = text.split("### The class list can be saved from any program")[1].split("### ")[0]
        for phrase in ("Notepad", "TextEdit", "`Plain Text`", "Google Docs", "it does not guess",
                       "The log names the line", "pick `UTF-8`", "two folders that look like the same child"):
            self.assertIn(phrase, section)


def unicodedata_nfc(name):
    """A Mac hands folder names back with the accent as a separate mark."""
    import unicodedata
    return unicodedata.normalize("NFC", name)


class ClassListSavedByAnyProgramInTheWatcherTests(unittest.TestCase):
    """Repair (class list, how it was saved), the watcher itself: a list it
    cannot read when it starts must not end it. It waits, says which line,
    and starts by itself once the list is saved again. Then the report end to
    end on a synthetic wall (make_wall.py, invented names) with the real
    reader: a list downloaded from Google Docs, a comment on its first line,
    the children's folders made by hand beforehand."""

    NAMES = ["Maya", "Jonah", "Sofia", "Elijah"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Drive", "Room 3")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.unsorted = os.path.join(self.cls, "Unsorted - needs a person")
        self.out = os.path.join(self.tmp, "tool")
        os.makedirs(self.out)
        self.roster = os.path.join(self.cls, "Class list - one first name per line.txt")
        self.settings = os.path.join(self.tmp, "settings.json")
        with open(self.settings, "w") as f:
            json.dump({"inbox": self.inbox, "sorted": self.cls, "unsorted": self.unsorted, "roster": self.roster,
                       "project": "Self-Portrait", "grade": "K", "interval": 1, "priority": 50}, f)
        self.saved = (bc.time.sleep, bc.is_settled, bc.GRACE_SECONDS, bc.run_inbox)
        bc.GRACE_SECONDS = 0
        bc.is_settled = lambda p, wait=0: True
        self.ticks = []

    def tearDown(self):
        bc.time.sleep, bc.is_settled, bc.GRACE_SECONDS, bc.run_inbox = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def save(self, raw):
        with open(self.roster, "wb") as f:
            f.write(raw)

    def watch(self, on_sleep):
        def fake_sleep(seconds):
            self.ticks.append(seconds)
            on_sleep(len(self.ticks))
        bc.time.sleep = fake_sleep
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                bc.main(["--watch", "--settings", self.settings, "--out", self.out])
        return buf.getvalue()

    def test_a_watcher_that_starts_with_a_list_it_cannot_read_waits_and_then_starts(self):
        handed = []
        bc.run_inbox = lambda inbox, roster, *a, **k: handed.append(list(roster)) or []
        self.save(b"Maya Torres\nZo\x81 Marin\n")

        def teacher(tick):
            if tick == 2:
                self.assertEqual(handed, [], "nothing is sorted with a list that could not be read")
                self.save("Maya Torres\nZoë Marin\n".encode("cp1252"))      # saved again, from Word
            if tick == 5:
                raise KeyboardInterrupt
        out = self.watch(teacher)
        self.assertEqual(self.ticks[:2], [60, 60], "it waits a minute at a time; it does not end")
        self.assertEqual(out.count("waiting: the class list cannot be read: line 2 has a letter"), 1, out)
        self.assertIn("'Class list - one first name per line.txt' in the class folder", out)
        self.assertIn("starts by itself", out)
        self.assertNotIn("Marin", out)
        self.assertNotIn("Traceback", out)
        self.assertTrue(handed and all(r == ["Maya Torres", "Zoë Marin"] for r in handed), handed)

    def test_a_list_from_google_docs_files_into_the_folders_the_teacher_made(self):
        for child in self.NAMES:
            os.makedirs(os.path.join(self.cls, child))                   # made by hand, in Drive
        self.save(("# Room 3, first names\r\n" + "\r\n".join(self.NAMES) + "\r\n").encode("utf-8-sig"))
        sys.path.insert(0, HERE)
        from make_wall import make_wall
        img, _ = make_wall(self.NAMES, rows=1, cols=4, size=(2400, 700))
        img.save(os.path.join(self.inbox, "wall.jpg"), quality=90)

        def stop(tick):
            if tick == 2:
                raise KeyboardInterrupt
        out = self.watch(stop)
        folders = sorted(n for n in os.listdir(self.cls) if os.path.isdir(os.path.join(self.cls, n)))
        children = [n for n in folders if n not in ("Wall Inbox", "Unsorted - needs a person", bc.STATUS_FOLDER)]
        self.assertEqual([ascii(n) for n in children], [ascii(n) for n in sorted(self.NAMES)], out)
        # Windows record of Sep 28, 2026: on this pale wall (outside the contract) the Windows reader did not read
        # 'Jonah'; on Windows the proof is carried by the three names it read, and Jonah's piece, if its name is
        # not read, must be in Unsorted and nowhere else
        not_read = ["Jonah"] if bc.IS_WIN else []
        for child in self.NAMES:
            piece = os.path.join(self.cls, child, "Self-Portrait")
            if child in not_read and not (os.path.isdir(piece) and os.listdir(piece)):
                unsorted = os.listdir(self.unsorted) if os.path.isdir(self.unsorted) else []
                self.assertEqual(len([n for n in unsorted if n.lower().endswith(".jpg")]), 1, out)
                continue
            self.assertEqual(os.listdir(os.path.join(self.cls, child, "Self-Portrait")), ["Self-Portrait K.jpg"],
                             out)


# ---------------------------------------------------------------------------
# Repair (filed once): a photo that is sorted a second time gave every child
# who already had their piece a second copy, '... 2.jpg'.
# ---------------------------------------------------------------------------
from unittest import mock as _mock_once  # noqa: E402


def _paint_wall(path, colours, cols=4, tile=(300, 240), quality=95):
    """A wall of plain coloured tiles, one per paper. Nothing on it is a
    child's work: the fake name reader answers by the colour alone."""
    from PIL import Image
    rows = (len(colours) + cols - 1) // cols
    img = Image.new("RGB", (cols * tile[0], rows * tile[1]), "white")
    for k, c in enumerate(colours):
        img.paste(Image.new("RGB", tile, c), ((k % cols) * tile[0], (k // cols) * tile[1]))
    img.save(path, quality=quality)


class _AWallOfEight:
    """Eight papers in one photo, eight invented children, and a name reader
    that answers by the colour of the crop it is handed. The detectors are
    replaced by an even grid, so these tests run on any computer."""

    ROSTER = ["Maya Torres", "Jonah Reed", "Sofia Marsh", "Elijah Stone",
              "Priya Nair", "Marcus Bell", "Lily Okafor", "Theo Lane"]
    COLOURS = [(200, 30, 30), (30, 160, 30), (30, 30, 200), (220, 200, 20),
               (200, 30, 200), (20, 200, 200), (120, 70, 20), (90, 90, 90)]
    ON_THE_WALL = ROSTER            # whose name is on each paper, in reading order
    GRID = (2, 4)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Drive", "Room 3")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.unsorted = os.path.join(self.cls, "Unsorted - needs a person")
        self.out = os.path.join(self.tmp, "tool")
        os.makedirs(self.out)
        self.photo = os.path.join(self.inbox, "wall.jpg")
        _paint_wall(self.photo, self.COLOURS[:len(self.ON_THE_WALL)])
        self.log = []
        self.saved = (bc.read_piece, bc.read_neighborhood, bc.read_photo_text, bc.is_settled, bc.piece_name)
        bc.read_piece = self.by_colour
        bc.read_neighborhood = lambda *a, **k: []
        bc.read_photo_text = lambda img, path, tmpdir, **k: []
        bc.is_settled = lambda p, wait=0: True

    def tearDown(self):
        bc.read_piece, bc.read_neighborhood, bc.read_photo_text, bc.is_settled, bc.piece_name = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ---------------------------------------------------------
    def by_colour(self, tmp_path, crop):
        from PIL import Image
        with Image.open(tmp_path) as im:
            px = im.convert("RGB").getpixel((im.width // 2, im.height // 2))
        k = min(range(len(self.COLOURS)), key=lambda j: sum((a - b) ** 2 for a, b in zip(px, self.COLOURS[j])))
        return [{"text": self.ON_THE_WALL[k], "conf": 1.0, "x": 10, "y": 10, "w": 160, "h": 30,
                 "rel_y": 0.05, "angle": 0}]

    def stop_at_piece(self, n, how):
        """The n-th piece to be filed cannot be: `how` is raised where its file
        name is chosen, which is after the pieces before it were saved."""
        real, calls = self.saved[4], []

        def name(project, grade, folder, ext=".jpg"):
            calls.append(folder)
            if len(calls) == n:
                raise how
            return real(project, grade, folder, ext)
        bc.piece_name = name

    def works_again(self):
        bc.piece_name = self.saved[4]
        self.log.clear()

    def sort(self, roster=None, out=None):
        return bc.run_inbox(self.inbox, roster or self.ROSTER, out or self.out, "Self-Portrait", grid=self.GRID,
                            log=self.log.append, grade="K", sorted_dir=self.cls, unsorted_dir=self.unsorted)

    def put_back(self, folder, name="wall.jpg"):
        shutil.move(os.path.join(self.inbox, folder, name), os.path.join(self.inbox, name))

    def pieces(self):
        got = {}
        for n in self.ROSTER:
            d = os.path.join(self.cls, n, "Self-Portrait")
            got[n] = sorted(os.listdir(d)) if os.path.isdir(d) else []
        return got

    def everything_in_the_class_folder(self):
        found = []
        for folder, _, files in os.walk(self.cls):
            if os.path.join(self.inbox, "") in os.path.join(folder, ""):
                continue
            found += [os.path.join(folder, f) for f in files]
        return sorted(found)

    ONE_EACH = {n: ["Self-Portrait K.jpg"] for n in ROSTER}


class FiledOnceHoweverOftenThePhotoIsSortedTests(_AWallOfEight, unittest.TestCase):
    """Repair (filed once). Pieces are saved into the children's folders one by
    one. When a photo stopped halfway (the fifth piece could not be saved and
    the photo went to 'failed'; the computer was switched off) and was put
    back into Wall Inbox, or when a teacher uploaded the same photo again
    after putting a name right on the class list, every child who already had
    the piece got it again as 'Self-Portrait K 2.jpg'.

    Every saved piece now says, inside the file, which photo it was cut from
    and where on the photo it was. A piece that is already in the child's
    folder is not saved again, and the log says so."""

    def test_the_reported_steps_failed_at_the_fifth_piece_and_put_back(self):
        self.stop_at_piece(5, OSError(28, "No space left on device"))
        self.sort()
        self.assertEqual(os.listdir(os.path.join(self.inbox, "failed")), ["wall.jpg"])
        got = self.pieces()
        self.assertEqual([got[n] for n in self.ROSTER], [["Self-Portrait K.jpg"]] * 4 + [[]] * 4)

        self.put_back("failed")                     # what a teacher does with a photo in 'failed'
        self.works_again()
        res = self.sort()
        self.assertEqual(self.pieces(), self.ONE_EACH, "a child was given the same piece twice")
        self.assertEqual([(r["name"], r["already"]) for r in res],
                         [(n, True) for n in self.ROSTER[:4]] + [(n, False) for n in self.ROSTER[4:]])
        for r in res:                               # the report still names the file each child has
            self.assertTrue(os.path.exists(r["file"]), r)
        said = [m for m in self.log if "already has this piece from this photo" in m]
        self.assertEqual(len(said), 4, self.log)
        self.assertIn("Maya Torres already has this piece from this photo ('Self-Portrait K.jpg'), "
                      "so it was not filed a second time", said[0])
        self.assertIn("wall.jpg: this photo has been sorted before. 4 of its 8 pieces were already in the "
                      "children's folders and were left as they are; nobody was given a piece twice", self.log)
        self.assertEqual(os.listdir(os.path.join(self.inbox, "done")), ["wall.jpg"])

    def test_a_third_and_a_fourth_time_change_nothing(self):
        self.sort()
        for _ in range(2):
            self.put_back("done")
            res = self.sort()
            self.assertEqual([r["already"] for r in res], [True] * 8)
        self.assertEqual(self.pieces(), self.ONE_EACH)

    def test_the_computer_was_stopped_halfway_and_the_teacher_does_what_the_note_says(self):
        self.stop_at_piece(5, KeyboardInterrupt())   # not an Exception: nothing tidies up, as when killed
        with self.assertRaises(KeyboardInterrupt):
            self.sort()
        self.works_again()
        self.assertEqual(self.sort(), [])            # the restart: it says so and sorts nothing
        note = read(os.path.join(self.unsorted, "NOT FINISHED - Self-Portrait - wall.jpg.txt"))
        for text in (note, " ".join(self.log)):
            self.assertIn("only the missing pieces are filed", text)
            self.assertNotIn("with a 2 at the end", text)
            self.assertNotIn("second copy with", text)
        self.assertIn("keeps it and is not given a second copy", note)

        self.put_back("done")
        self.log.clear()
        res = self.sort()
        self.assertEqual(self.pieces(), self.ONE_EACH)
        self.assertEqual([r["already"] for r in res], [True] * 4 + [False] * 4)

    def test_the_same_photo_uploaded_again_after_the_class_list_was_put_right(self):
        """Theo was not on the class list, so his piece went to a person. The
        teacher adds him and shares the photo again, under another name."""
        without_theo = self.ROSTER[:-1]
        keep = os.path.join(self.tmp, "the teacher's phone.jpg")
        shutil.copy(self.photo, keep)
        res = self.sort(roster=without_theo)
        self.assertEqual([r["status"] == "confident" for r in res], [True] * 7 + [False])
        doubtful = [f for f in os.listdir(self.unsorted) if f.endswith(".jpg")]
        self.assertEqual(len(doubtful), 1, doubtful)
        self.assertEqual(os.listdir(os.path.join(self.unsorted, "name-strips")), doubtful)

        shutil.copy(keep, os.path.join(self.inbox, "IMG_0002.jpg"))
        self.log.clear()
        res = self.sort()
        self.assertEqual(self.pieces(), self.ONE_EACH)
        self.assertEqual([r["already"] for r in res], [True] * 7 + [False])
        self.assertIn("IMG_0002.jpg: this photo has been sorted before. 7 of its 8 pieces", " ".join(self.log))

    def test_a_piece_moved_by_hand_out_of_the_doubtful_folder_is_known_too(self):
        without_theo = self.ROSTER[:-1]
        self.sort(roster=without_theo)
        doubtful = [f for f in os.listdir(self.unsorted) if f.endswith(".jpg")]
        theo = os.path.join(self.cls, "Theo Lane", "Self-Portrait")
        os.makedirs(theo)
        shutil.move(os.path.join(self.unsorted, doubtful[0]), os.path.join(theo, "Theo self portrait.jpg"))
        self.put_back("done")
        res = self.sort()                            # Theo is on the class list now
        self.assertEqual(os.listdir(theo), ["Theo self portrait.jpg"])
        self.assertTrue(res[-1]["already"])

    def test_a_new_photo_of_the_same_wall_is_a_second_piece_as_before(self):
        self.sort()
        _paint_wall(self.photo, self.COLOURS, quality=80)      # taken again: another file
        res = self.sort()
        self.assertEqual([r["already"] for r in res], [False] * 8)
        self.assertEqual(self.pieces(), {n: ["Self-Portrait K 2.jpg", "Self-Portrait K.jpg"] for n in self.ROSTER})
        self.assertFalse([m for m in self.log if "sorted before" in m], self.log)

    def test_a_piece_the_teacher_deleted_is_filed_again(self):
        self.sort()
        os.remove(os.path.join(self.cls, "Sofia Marsh", "Self-Portrait", "Self-Portrait K.jpg"))
        self.put_back("done")
        res = self.sort()
        self.assertEqual(self.pieces(), self.ONE_EACH)
        self.assertEqual([r["name"] for r in res if not r["already"]], ["Sofia Marsh"])

    def test_another_computer_sorting_the_photo_the_second_time_files_nothing_twice(self):
        """Two computers watch one class. What one of them filed is known to
        the other from the pieces themselves, which Google Drive brings to
        both; nothing is kept in either computer's own tool folder."""
        self.stop_at_piece(5, OSError("the disk is full"))
        self.sort()
        self.put_back("failed")
        self.works_again()
        other = os.path.join(self.tmp, "the other computer", "tool")
        os.makedirs(other)
        res = self.sort(out=other)
        self.assertEqual(self.pieces(), self.ONE_EACH)
        self.assertEqual([r["already"] for r in res], [True] * 4 + [False] * 4)

    def test_the_report_says_which_pieces_were_there_already(self):
        self.stop_at_piece(8, OSError("the disk is full"))
        self.sort()
        self.put_back("failed")
        self.works_again()
        self.sort()
        rows = [ln for ln in read(os.path.join(self.out, "run-report.md")).splitlines() if ln.startswith("| ")]
        rows = [ln for ln in rows if "Self-Portrait K.jpg" in ln]
        self.assertEqual(len(rows), 8, rows)
        self.assertEqual([("already there from an earlier try, not filed again" in ln) for ln in rows],
                         [True] * 7 + [False])

    def test_nothing_about_a_child_is_written_into_the_piece(self):
        self.sort()
        path = os.path.join(self.cls, "Maya Torres", "Self-Portrait", "Self-Portrait K.jpg")
        with open(path, "rb") as f:
            data = f.read()
        self.assertIn(bc.MARK + b"photo " + bc.photo_key(os.path.join(self.inbox, "done", "wall.jpg")).encode(), data)
        for word in (b"Maya", b"Torres", b"Room 3", b"Self-Portrait"):
            self.assertNotIn(word, data)
        from PIL import Image
        with Image.open(path) as im:                 # and it is still an ordinary picture
            im.load()
            self.assertEqual(im.size[0] > 100, True)
            self.assertTrue(im.info["comment"].startswith(bc.MARK))


class TwoPapersByOneChildTests(_AWallOfEight, unittest.TestCase):
    """One child can have two papers on the wall. Both are filed, the second
    as '... 2.jpg', and neither is filed again when the photo is put back."""

    ON_THE_WALL = ["Maya Torres", "Jonah Reed", "Maya Torres", "Sofia Marsh"]
    GRID = (1, 4)

    def test_both_are_filed_once(self):
        res = self.sort()
        self.assertEqual([r["already"] for r in res], [False] * 4)
        both = ["Self-Portrait K 2.jpg", "Self-Portrait K.jpg"]
        self.assertEqual(self.pieces()["Maya Torres"], both)
        self.put_back("done")
        res = self.sort()
        self.assertEqual([r["already"] for r in res], [True] * 4)
        self.assertEqual(self.pieces()["Maya Torres"], both)
        self.assertEqual(self.pieces()["Jonah Reed"], ["Self-Portrait K.jpg"])
        self.assertEqual([os.path.basename(r["file"]) for r in res if r["name"] == "Maya Torres"], sorted(both)[::-1])


class SavedWholeOrNotAtAllTests(_AWallOfEight, unittest.TestCase):
    """A piece used to be written straight into the child's folder under its
    real name, so a computer that stopped in the middle of saving left half a
    picture there for Google Drive to upload. It is now written under a name
    ending in '.part' and renamed when it is complete."""

    def pictures(self):
        return [p for p in self.everything_in_the_class_folder() if p.lower().endswith(".jpg")]

    def parts(self):
        return [os.path.relpath(p, self.cls) for p in self.everything_in_the_class_folder() if p.endswith(".part")]

    def test_stopped_in_the_middle_of_saving_the_third_piece(self):
        real, seen = os.replace, []

        def killed_at_the_third(src, dst):
            if src.endswith(".jpg" + bc.PART):
                seen.append(src)
                if len(seen) == 3:
                    raise KeyboardInterrupt
            return real(src, dst)
        with _mock_once.patch.object(bc.os, "replace", killed_at_the_third):
            with self.assertRaises(KeyboardInterrupt):
                self.sort()
        from PIL import Image
        self.assertEqual(len(self.pictures()), 2)
        for p in self.pictures():
            with Image.open(p) as im:
                im.load()                            # every picture that is there is a whole picture
        self.assertEqual(self.parts(), [os.path.join("Sofia Marsh", "Self-Portrait", "Self-Portrait K.jpg.part")])
        self.assertEqual(self.pieces()["Sofia Marsh"], ["Self-Portrait K.jpg.part"])

        self.assertEqual(self.sort(), [])            # the restart
        self.put_back("done")
        res = self.sort()
        self.assertEqual(self.pieces(), self.ONE_EACH)
        self.assertEqual(self.parts(), [])
        self.assertEqual([r["already"] for r in res], [True] * 2 + [False] * 6)

    def test_a_part_file_nobody_came_back_for_is_taken_away_an_hour_later(self):
        d = os.path.join(self.cls, "Maya Torres", "Self-Portrait")
        os.makedirs(d)
        old, fresh = os.path.join(d, "Fall Leaves K.jpg.part"), os.path.join(d, "Fall Leaves K 2.jpg.part")
        for p in (old, fresh):
            with open(p, "wb") as f:
                f.write(b"\xff\xd8 half a picture")
        long_ago = bc.time.time() - bc.SCRATCH_STALE_SECONDS - 60
        os.utime(old, (long_ago, long_ago))
        mine = os.path.join(d, "my own notes.part")            # not the tool's: left alone
        open(mine, "w").close()
        os.utime(mine, (long_ago, long_ago))
        self.sort()
        self.assertEqual(sorted(os.listdir(d)), ["Fall Leaves K 2.jpg.part", "Self-Portrait K.jpg",
                                                 "my own notes.part"])

    def test_a_part_file_that_cannot_be_taken_away_stops_nothing(self):
        d = os.path.join(self.tmp, "folder")
        os.makedirs(d)
        old = os.path.join(d, "Fall Leaves K.jpg.part")
        open(old, "w").close()

        def refuses(path):
            raise PermissionError(13, "in use")
        with _mock_once.patch.object(bc.os, "remove", refuses):
            self.assertIsNone(bc.filed_already(d, "0123456789abcdef", (0, 0, 10, 10), now=bc.time.time() + 7200))
        self.assertTrue(os.path.exists(old))

    def picture(self, mode="RGB"):
        from PIL import Image
        return Image.new(mode, (120, 90), (200, 30, 30) if mode == "RGB" else (0, 200, 200, 0))

    def test_windows_refusing_the_rename_for_a_moment_is_waited_out(self):
        dest = os.path.join(self.tmp, "piece.jpg")
        real, tries, waits = os.replace, [], []

        def busy_twice(src, dst):
            tries.append(src)
            if len(tries) < 3:
                raise PermissionError(13, "The process cannot access the file because it is being used")
            return real(src, dst)
        with _mock_once.patch.object(bc.os, "replace", busy_twice), \
                _mock_once.patch.object(bc.time, "sleep", waits.append):
            self.assertEqual(bc.save_whole(self.picture(), dest), dest)
        self.assertEqual(waits, [bc.RENAME_WAIT] * 2)
        self.assertEqual(sorted(os.listdir(self.tmp)), ["Drive", "piece.jpg", "tool"])

    def test_a_rename_that_never_works_leaves_nothing_behind_and_says_why(self):
        dest = os.path.join(self.tmp, "piece.jpg")

        def busy(src, dst):
            raise PermissionError(13, "Access is denied")
        for remove in (os.remove, _mock_once.Mock(side_effect=OSError("cannot"))):
            with _mock_once.patch.object(bc.os, "replace", busy), \
                    _mock_once.patch.object(bc.time, "sleep", lambda s: None), \
                    _mock_once.patch.object(bc.os, "remove", remove):
                with self.assertRaises(PermissionError):
                    bc.save_whole(self.picture(), dest)
            self.assertFalse(os.path.exists(dest))
        os.remove(dest + bc.PART)                    # the one that could not be removed, above
        self.assertEqual(sorted(os.listdir(self.tmp)), ["Drive", "tool"])

    def test_a_drive_that_cannot_be_told_to_write_now_still_gets_the_whole_file(self):
        dest = os.path.join(self.tmp, "piece.jpg")
        with _mock_once.patch.object(bc.os, "fsync", _mock_once.Mock(side_effect=OSError("not supported"))):
            bc.save_whole(self.picture(), dest, bc.piece_mark("0123456789abcdef", (1, 2, 30, 40)))
        self.assertEqual(bc.read_mark(dest), ("0123456789abcdef", (1, 2, 30, 40)))


class TheNoteInsideAPieceTests(unittest.TestCase):
    """photo_key, piece_mark, read_mark, jpeg_bytes and filed_already on their own."""

    KEY = "0123456789abcdef"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def save(self, name, box, key=None, mode="RGB"):
        from PIL import Image
        p = os.path.join(self.tmp, name)
        bc.save_whole(Image.new(mode, (80, 60)), p, bc.piece_mark(key or self.KEY, box))
        return p

    def test_the_fingerprint_is_of_the_file_not_of_its_name(self):
        a, b, c = (os.path.join(self.tmp, n) for n in ("IMG_0001.jpg", "renamed.jpg", "another.jpg"))
        for p, data in ((a, b"one wall"), (b, b"one wall"), (c, b"another wall")):
            with open(p, "wb") as f:
                f.write(data)
        self.assertEqual(bc.photo_key(a), bc.photo_key(b))
        self.assertNotEqual(bc.photo_key(a), bc.photo_key(c))
        self.assertRegex(bc.photo_key(a), r"^[0-9a-f]{16}$")

    def test_a_photo_that_cannot_be_read_has_no_fingerprint_and_nothing_is_skipped(self):
        self.assertIsNone(bc.photo_key(os.path.join(self.tmp, "gone.jpg")))
        self.assertIsNone(bc.piece_mark(None, (0, 0, 10, 10)))
        self.save("Self-Portrait K.jpg", (0, 0, 100, 100))
        self.assertIsNone(bc.filed_already(self.tmp, None, (0, 0, 100, 100)))
        from PIL import Image
        self.assertNotIn(bc.MARK, bc.jpeg_bytes(Image.new("RGB", (20, 20))))

    def test_the_same_place_on_the_same_photo_is_the_same_piece(self):
        p = self.save("Self-Portrait K.jpg", (100, 100, 500, 400))
        self.assertEqual(bc.read_mark(p), (self.KEY, (100, 100, 500, 400)))
        self.assertEqual(bc.filed_already(self.tmp, self.KEY, (100, 100, 500, 400)), p)
        # the other computer's detector puts the edges a little differently
        self.assertEqual(bc.filed_already(self.tmp, self.KEY, (110.4, 92.0, 515.9, 410.0)), p)
        # the paper next to it, and the same place on another photo
        self.assertIsNone(bc.filed_already(self.tmp, self.KEY, (520, 100, 920, 400)))
        self.assertIsNone(bc.filed_already(self.tmp, "f" * 16, (100, 100, 500, 400)))

    def test_files_without_a_note_are_never_taken_for_the_piece(self):
        from PIL import Image
        Image.new("RGB", (80, 60)).save(os.path.join(self.tmp, "Self-Portrait K.jpg"))       # an older version's
        with open(os.path.join(self.tmp, "Self-Portrait K 2.jpg"), "wb") as f:
            f.write(b"\xff\xd8" + bc.MARK + b"photo of something else")                        # a note cut short
        self.save("Maya - work.docx", (0, 0, 100, 100))                                       # not a picture
        self.save(".hidden.jpg", (0, 0, 100, 100))
        os.makedirs(os.path.join(self.tmp, "a folder.jpg"))
        self.assertIsNone(bc.filed_already(self.tmp, self.KEY, (0, 0, 100, 100)))
        self.assertIsNone(bc.read_mark(os.path.join(self.tmp, "a folder.jpg")))
        self.assertIsNone(bc.filed_already(os.path.join(self.tmp, "no such folder"), self.KEY, (0, 0, 1, 1)))

    def test_a_picture_without_the_usual_header_gets_its_note_too(self):
        p = self.save("Self-Portrait K.jpeg", (0, 0, 100, 100), mode="CMYK")
        with open(p, "rb") as f:
            self.assertEqual(f.read(4), b"\xff\xd8\xff\xfe")
        self.assertEqual(bc.filed_already(self.tmp, self.KEY, (0, 0, 100, 100)), p)
        from PIL import Image
        with Image.open(p) as im:
            im.load()

    def test_the_read_me_says_what_the_tool_now_does(self):
        text = " ".join(_readme_section(read(os.path.join(ROOT, "README.md")),
                                        "### If the computer stops in the middle of a photo").split())
        for words in ("only the missing pieces are filed", "is not given a second copy",
                      "The same goes for a photo that is shared again", ".part"):
            self.assertIn(words, text)
        self.assertNotIn("gets a second copy with a 2", text)


@unittest.skipUnless(bc.backend_ready(), "the name reader is not available on this machine")
class FiledOnceOnARealWallTests(unittest.TestCase):
    """The reported steps end to end: a synthetic wall of eight papers
    (make_wall.py, invented names), the real detectors and the real name
    reader, the fifth piece failing, the photo put back."""

    NAMES = ["Maya", "Jonah", "Sofia", "Elijah", "Priya", "Marcus", "Lily", "Theo"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Drive", "Room 3")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.unsorted = os.path.join(self.cls, "Unsorted - needs a person")
        self.out = os.path.join(self.tmp, "tool")
        os.makedirs(self.out)
        sys.path.insert(0, HERE)
        from make_wall import make_wall
        img, _ = make_wall(self.NAMES)
        img.save(os.path.join(self.inbox, "wall.jpg"), quality=90)
        self.saved = (bc.piece_name, bc.is_settled)
        bc.is_settled = lambda p, wait=0: True

    def tearDown(self):
        bc.piece_name, bc.is_settled = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sort(self, log):
        return bc.run_inbox(self.inbox, self.NAMES, self.out, "Self-Portrait", log=log.append, grade="K",
                            sorted_dir=self.cls, unsorted_dir=self.unsorted)

    def pieces(self):
        return {n: sorted(os.listdir(os.path.join(self.cls, n, "Self-Portrait"))) for n in self.NAMES}

    def test_failed_at_the_fifth_piece_put_back_and_nobody_has_it_twice(self):
        real, calls = self.saved[0], []

        def fifth_fails(project, grade, folder, ext=".jpg"):
            calls.append(folder)
            if len(calls) == 5:
                raise OSError(28, "No space left on device")
            return real(project, grade, folder, ext)
        bc.piece_name = fifth_fails
        log = []
        self.sort(log)
        self.assertEqual(os.listdir(os.path.join(self.inbox, "failed")), ["wall.jpg"], log)
        first = self.pieces()
        self.assertEqual(sorted(first.values()), [[]] * 4 + [["Self-Portrait K.jpg"]] * 4, first)

        shutil.move(os.path.join(self.inbox, "failed", "wall.jpg"), os.path.join(self.inbox, "wall.jpg"))
        bc.piece_name = real
        log = []
        res = self.sort(log)
        got = self.pieces()
        self.assertFalse([f for files in got.values() for f in files if f != "Self-Portrait K.jpg"], got)
        self.assertGreaterEqual(len([n for n in self.NAMES if got[n]]), 7, got)
        self.assertEqual(sorted(r["name"] for r in res if r["already"]), sorted(n for n in self.NAMES if first[n]))
        self.assertEqual(len([m for m in log if "already has this piece from this photo" in m]), 4, log)


# ---------------------------------------------------------------------------
# Repair (a class folder whose name ends with a space): a Mac, a phone and
# Google Drive in a browser keep a folder name that ends with a space or a
# full stop; Windows cannot open such a folder. A settings file written on a
# Mac named one, so the classroom PC could not be pointed at the same folder,
# and nothing said so: not the self-check, not the log, not the class tool.

class FolderNameEndsWithASpaceTests(unittest.TestCase):
    """The class folder here is 'Kindergarten - Room 3 ' (a space at the end),
    an invented class in a temporary folder. The self-check and the watcher's
    log say in plain words what is wrong and what to do; the class tool
    refuses to make such a folder; and the day the folder is renamed in Google
    Drive, the settings file that still has the space leads to it."""

    BAD = "Kindergarten - Room 3 "
    GOOD = "Kindergarten - Room 3"

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.drive = os.path.join(self.tmp, "My Drive")
        os.makedirs(self.drive)
        self.out = os.path.join(self.tmp, "tool")
        os.makedirs(self.out)
        self.settings = os.path.join(self.tmp, "settings.json")
        self.saved = (bc.IS_WIN, bc.my_drive_candidates, bc.time.sleep, bc.run_inbox, bc.GRACE_SECONDS)
        bc.my_drive_candidates = lambda: [os.path.join(self.tmp, "Other Drive"), self.drive]
        os.makedirs(os.path.join(self.tmp, "Other Drive"))

    def tearDown(self):
        bc.IS_WIN, bc.my_drive_candidates, bc.time.sleep, bc.run_inbox, bc.GRACE_SECONDS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_class(self, name):
        cls = os.path.join(self.drive, name)
        os.makedirs(os.path.join(cls, "Wall Inbox"))
        os.makedirs(os.path.join(cls, "Unsorted - needs a person"))
        with open(os.path.join(cls, "Class list.txt"), "w", encoding="utf-8") as f:
            f.write("Maya Torres\nJordan Lum\n")
        return cls

    def write_settings(self, name, root="{DRIVE}"):
        with open(self.settings, "w", encoding="utf-8") as f:
            json.dump({"inbox": f"{root}/{name}/Wall Inbox", "sorted": f"{root}/{name}",
                       "unsorted": f"{root}/{name}/Unsorted - needs a person",
                       "roster": f"{root}/{name}/Class list.txt",
                       "project": "Self-Portrait", "grade": "K", "interval": 1, "priority": 50}, f)

    def check(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = bc.self_check(self.settings)
        return code, buf.getvalue()

    # --- the rule itself ---------------------------------------------------

    def test_the_names_that_end_with_a_space_or_a_full_stop_are_found(self):
        self.assertEqual(bc.bad_endings("{DRIVE}/" + self.BAD + "/Wall Inbox"), [self.BAD])
        self.assertEqual(bc.bad_endings("C:\\Users\\teacher\\My Drive\\Room 3.\\Wall Inbox"), ["Room 3."])
        self.assertEqual(bc.bad_endings("{DRIVE}/Room 3 /Room 3 /Done. "), ["Room 3 ", "Done. "])
        for fine in ("{DRIVE}/" + self.GOOD + "/Wall Inbox", "~/My Drive/Class list.txt", "../a/./b", "/a/.../b",
                     "%USERPROFILE%/My Drive/Maya T", "G:\\My Drive\\Room 3", "", None):
            self.assertEqual(bc.bad_endings(fine), [], fine)

    def test_taking_the_endings_off_leaves_the_rest_of_the_path_alone(self):
        self.assertEqual(bc.without_bad_endings("/d/" + self.BAD + "/Wall Inbox"), "/d/" + self.GOOD + "/Wall Inbox")
        self.assertEqual(bc.without_bad_endings("G:\\My Drive\\Room 3. \\Class list.txt"),
                         "G:\\My Drive\\Room 3\\Class list.txt")
        self.assertEqual(bc.without_bad_endings("../a/./b/.../c"), "../a/./b/.../c")
        self.assertEqual(bc.without_bad_endings("/d/" + self.GOOD), "/d/" + self.GOOD)

    def test_on_windows_the_name_without_the_ending_is_the_only_one_there_can_be(self):
        bc.IS_WIN = True
        self.assertEqual(bc.as_found_here("G:\\My Drive\\" + self.BAD + "\\Wall Inbox"),
                         "G:\\My Drive\\" + self.GOOD + "\\Wall Inbox")
        self.assertEqual(bc.as_found_here("G:\\My Drive\\" + self.BAD), "G:\\My Drive\\" + self.GOOD)
        self.assertEqual(bc.as_found_here("G:\\My Drive\\" + self.GOOD), "G:\\My Drive\\" + self.GOOD)

    # --- a Mac that has the folder under the name with the space -------------

    @unittest.skipIf(bc.IS_WIN, "Windows cannot make the folder this test starts from")
    def test_the_self_check_warns_in_plain_words_and_the_mac_is_still_ready(self):
        cls = self.make_class(self.BAD)
        self.write_settings(self.BAD)
        self.assertEqual(bc.load_settings(self.settings)["sorted"], cls, "the folder that is there is the one used")
        code, out = self.check()
        if not bc.backend_ready():
            self.skipTest("no name reader on this machine")
        self.assertEqual(code, 0, out)
        self.assertIn(f"  WARN: the folder name '{self.BAD}' ends with a space.", out)
        for phrase in ("a Windows PC cannot", f"rename the folder to '{self.GOOD}'", "drive.google.com",
                       "double-click Setup again on every computer that watches this class",
                       "The settings file can stay as it is."):
            self.assertIn(phrase, out)
        self.assertEqual(out.count("WARN: the folder name"), 1, "said once, not once per folder in the settings")
        self.assertTrue(out.rstrip().endswith("READY") and "NOT READY" not in out, out)

    @unittest.skipIf(bc.IS_WIN, "Windows cannot make the folder this test starts from")
    def test_a_full_stop_at_the_end_is_said_as_a_full_stop(self):
        self.make_class("Room 3 Jr.")
        self.write_settings("Room 3 Jr.")
        code, out = self.check()
        if not bc.backend_ready():
            self.skipTest("no name reader on this machine")
        self.assertIn("WARN: the folder name 'Room 3 Jr.' ends with a full stop.", out)
        self.assertIn("rename the folder to 'Room 3 Jr'", out)

    def test_a_folder_with_an_ordinary_name_says_nothing_about_names(self):
        self.make_class(self.GOOD)
        self.write_settings(self.GOOD)
        code, out = self.check()
        if not bc.backend_ready():
            self.skipTest("no name reader on this machine")
        self.assertEqual(code, 0, out)
        self.assertNotIn("ends with", out)
        self.assertNotIn("at the end", out)

    # --- the folder has been renamed in Google Drive; the settings file has not

    def test_after_the_rename_the_old_settings_file_still_leads_to_the_folder(self):
        cls = self.make_class(self.GOOD)
        self.write_settings(self.BAD)
        st = bc.load_settings(self.settings)
        self.assertEqual(st["sorted"], cls)
        self.assertEqual(st["inbox"], os.path.join(cls, "Wall Inbox"))
        self.assertEqual(st["roster"], os.path.join(cls, "Class list.txt"))
        self.assertEqual(bc.load_roster(st["roster"]), ["Maya Torres", "Jordan Lum"])
        code, out = self.check()
        if not bc.backend_ready():
            self.skipTest("no name reader on this machine")
        self.assertEqual(code, 0, out)
        self.assertIn(f"  ok: the settings file says '{self.BAD}', with a space at the end; on this computer the "
                      f"folder is '{self.GOOD}', and that is the one used.", out)
        self.assertNotIn("WARN: the folder name", out)
        self.assertNotIn("FAIL", out)

    def test_the_same_on_a_windows_pc_where_the_path_is_written_out_in_full(self):
        bc.IS_WIN = True
        cls = self.make_class(self.GOOD)
        self.write_settings(self.BAD, root=self.drive)
        st = bc.load_settings(self.settings)
        self.assertEqual(os.path.normpath(st["sorted"]), cls)
        self.assertEqual(os.path.normpath(st["inbox"]), os.path.join(cls, "Wall Inbox"))

    def test_with_two_google_drives_the_one_that_has_the_renamed_folder_is_picked(self):
        cls = self.make_class(self.GOOD)
        self.assertEqual(bc.expand_path("{DRIVE}/" + self.BAD + "/Wall Inbox"), os.path.join(cls, "Wall Inbox"))

    # --- one settings file, written once, read by a Mac and by a Windows PC ---
    #
    # The settings file says '{DRIVE}/Kindergarten - Room 3/Wall Inbox', with
    # forward slashes, on every computer. In the build of Sep 28 2026 the
    # Windows build machine showed the path the program made of it:
    # '...\My Drive\Kindergarten - Room 3/Wall Inbox', half one way and half the
    # other, in the log a person reads and in every comparison of two paths.

    def record(self, what):
        """A line for the build's own record (tests-on-build-machine.txt in the bundle)."""
        sys.stderr.write(f"\nEVIDENCE[paths] {sys.platform}: {what}\n")
        sys.stderr.flush()

    def test_forward_slashes_in_a_settings_file_become_backslashes_on_a_windows_pc(self):
        self.assertEqual(bc.own_separators("C:\\Users\\teacher/My Drive/" + self.GOOD + "/Wall Inbox", sep="\\"),
                         "C:\\Users\\teacher\\My Drive\\" + self.GOOD + "\\Wall Inbox")
        self.assertEqual(bc.own_separators("G:\\My Drive\\Room 3", sep="\\"), "G:\\My Drive\\Room 3")
        self.assertEqual(bc.own_separators("{DRIVE}/" + self.BAD + "/Wall Inbox", sep="\\"),
                         "{DRIVE}\\" + self.BAD + "\\Wall Inbox", "the space at the end is not this one's to take off")

    def test_on_a_mac_a_path_is_left_exactly_as_it_was_written(self):
        for written in ("/Users/teacher/My Drive/Room 3/Wall Inbox", "/d/a name with a \\ in it/Wall Inbox",
                        "{DRIVE}/" + self.BAD + "/Wall Inbox", "", None):
            self.assertEqual(bc.own_separators(written, sep="/"), written)

    def test_every_path_from_a_settings_file_is_written_one_way_on_this_computer(self):
        cls = self.make_class(self.GOOD)
        not_ours = "/" if os.sep == "\\" else "\\"
        for written in ("{DRIVE}/" + self.GOOD + "/Wall Inbox", "{DRIVE}/" + self.BAD + "/Wall Inbox",
                        self.drive + "/" + self.GOOD + "/Wall Inbox"):
            got = bc.expand_path(written)
            self.assertEqual(got, os.path.join(cls, "Wall Inbox"), written)
            self.assertNotIn(not_ours, got)
        self.write_settings(self.GOOD)
        st = bc.load_settings(self.settings)
        self.assertEqual([st[k] for k in ("inbox", "sorted", "unsorted", "roster")],
                         [os.path.join(cls, "Wall Inbox"), cls, os.path.join(cls, "Unsorted - needs a person"),
                          os.path.join(cls, "Class list.txt")])
        example = bc.load_settings(os.path.join(ROOT, "settings.example.json"))
        for k in ("inbox", "sorted", "unsorted", "roster"):
            self.assertNotIn(not_ours, example[k], "the settings file every class starts from")

    @unittest.skipUnless(sys.platform == "win32", "prints the paths a real Windows PC made, for the build's "
                                                  "record; the tests above cover every computer")
    def test_on_windows_the_record_of_the_paths_a_settings_file_gives(self):
        self.record(f"the temporary folder is {tempfile.gettempdir()!r}; written out in full it is "
                    f"{os.path.realpath(tempfile.gettempdir())!r}; this test's own is {self.tmp!r}")
        self.make_class(self.GOOD)
        self.write_settings(self.BAD)
        st = bc.load_settings(self.settings)
        example = bc.load_settings(os.path.join(ROOT, "settings.example.json"))
        self.record(f"settings file with the space at the end gives {[st[k] for k in ('inbox', 'sorted', 'roster')]}")
        self.record(f"settings.example.json gives {[example[k] for k in ('inbox', 'sorted', 'roster')]}")
        out = self.watch(self.stop_at(3))
        self.record(f"the watcher's log: {[ln for ln in out.splitlines() if 'control tower for ' in ln or 'waiting' in ln]}")
        for p in [st[k] for k in ("inbox", "sorted", "unsorted", "roster")] + [example["inbox"]]:
            self.assertNotIn("/", p)
        self.assertIn("control tower for " + st["inbox"] + " (Ctrl+C to stop)", out)

    # --- the folder cannot be found at all (the classroom PC today) ----------

    def test_a_folder_that_cannot_be_found_fails_and_says_why_and_what_to_do(self):
        self.write_settings(self.BAD)
        code, out = self.check()
        if not bc.backend_ready():
            self.skipTest("no name reader on this machine")
        self.assertEqual(code, 1, out)
        self.assertIn(f"  FAIL: the name '{self.BAD}' in the settings file ends with a space, and this computer "
                      f"cannot find the folder under that name or as '{self.GOOD}'.", out)
        for phrase in ("A Windows PC cannot open a folder whose name ends with a space or a full stop.",
                       f"rename the folder to '{self.GOOD}'", "run this check again"):
            self.assertIn(phrase, out)
        self.assertTrue(out.rstrip().endswith("NOT READY"), out)

    # --- the watcher's log ----------------------------------------------------

    def watch(self, on_sleep):
        ticks = []

        def fake_sleep(seconds):
            ticks.append(seconds)
            on_sleep(len(ticks))
        bc.time.sleep = fake_sleep
        bc.GRACE_SECONDS = 0
        bc.run_inbox = lambda *a, **k: []
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                bc.main(["--watch", "--settings", self.settings, "--out", self.out])
        return buf.getvalue()

    def stop_at(self, n):
        def stop(tick):
            if tick >= n:
                raise KeyboardInterrupt
        return stop

    def test_a_watcher_waiting_for_a_folder_it_cannot_find_says_the_name_is_the_reason(self):
        self.write_settings(self.BAD)

        def teacher(tick):
            if tick == 2:
                self.make_class(self.GOOD)          # the folder is renamed in Google Drive and arrives
            if tick >= 4:
                raise KeyboardInterrupt
        out = self.watch(teacher)
        self.assertEqual(out.count("waiting: cannot find"), 1, out)
        waiting = [ln for ln in out.splitlines() if "waiting: cannot find" in ln][0]
        self.assertIn(f"Also: the folder name '{self.BAD}' in the settings file ends with a space.", waiting)
        self.assertIn(f"rename the folder to '{self.GOOD}'", waiting)
        self.assertIn("control tower for " + os.path.join(self.drive, self.GOOD, "Wall Inbox"), out,
                      "it starts by itself once the renamed folder is there")
        self.assertNotIn("Traceback", out)

    @unittest.skipIf(bc.IS_WIN, "Windows cannot make the folder this test starts from")
    def test_a_watcher_on_a_mac_that_has_the_folder_says_it_once_at_start(self):
        self.make_class(self.BAD)
        self.write_settings(self.BAD)
        out = self.watch(self.stop_at(3))
        self.assertIn("control tower for " + os.path.join(self.drive, self.BAD, "Wall Inbox"), out)
        self.assertEqual(out.count(f"the folder name '{self.BAD}' in the settings file ends with a space."), 1, out)
        self.assertIn("A Windows PC cannot open a folder whose name ends with a space or a full stop.", out)

    def test_a_watcher_whose_folder_has_an_ordinary_name_says_nothing_about_names(self):
        self.make_class(self.GOOD)
        for name in (self.GOOD, self.BAD):          # the second: renamed already, old settings file
            self.write_settings(name)
            out = self.watch(self.stop_at(3))
            self.assertIn("control tower for " + os.path.join(self.drive, self.GOOD, "Wall Inbox"), out)
            self.assertNotIn("ends with", out)

    # --- the class tool and the read-me ----------------------------------------

    @unittest.skipUnless(os.path.exists(NEW_CLASS_TOOL), "the class tool is not part of this copy")
    def test_the_class_tool_will_not_make_a_folder_a_windows_pc_cannot_open(self):
        spec = _importlib_util.spec_from_file_location("new_class_under_test_names", NEW_CLASS_TOOL)
        nc = _importlib_util.module_from_spec(spec)
        spec.loader.exec_module(nc)
        roster = os.path.join(self.tmp, "roster.txt")
        _write(roster, "Maya Torres\nJordan Lum\n")
        for name, said in ((self.BAD, f"ends with a space. A Windows PC cannot open a folder whose name ends with "
                                      f"a space or a full stop. Use '{self.GOOD}' instead."),
                           ("Room 3 Jr.", "ends with a full stop."),
                           ("Unit 2: Leaves", "has a character that a Windows PC cannot use in a folder name")):
            argv = ["new_class.py", "--class-name", name, "--roster", roster, "--drive-root", self.drive]
            with _mock.patch.object(nc, "ROOT", self.out), _mock.patch.object(sys, "argv", argv):
                with self.assertRaises(SystemExit) as stop:
                    nc.main()
            self.assertIn(said, str(stop.exception))
            self.assertEqual(os.listdir(self.drive), [], "nothing is made in Google Drive")
            self.assertFalse(os.path.exists(os.path.join(self.out, "classes")))
            self.assertFalse(os.path.exists(os.path.join(self.out, ".private-names")))
        for fine in (self.GOOD, "Zoë's class, 5-6"):
            self.assertIsNone(nc.class_name_problem(fine), fine)
        self.assertIn("no space or full stop at the very end of the name", nc.README)

    def test_the_read_me_says_what_the_check_says_and_what_to_do(self):
        text = " ".join(read(os.path.join(ROOT, "README.md")).split())
        section = text.split("### A class folder whose name ends with a space")[1].split("## ")[0]
        for phrase in ("a space or a full stop", "A Windows PC cannot open", "rename the folder",
                       "`WARN: the folder name", "double-click Setup again", "settings file can stay as it is"):
            self.assertIn(phrase, section)


def _heic_wall(folder, name="IMG_0001.HEIC"):
    """A synthetic wall saved the way an iPhone saves it. Returns the path, or
    None when this computer has nothing that can write a HEIC file."""
    sys.path.insert(0, HERE)
    from make_wall import make_wall
    img, _ = make_wall(["Maya Torres", "Priya Nair"], rows=1, cols=2, size=(800, 400))
    heic = os.path.join(folder, name)
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        img.save(heic, quality=90)
        return heic
    except ImportError:
        if not bc.IS_MAC:
            return None
    jpg = os.path.join(os.path.dirname(folder), "wall-for-heic.jpg")
    img.save(jpg, quality=90)
    r = bc.subprocess.run(["sips", "-s", "format", "heic", jpg, "--out", heic], capture_output=True)
    os.remove(jpg)
    return heic if r.returncode == 0 and os.path.exists(heic) else None


def _tree(top):
    """Every file under a folder, as paths from that folder, sorted."""
    return sorted(os.path.relpath(os.path.join(d, f), top).replace(os.sep, "/")
                  for d, _, fs in os.walk(top) for f in fs)


class HeicStoppedMidPhotoTests(unittest.TestCase):
    """Repair 3, the whole story as it was reported: an iPhone photo arrives
    in Wall Inbox, the watcher starts on it and is stopped in the middle, and
    the watcher starts again. While the photo is being sorted the inbox must
    hold nothing but the photo itself, and after the stop there must be no
    JPEG copy anywhere in the inbox for the next start (or for another
    computer that shares the folder through Google Drive) to sort as a second
    photo of the same wall."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inbox = os.path.join(self.tmp, "Wall Inbox")
        self.out = os.path.join(self.tmp, "Class")
        os.makedirs(self.inbox)
        os.makedirs(self.out)
        self.heic = _heic_wall(self.inbox)
        if not self.heic:
            self.skipTest("this computer cannot write a HEIC test photo")
        self.saved = (bc.is_settled, bc.read_photo_text, bc.detect_pieces, bc.pieces_from_labels)
        bc.is_settled = lambda path, wait=2.0: True
        bc.detect_pieces = lambda img, path: []
        bc.pieces_from_labels = lambda *a, **k: None
        self.lines = []

    def tearDown(self):
        if hasattr(self, "saved"):
            bc.is_settled, bc.read_photo_text, bc.detect_pieces, bc.pieces_from_labels = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sort(self):
        return bc.run_inbox(self.inbox, ["Maya Torres", "Priya Nair"], self.out, "Art", log=self.lines.append)

    def test_while_the_photo_is_sorted_the_inbox_holds_only_the_photo(self):
        seen = {}

        def reading(img, path, tmpdir, **k):
            seen["inbox"] = _tree(self.inbox)
            seen["read from"] = path
            seen["scratch"] = tmpdir
            return []
        bc.read_photo_text = reading
        self.sort()
        self.assertEqual(seen["inbox"], ["done/IMG_0001.HEIC"])
        self.assertEqual(os.path.dirname(seen["read from"]), seen["scratch"])
        self.assertTrue(seen["scratch"].startswith(os.path.join(self.out, ".tmp") + os.sep))
        self.assertEqual(_tree(self.inbox), ["done/IMG_0001.HEIC"])
        self.assertFalse(os.path.exists(os.path.join(self.out, ".tmp")))

    def test_stopped_in_the_middle_and_started_again_the_wall_is_not_sorted_as_two_photos(self):
        def stopped(img, path, tmpdir, **k):
            raise KeyboardInterrupt()       # the watcher is stopped after the JPEG copy was made
        bc.read_photo_text = stopped
        with self.assertRaises(KeyboardInterrupt):
            self.sort()
        self.assertEqual(_tree(self.inbox), ["done/IMG_0001.HEIC"], "no JPEG copy may stay in the inbox")
        self.assertEqual(bc.inbox_jobs(self.inbox, "Art"), [])
        started = []
        bc.read_photo_text = lambda img, path, tmpdir, **k: started.append(path) or []
        self.sort()
        self.assertEqual(started, [], "nothing is left in the inbox to sort a second time")
        self.assertFalse([l for l in self.lines if "IMG_0001.HEIC.jpg" in l], self.lines)


class JpegCopyFromAnOlderVersionTests(unittest.TestCase):
    """Repair 3, for a class that two computers share while one of them still
    has the older version. That computer writes 'IMG_0001.HEIC.jpg' into Wall
    Inbox next to the iPhone photo for as long as it works on the photo, and
    leaves it there for good when it is stopped in the middle. Google Drive
    brings the copy to this computer. It is the same wall, so this computer
    must not sort it as a second photo. A photo that only has such a name,
    with no iPhone photo to go with it, is still a photo and is still sorted:
    a teacher's photo is never quietly skipped."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inbox = os.path.join(self.tmp, "Wall Inbox")
        os.makedirs(self.inbox)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, *parts):
        path = os.path.join(self.inbox, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"photo")
        return path

    def waiting(self):
        return [os.path.relpath(j[0], self.inbox).replace(os.sep, "/") for j in bc.inbox_jobs(self.inbox, "Art")]

    def test_a_copy_next_to_its_iphone_photo_is_not_a_second_photo(self):
        self.put("IMG_0001.HEIC")
        self.put("IMG_0001.HEIC.jpg")
        self.put("img_0002.heic")
        self.put("img_0002.heic.JPG")
        self.assertEqual(self.waiting(), ["IMG_0001.HEIC", "img_0002.heic"])

    def test_a_copy_whose_iphone_photo_is_already_in_done_or_failed_is_not_sorted(self):
        self.put("done", "IMG_0001.HEIC")
        self.put("IMG_0001.HEIC.jpg")
        self.put("failed", "IMG_0003.HEIC")
        self.put("IMG_0003.HEIC.jpg")
        self.assertEqual(self.waiting(), [])

    def test_the_same_inside_a_project_folder(self):
        self.put("Fall Leaves", "IMG_0001.HEIC")
        self.put("Fall Leaves", "IMG_0001.HEIC.jpg")
        self.put("done", "Fall Leaves", "IMG_0002.HEIC")
        self.put("Fall Leaves", "IMG_0002.HEIC.jpg")
        self.put("Fall Leaves", "wall.jpg")
        self.assertEqual(self.waiting(), ["Fall Leaves/IMG_0001.HEIC", "Fall Leaves/wall.jpg"])

    def test_a_photo_that_only_has_such_a_name_is_still_sorted(self):
        self.put("IMG_0009.HEIC.jpg")            # no IMG_0009.HEIC anywhere
        self.put("wall.heic")
        self.put("wall.jpg")                     # another photo, not a copy of wall.heic
        self.put("wall.heic.png")                # the older version only ever wrote .jpg
        self.assertEqual(self.waiting(), ["IMG_0009.HEIC.jpg", "wall.heic", "wall.heic.png", "wall.jpg"])

    def test_the_watcher_sorts_the_wall_once_and_leaves_the_copy_alone(self):
        out = os.path.join(self.tmp, "Class")
        os.makedirs(out)
        self.put("IMG_0001.HEIC")
        copy = self.put("IMG_0001.HEIC.jpg")
        sorted_photos, lines = [], []
        saved = (bc.is_settled, bc.process_photo)
        bc.is_settled = lambda path, wait=2.0: True
        bc.process_photo = lambda path, *a, **k: sorted_photos.append(os.path.basename(path)) or []
        try:
            for _ in range(2):      # the second look finds the iPhone photo in done
                bc.run_inbox(self.inbox, ["Maya Torres"], out, "Art", log=lines.append)
        finally:
            bc.is_settled, bc.process_photo = saved
        self.assertEqual(sorted_photos, ["IMG_0001.HEIC"])
        self.assertTrue(os.path.exists(copy), "the other computer may be reading it; it is not this computer's to move")
        self.assertTrue(os.path.exists(os.path.join(self.inbox, "done", "IMG_0001.HEIC")))


class OneScratchFolderPerSelfCheckTests(unittest.TestCase):
    """Repair (scratch folder, the self-check): `--check` drew its test word
    into one fixed file, <tool folder>/.selfcheck.png, read it back and deleted
    it. One tool folder holds several classes, and each class is checked from
    that same folder, so two checks at the same time (or two runs of the tests)
    wrote and deleted the same file: the slower one stopped with "No such file
    or directory" and the teacher saw a crash where READY should have been.
    The check now draws into a scratch folder of its own, exactly as every
    photo does (.tmp/<process id>-<random letters>), and takes only that
    folder away.

    Two checks run as two threads. Check B is held at a known point (its
    picture is saved and it is about to read it) while check A runs from start
    to finish. Nothing is timed. The tool folder is a temporary one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tool = os.path.join(self.tmp, "tool")            # the one tool folder both checks run from
        cls = os.path.join(self.tmp, "Drive", "Room 3")
        os.makedirs(self.tool)
        os.makedirs(os.path.join(cls, "Wall Inbox"))
        os.makedirs(os.path.join(cls, "Unsorted - needs a person"))
        with open(os.path.join(cls, "Class list.txt"), "w", encoding="utf-8") as f:
            f.write("Maya Torres\nJordan Lum\n")
        self.settings = os.path.join(self.tmp, "class.json")
        with open(self.settings, "w", encoding="utf-8") as f:
            json.dump({"inbox": os.path.join(cls, "Wall Inbox"), "sorted": cls,
                       "unsorted": os.path.join(cls, "Unsorted - needs a person"),
                       "roster": os.path.join(cls, "Class list.txt"),
                       "project": "Self-Portrait", "grade": "K", "interval": 1, "priority": 50}, f)
        self.saved = (bc.HERE, bc.run_vision, bc.backend_ready, bc.my_drive_candidates)
        bc.HERE = self.tool
        bc.my_drive_candidates = lambda: []
        self.b_has_a_picture, self.a_is_finished = threading.Event(), threading.Event()
        self.read_from = {"a": [], "b": []}

    def tearDown(self):
        bc.HERE, bc.run_vision, bc.backend_ready, bc.my_drive_candidates = self.saved
        self.a_is_finished.set()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def hold_b_before_it_reads(self, reader):
        """Wrap a reader: check B stops with its picture saved, until check A
        has run from start to finish, and then reads that picture."""
        def read(mode, path, *extra):
            who = threading.current_thread().name
            self.read_from[who].append(path)
            if who == "b" and not self.b_has_a_picture.is_set():
                self.b_has_a_picture.set()
                if not self.a_is_finished.wait(120):
                    raise AssertionError("check A never finished")
            return reader(mode, path, *extra)
        return read

    @staticmethod
    def a_reader_that_opens_the_file(mode, path, *extra):
        from PIL import Image
        with Image.open(path) as im:       # No such file or directory, if somebody else took it away
            im.load()
        return [{"text": "Baggage 42"}]

    def both_at_once(self):
        """Returns ({"a": exit code, "b": exit code}, everything both printed)."""
        codes, wrong, buf = {}, {}, io.StringIO()

        def b():
            try:
                codes["b"] = bc.self_check(self.settings)
            except BaseException as e:   # noqa: B036  (reported by the test, not swallowed)
                wrong["b"] = e
        t = threading.Thread(target=b, name="b")
        threading.current_thread().name, mine = "a", threading.current_thread().name
        try:
            with contextlib.redirect_stdout(buf):
                t.start()
                self.assertTrue(self.b_has_a_picture.wait(120), wrong)
                try:
                    codes["a"] = bc.self_check(self.settings)
                finally:
                    self.a_is_finished.set()
                t.join(120)
        finally:
            threading.current_thread().name = mine
        self.assertEqual(wrong, {}, "check B stopped because check A finished first")
        return codes, buf.getvalue()

    def test_a_check_finishing_first_does_not_delete_the_other_checks_picture(self):
        bc.backend_ready = lambda: True
        bc.run_vision = self.hold_b_before_it_reads(self.a_reader_that_opens_the_file)
        codes, said = self.both_at_once()
        self.assertEqual(codes, {"a": 0, "b": 0}, said)
        self.assertEqual(said.count("ok: reader read back 'Baggage 42'"), 2, said)
        self.assertEqual(said.count("READY"), 2, said)
        self.assertNotIn("NOT READY", said)

    def test_no_two_checks_are_handed_the_same_file_and_none_is_in_the_tool_folder_itself(self):
        bc.backend_ready = lambda: True
        bc.run_vision = self.hold_b_before_it_reads(self.a_reader_that_opens_the_file)
        self.both_at_once()
        (a,), (b,) = self.read_from["a"], self.read_from["b"]
        self.assertNotEqual(a, b, "two checks drew their test word into the same file")
        self.assertNotEqual(os.path.dirname(a), os.path.dirname(b))
        for p in (a, b):
            self.assertEqual(os.path.dirname(os.path.dirname(p)), os.path.join(self.tool, ".tmp"))

    def test_nothing_is_left_in_the_tool_folder_afterwards(self):
        bc.backend_ready = lambda: True
        bc.run_vision = self.hold_b_before_it_reads(self.a_reader_that_opens_the_file)
        self.both_at_once()
        self.assertEqual(os.listdir(self.tool), [])

    def test_a_reader_that_stops_leaves_nothing_behind_either(self):
        bc.backend_ready = lambda: True

        def broken(mode, path, *extra):
            raise RuntimeError("vision text failed: the reader stopped")
        bc.run_vision = broken
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                bc.self_check(self.settings)
        self.assertEqual(os.listdir(self.tool), [])

    def test_a_photo_being_cut_in_the_same_tool_folder_keeps_its_crops(self):
        """The watcher and the check share <tool folder>/.tmp: the check takes
        its own folder away and leaves the photo's folder where it is."""
        bc.backend_ready = lambda: True
        bc.run_vision = self.a_reader_that_opens_the_file
        photo = bc.scratch_folder(self.tool)
        crop = os.path.join(photo, "crop-1.png")
        with open(crop, "wb") as f:
            f.write(b"a crop")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bc.self_check(self.settings), 0)
        self.assertTrue(os.path.exists(crop))
        self.assertEqual(os.listdir(os.path.join(self.tool, ".tmp")), [os.path.basename(photo)])
        bc.drop_scratch(photo)
        self.assertEqual(os.listdir(self.tool), [])

    def test_two_checks_at_once_with_the_real_reader(self):
        if not self.saved[2]():
            self.skipTest("no name reader on this machine")
        bc.run_vision = self.hold_b_before_it_reads(self.saved[1])
        codes, said = self.both_at_once()
        self.assertEqual(codes, {"a": 0, "b": 0}, said)
        self.assertEqual(said.count("ok: reader read back"), 2, said)
        self.assertEqual(os.listdir(self.tool), [])


class CheckSetupSaysWhenTheRunningWatcherIsBehindTests(_ASharedClass, unittest.TestCase):
    """Repair (two computers sorting one class, the part that was still live):
    every repair for a class shared with an older version was on the helper's
    Mac already, in the program and in the settings file ("shared": true,
    priority 90). The watcher running on that Mac had been started hours
    before, and a watcher reads the settings file and the program once, when
    it starts. So it still sorted every photo at once, with priority 50, next
    to the classroom computer that sorts every photo too. Nothing said so:
    Check Setup read the settings file and printed "this computer leaves each
    new photo for that computer for 10 minutes" about a watcher that did no
    such thing. The check now compares the watcher that is running (its own
    status file) with the settings file and the program, and says what is
    different and the one thing to do. It still ends in READY, so Setup, which
    starts the watcher again, is not stopped by its own check.

    The watcher from before is played by a status file written the way that
    watcher wrote it. No photo is opened and the reader is a stand-in."""

    def setUp(self):
        super().setUp()
        self.tool = os.path.join(self.tmp, "tool")
        os.makedirs(self.tool)
        self.saved_check = (bc.HERE, bc.run_vision, bc.backend_ready, bc.my_drive_candidates)
        bc.HERE = self.tool
        bc.run_vision = lambda mode, path, *extra: [{"text": "Baggage 42"}]
        bc.backend_ready = lambda: True
        bc.my_drive_candidates = lambda: []
        self.sdir = bc.status_dir(self.cls)
        self.me = bc.machine_name()

    def tearDown(self):
        bc.HERE, bc.run_vision, bc.backend_ready, bc.my_drive_candidates = self.saved_check
        super().tearDown()

    def a_watcher_from_this_afternoon(self, priority=50, hours_ago=4, role="watching", **kw):
        """The watcher that is running: started hours ago, before the settings
        file said the class is shared, and still writing its status file."""
        now = bc.time.time()
        bc.write_status(self.sdir, self.me, now, role, priority, started=now - hours_ago * 3600, **kw)

    def behind(self, program=()):
        return bc.watcher_behind(self.sdir, self.me, bc.load_settings(self.settings), self.settings,
                                 program=list(program))

    def check(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = bc.self_check(self.settings)
        return code, buf.getvalue()

    def test_the_report_the_watcher_from_this_afternoon_is_found_out(self):
        self.a_watcher_from_this_afternoon()
        why = self.behind()
        self.assertEqual(len(why), 3, why)
        self.assertEqual(why[0], "It sorts with priority 50; the settings file says 90.")
        self.assertIn("it sorts each new photo at once and does not leave it for the other computer first, "
                      "so a child can get the same piece twice", why[1])
        self.assertTrue(why[2].startswith("The settings file was changed at "), why[2])
        self.assertIn("after the control tower started", why[2])

    def test_check_setup_says_so_with_the_one_thing_to_do_and_is_still_ready(self):
        self.a_watcher_from_this_afternoon()
        code, out = self.check()
        self.assertEqual(code, 0, out)                  # Setup runs this check before it restarts the watcher
        self.assertTrue(out.rstrip().endswith("READY"), out)
        self.assertEqual(out.count("  WARN: the control tower that is running on this computer is still working "
                                   "the old way."), 1, out)
        self.assertIn("        It sorts with priority 50; the settings file says 90.", out)
        self.assertIn("Double-click Setup (Setup.command on a Mac, Setup.bat on a Windows PC)", out)
        self.assertIn("nothing is lost", out)

    def test_check_setup_no_longer_says_the_running_watcher_does_what_it_does_not_do(self):
        self.a_watcher_from_this_afternoon()
        out = self.check()[1]
        self.assertNotIn("this computer leaves each new photo for that computer", out)
        self.assertIn("this class is shared, the settings file says. The control tower that is running on this "
                      "computer started before that was written; see the WARN below.", out)

    def test_a_watcher_started_with_these_settings_is_not_behind(self):
        # the real watch loop, started now, with the settings file as it is
        self.drop_photo()
        self.run_main(stop_after=2)
        self.assertIn("Note: this class is shared", self.status_text())
        self.assertEqual(bc.watcher_behind(self.sdir, self.me, bc.load_settings(self.settings), self.settings), [])
        code, out = self.check()
        self.assertEqual(code, 0)
        self.assertNotIn("WARN: the watcher", out)
        self.assertIn("this class is shared: The settings file says another computer watches this class too", out)

    def test_no_watcher_running_here_is_not_a_watcher_that_is_behind(self):
        self.assertEqual(self.behind(), [])                                 # no status file at all
        long_ago = bc.time.time() - bc.STALE_SECONDS - 60
        bc.write_status(self.sdir, self.me, long_ago, "watching", 50, started=long_ago - 3600)
        self.assertEqual(self.behind(), [])                                 # it stopped over five minutes ago
        self.assertNotIn("WARN: the watcher", self.check()[1])
        with open(os.path.join(self.sdir, self.me + ".txt"), "w") as f:
            f.write("not a status file\n")
        self.assertEqual(self.behind(), [])

    def test_a_status_file_with_no_started_line_is_still_found_out_by_what_it_says(self):
        # a watcher from before the 'Watcher started' line existed
        now = bc.time.time()
        bc.write_status(self.sdir, self.me, now, "watching", 50)
        self.assertNotIn("Watcher started", self.status_text())
        why = self.behind()
        self.assertEqual(len(why), 2, why)
        self.assertTrue(why[0].startswith("It sorts with priority 50"))
        self.write_settings(priority=50)                                    # same priority, class not shared
        self.assertEqual(self.behind(), [])

    def test_a_new_version_of_the_program_is_a_reason_too(self):
        program = os.path.join(self.tool, "baggage-claim")
        with open(program, "w") as f:
            f.write("the new version, unzipped over the folder a moment ago")
        long_ago = bc.time.time() - 30 * 86400
        os.utime(program, (long_ago, long_ago))         # a zip keeps the day the program was built
        self.write_settings(priority=50)
        self.a_watcher_from_this_afternoon()
        why = self.behind(program=[program])
        self.assertEqual([w.split(" was changed at ")[0] for w in why], ["The settings file", "The program"], why)
        # a watcher started after the program arrived is up to date
        self.a_watcher_from_this_afternoon(hours_ago=0)
        self.assertEqual(self.behind(program=[program]), [])

    def test_a_computer_that_is_standing_by_or_has_company_is_not_told_off_for_the_shared_line(self):
        self.a_watcher_from_this_afternoon(priority=90, hours_ago=0, role="standing by", leader="CLASSROOM-PC")
        self.assertEqual(self.behind(), [])
        self.a_watcher_from_this_afternoon(priority=90, hours_ago=0)
        bc.write_status(self.sdir, "CLASSROOM-PC", bc.time.time(), "standing by", 95)
        self.assertEqual(self.behind(), [])             # the other computer has reported in: the election covers it
        os.remove(os.path.join(self.sdir, "CLASSROOM-PC.txt"))
        self.assertEqual(len(self.behind()), 1)

    def test_a_priority_that_is_not_a_number_counts_as_the_usual_one(self):
        self.write_settings(priority="high", shared=False)
        self.a_watcher_from_this_afternoon(priority=50, hours_ago=0)
        self.assertEqual(self.behind(), [])

    def test_the_started_line_is_read_back_as_it_was_written(self):
        started = 1_800_000_000.0
        text = bc.format_status("Helpers-MacBook", started + 600, "watching", 90, started=started)
        self.assertEqual(bc.started_at(text), started - started % 60)
        self.assertIsNone(bc.started_at(bc.format_status("Helpers-MacBook", started, "watching", 90)))
        self.assertIsNone(bc.started_at("Watcher started: some time this afternoon\n"))

    def test_the_time_a_file_was_changed(self):
        self.assertIsNone(bc.changed_at([os.path.join(self.tmp, "not there"), None]))
        self.assertGreater(bc.changed_at([self.settings, os.path.join(self.tmp, "not there")]), NOW - 10 * 365 * 86400)
        self.assertEqual(bc.program_files(), [os.path.abspath(bc.__file__)])

    def test_the_program_files_of_a_one_click_bundle(self):
        exe = os.path.join(self.tool, "BaggageClaim.exe")
        watcher = os.path.join(self.tool, "BaggageClaimWatcher.exe")
        for p in (exe, watcher):
            open(p, "w").close()
        saved = (getattr(sys, "frozen", None), sys.executable)
        sys.frozen, sys.executable = True, exe
        try:
            self.assertEqual(bc.program_files(), [exe, watcher])
            os.remove(watcher)
            self.assertEqual(bc.program_files(), [exe])
        finally:
            sys.executable = saved[1]
            if saved[0] is None:
                del sys.frozen
            else:
                sys.frozen = saved[0]

    def test_the_read_me_says_when_to_start_the_watcher_again_and_how(self):
        text = read(os.path.join(ROOT, "README.md"))
        self.assertIn("### After a change, start the control tower again", text)
        section = " ".join(text.split("### After a change, start the control tower again")[1].split("\n## ")[0].split())
        for phrase in ("once, when it starts", "`Setup.command`", "`Setup.bat`",
                       "`WARN: the control tower that is running on this computer is still working the old way`",
                       "It still says READY"):
            self.assertIn(phrase, section)


class _AClassInDrive:
    """Repair (a renamed folder came back empty). An invented class, 'Room 3',
    in a temporary folder that stands for Google Drive, and a tool folder of
    its own. No photo is opened: process_photo is a stand-in that files one
    piece for Maya Torres, and the 'photos' are a few bytes."""

    PROJECT = "Self-Portrait"
    CLASS_NAME = "Room 3"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.drive = os.path.join(self.tmp, "Drive")
        self.cls = os.path.join(self.drive, self.CLASS_NAME)
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.unsorted = os.path.join(self.cls, "Unsorted - needs a person")
        self.roster = os.path.join(self.cls, "Class list.txt")
        with open(self.roster, "w", encoding="utf-8") as f:
            f.write("Maya Torres\nJordan Lum\n")
        self.out = os.path.join(self.tmp, "tool")
        os.makedirs(self.out)
        self.settings = os.path.join(self.tmp, "settings.json")
        self.write_settings(inbox=self.inbox, sorted=self.cls, unsorted=self.unsorted, roster=self.roster)
        self.saved = (bc.time.sleep, bc.is_settled, bc.GRACE_SECONDS, bc.process_photo, bc.my_drive_candidates,
                      bc.HERE)
        bc.GRACE_SECONDS = 0
        bc.is_settled = lambda p, wait=0: True
        self.sorted_photos = []

        def process_photo(path, roster, out_dir, project, grid=None, log=print, grade="", sorted_dir=None,
                          unsorted_dir=None):
            self.sorted_photos.append(path)
            folder = os.path.join(sorted_dir, "Maya Torres", project)
            os.makedirs(folder, exist_ok=True)
            saved_as = os.path.join(folder, bc.piece_name(project, grade, folder))
            open(saved_as, "w").close()
            return [{"piece": 1, "status": "confident", "name": "Maya Torres", "text": "Maya", "score": 1.0,
                     "margin": 1.0, "box": None, "file": saved_as, "bbox": (0, 0, 1, 1)}]
        bc.process_photo = process_photo
        self.log = []

    def tearDown(self):
        (bc.time.sleep, bc.is_settled, bc.GRACE_SECONDS, bc.process_photo, bc.my_drive_candidates,
         bc.HERE) = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_settings(self, **paths):
        with open(self.settings, "w", encoding="utf-8") as f:
            json.dump(dict(paths, project=self.PROJECT, grade="K", interval=1, priority=50), f)

    def drop_photo(self, folder, name="wall.jpg"):
        with open(os.path.join(folder, name), "wb") as f:
            f.write(b"\xff\xd8 not really a jpeg")
        return os.path.join(folder, name)

    def status_text(self, cls=None):
        try:
            return read(os.path.join(cls or self.cls, "Watcher status", bc.machine_name() + ".txt"))
        except OSError:
            return ""

    def everything_in(self, top):
        found = []
        for folder, dirs, files in os.walk(top):
            found += [os.path.relpath(os.path.join(folder, n), top) for n in dirs + files]
        return sorted(found)

    def run_main(self, teacher, stop_after):
        """The real watch loop. `teacher` is called while the watcher sleeps
        between two looks at the inbox, with the number of the look just done
        and everything the log has said so far."""
        ticks = []
        buf = io.StringIO()

        def fake_sleep(s):
            ticks.append(s)
            teacher(len(ticks), buf.getvalue())
            if len(ticks) >= stop_after:
                raise KeyboardInterrupt
        bc.time.sleep = fake_sleep
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                bc.main(["--watch", "--settings", self.settings, "--out", self.out])
        return buf.getvalue()


class RenamedFolderIsNotMadeAgainTests(_AClassInDrive, unittest.TestCase):
    """Every look at the inbox began with os.makedirs(<inbox>/done), which
    makes every folder on the way down. A teacher who renamed 'Wall Inbox' had
    an empty 'Wall Inbox' back within five seconds and her photos were never
    seen; a class folder that was renamed came back empty under the old name;
    and the log said nothing, because every call succeeded. Now the watcher
    looks for the two folders first, on every look, says in plain words when
    one is gone, makes nothing in its place, and carries on by itself when
    the folder is back."""

    def test_the_report_wall_inbox_is_renamed_while_the_watcher_runs(self):
        photos = os.path.join(self.cls, "Photos")
        seen = {}

        def teacher(look, log):
            if look == 1:                   # the watcher is running; she renames the folder and adds a photo
                os.rename(self.inbox, photos)
                self.drop_photo(photos)
            if look in (2, 3):              # five and ten seconds later, on a real computer
                seen[look] = (sorted(os.listdir(self.cls)), self.status_text(), log,
                              os.path.exists(os.path.join(photos, "wall.jpg")))
            if look == 3 and not os.path.exists(self.inbox):
                os.rename(photos, self.inbox)       # she reads the status file and gives the folder its name back
        out = self.run_main(teacher, stop_after=5)
        for look in (2, 3):
            names, status, log, photo_waits = seen[look]
            self.assertNotIn("Wall Inbox", names, "an empty Wall Inbox was made in place of the renamed one")
            self.assertIn("Photos", names)
            self.assertTrue(photo_waits, "her photo is where she put it")
            self.assertIn("cannot find the folder 'Wall Inbox' any more", log)
            self.assertIn("Role: standing by", status)
            self.assertIn("Note: this computer cannot find the folder 'Wall Inbox', so nothing is being sorted",
                          status)
            self.assertIn("Photos waiting in Arrivals: not known", status)
            self.assertNotIn("the control tower for this class", status)
        self.assertEqual(out.count("cannot find the folder 'Wall Inbox' any more"), 1, "said once, not every look")
        self.assertIn("give the folder its old name back, 'Wall Inbox', in Google Drive", out)
        self.assertIn("Photos put into a folder with another name are not seen", out)
        self.assertIn("the folders are there again", out)
        # with its name back, the photo she added is sorted without anybody starting anything
        self.assertEqual([os.path.basename(p) for p in self.sorted_photos], ["wall.jpg"], out)
        self.assertTrue(os.path.exists(os.path.join(self.inbox, "done", "wall.jpg")))
        self.assertEqual(os.listdir(os.path.join(self.cls, "Maya Torres", self.PROJECT)), ["Self-Portrait K.jpg"])
        self.assertIn("Role: the control tower for this class", self.status_text())

    def test_the_report_the_class_folder_is_renamed_while_the_watcher_runs(self):
        renamed = os.path.join(self.drive, "Room 3 - Kindergarten")
        seen = {}

        def teacher(look, log):
            if look == 1:
                os.rename(self.cls, renamed)
                self.drop_photo(os.path.join(renamed, "Wall Inbox"))
                seen["work"] = self.everything_in(renamed)
            if look in (2, 3, 4):
                seen[look] = (sorted(os.listdir(self.drive)), self.everything_in(renamed))
        out = self.run_main(teacher, stop_after=4)
        for look in (2, 3, 4):
            in_drive, in_class = seen[look]
            self.assertEqual(in_drive, ["Room 3 - Kindergarten"],
                             "the class was made again, empty, under its old name")
            self.assertEqual(in_class, seen["work"], "the folder that holds the real work is left as it is")
        self.assertFalse(os.path.exists(self.cls))
        self.assertEqual(self.sorted_photos, [], "nothing is filed into a folder made in place of the class folder")
        self.assertEqual(out.count("cannot find the folder 'Room 3' any more"), 1, out)
        self.assertIn("It has been renamed, moved or deleted", out)
        self.assertIn("the settings file on this computer has to say the new name", out)
        self.assertNotIn("Wall Inbox' any more", out, "one thing happened, and it is said once")
        self.assertNotIn("could not write this computer's status file", out)

    def test_the_class_folder_is_given_its_name_back_and_the_watcher_carries_on(self):
        renamed = os.path.join(self.drive, "Room 3 - Kindergarten")

        def teacher(look, log):
            if look == 1:
                os.rename(self.cls, renamed)
                self.drop_photo(os.path.join(renamed, "Wall Inbox"))
            if look == 3 and not os.path.exists(self.cls):
                os.rename(renamed, self.cls)
        out = self.run_main(teacher, stop_after=5)
        self.assertEqual(sorted(os.listdir(self.drive)), ["Room 3"])
        self.assertEqual([os.path.basename(p) for p in self.sorted_photos], ["wall.jpg"], out)
        self.assertIn("the folders are there again", out)
        self.assertIn("Role: the control tower for this class", self.status_text())

    def test_google_drive_signs_out_and_nothing_is_built_on_the_computers_own_disk(self):
        away = os.path.join(self.tmp, "Drive is signed out")
        seen = {}

        def drive(look, log):
            if look == 1:
                os.rename(self.drive, away)         # the whole Drive folder is gone from the computer
            if look in (2, 3):
                seen[look] = sorted(os.listdir(self.tmp))
            if look == 3 and not os.path.exists(self.drive):
                os.rename(away, self.drive)         # signed in again
                self.drop_photo(self.inbox)
        out = self.run_main(drive, stop_after=5)
        for look in (2, 3):
            self.assertNotIn("Drive", seen[look], "the class was built again as ordinary folders on this computer")
        self.assertEqual(out.count("cannot find the folder 'Room 3' any more"), 1, out)
        self.assertIn("most likely Google Drive is signed out, closed or still starting on this computer", out)
        self.assertIn("open Google Drive on this computer and sign in", out)
        self.assertNotIn("could not write this computer's status file", out)
        self.assertIn("the folders are there again", out)
        self.assertEqual([os.path.basename(p) for p in self.sorted_photos], ["wall.jpg"], out)

    def test_my_drive_moves_while_the_watcher_runs_and_the_watcher_follows_it(self):
        # On Windows "My Drive" can come back under another drive letter. The
        # place was worked out again only while the watcher waited to start.
        first = os.path.join(self.tmp, "G", "My Drive")
        second = os.path.join(self.tmp, "H", "My Drive")
        os.makedirs(os.path.dirname(first))
        os.makedirs(os.path.dirname(second))
        os.rename(self.drive, first)
        bc.my_drive_candidates = lambda: [first, second]
        self.write_settings(inbox="{DRIVE}/Room 3/Wall Inbox", sorted="{DRIVE}/Room 3",
                            unsorted="{DRIVE}/Room 3/Unsorted - needs a person",
                            roster="{DRIVE}/Room 3/Class list.txt")

        def drive(look, log):
            if look == 1:
                os.rename(first, second)
                self.drop_photo(os.path.join(second, "Room 3", "Wall Inbox"))
        out = self.run_main(drive, stop_after=3)
        self.assertEqual(os.listdir(os.path.join(self.tmp, "G")), [], "nothing is made where My Drive used to be")
        self.assertEqual(self.sorted_photos, [os.path.join(second, "Room 3", "Wall Inbox", "done", "wall.jpg")], out)
        self.assertEqual(os.listdir(os.path.join(second, "Room 3", "Maya Torres", self.PROJECT)),
                         ["Self-Portrait K.jpg"])
        self.assertIn("the folders are there again (Arrivals is "
                      + os.path.join(second, "Room 3", "Wall Inbox") + ")", out)
        self.assertNotIn("cannot find", out)
        self.assertIn("Role: the control tower for this class", self.status_text(os.path.join(second, "Room 3")))

    @unittest.skipIf(bc.IS_WIN, "a Windows PC cannot hold a folder whose name ends with a space")
    def test_a_space_taken_off_the_end_of_the_class_folders_name_needs_no_restart(self):
        spaced = self.cls + " "
        os.rename(self.cls, spaced)
        self.write_settings(inbox=os.path.join(spaced, "Wall Inbox"), sorted=spaced,
                            unsorted=os.path.join(spaced, "Unsorted - needs a person"),
                            roster=os.path.join(spaced, "Class list.txt"))

        def teacher(look, log):
            if look == 1:
                os.rename(spaced, self.cls)
                self.drop_photo(self.inbox)
        out = self.run_main(teacher, stop_after=3)
        self.assertEqual(os.listdir(self.drive), ["Room 3"], "the folder with the space was made again")
        self.assertEqual(self.sorted_photos, [os.path.join(self.inbox, "done", "wall.jpg")], out)
        self.assertIn("the folders are there again", out)

    def test_a_photo_left_for_the_other_computer_is_not_said_to_be_taken_when_the_folder_was_renamed(self):
        with open(self.settings, encoding="utf-8") as f:
            st = json.load(f)
        with open(self.settings, "w", encoding="utf-8") as f:
            json.dump(dict(st, shared=True), f)
        self.drop_photo(self.inbox)
        photos = os.path.join(self.cls, "Photos")

        def teacher(look, log):
            if look == 1:
                os.rename(self.inbox, photos)
                os.remove(os.path.join(photos, "wall.jpg"))
            if look == 2 and not os.path.exists(self.inbox):
                os.rename(photos, self.inbox)
        out = self.run_main(teacher, stop_after=4)
        self.assertIn("wall.jpg: new photo, left in Arrivals for the other computer", out)
        self.assertNotIn("The other computer took it", out)
        self.assertEqual(self.sorted_photos, [])

    # ---- one look at the inbox, the way the watch loop does it ----

    def look(self, **k):
        return bc.run_inbox(self.inbox, ["Maya Torres", "Jordan Lum"], self.out, self.PROJECT,
                            log=self.log.append, grade="K", sorted_dir=self.cls, unsorted_dir=self.unsorted, **k)

    def test_a_look_at_an_inbox_that_is_not_there_makes_nothing_and_says_why(self):
        self.look(folders={})
        before = self.everything_in(self.cls)
        os.rename(self.inbox, os.path.join(self.cls, "Photos"))
        for memory in ({}, None):           # the watcher, and a run that is once through
            with self.assertRaises(FileNotFoundError) as e:
                self.look(folders=memory)
            self.assertIn("cannot find the folder 'Wall Inbox' any more", str(e.exception))
            self.assertNotIn("Errno", str(e.exception), "the operating system's words are not a teacher's")
            self.assertFalse(os.path.exists(self.inbox))
        self.assertEqual([n for n in self.everything_in(self.cls) if not n.startswith("Photos")],
                         [n for n in before if not n.startswith("Wall Inbox")])

    def test_an_inbox_kept_outside_the_class_folder_does_not_bring_a_renamed_class_folder_back(self):
        inbox = os.path.join(self.drive, "Wall Inbox")
        os.rename(self.inbox, inbox)
        self.inbox = inbox
        made = {}
        self.look(folders=made)
        os.rename(self.cls, os.path.join(self.drive, "Room 4"))
        photo = self.drop_photo(inbox)
        with open(self.roster.replace("Room 3", "Room 4"), "a", encoding="utf-8") as f:
            f.write("Sofia Marin\n")
        with self.assertRaises(FileNotFoundError) as e:
            bc.run_inbox(inbox, ["Maya Torres", "Jordan Lum", "Sofia Marin"], self.out, self.PROJECT,
                         log=self.log.append, grade="K", sorted_dir=self.cls, unsorted_dir=self.unsorted,
                         folders=made)                  # a new child: her folder cannot be made
        self.assertIn("cannot find the folder 'Room 3' any more", str(e.exception))
        with self.assertRaises(FileNotFoundError):
            self.look(folders=made)                     # nobody new: the photo is not claimed all the same
        self.assertFalse(os.path.exists(self.cls))
        self.assertTrue(os.path.exists(photo), "the photo waits in the inbox")
        self.assertEqual(self.sorted_photos, [])

    def test_a_folder_renamed_in_the_middle_of_a_batch_is_not_blamed_on_another_computer(self):
        self.drop_photo(self.inbox, "wall 1.jpg")
        self.drop_photo(self.inbox, "wall 2.jpg")
        photos = os.path.join(self.cls, "Photos")
        stand_in = bc.process_photo

        def renamed_meanwhile(path, *a, **k):
            res = stand_in(path, *a, **k)
            os.rename(self.inbox, photos)
            return res
        bc.process_photo = renamed_meanwhile
        taken = []
        with self.assertRaises(FileNotFoundError) as e:
            self.look(folders={}, taken=taken)
        self.assertIn("cannot find the folder 'Wall Inbox' any more", str(e.exception))
        self.assertEqual(taken, [], "a renamed folder is not another computer taking the photo")
        self.assertFalse(os.path.exists(self.inbox))
        self.assertTrue(os.path.exists(os.path.join(photos, "wall 2.jpg")))
        self.assertEqual(len(self.sorted_photos), 1)

    # ---- the pieces ----

    def test_make_inside_makes_what_is_inside_and_never_the_folder_itself(self):
        deep = os.path.join(self.cls, "Maya Torres", self.PROJECT)
        self.assertEqual(bc.make_inside(self.cls, deep), deep)
        self.assertTrue(os.path.isdir(deep))
        bc.make_inside(self.cls, deep)                  # there already: nothing to do, nothing to say
        bc.make_inside(self.cls, self.cls)
        gone = os.path.join(self.drive, "Room 9")
        for path in (os.path.join(gone, "Maya Torres", self.PROJECT), os.path.join(gone, "done"), gone):
            with self.assertRaises(FileNotFoundError) as e:
                bc.make_inside(gone, path)
            self.assertIn("cannot find the folder 'Room 9' any more", str(e.exception))
        self.assertFalse(os.path.exists(gone))
        # the tool's own folders, next to the program, are made whole as they always were
        own = os.path.join(self.out, "sorted", "Maya Torres")
        bc.make_inside(None, own)
        self.assertTrue(os.path.isdir(own))

    def test_make_inside_says_it_in_the_systems_words_when_something_else_is_wrong(self):
        with open(os.path.join(self.cls, "Maya Torres"), "w") as f:
            f.write("a file where a folder should be")
        with self.assertRaises(OSError) as e:
            bc.make_inside(self.cls, os.path.join(self.cls, "Maya Torres", self.PROJECT))
        self.assertNotIn("cannot find the folder", str(e.exception))
        # a folder on the way down that was taken away this instant: the class folder is still there
        real = os.mkdir
        os.mkdir = lambda p, *a: (_ for _ in ()).throw(FileNotFoundError(2, "No such file or directory", p))
        try:
            with self.assertRaises(FileNotFoundError) as e:
                bc.make_inside(self.cls, os.path.join(self.cls, "Jordan Lum"))
        finally:
            os.mkdir = real
        self.assertNotIn("cannot find the folder", str(e.exception))

    def test_which_folders_are_gone(self):
        self.assertEqual(bc.folders_gone(self.inbox, self.cls, None, ""), [])
        os.rename(self.inbox, os.path.join(self.cls, "Photos"))
        self.assertEqual(bc.folders_gone(self.inbox, self.cls), [self.inbox])
        self.assertEqual(bc.folders_gone(self.inbox, self.inbox + os.sep), [self.inbox], "each once")
        os.rename(self.cls, os.path.join(self.drive, "Room 4"))
        self.assertEqual(bc.folders_gone(self.inbox, self.cls), [self.cls],
                         "a folder inside one that is gone is the same thing happening")
        elsewhere = os.path.join(self.drive, "Room 33", "Wall Inbox")
        self.assertEqual(bc.folders_gone(elsewhere, self.cls), [elsewhere, self.cls])
        with open(os.path.join(self.drive, "Room 5"), "w") as f:
            f.write("a file is not a folder")
        self.assertEqual(bc.folders_gone(os.path.join(self.drive, "Room 5")), [os.path.join(self.drive, "Room 5")])

    def test_the_status_file_never_makes_the_class_folder(self):
        sdir = bc.status_dir(self.cls)
        path = bc.write_status(sdir, "CLASSROOM-PC", NOW, "watching", 50)
        self.assertTrue(os.path.exists(path), "'Watcher status' is made inside a class folder that is there")
        os.rename(self.cls, os.path.join(self.drive, "Room 4"))
        with self.assertRaises(OSError):
            bc.write_status(sdir, "CLASSROOM-PC", NOW, "watching", 50)
        self.assertFalse(os.path.exists(self.cls))

    def test_the_note_about_an_unfinished_photo_never_makes_the_class_folder(self):
        # the inbox and the class folder side by side, and the class folder is the one renamed
        inbox = os.path.join(self.cls + " photos", "Wall Inbox")
        done = os.path.join(inbox, "done")
        os.makedirs(done)
        self.drop_photo(inbox)
        bc.mark_started(self.out, inbox, os.path.join(inbox, "wall.jpg"), os.path.join(done, "wall.jpg"),
                        self.PROJECT)
        os.rename(os.path.join(inbox, "wall.jpg"), os.path.join(done, "wall.jpg"))
        os.rename(self.cls, os.path.join(self.drive, "Room 4"))
        told = bc.tell_unfinished(inbox, self.out, self.log.append, self.unsorted, self.cls)
        self.assertEqual(told, ["wall.jpg"])
        self.assertIn("A note for the teacher could not be written", self.log[-1])
        self.assertFalse(os.path.exists(self.cls))
        # and a class folder that is there is never made for the note's sake either
        self.assertIsNone(bc.held_by(self.unsorted, os.path.join(self.drive, "Room 33")))
        self.assertIsNone(bc.held_by(None, self.cls))
        self.assertIsNone(bc.held_by(self.unsorted, None))
        self.assertEqual(bc.held_by(self.unsorted, self.cls), self.cls)
        self.assertEqual(bc.held_by(self.cls, self.cls), self.cls)

    def test_a_doubtful_pieces_folder_kept_somewhere_else_is_made_whole_as_before(self):
        self.drop_photo(self.inbox)
        done = os.path.join(self.inbox, "done")
        os.makedirs(done)
        bc.mark_started(self.out, self.inbox, os.path.join(self.inbox, "wall.jpg"),
                        os.path.join(done, "wall.jpg"), self.PROJECT)
        os.rename(os.path.join(self.inbox, "wall.jpg"), os.path.join(done, "wall.jpg"))
        elsewhere = os.path.join(self.tmp, "For the teacher", "Unsorted - needs a person")
        bc.tell_unfinished(self.inbox, self.out, self.log.append, elsewhere)
        self.assertEqual(os.listdir(elsewhere), ["NOT FINISHED - Self-Portrait - wall.jpg.txt"])

    def test_the_doubtful_pieces_folder_is_still_made_when_it_is_needed(self):
        self.drop_photo(self.inbox)
        done = os.path.join(self.inbox, "done")
        os.makedirs(done)
        bc.mark_started(self.out, self.inbox, os.path.join(self.inbox, "wall.jpg"),
                        os.path.join(done, "wall.jpg"), self.PROJECT)
        os.rename(os.path.join(self.inbox, "wall.jpg"), os.path.join(done, "wall.jpg"))
        self.assertFalse(os.path.exists(self.unsorted))
        bc.tell_unfinished(self.inbox, self.out, self.log.append, self.unsorted)
        self.assertEqual(os.listdir(self.unsorted), ["NOT FINISHED - Self-Portrait - wall.jpg.txt"])

    def test_once_through_with_an_inbox_that_is_not_there(self):
        gone = os.path.join(self.drive, "Room 3", "Photos from the wall")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as e:
                bc.main(["--roster", self.roster, "--inbox", gone, "--out", self.out, "--sorted", self.cls])
        self.assertIn("cannot find the inbox folder, so nothing was sorted", str(e.exception))
        self.assertFalse(os.path.exists(gone))

    def test_once_through_the_tools_own_inbox_is_made_the_first_time(self):
        bc.HERE = os.path.join(self.tmp, "a new copy of the tool")
        os.makedirs(bc.HERE)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(bc.main(["--roster", self.roster, "--out", self.out]), 0)
        self.assertTrue(os.path.isdir(os.path.join(bc.HERE, "inbox", "done")))
        self.assertIn("0 pieces", buf.getvalue())

    def test_the_read_me_says_what_happens_when_a_folder_is_renamed(self):
        text = " ".join(read(os.path.join(ROOT, "README.md")).split())
        self.assertIn("### If Arrivals or the class folder is renamed", text)
        section = text.split("### If Arrivals or the class folder is renamed")[1].split("### ")[0]
        for phrase in ("`cannot find the folder 'Arrivals' any more`", "never makes a new",
                       "give the folder its old name back", "carries on by itself", "`Watcher status`",
                       "Google Drive is signed out"):
            self.assertIn(phrase, section)


class RenamedFolderOnARealWallTests(_AClassInDrive, unittest.TestCase):
    """The same, with the real cutting and filing and a synthetic wall from
    make_wall.py: a piece that is about to be filed never makes the class
    folder, or the folder that holds the doubtful pieces, again."""

    NAMES = ["Maya", "Jonah", "Sofia", "Elijah"]

    def setUp(self):
        super().setUp()
        bc.process_photo = self.saved[3]
        sys.path.insert(0, HERE)
        from make_wall import make_wall
        img, _ = make_wall(self.NAMES, rows=1, cols=4, size=(2400, 700))
        self.wall = os.path.join(self.tmp, "wall.jpg")
        img.save(self.wall, quality=90)

    @unittest.skipUnless(bc.backend_ready(), "no name reader on this machine")
    def test_a_piece_is_not_filed_into_a_class_folder_made_in_place_of_the_renamed_one(self):
        os.rename(self.cls, os.path.join(self.drive, "Room 4"))
        with self.assertRaises(FileNotFoundError) as e:
            bc.process_photo(self.wall, self.NAMES, self.out, self.PROJECT, log=self.log.append, grade="K",
                             sorted_dir=self.cls, unsorted_dir=self.unsorted)
        self.assertIn("cannot find the folder 'Room 3' any more", str(e.exception))
        self.assertEqual(os.listdir(self.drive), ["Room 4"])
        # nobody on the class list is on this wall, so every piece is a doubtful one
        with self.assertRaises(FileNotFoundError) as e:
            bc.process_photo(self.wall, ["Zed Quill"], self.out, self.PROJECT, log=self.log.append, grade="K",
                             sorted_dir=self.cls, unsorted_dir=self.unsorted)
        self.assertIn("cannot find the folder 'Room 3' any more", str(e.exception))
        self.assertEqual(os.listdir(self.drive), ["Room 4"])

    @unittest.skipUnless(bc.backend_ready(), "no name reader on this machine")
    def test_with_the_folders_there_the_wall_is_filed_as_before(self):
        shutil.copy(self.wall, os.path.join(self.inbox, "wall.jpg"))
        res = bc.run_inbox(self.inbox, self.NAMES, self.out, self.PROJECT, log=self.log.append, grade="K",
                           sorted_dir=self.cls, unsorted_dir=self.unsorted, folders={})
        self.assertEqual(len(res), 4, res)
        for r in res:
            self.assertTrue(os.path.exists(r["file"]), r)
            self.assertTrue(r["file"].startswith(self.cls + os.sep), r)
        self.assertEqual(sorted(os.listdir(self.inbox)), ["done"])


class RenamedFolderSaidOnceAndOnlyWhenGoneTests(_AClassInDrive, unittest.TestCase):
    """Two things the repair above must not get wrong: a folder this program
    is not allowed to look at is not a folder that was renamed, and a rename
    that is noticed in the middle of a look is said once, not twice."""

    def test_a_folder_this_program_may_not_look_at_is_not_gone(self):
        real = os.stat

        def refused(p, *a, **k):
            if os.fspath(p) == self.inbox:
                raise PermissionError(1, "Operation not permitted", self.inbox)
            return real(p, *a, **k)
        os.stat = refused
        try:
            self.assertFalse(bc.is_gone(self.inbox))
            self.assertEqual(bc.folders_gone(self.inbox, self.cls), [])
        finally:
            os.stat = real
        self.assertFalse(bc.is_gone(self.inbox))
        self.assertTrue(bc.is_gone(os.path.join(self.cls, "Photos")))
        self.assertTrue(bc.is_gone(os.path.join(self.roster, "Wall Inbox")), "inside a file there is no folder")
        self.assertTrue(bc.is_gone(self.roster), "a file is not a folder")

    def test_a_rename_in_the_middle_of_a_look_is_said_once_and_the_rest_is_sorted_afterwards(self):
        self.drop_photo(self.inbox, "wall 1.jpg")
        self.drop_photo(self.inbox, "wall 2.jpg")
        photos = os.path.join(self.cls, "Photos")
        stand_in = bc.process_photo

        def renamed_meanwhile(path, *a, **k):
            res = stand_in(path, *a, **k)
            if len(self.sorted_photos) == 1:
                os.rename(self.inbox, photos)
            return res
        bc.process_photo = renamed_meanwhile
        seen = {}

        def teacher(look, log):
            if look == 2:
                seen["names"] = sorted(os.listdir(self.cls))
            if look == 3 and not os.path.exists(self.inbox):
                os.rename(photos, self.inbox)
        out = self.run_main(teacher, stop_after=5)
        self.assertNotIn("Wall Inbox", seen["names"])
        self.assertEqual(out.count("cannot find the folder 'Wall Inbox' any more"), 1, out)
        self.assertNotIn("another computer took it", out)
        self.assertNotIn("older version of Baggage Claim is the control tower", out)
        self.assertIn("the folders are there again", out)
        self.assertEqual([os.path.basename(p) for p in self.sorted_photos], ["wall 1.jpg", "wall 2.jpg"], out)
        self.assertEqual(sorted(os.listdir(os.path.join(self.inbox, "done"))), ["wall 1.jpg", "wall 2.jpg"])


class ClassListReloadOnAComputerStandingByTests(unittest.TestCase):
    """Repair (class list), with two computers on one class: the classroom
    computer sorts and a helper's computer stands by. The teacher adds a child
    to the class list while the helper's computer is standing by. It must
    read the new list all the same, so that when the classroom computer is
    switched off and this one takes over, the new child is known from the
    first look: the child gets a folder and the new list goes to the sorting.
    The real run_inbox, an empty inbox, invented names, temporary folders."""

    PROJECT = "Self-Portrait"
    TWO = ["Maya Torres", "Jonah Reed"]
    THREE = ["Maya Torres", "Jonah Reed", "Sofia Marin"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Drive", "Room 3")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.out = os.path.join(self.tmp, "tool")
        os.makedirs(self.out)
        self.roster = os.path.join(self.cls, "Class list - one first name per line.txt")
        with open(self.roster, "w", encoding="utf-8") as f:
            f.write("".join(n + "\n" for n in self.TWO))
        self.settings = os.path.join(self.tmp, "settings.json")
        with open(self.settings, "w") as f:
            json.dump({"inbox": self.inbox, "sorted": self.cls,
                       "unsorted": os.path.join(self.cls, "Unsorted - needs a person"), "roster": self.roster,
                       "project": self.PROJECT, "grade": "K", "interval": 1, "priority": 90}, f)
        self.saved = (bc.time.sleep, bc.run_inbox, bc.GRACE_SECONDS)
        bc.GRACE_SECONDS = 0
        self.handed = []
        real = bc.run_inbox

        def run_inbox(inbox, roster, *a, **k):
            self.handed.append(list(roster))
            return real(inbox, roster, *a, **k)
        bc.run_inbox = run_inbox

    def tearDown(self):
        bc.time.sleep, bc.run_inbox, bc.GRACE_SECONDS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def classroom_computer(self, seconds_ago):
        bc.write_status(bc.status_dir(self.cls), "CLASSROOM-PC", bc.time.time() - seconds_ago, "watching", 50)

    def has_folder(self, child):
        return os.path.isdir(os.path.join(self.cls, child, self.PROJECT))

    def run_main(self, on_sleep, stop_after):
        ticks = []

        def fake_sleep(s):
            ticks.append(s)
            on_sleep(len(ticks))
            if len(ticks) >= stop_after:
                raise KeyboardInterrupt
        bc.time.sleep = fake_sleep
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                bc.main(["--watch", "--settings", self.settings, "--out", self.out])
        return buf.getvalue()

    def test_a_child_added_while_standing_by_is_known_when_this_computer_takes_over(self):
        self.classroom_computer(seconds_ago=0)
        seen = {}

        def day(tick):
            if tick == 1:       # standing by; the teacher adds the new child
                with open(self.roster, "a", encoding="utf-8") as f:
                    f.write("Sofia Marin\n")
            if tick == 3:       # still standing by, two looks later: the list was read, nothing was sorted
                seen["sorted while standing by"] = list(self.handed)
                self.classroom_computer(seconds_ago=3600)       # the classroom computer is switched off
        out = self.run_main(day, stop_after=5)
        self.assertIn("standing by, CLASSROOM-PC is the control tower for this class", out)
        self.assertEqual(seen["sorted while standing by"], [], out)
        self.assertEqual(out.count("class list changed: 3 children (there were 2)"), 1, out)
        self.assertIn("this computer is the control tower for this class", out)
        # from its first look as the computer that sorts, the list has the new child on it
        self.assertEqual(self.handed, [self.THREE, self.THREE], out)
        for child in self.THREE:
            self.assertTrue(self.has_folder(child), f"{child} has no folder\n{out}")

    def test_without_a_change_to_the_list_the_take_over_uses_the_list_from_the_start(self):
        self.classroom_computer(seconds_ago=0)

        def day(tick):
            if tick == 2:
                self.classroom_computer(seconds_ago=3600)
        out = self.run_main(day, stop_after=4)
        self.assertNotIn("class list changed", out)
        self.assertEqual(self.handed, [self.TWO, self.TWO], out)
        self.assertFalse(has_folder_named(self.cls, "Sofia Marin"))

    def test_the_read_me_says_what_to_do_when_the_other_computer_has_an_older_version(self):
        text = " ".join(read(os.path.join(ROOT, "README.md")).split())
        section = text.split("### A new child joins the class")[1].split("### ")[0]
        for phrase in ("Nobody restarts anything",
                       "When two computers watch the same class, both need this version",
                       "reads the class list only when it starts",
                       "restart that computer after adding a child"):
            self.assertIn(phrase, section)


def has_folder_named(class_folder, child):
    return os.path.isdir(os.path.join(class_folder, child))


# ---------------------------------------------------------------------------
# Repair (name read, picture to check): one photo of a whole wall, or pale
# paper on a pale wall, and the paper detectors cannot be trusted, so every
# piece is cut out around its name label and sent to a person (the edges are
# a guess). Every one of them was called 'GUESS <child> ...' and logged as
# 'unsure ... score 1.0', so a teacher who opened 'Unsorted - needs a person'
# found 25 GUESS files and concluded the name reader had failed, and the
# status file said '25 pieces, 0 filed, 25 to unsorted' with no cause. Now
# such a piece is called 'CHECK PICTURE <child> ...', a note beside the pieces
# says what happened and what to do, and the log, the report and the status
# file all say that the names were read and the pictures are what to check.

def _pale_wall(path, size=(2400, 1600)):
    """A plain pale picture. Nothing on it is a child's work: the fake name
    reader below says where the name labels are."""
    from PIL import Image
    Image.new("RGB", size, (250, 250, 248)).save(path, quality=90)


class _AWholeWallInOnePhoto:
    """Eight invented children, one photo, a name reader that reads all eight
    name labels, and paper detectors that find two papers. Runs on any
    computer: no reader and no detector is needed."""

    ROSTER = ["Maya Torres", "Jonah Reed", "Sofia Marsh", "Elijah Stone",
              "Priya Nair", "Marcus Bell", "Lily Okafor", "Theo Lane"]
    PAPERS_FOUND = 2

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Drive", "Room 3")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.unsorted = os.path.join(self.cls, "Unsorted - needs a person")
        self.out = os.path.join(self.tmp, "tool")
        os.makedirs(self.out)
        self.roster = os.path.join(self.cls, "Class list.txt")
        with open(self.roster, "w", encoding="utf-8") as f:
            f.write("\n".join(self.ROSTER) + "\n")
        self.settings = os.path.join(self.tmp, "settings.json")
        with open(self.settings, "w", encoding="utf-8") as f:
            json.dump({"inbox": self.inbox, "sorted": self.cls, "unsorted": self.unsorted, "roster": self.roster,
                       "project": "Self-Portrait", "grade": "Kindergarten", "interval": 5, "priority": 50}, f)
        _pale_wall(os.path.join(self.inbox, "IMG_1234.jpg"))
        self.log = []
        self.saved = (bc.read_photo_text, bc.detect_pieces, bc.read_piece, bc.read_neighborhood, bc.is_settled,
                      bc.LAST_DETECTOR, bc.time.time, bc.time.sleep)
        bc.read_photo_text = lambda img, path, tmpdir, **k: self.labels()
        bc.detect_pieces = self.two_papers
        bc.read_piece = lambda tmp_path, crop: []
        bc.read_neighborhood = lambda *a, **k: []
        bc.is_settled = lambda p, wait=0: True

    def tearDown(self):
        (bc.read_photo_text, bc.detect_pieces, bc.read_piece, bc.read_neighborhood, bc.is_settled,
         bc.LAST_DETECTOR, bc.time.time, bc.time.sleep) = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def labels(self):
        return [{"text": name, "conf": 1.0, "x": (k % 4) * 600 + 80, "y": (k // 4) * 800 + 60, "w": 260, "h": 44,
                 "angle": 0} for k, name in enumerate(self.ROSTER)]

    def two_papers(self, img, path):
        bc.LAST_DETECTOR = "texture"        # pale on pale: the colour detector had nothing to go on
        quads = []
        for k in range(self.PAPERS_FOUND):
            x0, y0, x1, y1 = 40 + k * 1200, 20, 1100 + k * 1200, 1500
            quads.append({"conf": 0.9, "tl": [x0, y0], "tr": [x1, y0], "br": [x1, y1], "bl": [x0, y1]})
        return quads

    def sort(self, **kw):
        return bc.run_inbox(self.inbox, self.ROSTER, self.out, "Self-Portrait", log=self.log.append,
                            grade="Kindergarten", sorted_dir=self.cls, unsorted_dir=self.unsorted, **kw)

    def in_unsorted(self):
        return sorted(n for n in os.listdir(self.unsorted) if n != "name-strips")

    NOTE = "CHECK PICTURE - read me - Self-Portrait - IMG_1234.jpg.txt"


class NameReadPictureToCheckTests(_AWholeWallInOnePhoto, unittest.TestCase):

    def test_the_reported_repro_no_file_is_called_guess_when_every_name_was_read(self):
        res = self.sort()
        self.assertEqual(len(res), 8, self.log)
        self.assertEqual(sorted(r["name"] for r in res), sorted(self.ROSTER))
        # still never filed: the edges are a guess, and a person looks at the picture
        self.assertEqual({r["status"] for r in res}, {"unsure"})
        self.assertEqual({r["reason"] for r in res}, {bc.EDGES})
        for child in self.ROSTER:
            folder = os.path.join(self.cls, child, "Self-Portrait")
            self.assertEqual(os.listdir(folder) if os.path.isdir(folder) else [], [], child)
        names = self.in_unsorted()
        self.assertEqual([n for n in names if n.startswith("GUESS")], [], names)
        pieces = [n for n in names if n.endswith(".jpg")]
        self.assertEqual(len(pieces), 8, names)
        for child in self.ROSTER:
            mine = [n for n in pieces if n.startswith(f"CHECK PICTURE {child} - Self-Portrait Kindergarten - IMG_1234 ")]
            self.assertEqual(len(mine), 1, (child, names))
            self.assertTrue(os.path.exists(os.path.join(self.unsorted, "name-strips", mine[0])), mine)

    def test_a_note_beside_the_pieces_says_what_happened_and_what_to_do(self):
        self.sort()
        self.assertIn(self.NOTE, self.in_unsorted())
        note = " ".join(read(os.path.join(self.unsorted, self.NOTE)).split())
        for phrase in ("Baggage Claim read the names on this photo",
                       "Photo: IMG_1234.jpg",
                       "The name reader worked",
                       "8 name labels read, and the edges of 2 papers found, fewer than there are names",
                       "when pale paper hangs on a pale wall, when two papers hang edge to edge",
                       "It is not the number of papers: one photo can hold the whole wall",
                       "a little of the background showing on every side",
                       "move the file into that child's folder",
                       "A file called 'GUESS' is different"):
            self.assertIn(phrase, note)
        for child in self.ROSTER:       # the note names the photo and the numbers, never a child
            self.assertNotIn(child, note)
            self.assertNotIn(child.split()[0], note)

    def test_the_log_says_the_names_were_read_and_why_nothing_was_filed(self):
        self.sort()
        per_piece = [m for m in self.log if m.startswith("  piece ")]
        self.assertEqual(len(per_piece), 8, self.log)
        for m in per_piece:
            self.assertIn("check picture", m)
            self.assertNotIn("unsure", m)
        self.assertEqual(len([m for m in per_piece
                              if m.endswith(": check picture Maya Torres  read 'Maya Torres' score 1.0")]), 1, per_piece)
        why = [m for m in self.log if "so the name reader worked" in m]
        self.assertEqual(len(why), 1, self.log)
        for phrase in ("IMG_1234.jpg: the name was read on 8 of the 8 pieces",
                       "8 name labels read, and the edges of 2 papers found",
                       "pale paper on a pale wall, or papers hung with no edge showing between them",
                       "in 'Unsorted - needs a person', called 'CHECK PICTURE' and the child's name",
                       "a little of the background showing on every side of each paper",
                       "A note that says this is in 'Unsorted - needs a person'."):
            self.assertIn(phrase, why[0])
        self.assertIn("IMG_1234.jpg: found 8 pieces (name labels (8 readable, detectors found 2))", self.log)

    def test_the_report_says_name_read_check_the_picture(self):
        self.sort()
        rows = [ln for ln in read(os.path.join(self.out, "run-report.md")).splitlines() if ln.startswith("| ")][1:]
        self.assertEqual(len(rows), 8, rows)
        for row in rows:
            self.assertIn("| name read, check the picture |", row)
            self.assertNotIn("unsure", row)

    def test_papers_were_found_and_the_labels_are_not_on_them(self):
        """The other way into the same path: as many papers found as names
        read, but the boxes are not where the labels are. The words must not
        say 'fewer papers than names' then."""
        self.PAPERS_FOUND = 8

        def eight_papers_elsewhere(img, path):
            bc.LAST_DETECTOR = "texture"
            quads = []
            for k in range(8):
                x0, y0 = (k % 4) * 600 + 420, (k // 4) * 800 + 560
                quads.append({"conf": 0.9, "tl": [x0, y0], "tr": [x0 + 150, y0], "br": [x0 + 150, y0 + 150],
                              "bl": [x0, y0 + 150]})
            return quads
        bc.detect_pieces = eight_papers_elsewhere
        res = self.sort()
        self.assertEqual({r.get("reason") for r in res}, {bc.EDGES}, self.log)
        note = " ".join(read(os.path.join(self.unsorted, self.NOTE)).split())
        self.assertIn("8 name labels read, and 8 papers found, but some of the name labels were not on or beside "
                      "the papers that were found", note)
        self.assertNotIn("fewer than there are names", note)
        self.assertEqual([n for n in self.in_unsorted() if n.startswith("GUESS")], [])

    def test_a_name_that_really_is_a_guess_is_still_called_guess(self):
        """An even grid, a paper with nothing readable on it: the name is the
        doubt, the file says GUESS as before, and no note is written."""
        res = self.sort(grid=(2, 4))
        self.assertEqual(len(res), 8)
        self.assertEqual({r.get("reason") for r in res}, {None})
        names = self.in_unsorted()
        self.assertEqual(len([n for n in names if n.startswith("GUESS no-name - Self-Portrait Kindergarten - ")]), 8,
                         names)
        self.assertEqual([n for n in names if n.startswith("CHECK PICTURE")], [], names)
        self.assertFalse([m for m in self.log if "name reader worked" in m or "check picture" in m], self.log)
        self.assertEqual(bc.batch_text(res, "Unsorted - needs a person"), "8 pieces, 0 filed, 8 to unsorted")

    def test_one_shaky_label_among_the_eight_is_a_guess_and_the_other_seven_are_not(self):
        shaky = dict(self.labels()[0], text="Maya Torrs Q")    # a label, but not read well enough to be sure of
        hits = bc.label_hits([shaky], self.ROSTER)
        self.assertEqual(len(hits), 1, "the test needs a line that counts as a label")
        bc.read_photo_text = lambda img, path, tmpdir, **k: [shaky] + self.labels()[1:]
        real = bc.match_name

        def unsure_of_the_first(texts, roster):
            m = real(texts, roster)
            if texts and texts[0]["text"] == shaky["text"]:
                m["status"] = "unsure"
            return m
        bc.match_name = unsure_of_the_first
        try:
            res = self.sort()
        finally:
            bc.match_name = real
        self.assertEqual(len(res), 8, self.log)
        self.assertEqual(len(bc.edges_guessed(res)), 7)
        names = self.in_unsorted()
        self.assertEqual(len([n for n in names if n.startswith("GUESS Maya Torres - ")]), 1, names)
        self.assertEqual(len([n for n in names if n.startswith("CHECK PICTURE ") and n.endswith(".jpg")]), 7, names)
        self.assertIn("the name was read on 7 of the 8 pieces", " ".join(self.log))
        self.assertIn("(on 7 of them the name was read", bc.batch_text(res, "Unsorted - needs a person"))

    def test_a_note_that_cannot_be_written_is_said_and_the_pieces_are_still_there(self):
        os.makedirs(os.path.join(self.unsorted, self.NOTE))     # something in the way, of the same name
        res = self.sort()
        self.assertEqual(len(bc.edges_guessed(res)), 8)
        self.assertEqual(len([n for n in self.in_unsorted() if n.endswith(".jpg")]), 8)
        why = [m for m in self.log if "so the name reader worked" in m]
        self.assertEqual(len(why), 1, self.log)
        self.assertIn("A note for the teacher could not be written (", why[0])
        self.assertIsNone(bc.tell_edges_guessed("IMG_1234.jpg", "Self-Portrait", res, 8, 2, self.unsorted,
                                                lambda m: None))

    def test_no_piece_of_that_kind_no_note_and_nothing_said(self):
        said = []
        filed = [{"piece": 1, "status": "confident", "name": "Maya Torres"},
                 {"piece": 2, "status": "unsure", "name": "Jonah Reed"}]
        self.assertIsNone(bc.tell_edges_guessed("IMG_1234.jpg", "Self-Portrait", filed, 0, 0, self.unsorted,
                                                said.append))
        self.assertEqual(said, [])
        self.assertFalse(os.path.exists(self.unsorted))
        self.assertEqual(bc.batch_text(filed), "2 pieces, 1 filed, 1 to unsorted")
        self.assertEqual(bc.edges_found_text(8, 1),
                         "8 name labels read, and the edges of 1 paper found, fewer than there are names")

    def test_once_through_with_the_settings_file_says_it_at_the_end(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(bc.main(["--settings", self.settings, "--out", self.out]), 0)
        out = buf.getvalue()
        self.assertIn("8 pieces: 0 filed, 8 in unsorted/", out)
        self.assertIn("On 8 of the pieces in unsorted the name was read, and the picture is what a person has to "
                      "check", out)
        self.assertIn("See the note in 'Unsorted - needs a person'.", out)
        self.assertNotIn("unsure", out)
        self.assertEqual([n for n in self.in_unsorted() if n.startswith("GUESS")], [])

    def test_the_status_file_and_the_watchers_line_give_the_cause(self):
        """What a person looking from somewhere else has to go on: the 'Last
        batch' line of this computer's file in 'Watcher status'."""
        real_time = self.saved[6]
        clock = {"ahead": 0.0}
        bc.time.time = lambda: real_time() + clock["ahead"]
        ticks = []

        def fake_sleep(s):
            ticks.append(s)
            clock["ahead"] += bc.GRACE_SECONDS + 10 if len(ticks) == 1 else s
            if len(ticks) >= 2:
                raise KeyboardInterrupt
        bc.time.sleep = fake_sleep
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                bc.main(["--watch", "--settings", self.settings, "--out", self.out])
        out = buf.getvalue()
        cause = ("8 pieces, 0 filed, 8 to unsorted (on 8 of them the name was read, but the tool could not find "
                 "the edges of the papers for certain: pale paper on a pale wall, or papers hung with no edge "
                 "showing between them. A person checks each picture. See the note in 'Unsorted - needs a person')")
        self.assertIn(cause, out)
        status = read(os.path.join(self.cls, "Watcher status", bc.machine_name() + ".txt"))
        last = [ln for ln in status.splitlines() if ln.startswith("Last batch: ")]
        self.assertEqual(len(last), 1, status)
        self.assertTrue(last[0].endswith(cause), last[0])
        # the other watchers still read the file as before
        st = bc.parse_status(status)
        self.assertEqual((st["machine"], st["priority"], st["role"]), (bc.machine_name(), 50, "watching"))

    def test_the_read_me_says_what_a_check_picture_file_is(self):
        text = " ".join(read(os.path.join(ROOT, "README.md")).split())
        section = text.split("### Files called CHECK PICTURE")[1].split("### ")[0]
        for phrase in ("`GUESS Maya Torres - ...`: the tool could not read the name for certain",
                       "`CHECK PICTURE Maya Torres - ...`: the name was read",
                       "The name reader did not fail",
                       "`CHECK PICTURE - read me - <project> - <photo>.txt`",
                       "one photo can hold the whole wall",
                       "a little of the background showing on every side",
                       "25 pieces, 0 filed, 25 to unsorted (on 25 of them the name was read",
                       "A computer that still does that needs this version"):
            self.assertIn(phrase, section)


class NameReadPictureToCheckOnASyntheticWallTests(unittest.TestCase):
    """The reported steps with the real detectors and the real name reader, on
    a synthetic wall (make_wall.py, invented names): pale paper on a pale
    wall, so the colour detector is not the one that found the papers."""

    NAMES = ["Maya", "Jonah", "Sofia", "Elijah", "Priya", "Marcus", "Lily", "Theo"]

    def setUp(self):
        if not bc.backend_ready():
            self.skipTest("reader not available")
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Drive", "Room 3")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.unsorted = os.path.join(self.cls, "Unsorted - needs a person")
        self.out = os.path.join(self.tmp, "tool")
        os.makedirs(self.out)
        sys.path.insert(0, HERE)
        from make_wall import make_wall
        img, _ = make_wall(self.NAMES, writing=True, wall=(250, 250, 248), tilt=False, seed=9)
        img.save(os.path.join(self.inbox, "IMG_1234.jpg"), quality=90)
        self.saved = bc.is_settled
        bc.is_settled = lambda p, wait=0: True

    def tearDown(self):
        if hasattr(self, "saved"):
            bc.is_settled = self.saved
            shutil.rmtree(self.tmp, ignore_errors=True)

    def test_every_name_read_and_not_one_file_called_guess(self):
        log = []
        res = bc.run_inbox(self.inbox, self.NAMES, self.out, "Self-Portrait", log=log.append,
                           grade="Kindergarten", sorted_dir=self.cls, unsorted_dir=self.unsorted)
        self.assertNotEqual(bc.LAST_DETECTOR, "colour")
        self.assertTrue([m for m in log if "pieces (name labels (" in m], log)
        self.assertGreaterEqual(len(res), 8, log)
        self.assertEqual({r["status"] for r in res}, {"unsure"}, log)
        read_well = bc.edges_guessed(res)
        self.assertEqual(sorted({r["name"] for r in read_well}), sorted(self.NAMES), log)
        names = sorted(n for n in os.listdir(self.unsorted) if n != "name-strips")
        for r in res:
            lead = "CHECK PICTURE " if r.get("reason") == bc.EDGES else "GUESS "
            self.assertTrue(os.path.basename(r["file"]).startswith(lead), r)
        self.assertEqual(len([n for n in names if n.startswith("CHECK PICTURE ") and n.endswith(".jpg")]),
                         len(read_well), names)
        self.assertIn("CHECK PICTURE - read me - Self-Portrait - IMG_1234.jpg.txt", names)
        self.assertFalse([m for m in log if m.startswith("  piece ") and "score 1.0" in m and "unsure" in m], log)
        self.assertEqual(len([m for m in log if "so the name reader worked" in m]), 1, log)
        self.assertIn(f"(on {len(read_well)} of them the name was read", bc.batch_text(res))


# ------------------------------------------ a photo that could not be sorted ---
#
# Repair (a photo in 'failed'): a photo the tool could not open, read or save
# from was moved to 'Wall Inbox/failed' and the only record was one line in
# the log on the watching computer, in the program's own words. The teacher
# saw a folder called 'failed' appear with her photo in it and nothing that
# said why or what to do, and the status file went on showing the batch
# before. Now a note called 'COULD NOT SORT - <project> - <photo>.txt' is
# written into the doubtful-pieces folder, the 'Last batch' line says so, and
# the status file counts the photos in 'failed' for as long as they are there.
# Invented names and temporary folders; the only pictures are synthetic walls
# from make_wall.py, one of them cut short the way a broken upload is.

def _half_a_photo(path):
    """A synthetic wall saved as a JPEG and cut off halfway, like a photo
    whose upload from the phone stopped in the middle."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    from make_wall import make_wall
    img, _ = make_wall(["Maya Torres", "Priya Nair"], rows=1, cols=2, size=(800, 400))
    whole = io.BytesIO()
    img.save(whole, "JPEG", quality=90)
    with open(path, "wb") as f:
        f.write(whole.getvalue()[:len(whole.getvalue()) // 2])


class _AClassWithAPhotoThatCannotBeSorted:
    NAMES = ["Maya Torres", "Priya Nair"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Kindergarten - Room 3")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.unsorted = os.path.join(self.cls, "Unsorted - needs a person")
        self.out = os.path.join(self.tmp, "tool")
        os.makedirs(self.out)
        self.log = []
        self.could_not = []
        self.saved_for_sorting = (bc.is_settled, bc.process_photo, bc.shutil.move)
        bc.is_settled = lambda p, wait=0: True

    def tearDown(self):
        bc.is_settled, bc.process_photo, bc.shutil.move = self.saved_for_sorting
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sort(self, **kw):
        return bc.run_inbox(self.inbox, self.NAMES, self.out, "Self-Portrait", log=self.log.append,
                            grade="Kindergarten", sorted_dir=self.cls, unsorted_dir=self.unsorted,
                            could_not=self.could_not, **kw)

    def notes(self):
        try:
            return sorted(n for n in os.listdir(self.unsorted) if n.startswith("COULD NOT SORT"))
        except OSError:
            return []

    def stops_with(self, error, only=None):
        """The cutting stops with this error, for every photo or for one."""
        def process_photo(path, roster, out_dir, project, *a, **k):
            if only is None or os.path.basename(path) == only:
                raise error
            return [{"piece": 1, "status": "confident", "name": "Maya Torres", "text": "Maya", "score": 1.0,
                     "margin": 1.0, "box": None, "file": os.path.join(self.cls, "Maya Torres", "x.jpg"),
                     "bbox": (0, 0, 1, 1)}]
        bc.process_photo = process_photo

    def drop(self, name, folder=None):
        where = os.path.join(self.inbox, folder) if folder else self.inbox
        os.makedirs(where, exist_ok=True)
        with open(os.path.join(where, name), "wb") as f:
            f.write(b"\xff\xd8 not really a jpeg")


class PhotoThatCouldNotBeSortedTests(_AClassWithAPhotoThatCannotBeSorted, unittest.TestCase):
    """What the teacher finds in Drive, and what the log says."""

    def test_the_reported_steps_a_photo_cut_short_gets_a_note_that_says_why_and_what_to_do(self):
        _half_a_photo(os.path.join(self.inbox, "IMG_1234.jpg"))
        self.assertEqual(self.sort(), [])
        self.assertEqual(os.listdir(os.path.join(self.inbox, "failed")), ["IMG_1234.jpg"])
        self.assertEqual(self.notes(), ["COULD NOT SORT - Self-Portrait - IMG_1234.jpg.txt"])
        note = read(os.path.join(self.unsorted, self.notes()[0]))
        for said in ("Baggage Claim could not sort this photo.",
                     "Photo:    IMG_1234.jpg",
                     "Project:  Self-Portrait",
                     f"on the computer called {bc.machine_name()}",
                     "The photo is now in:  Wall Inbox/failed",
                     "The file could not be opened as a picture. It is damaged, or it did not finish arriving "
                     "from the phone, or it is not a photo.",
                     "1. Share the photo to 'Wall Inbox' again, from the phone it was taken with.",
                     "2. If the photo is no longer on the phone, photograph the wall again",
                     "3. Then delete the photo in 'Wall Inbox/failed'.",
                     "You can delete this note when you are done."):
            self.assertIn(said, note)
        # plain words only: nothing of the program's own, no path, and no child
        for not_said in ("truncated", "OSError", "Traceback", self.tmp, "Maya", "Priya"):
            self.assertNotIn(not_said, note)
        self.assertEqual([(c["photo"], c["project"], c["kind"]) for c in self.could_not],
                         [("IMG_1234.jpg", "Self-Portrait", "photo")])
        self.assertEqual(self.could_not[0]["note"], os.path.join(self.unsorted, self.notes()[0]))

    def test_the_log_says_it_in_plain_words_and_keeps_the_programs_own_for_whoever_set_it_up(self):
        _half_a_photo(os.path.join(self.inbox, "IMG_1234.jpg"))
        self.sort()
        line = [m for m in self.log if m.startswith("IMG_1234.jpg: this photo could not be sorted")]
        self.assertEqual(len(line), 1, self.log)
        for said in ("because the file could not be opened as a picture",
                     "moved to inbox/failed (the folder 'Wall Inbox/failed')",
                     "What to do: Share the photo to 'Wall Inbox' again",
                     "A note that says this, and what to do, is in 'Unsorted - needs a person'.",
                     "the program's own words were: OSError: image file is truncated"):
            self.assertIn(said, line[0])

    # --- a Windows PC cannot move or delete a file that is still open ----------
    #
    # In the build of Sep 28 2026 the two tests above stopped on the Windows
    # build machine with "the process cannot access the file because it is
    # being used by another process": the photo that was cut short had been
    # opened, the reading had stopped halfway, and the file was never closed.
    # A Mac does not mind. These say, on every computer, that the file is
    # closed again; the two above say on a real Windows PC that it then moves.

    def opened_by_the_program(self):
        """Every picture file the program opens from now on: (path, the open file)."""
        opened = []
        real_open = bc.Image.open

        def watched(fp, *a, **k):
            im = real_open(fp, *a, **k)
            opened.append((str(fp), im.fp))
            return im
        patch = _mock.patch.object(bc.Image, "open", watched)
        patch.start()
        self.addCleanup(patch.stop)
        return opened

    def record(self, what):
        """A line for the build's own record (tests-on-build-machine.txt in the bundle)."""
        sys.stderr.write(f"\nEVIDENCE[open files] {sys.platform}: {what}\n")
        sys.stderr.flush()

    def test_a_photo_cut_short_is_closed_again_so_that_it_can_be_moved_to_failed(self):
        _half_a_photo(os.path.join(self.inbox, "IMG_1234.jpg"))
        opened = self.opened_by_the_program()
        self.assertEqual(self.sort(), [])
        mine = [(p, f) for p, f in opened if os.path.basename(p) == "IMG_1234.jpg"]
        self.assertTrue(mine, "the photo was opened")
        for p, f in mine:
            self.assertTrue(f.closed, "the photo was left open after it could not be read")
        self.assertEqual(os.listdir(os.path.join(self.inbox, "failed")), ["IMG_1234.jpg"])
        self.assertEqual(os.listdir(os.path.join(self.inbox, "done")), [])

    def test_a_photo_that_can_be_read_is_whole_in_memory_and_its_file_is_closed(self):
        good = os.path.join(self.tmp, "good.jpg")
        on_its_side = bc.Image.Exif()
        on_its_side[0x0112] = 6                 # the phone's tag for "turn me a quarter turn"
        bc.Image.new("RGB", (64, 48), (20, 30, 90)).save(good, exif=on_its_side)
        opened = self.opened_by_the_program()
        img, path, scratch = bc.open_photo(good)
        self.assertEqual((img.size, img.mode, path, scratch), ((48, 64), "RGB", good, None))
        self.assertEqual([f.closed for p, f in opened], [True])
        r, g, b = img.getpixel((10, 10))        # every byte was read before the file was closed
        self.assertTrue(abs(r - 20) < 12 and abs(g - 30) < 12 and abs(b - 90) < 12, (r, g, b))
        os.remove(good)                         # what a Windows PC refuses while a file is open
        self.assertEqual(img.resize((8, 8)).size, (8, 8), "the picture does not need its file any more")
        half = os.path.join(self.tmp, "half.jpg")
        _half_a_photo(half)
        del opened[:]
        with self.assertRaises(OSError):
            bc.open_photo(half)
        self.assertEqual([f.closed for p, f in opened], [True])
        os.remove(half)

    def test_the_pictures_put_into_a_childs_document_are_closed_again(self):
        folder = os.path.join(self.cls, "Maya Torres", "Self-Portrait")
        os.makedirs(folder)
        for n in ("Self-Portrait K.jpg", "Self-Portrait K 2.jpg"):
            bc.Image.new("RGB", (64, 48), (20, 30, 90)).save(os.path.join(folder, n))
        opened = self.opened_by_the_program()
        made = bc.build_docx(os.path.join(self.cls, "Maya Torres"), "Maya Torres")
        self.assertTrue(os.path.exists(made))
        self.assertEqual([f.closed for p, f in opened], [True, True])
        shutil.rmtree(os.path.join(self.cls, "Maya Torres"))    # a Windows PC refuses while a file in it is open
        self.assertFalse(os.path.exists(folder))

    @unittest.skipUnless(sys.platform == "win32", "prints what a real Windows PC did with the photo, for the "
                                                  "build's record; the tests above cover every computer")
    def test_on_windows_the_record_of_where_a_photo_cut_short_went(self):
        _half_a_photo(os.path.join(self.inbox, "IMG_1234.jpg"))
        try:
            said = f"the sorting came back with {self.sort()!r}"
        except Exception as e:      # printed, then failed below: the record must have it either way
            said = f"the sorting STOPPED with {type(e).__name__}: {e}"
        found = {}
        for folder in ("", "done", "failed"):
            try:
                found[folder or "Wall Inbox"] = sorted(os.listdir(os.path.join(self.inbox, folder)))
            except OSError as e:
                found[folder or "Wall Inbox"] = f"not there ({type(e).__name__})"
        self.record(f"a photo cut short: {said}; folders now {found}; notes {self.notes()}; "
                    f"log {[m.replace(self.tmp, '<class>') for m in self.log]}")
        self.assertEqual(found["failed"], ["IMG_1234.jpg"])
        self.assertEqual(found["done"], [])
        self.assertEqual(found["Wall Inbox"], ["done", "failed"])

    def test_a_list_for_the_photos_that_failed_is_optional(self):
        self.stops_with(ValueError("not an image"))
        self.drop("wall.jpg")
        res = bc.run_inbox(self.inbox, self.NAMES, self.out, "Self-Portrait", log=self.log.append,
                           sorted_dir=self.cls, unsorted_dir=self.unsorted)
        self.assertEqual(res, [])
        self.assertEqual(self.notes(), ["COULD NOT SORT - Self-Portrait - wall.jpg.txt"])

    def test_a_photo_from_a_project_folder_is_to_be_put_back_into_that_folder(self):
        self.stops_with(RuntimeError("vision text failed: the reader stopped"))
        self.drop("wall.jpg", folder="Fall Leaves")
        self.sort()
        self.assertEqual(self.notes(), ["COULD NOT SORT - Fall Leaves - wall.jpg.txt"])
        note = read(os.path.join(self.unsorted, self.notes()[0]))
        self.assertIn("The part of this computer that reads the names did not work.", note)
        self.assertIn("1. Nothing is known to be wrong with the photo. Move the photo from 'Wall Inbox/failed' "
                      "back into 'Wall Inbox/Fall Leaves'. It is sorted again.", note)
        self.assertIn("is not given a second copy", note)
        self.assertIn("2. If the photo comes back to 'Wall Inbox/failed', tell the person who set Baggage Claim up",
                      note)
        self.assertNotIn("vision text failed", note)

    def test_a_full_disk_is_the_computers_trouble_and_the_photo_is_to_be_put_back(self):
        self.stops_with(OSError(28, "No space left on device", os.path.join(self.cls, "Maya Torres", "x.jpg")))
        self.drop("wall.jpg")
        self.sort()
        note = read(os.path.join(self.unsorted, self.notes()[0]))
        self.assertIn("This computer could not save the pieces, or could not find a folder it needs.", note)
        self.assertIn(f"1. Nothing is wrong with the photo. On the computer called {bc.machine_name()}, see that "
                      f"Google Drive is signed in and that the disk is not full.", note)
        self.assertIn("2. Move the photo from 'Wall Inbox/failed' back into 'Wall Inbox'.", note)
        self.assertNotIn("Maya", note)          # the path in the program's error names a child; the note must not
        self.assertEqual(self.could_not[0]["kind"], "computer")

    def test_the_good_photos_beside_it_are_sorted_and_only_the_bad_one_is_reported(self):
        self.stops_with(ValueError("not an image"), only="wall 2.jpg")
        for n in ("wall 1.jpg", "wall 2.jpg", "wall 3.jpg"):
            self.drop(n)
        self.assertEqual(len(self.sort()), 2)
        self.assertEqual(sorted(os.listdir(os.path.join(self.inbox, "done"))), ["wall 1.jpg", "wall 3.jpg"])
        self.assertEqual(os.listdir(os.path.join(self.inbox, "failed")), ["wall 2.jpg"])
        self.assertEqual([c["photo"] for c in self.could_not], ["wall 2.jpg"])
        self.assertEqual(self.could_not[0]["kind"], "unknown")
        self.assertEqual(self.notes(), ["COULD NOT SORT - Self-Portrait - wall 2.jpg.txt"])
        self.assertIsNone(bc.unfinished_photos(self.out, self.inbox) or None)

    def test_when_the_note_cannot_be_written_the_log_says_so_and_the_photo_is_still_put_aside(self):
        with open(self.unsorted, "w") as f:      # a file where the folder should be
            f.write("in the way")
        self.stops_with(ValueError("not an image"))
        self.drop("wall.jpg")
        self.assertEqual(self.sort(), [])
        self.assertEqual(os.listdir(os.path.join(self.inbox, "failed")), ["wall.jpg"])
        self.assertTrue([m for m in self.log if "A note for the teacher could not be written (" in m], self.log)
        self.assertEqual([(c["photo"], c["note"]) for c in self.could_not], [("wall.jpg", None)])

    def test_when_the_photo_cannot_be_moved_to_failed_the_log_still_has_the_reason(self):
        self.stops_with(ValueError("not an image"))
        self.drop("wall.jpg")
        real_move = bc.shutil.move

        def move(src, dst, *a, **k):
            if os.path.basename(os.path.dirname(dst)) == "failed":
                raise OSError(28, "No space left on device")
            return real_move(src, dst, *a, **k)
        bc.shutil.move = move
        with self.assertRaises(OSError):
            self.sort()
        self.assertEqual(os.listdir(os.path.join(self.inbox, "done")), ["wall.jpg"])
        line = [m for m in self.log if m.startswith("wall.jpg: this photo could not be sorted")]
        self.assertEqual(len(line), 1, self.log)
        self.assertIn("It could not be moved to inbox/failed either", line[0])
        self.assertIn("so it is still in the folder 'done'", line[0])
        self.assertIn("ValueError: not an image", line[0])
        self.assertEqual((self.could_not, self.notes()), ([], []))
        # the marker is still there, so the next start says the photo was not finished
        self.assertEqual(len(bc.unfinished_photos(self.out, self.inbox)), 1)


class WhyAPhotoCouldNotBeSortedTests(unittest.TestCase):
    """The reason, and the words for the status file. No file is touched."""

    def test_each_kind_of_trouble_has_its_own_plain_words(self):
        from PIL import UnidentifiedImageError
        kinds = [(OSError("image file is truncated (12 bytes not processed)"), "photo"),
                 (UnidentifiedImageError("cannot identify image file 'wall.jpg'"), "photo"),
                 (SyntaxError("not a TIFF file"), "photo"),
                 (RuntimeError("could not convert IMG_0001.HEIC: no such codec"), "photo"),
                 (OSError(28, "No space left on device"), "computer"),
                 (PermissionError(13, "Permission denied"), "computer"),
                 (FileNotFoundError("cannot find the folder 'Kindergarten - Room 3' any more"), "computer"),
                 (RuntimeError("vision text failed: the reader stopped"), "reader"),
                 (RuntimeError("Windows reader not available; run: pip install winsdk"), "reader"),
                 (RuntimeError("HEIC photo but pillow-heif is not installed"), "unknown"),
                 (ValueError("not an image"), "unknown"),
                 (KeyError("Maya Torres"), "unknown")]
        words = {}
        for error, kind in kinds:
            got, why = bc.why_not_sorted(error)
            self.assertEqual(got, kind, repr(error))
            words.setdefault(kind, set()).add(why)
            for not_said in (str(error), type(error).__name__, "Maya"):
                self.assertNotIn(not_said, why)
        self.assertEqual({k: len(v) for k, v in words.items()}, {"photo": 1, "computer": 1, "reader": 1, "unknown": 1})

    def test_the_steps_for_each_kind(self):
        for kind, first in (("photo", "Share the photo to 'Wall Inbox' again"),
                            ("computer", "Nothing is wrong with the photo. On the computer called CLASSROOM-PC"),
                            ("reader", "Nothing is known to be wrong with the photo. Move the photo from"),
                            ("unknown", "Nothing is known to be wrong with the photo. Move the photo from")):
            steps = bc.what_to_do(kind, "Wall Inbox/failed", "Wall Inbox", "CLASSROOM-PC")
            self.assertTrue(steps[0].startswith(first), steps)
            self.assertGreaterEqual(len(steps), 2)

    def test_the_line_for_the_status_file(self):
        def failed(n):
            return [{"photo": f"wall {i}.jpg", "why": "the file could not be opened as a picture"}
                    for i in range(1, n + 1)]
        self.assertEqual(bc.failed_text([]), "")
        self.assertEqual(bc.failed_text(failed(1), "Unsorted - needs a person"),
                         "1 photo could not be sorted and is in 'failed' inside Arrivals ('wall 1.jpg': the file "
                         "could not be opened as a picture). See the note called 'COULD NOT SORT' in 'Unsorted - "
                         "needs a person' for what to do")
        five = bc.failed_text(failed(5))
        self.assertTrue(five.startswith("5 photos could not be sorted and are in 'failed' inside Arrivals"), five)
        self.assertIn("'wall 3.jpg': the file could not be opened as a picture; and 2 more)", five)
        self.assertNotIn("wall 4.jpg", five)
        self.assertIn("See the notes called 'COULD NOT SORT' in 'unsorted'", five)

    def test_the_status_file_has_the_count_only_when_there_is_something_to_count(self):
        plain = bc.format_status("CLASSROOM-PC", NOW, "watching", 50, waiting=0)
        self.assertNotIn("could not be sorted", plain)
        text = bc.format_status("CLASSROOM-PC", NOW, "watching", 50, waiting=0, failed=2)
        lines = text.splitlines()
        count = [ln for ln in lines if ln.startswith("Photos that could not be sorted: 2 (in 'failed' inside "
                                                     "Arrivals; the notes called 'COULD NOT SORT'")]
        self.assertEqual(len(count), 1, text)
        self.assertEqual(lines.index(count[0]), lines.index("Photos waiting in Arrivals: 0") + 1)
        self.assertEqual([ln for ln in lines if ln not in count], plain.splitlines())
        # the other watchers read the file as before
        self.assertEqual(bc.parse_status(text), bc.parse_status(plain))

    def test_the_count_is_taken_from_the_folder(self):
        tmp = tempfile.mkdtemp()
        try:
            self.assertEqual(bc.photos_in_failed(tmp), 0)               # no folder called failed
            failed = os.path.join(tmp, "failed")
            os.makedirs(os.path.join(failed, "a folder.jpg"))
            for n in ("IMG_1.HEIC", "wall.jpg", ".hidden.jpg", "a note.txt"):
                open(os.path.join(failed, n), "w").close()
            self.assertEqual(bc.photos_in_failed(tmp), 3)               # two photos, and a folder named like one
            os.remove(os.path.join(failed, "wall.jpg"))
            self.assertEqual(bc.photos_in_failed(tmp), 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class FailedPhotoInTheStatusFileTests(_ASortingComputer, unittest.TestCase):
    """What a person who is not at the computer sees: this computer's file in
    'Watcher status'. The whole watch loop runs, with the clock faked."""

    def failing_photo(self, *bad):
        real = bc.process_photo
        self.fake_process_photo(takes=0)
        good = bc.process_photo

        def process_photo(path, *a, **k):
            if os.path.basename(path) in bad:
                return real(path, *a, **k)      # the real one: it cannot open what drop_photos wrote
            return good(path, *a, **k)
        bc.process_photo = process_photo

    def last_batch(self, text):
        found = [ln for ln in text.splitlines() if ln.startswith("Last batch: ")]
        self.assertEqual(len(found), 1, text)
        return found[0]

    def test_the_reported_steps_the_status_file_says_a_photo_failed(self):
        self.drop_photos("IMG_1234.jpg")
        self.failing_photo("IMG_1234.jpg")
        out = self.run_main({1: bc.GRACE_SECONDS + 10}, stop_after=2)
        self.assertEqual(os.listdir(os.path.join(self.inbox, "failed")), ["IMG_1234.jpg"], out)
        status = self.status_at[2]
        said = ("1 photo could not be sorted and is in 'failed' inside Arrivals ('IMG_1234.jpg': the file could "
                "not be opened as a picture. It is damaged, or it did not finish arriving from the phone, or it is "
                "not a photo). See the note called 'COULD NOT SORT' in 'Unsorted - needs a person' for what to do")
        self.assertNotIn("Last batch: none yet", status)
        self.assertTrue(self.last_batch(status).endswith(": " + said), status)
        self.assertIn("Photos that could not be sorted: 1 (in 'failed' inside Arrivals", status)
        self.assertIn("Photos waiting in Arrivals: 0", status)
        self.assertLess(self.age_at[2], 2)          # written at once, not a minute later
        self.assertIn(said, out)                    # and the log has the same line
        self.assertEqual(os.listdir(os.path.join(self.cls, "Unsorted - needs a person")),
                         ["COULD NOT SORT - Self-Portrait - IMG_1234.jpg.txt"])
        # nothing of the program's own words, and no path, where a teacher reads
        for not_said in ("cannot identify", "Error", self.tmp):
            self.assertNotIn(not_said, status)
        st = bc.parse_status(status)
        self.assertEqual((st["machine"], st["priority"], st["role"]), (bc.machine_name(), 50, "watching"))

    def test_a_batch_with_good_photos_and_a_bad_one_says_both(self):
        self.drop_photos("wall 1.jpg", "wall 2.jpg", "wall 3.jpg")
        self.failing_photo("wall 2.jpg")
        out = self.run_main({1: bc.GRACE_SECONDS + 10}, stop_after=2)
        last = self.last_batch(self.status_at[2])
        self.assertIn("2 pieces, 2 filed, 0 to unsorted. Also: 1 photo could not be sorted and is in 'failed' "
                      "inside Arrivals ('wall 2.jpg': ", last)
        self.assertIn("Photos that could not be sorted: 1 ", self.status_at[2])
        self.assertIn("2 pieces, 2 filed, 0 to unsorted. Also: 1 photo could not be sorted", out)

    def test_a_batch_with_nothing_wrong_says_nothing_about_failed_photos(self):
        self.drop_photos("wall 1.jpg")
        self.failing_photo()
        self.run_main({1: bc.GRACE_SECONDS + 10}, stop_after=2)
        self.assertTrue(self.last_batch(self.status_at[2]).endswith(": 1 pieces, 1 filed, 0 to unsorted"))
        self.assertNotIn("could not be sorted", self.status_at[2])

    def test_it_is_still_said_after_the_next_batch_and_until_a_person_has_dealt_with_the_photo(self):
        self.drop_photos("IMG_1234.jpg")
        self.failing_photo("IMG_1234.jpg")

        def on_tick(n):
            if n == 2:          # the next photo, a good one
                self.drop_photos("wall 1.jpg")
            if n == 4:          # the teacher has shared the photo again and deleted the one in failed
                os.remove(os.path.join(self.inbox, "failed", "IMG_1234.jpg"))
        self.run_main({1: bc.GRACE_SECONDS + 10, "else": 70}, stop_after=5, on_tick=on_tick)
        self.assertIn("1 photo could not be sorted", self.last_batch(self.status_at[2]))
        self.assertTrue(self.last_batch(self.status_at[3]).endswith(": 1 pieces, 1 filed, 0 to unsorted"))
        for tick in (3, 4):
            self.assertIn("Photos that could not be sorted: 1 ", self.status_at[tick], tick)
        self.assertNotIn("Photos that could not be sorted", self.status_at[5])

    def test_a_watcher_that_is_started_again_still_says_a_photo_is_in_failed(self):
        os.makedirs(os.path.join(self.inbox, "failed"))
        with open(os.path.join(self.inbox, "failed", "IMG_1234.jpg"), "wb") as f:
            f.write(b"\xff\xd8 not really a jpeg")
        self.fake_run_inbox()
        self.run_main({1: bc.GRACE_SECONDS + 10}, stop_after=2)
        for tick in (1, 2):
            self.assertIn("Photos that could not be sorted: 1 ", self.status_at[tick], tick)
        self.assertIn("Last batch: none yet", self.status_at[2])


class FailedPhotoReadMeTests(unittest.TestCase):
    def test_the_read_me_says_what_a_photo_in_failed_means(self):
        text = " ".join(read(os.path.join(ROOT, "README.md")).split())
        section = text.split("### A photo in the folder called failed")[1].split("### ")[0]
        for phrase in ("`COULD NOT SORT - <project> - <photo>.txt`",
                       "`Unsorted - needs a person`",
                       "Share the photo to `Arrivals` again",
                       "move the photo from `Arrivals/failed` back into `Arrivals`",
                       "`Photos that could not be sorted: 1",
                       "A computer that still does that needs this version"):
            self.assertIn(phrase, section)


class ScratchStaysOutOfDriveTests(unittest.TestCase):
    """Repair 3, the last way the JPEG copy of an iPhone photo could still
    reach Google Drive. The copy goes into the tool's scratch folder, and the
    scratch folder was always <tool folder>/.tmp. The one-click zip is handed
    to a teacher in the class's Drive folder; unzipped where it was found, the
    tool folder is inside Drive, so the full-size JPEG of the wall (and every
    crop) was uploaded for the ten seconds a photo takes and then kept in
    Drive's trash for 30 days, on every photo. A tool folder inside Google
    Drive now keeps its scratch in the computer's own temp folder."""

    def setUp(self):
        self.top = tempfile.mkdtemp()
        self.drive = os.path.join(self.top, "My Drive")
        self.room = os.path.join(self.drive, "Kindergarten - Room 3")
        self.inbox = os.path.join(self.room, "Wall Inbox")
        self.tool = os.path.join(self.room, "BaggageClaim-windows")
        self.computer = os.path.join(self.top, "computer temp folder")
        for d in (self.inbox, self.tool, self.computer):
            os.makedirs(d)
        self.saved_temp = tempfile.tempdir
        tempfile.tempdir = self.computer
        self.saved = (bc.is_settled, bc.read_photo_text, bc.detect_pieces, bc.pieces_from_labels)
        bc.is_settled = lambda path, wait=2.0: True
        bc.detect_pieces = lambda img, path: []
        bc.pieces_from_labels = lambda *a, **k: None

    def tearDown(self):
        tempfile.tempdir = self.saved_temp
        bc.is_settled, bc.read_photo_text, bc.detect_pieces, bc.pieces_from_labels = self.saved
        shutil.rmtree(self.top, ignore_errors=True)

    def pictures_in_drive(self):
        return [f for f in _tree(self.drive) if os.path.splitext(f)[1].lower() in bc.IMAGE_EXT]

    def test_a_folder_in_drive_is_known_by_its_name_on_a_mac_and_on_a_pc(self):
        for inside in ("/Users/maya/Library/CloudStorage/GoogleDrive-maya@example.org/My Drive/Room 3/BaggageClaim-mac",
                       "/Users/maya/Library/CloudStorage/GoogleDrive-maya@example.org/Shared drives/Room 3",
                       "/Users/maya/Google Drive/Room 3/baggage-claim",
                       "G:\\My Drive\\Room 3\\BaggageClaim-windows",
                       "G:\\Shared drives\\Room 3\\BaggageClaim-windows",
                       "C:\\Users\\maya\\My Drive\\Room 3\\BaggageClaim-windows",
                       "c:/users/maya/my drive/room 3",
                       self.tool):
            self.assertTrue(bc.inside_google_drive(inside), inside)
        for outside in ("/Users/maya/baggage-claim", "/Users/maya/Desktop/BaggageClaim-mac",
                        "C:\\Users\\maya\\baggage-claim", "C:\\Users\\maya\\Desktop\\My Drive photos",
                        self.computer):
            self.assertFalse(bc.inside_google_drive(outside), outside)

    def test_a_tool_folder_on_the_computer_keeps_its_scratch_where_it_was(self):
        own = os.path.join(self.top, "baggage-claim")
        os.makedirs(own)
        self.assertEqual(bc.scratch_home(own), own)
        mine = bc.scratch_folder(own)
        self.assertEqual(os.path.dirname(mine), os.path.join(own, ".tmp"))
        bc.drop_scratch(mine)
        self.assertEqual(os.listdir(own), [])

    def test_a_tool_folder_inside_drive_keeps_its_scratch_in_the_computers_temp_folder(self):
        mine = bc.scratch_folder(self.tool)
        self.assertTrue(os.path.isdir(mine))
        self.assertTrue(mine.startswith(self.computer + os.sep), mine)
        self.assertFalse(bc.inside_google_drive(mine), mine)
        self.assertEqual(os.listdir(self.tool), [], "nothing is made in the tool folder")
        other = bc.scratch_folder(self.tool)
        self.assertNotEqual(mine, other, "one scratch folder per photo there as well")
        bc.drop_scratch(mine)
        self.assertTrue(os.path.isdir(other), "taking one photo's scratch away leaves the other's alone")
        bc.drop_scratch(other)
        self.assertEqual(_tree(self.computer), [])

    def test_an_iphone_photo_is_sorted_without_one_copy_of_it_in_drive(self):
        heic = _heic_wall(self.inbox)
        if not heic:
            self.skipTest("this computer cannot write a HEIC test photo")
        seen = {}

        def reading(img, path, tmpdir, **k):
            seen["pictures in drive"] = self.pictures_in_drive()
            seen["read from"] = path
            seen["there"] = os.path.exists(path)
            return []
        bc.read_photo_text = reading
        bc.run_inbox(self.inbox, ["Maya Torres", "Priya Nair"], self.tool, "Art", log=lambda *a: None)
        self.assertEqual(seen["pictures in drive"], ["Kindergarten - Room 3/Wall Inbox/done/IMG_0001.HEIC"])
        self.assertTrue(seen["there"])
        self.assertTrue(seen["read from"].lower().endswith(".heic.jpg"), seen["read from"])
        self.assertTrue(seen["read from"].startswith(self.computer + os.sep), seen["read from"])
        self.assertEqual(self.pictures_in_drive(), ["Kindergarten - Room 3/Wall Inbox/done/IMG_0001.HEIC"])
        self.assertFalse(os.path.exists(os.path.join(self.tool, ".tmp")))
        self.assertEqual(_tree(self.computer), [], "and nothing is left in the temp folder")

    def test_stopped_in_the_middle_nothing_is_left_in_drive_or_in_the_temp_folder(self):
        heic = _heic_wall(self.inbox)
        if not heic:
            self.skipTest("this computer cannot write a HEIC test photo")

        def stopped(img, path, tmpdir, **k):
            raise KeyboardInterrupt()       # the watcher is stopped after the JPEG copy was made
        bc.read_photo_text = stopped
        with self.assertRaises(KeyboardInterrupt):
            bc.run_inbox(self.inbox, ["Maya Torres", "Priya Nair"], self.tool, "Art", log=lambda *a: None)
        self.assertEqual(self.pictures_in_drive(), ["Kindergarten - Room 3/Wall Inbox/done/IMG_0001.HEIC"])
        self.assertEqual(_tree(self.computer), [])

    def test_the_crops_of_a_plain_photo_stay_out_of_drive_too(self):
        sys.path.insert(0, HERE)
        from make_wall import make_wall
        img, _ = make_wall(["Maya Torres", "Priya Nair"], rows=1, cols=2, size=(800, 400))
        photo = os.path.join(self.inbox, "IMG_0002.jpg")
        img.save(photo, quality=90)
        seen = {}

        def reading(img, path, tmpdir, **k):
            seen["scratch"] = tmpdir
            return []
        bc.read_photo_text = reading
        bc.process_photo(photo, ["Maya Torres", "Priya Nair"], self.tool, "Art", log=lambda *a: None)
        self.assertTrue(seen["scratch"].startswith(self.computer + os.sep), seen["scratch"])
        self.assertEqual(self.pictures_in_drive(), ["Kindergarten - Room 3/Wall Inbox/IMG_0002.jpg"])

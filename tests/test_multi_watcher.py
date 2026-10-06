"""Two computers watching one class folder.

Everything here runs against a temporary folder standing in for the shared
Drive class folder. No sleeping: the election functions take "now" as a
parameter, so a stale file or a grace period is a number, not a wait.
Run:  python3 -m unittest tests.test_multi_watcher
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


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()

NOW = 1_800_000_000.0          # any fixed moment
LONG_AGO = NOW - 3600          # a watcher that started an hour ago is past its grace period
PC = {"machine": "CLASSROOM-PC", "priority": 50}
MAC = {"machine": "Helpers-MacBook", "priority": 90}


class StatusFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Class")
        os.makedirs(self.cls)
        self.sdir = bc.status_dir(self.cls)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_status_file_is_named_for_the_machine_inside_the_visible_folder(self):
        p = bc.write_status(self.sdir, "CLASSROOM-PC", NOW, "watching", 50)
        self.assertEqual(p, os.path.join(self.cls, "Watcher status", "CLASSROOM-PC.txt"))
        self.assertTrue(os.path.isfile(p))

    def test_status_text_is_plain_english_and_round_trips(self):
        text = bc.format_status("CLASSROOM-PC", NOW, "watching", 50, waiting=2,
                                last_batch="Sep 26 09:10 AM: 8 pieces, 7 filed, 1 to unsorted", started=NOW - 600,
                                system="Windows PC")
        for phrase in ("Computer: CLASSROOM-PC", "System: Windows PC", "Last checked at:", "the control tower for this class",
                       "Priority: 50", "Photos waiting in Arrivals: 2", "Last batch: Sep 26 09:10 AM",
                       "Tool version: " + bc.VERSION_DATE, "Watcher started:"):
            self.assertIn(phrase, text)
        st = bc.parse_status(text)
        self.assertEqual(st, {"machine": "CLASSROOM-PC", "epoch": int(NOW), "priority": 50, "role": "watching"})

    def test_standing_by_text_names_the_computer_that_is_watching(self):
        text = bc.format_status("Helpers-MacBook", NOW, "standing by", 90, leader="CLASSROOM-PC")
        self.assertIn("standing by; CLASSROOM-PC is the control tower for this class", text)
        self.assertIn("just started", bc.format_status("Helpers-MacBook", NOW, "starting", 90))

    def test_parse_rejects_files_that_are_not_ours_or_half_written(self):
        self.assertIsNone(bc.parse_status("A teacher's note: nothing to see here\n"))
        self.assertIsNone(bc.parse_status("checked-at-epoch: 12\n"))              # no machine line
        self.assertIsNone(bc.parse_status("checked-at-epoch: soon\nmachine: X\n"))  # not a number
        # the plain-English "Priority: 50 (the lowest ...)" line must not be mistaken for the machine line
        text = bc.format_status("PC", NOW, "watching", 7)
        self.assertEqual(bc.parse_status(text)["priority"], 7)

    def test_read_statuses_skips_junk_and_missing_folder(self):
        self.assertEqual(bc.read_statuses(os.path.join(self.tmp, "nowhere")), [])
        bc.write_status(self.sdir, "CLASSROOM-PC", NOW, "watching", 50)
        with open(os.path.join(self.sdir, "notes.txt"), "w") as f:
            f.write("a teacher left a note here\n")
        with open(os.path.join(self.sdir, "photo.jpg"), "w") as f:
            f.write("not text")
        got = bc.read_statuses(self.sdir)
        self.assertEqual([s["machine"] for s in got], ["CLASSROOM-PC"])
        self.assertEqual(got[0]["file"], "CLASSROOM-PC.txt")

    def test_write_at_most_once_a_minute_unless_a_batch_just_finished(self):
        self.assertTrue(bc.should_write_status(None, NOW))
        self.assertFalse(bc.should_write_status(NOW - 30, NOW))
        self.assertTrue(bc.should_write_status(NOW - 60, NOW))
        self.assertTrue(bc.should_write_status(NOW - 1, NOW, force=True))

    def test_describe_statuses_reads_like_a_person_talking(self):
        bc.write_status(self.sdir, "CLASSROOM-PC", NOW - 120, "watching", 50)
        bc.write_status(self.sdir, "Helpers-MacBook", NOW - 4 * 3600, "standing by", 90)
        lines = bc.describe_statuses(bc.read_statuses(self.sdir), NOW, me="Helpers-MacBook")
        self.assertEqual(len(lines), 2)
        self.assertIn("CLASSROOM-PC: last checked 2 minutes ago, watching, priority 50", lines[0])
        self.assertIn("Helpers-MacBook: last checked 4 hours ago, standing by, priority 90; OFF or asleep", lines[1])
        self.assertIn("<- this computer", lines[1])
        self.assertIn("no computer has written a status file yet", bc.describe_statuses([], NOW)[0])

    def test_ago_text(self):
        self.assertEqual(bc.ago_text(10), "just now")
        self.assertEqual(bc.ago_text(70), "1 minute ago")
        self.assertEqual(bc.ago_text(300), "5 minutes ago")
        self.assertEqual(bc.ago_text(5000), "1 hour ago")
        self.assertEqual(bc.ago_text(3 * 86400), "3 days ago")


class ElectionTests(unittest.TestCase):
    """(a) two watchers, 50 and 90: only 50 sorts. (b) the 50 goes stale: 90
    takes over. (c) a watcher in its first 90 seconds does not sort."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "Class"))    # a status file is never what makes the class folder
        self.sdir = bc.status_dir(os.path.join(self.tmp, "Class"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def both_fresh(self):
        bc.write_status(self.sdir, PC["machine"], NOW - 20, "watching", 50)
        bc.write_status(self.sdir, MAC["machine"], NOW - 40, "standing by", 90)
        return bc.read_statuses(self.sdir)

    def test_a_lowest_priority_sorts_and_the_other_stands_by(self):
        statuses = self.both_fresh()
        pc = bc.decide_role(statuses, PC, NOW, started=LONG_AGO)
        mac = bc.decide_role(statuses, MAC, NOW, started=LONG_AGO)
        self.assertEqual(pc["role"], "watching")
        self.assertEqual(pc["leader"], "CLASSROOM-PC")
        self.assertIn("Helpers-MacBook standing by", pc["reason"])
        self.assertEqual(mac["role"], "standing by")
        self.assertEqual(mac["reason"], "standing by, CLASSROOM-PC is the control tower for this class")
        # both machines agree on the leader from the same files
        self.assertEqual(pc["leader"], mac["leader"])

    def test_a_own_file_never_counts_twice_and_a_missing_own_file_is_fine(self):
        # the PC has not written yet (first tick); the Mac's fresh file alone
        bc.write_status(self.sdir, MAC["machine"], NOW, "watching", 90)
        pc = bc.decide_role(bc.read_statuses(self.sdir), PC, NOW, started=LONG_AGO)
        self.assertEqual(pc["role"], "watching")

    def test_b_follower_takes_over_when_the_leader_goes_stale(self):
        statuses = self.both_fresh()
        later = NOW + bc.STALE_SECONDS + 5            # the PC's file is now 5m25s old
        mac = bc.decide_role(statuses, MAC, later, started=LONG_AGO)
        self.assertEqual(mac["role"], "watching")
        self.assertIn("no other computer has reported in", mac["reason"])
        # ... and gives it back the moment the PC writes again
        bc.write_status(self.sdir, PC["machine"], later, "watching", 50)
        mac2 = bc.decide_role(bc.read_statuses(self.sdir), MAC, later + 1, started=LONG_AGO)
        self.assertEqual(mac2["role"], "standing by")

    def test_b_staleness_is_judged_by_the_time_inside_the_file_not_mtime(self):
        p = bc.write_status(self.sdir, PC["machine"], NOW - 2000, "watching", 50)
        os.utime(p, None)                             # Drive "touched" the file just now
        mac = bc.decide_role(bc.read_statuses(self.sdir), MAC, NOW, started=LONG_AGO)
        self.assertEqual(mac["role"], "watching")     # the PC is treated as off

    def test_clock_skew_a_file_from_the_future_is_fresh(self):
        bc.write_status(self.sdir, PC["machine"], NOW + 240, "watching", 50)   # PC clock 4 minutes fast
        mac = bc.decide_role(bc.read_statuses(self.sdir), MAC, NOW, started=LONG_AGO)
        self.assertEqual(mac["role"], "standing by")

    def test_c_grace_period_holds_a_fresh_watcher_back(self):
        started = NOW - 10
        alone = bc.decide_role([], PC, NOW, started=started)
        self.assertEqual(alone["role"], "starting")
        self.assertIn("just started", alone["reason"])
        self.assertIn("in the middle of a photo", alone["reason"])
        self.assertEqual(bc.decide_role([], PC, started + 89, started=started)["role"], "starting")
        self.assertEqual(bc.decide_role([], PC, started + 90, started=started)["role"], "watching")

    def test_ties_break_by_machine_name_so_both_sides_agree(self):
        a = {"machine": "Alpha", "priority": 50, "epoch": int(NOW)}
        b = {"machine": "Bravo", "priority": 50, "epoch": int(NOW)}
        self.assertEqual(bc.choose_leader([b], a, NOW), "Alpha")
        self.assertEqual(bc.choose_leader([a], b, NOW), "Alpha")
        self.assertTrue(bc.in_grace(NOW - 1, NOW))
        self.assertFalse(bc.in_grace(NOW - 90, NOW))


class ChildFolderWalkTests(unittest.TestCase):
    """(d) the status folder and the Unsorted folder are never treated as a child."""

    def test_is_child_folder(self):
        for n in ("Watcher status", "Unsorted - needs a person", "Wall Inbox", ".tmp", "done"):
            self.assertFalse(bc.is_child_folder(n), n)
        self.assertTrue(bc.is_child_folder("Maya Torres"))

    def test_docx_build_skips_status_and_unsorted_folders(self):
        tmp = tempfile.mkdtemp()
        try:
            from PIL import Image
            cls = os.path.join(tmp, "Class")
            child = os.path.join(cls, "Maya Torres", "Self-Portrait")
            os.makedirs(child)
            Image.new("RGB", (300, 400), "white").save(os.path.join(child, "Self-Portrait K.jpg"))
            # a status file, and a doubtful piece with its name strip, both with images inside subfolders
            bc.write_status(bc.status_dir(cls), "CLASSROOM-PC", NOW, "watching", 50)
            strips = os.path.join(cls, "Unsorted - needs a person", "name-strips")
            os.makedirs(strips)
            Image.new("RGB", (300, 60), "white").save(os.path.join(strips, "GUESS x.jpg"))
            made = bc.build_all_docx(tmp, cls)
            self.assertEqual(made, [os.path.join(cls, "Maya Torres", "Maya Torres - work.docx")])
            self.assertEqual(os.listdir(os.path.join(cls, "Watcher status")), ["CLASSROOM-PC.txt"])
            self.assertFalse(any(f.endswith(".docx") for f in os.listdir(os.path.join(cls, "Unsorted - needs a person"))))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_child_folders_are_made_beside_the_status_folder_untouched(self):
        tmp = tempfile.mkdtemp()
        try:
            cls = os.path.join(tmp, "Class")
            os.makedirs(cls)                            # a status file is never what makes the class folder
            p = bc.write_status(bc.status_dir(cls), "CLASSROOM-PC", NOW, "watching", 50)
            bc.make_child_folders(["Maya Torres", "Jordan Lum"], tmp, "Leaves", cls)
            self.assertTrue(os.path.isfile(p))
            self.assertEqual(sorted(n for n in os.listdir(cls) if bc.is_child_folder(n)), ["Jordan Lum", "Maya Torres"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class MachineNameTests(unittest.TestCase):
    """(e) platform.node() can hold characters Windows will not put in a file name."""

    def test_slash_and_colon_are_dropped(self):
        self.assertEqual(bc.machine_name("Room 3: Torres/PC"), "Room 3 TorresPC")
        self.assertEqual(bc.machine_name("desk\\top?*"), "desktop")
        self.assertEqual(bc.machine_name("Torres-MacBook-Air.local"), "Torres-MacBook-Air.local")
        self.assertEqual(bc.machine_name("::"), "unnamed-computer")

    def test_default_is_this_computer_and_legal_everywhere(self):
        n = bc.machine_name()
        self.assertTrue(n)
        self.assertFalse(any(ch in n for ch in '<>:"/\\|?*'))
        self.assertFalse(n.endswith("."))


class PhotoVanishesTests(unittest.TestCase):
    """(f) the other computer takes the photo while this one is working on it."""

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

    def fake_result(self, n):
        return [{"piece": i, "status": "confident", "name": "Maya Torres", "text": "Maya", "score": 1.0,
                 "margin": 1.0, "box": None, "file": "x", "bbox": (0, 0, 1, 1)} for i in range(1, n + 1)]

    def test_photo_taken_by_the_other_machine_before_the_claim_is_not_cut_at_all(self):
        calls = []
        bc.process_photo = lambda *a, **k: calls.append(a) or self.fake_result(3)
        real_move = bc.shutil.move

        def other_machine_moved_it_first(src, dst):
            os.remove(src)                   # the other computer's move to done has just synced
            return real_move(src, dst)       # so ours fails
        bc.shutil.move = other_machine_moved_it_first
        try:
            taken = []
            res = bc.run_inbox(self.inbox, ["Maya Torres"], self.tmp, "Leaves", log=self.log.append, sorted_dir=self.cls,
                               taken=taken)
        finally:
            bc.shutil.move = real_move
        self.assertEqual(res, [])
        self.assertEqual(calls, [])          # nothing was cut, so nothing was filed twice
        self.assertEqual(taken, ["wall.jpg"])
        self.assertTrue(any("another computer finished this photo first" in m and "nothing filed twice" in m for m in self.log), self.log)
        self.assertEqual(os.listdir(os.path.join(self.inbox, "done")), [])

    def test_photo_gone_before_this_machine_starts_is_skipped_plainly(self):
        calls = []
        bc.process_photo = lambda *a, **k: calls.append(a) or self.fake_result(1)
        os.remove(self.photo)
        saved = bc.inbox_jobs
        bc.inbox_jobs = lambda inbox, project: [(self.photo, project, os.path.join(inbox, "done"))]
        try:
            res = bc.run_inbox(self.inbox, ["Maya Torres"], self.tmp, "Leaves", log=self.log.append, sorted_dir=self.cls)
        finally:
            bc.inbox_jobs = saved
        self.assertEqual(res, [])
        self.assertEqual(calls, [])
        self.assertTrue(any("gone from the inbox" in m and "another computer took it" in m for m in self.log), self.log)

    def test_photo_vanishing_mid_read_is_not_moved_to_failed(self):
        def vanishes(path, *a, **k):
            os.remove(path)
            raise OSError("file disappeared while reading")
        bc.process_photo = vanishes
        res = bc.run_inbox(self.inbox, ["Maya Torres"], self.tmp, "Leaves", log=self.log.append, sorted_dir=self.cls)
        self.assertEqual(res, [])
        self.assertFalse(os.path.isdir(os.path.join(self.inbox, "failed")))
        self.assertTrue(any("vanished while it was being sorted" in m for m in self.log), self.log)

    def test_a_photo_that_stays_is_still_filed_and_moved_to_done(self):
        bc.process_photo = lambda *a, **k: self.fake_result(2)
        res = bc.run_inbox(self.inbox, ["Maya Torres"], self.tmp, "Leaves", log=self.log.append, sorted_dir=self.cls)
        self.assertEqual(len(res), 2)
        self.assertEqual(os.listdir(os.path.join(self.inbox, "done")), ["wall.jpg"])

    def test_inbox_jobs_lists_root_and_project_folders_only(self):
        proj = os.path.join(self.inbox, "Fall Leaves")
        os.makedirs(proj)
        open(os.path.join(proj, "b.HEIC"), "w").close()
        os.makedirs(os.path.join(self.inbox, "done", "old"))
        open(os.path.join(self.inbox, "done", "old", "c.jpg"), "w").close()
        open(os.path.join(self.inbox, "READ ME.txt"), "w").close()
        jobs = bc.inbox_jobs(self.inbox, "Artwork")
        self.assertEqual([(os.path.basename(s), p) for s, p, _ in jobs], [("b.HEIC", "Fall Leaves"), ("wall.jpg", "Artwork")])
        self.assertEqual(jobs[0][2], os.path.join(self.inbox, "done", "Fall Leaves"))


class WatchLoopTests(unittest.TestCase):
    """The --watch loop itself, with sleep replaced so two passes run and stop."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cls = os.path.join(self.tmp, "Class")
        self.inbox = os.path.join(self.cls, "Wall Inbox")
        os.makedirs(self.inbox)
        self.roster = os.path.join(self.cls, "Class list.txt")
        with open(self.roster, "w") as f:
            f.write("Maya Torres\n")
        self.settings = os.path.join(self.tmp, "settings.json")
        self.saved = (bc.time.sleep, bc.run_inbox, bc.GRACE_SECONDS)
        self.ticks = []

        def stop_after(n):
            def fake_sleep(s):
                self.ticks.append(s)
                if len(self.ticks) >= n:
                    raise KeyboardInterrupt
            return fake_sleep
        self.stop_after = stop_after

    def tearDown(self):
        bc.time.sleep, bc.run_inbox, bc.GRACE_SECONDS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_settings(self, priority):
        with open(self.settings, "w") as f:
            json.dump({"inbox": self.inbox, "sorted": self.cls, "unsorted": os.path.join(self.cls, "Unsorted - needs a person"),
                       "roster": self.roster, "project": "Leaves", "interval": 1, "priority": priority}, f)

    def run_main(self, ticks):
        bc.time.sleep = self.stop_after(ticks)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                bc.main(["--watch", "--settings", self.settings, "--out", self.tmp])
        return buf.getvalue()

    def test_follower_writes_status_and_never_sorts(self):
        self.write_settings(90)
        bc.write_status(bc.status_dir(self.cls), "CLASSROOM-PC", bc.time.time(), "watching", 50)
        calls = []
        bc.run_inbox = lambda *a, **k: calls.append(1) or []
        bc.GRACE_SECONDS = 0
        out = self.run_main(2)
        self.assertEqual(calls, [])
        self.assertIn("standing by, CLASSROOM-PC is the control tower for this class", out)
        self.assertEqual(out.count("standing by, CLASSROOM-PC"), 1)      # said once, not every tick
        mine = os.path.join(self.cls, "Watcher status", bc.machine_name() + ".txt")
        self.assertTrue(os.path.isfile(mine))
        self.assertIn("standing by; CLASSROOM-PC is the control tower", read(mine))
        self.assertIn("Priority: 90", read(mine))

    def test_leader_sorts_and_records_the_batch_in_its_status(self):
        self.write_settings(50)
        bc.GRACE_SECONDS = 0
        batches = iter([[{"status": "confident"}, {"status": "unsure"}], []])
        bc.run_inbox = lambda *a, **k: next(batches, [])
        out = self.run_main(2)
        self.assertIn("this computer is the control tower for this class (no other computer has reported in)", out)
        self.assertIn("2 pieces, 1 filed, 1 to unsorted", out)
        mine = read(os.path.join(self.cls, "Watcher status", bc.machine_name() + ".txt"))
        self.assertIn("Role: the control tower for this class", mine)
        self.assertIn("Last batch:", mine)
        self.assertIn("2 pieces, 1 filed, 1 to unsorted", mine)

    def test_grace_period_is_explained_and_status_is_still_written(self):
        self.write_settings(50)
        calls = []
        bc.run_inbox = lambda *a, **k: calls.append(1) or []
        out = self.run_main(1)
        self.assertEqual(calls, [])
        self.assertIn("just started: standing by for another", out)
        mine = read(os.path.join(self.cls, "Watcher status", bc.machine_name() + ".txt"))
        self.assertIn("just started", mine)

    def test_check_lists_the_computers_watching(self):
        self.write_settings(90)
        os.makedirs(os.path.join(self.cls, "Unsorted - needs a person"))
        bc.write_status(bc.status_dir(self.cls), "CLASSROOM-PC", bc.time.time() - 130, "watching", 50)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            bc.self_check(self.settings)
        out = buf.getvalue()
        self.assertIn("control towers for this class", out)
        self.assertIn("CLASSROOM-PC: last checked 2 minutes ago, watching, priority 50", out)
        self.assertIn("priority 90", out)

    def test_bad_priority_in_settings_falls_back_to_default(self):
        self.write_settings("high")
        bc.run_inbox = lambda *a, **k: []
        out = self.run_main(1)
        self.assertIn("should be a whole number", out)
        self.assertIn(f"priority {bc.DEFAULT_PRIORITY}", out)


if __name__ == "__main__":
    unittest.main()

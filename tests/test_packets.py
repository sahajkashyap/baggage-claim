"""PDF packets: a PDF dropped into Wall Inbox, every page filed to its child.

The rule a teacher is given: the child's name TYPED in a corner of EVERY page,
"page X of Y" beside it if they like. One PDF per child per packet, pages in
packet order; a page whose name is not certain goes to a person; a child whose
numbered pages are not a whole set is not filed; a note says what happened.
The whole grid is tests/packet_check.py; these are the core cases and each
rule on its own. Invented names only (contract_wall NAMES).
Run:  python3 -m unittest tests.test_packets
"""
import contextlib
import importlib
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import baggage_claim as sw  # noqa: E402
from contract_wall import NAMES  # noqa: E402


def have(*mods):
    try:
        for m in mods:
            importlib.import_module(m)
        return True
    except ImportError:
        return False


PDF = have("pypdfium2", "pypdf", "reportlab")
READER = sw.backend_ready()
if PDF:
    from make_packet import make_packet, packet_pages, fingerprints  # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Work(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="packet-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = []

    def packet(self, pages, kind="digital", name="Packet.pdf", folder=None, **kw):
        d = folder or os.path.join(self.tmp, "made")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, name)
        make_packet(path, pages, kind, **kw)
        return path

    def sort(self, path, project="Reading", roster=NAMES):
        return sw.process_packet(path, roster, self.tmp, project, log=self.log.append, grade="K")

    def child_pdfs(self, child, project="Reading"):
        d = os.path.join(self.tmp, "sorted", sw.safe_folder(child), project)
        return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".pdf")) if os.path.isdir(d) else []

    def unsorted(self):
        d = os.path.join(self.tmp, "unsorted")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def note(self):
        notes = [f for f in self.unsorted() if f.startswith(sw.PACKET_NOTE)]
        self.assertEqual(len(notes), 1, self.unsorted())
        return read(os.path.join(self.tmp, "unsorted", notes[0]))

    def assert_filed_in_order(self, path, pages, children):
        prints = fingerprints(path)
        for child in children:
            want = [prints[i] for i, pg in enumerate(pages) if pg["name"] == child]
            got = self.child_pdfs(child)
            self.assertEqual(len(got), 1, f"{child}: one PDF")
            self.assertEqual(fingerprints(got[0]), want, f"{child}: exactly its pages, in packet order")


# ----------------------------------------------------------- small parts ---

class PageNumbers(unittest.TestCase):
    def test_forms(self):
        t = sw.take_page_number
        self.assertEqual(t("Maya Torres page 2 of 3"), ("Maya Torres", (2, 3, "page")))
        self.assertEqual(t("Theopage 2 of 2"), ("Theo", (2, 2, "page")))
        self.assertEqual(t("Caleb 2of 2"), ("Caleb", (2, 2, "of")))
        self.assertEqual(t(".2 of 2"), ("", (2, 2, "of")))
        self.assertEqual(t("Nadia 3/3"), ("Nadia", (3, 3, "slash")))
        self.assertEqual(t("Page 1 of 3"), ("", (1, 3, "page")))
        self.assertEqual(t("Nadia page 1 ot 3"), ("Nadia", (1, 3, "page")), "a reader's 'ot' for 'of'")

    def test_what_is_not_a_page_number(self):
        t = sw.take_page_number
        self.assertEqual(t("Maya Torres"), ("Maya Torres", None))
        self.assertEqual(t("Due 9/30/2026"), ("Due 9/30/2026", None), "a date is not a page number")
        self.assertEqual(t("Oct 9/30"), ("Oct 9/30", None), "30 pages is not a packet: a date")
        self.assertEqual(t("4 of 3"), ("4 of 3", None))

    def test_problems(self):
        p = sw.page_number_problems
        self.assertEqual(p("Lily", [(1, (1, 2)), (2, (2, 2))]), [])
        self.assertEqual(p("Lily", [(1, None), (2, None)]), [], "no numbers: filed as they are")
        self.assertEqual(p("Lily", [(1, (1, 3)), (5, (3, 3))]), ["page 2 of 3 is missing"])
        doubled = p("Lily", [(1, (1, 2)), (2, (1, 2)), (3, (2, 2))])
        self.assertEqual(doubled, ["page 1 of 2 is there 2 times (packet pages 1, 2)"])
        self.assertIn("packet page 2 carries no page number, though Lily's other pages do",
                      p("Lily", [(1, (1, 2)), (2, None)]))

    def test_where_it_sat(self):
        self.assertEqual(sw.where_it_sat(1, ["Lily", None, "Lily"]), "between two of Lily's pages")
        self.assertEqual(sw.where_it_sat(1, ["Lily", None, "Theo"]), "after a page of Lily, before a page of Theo")
        self.assertIn("first page of the packet", sw.where_it_sat(0, [None, "Theo"]))

    def test_batch_text_counts_packet_pages(self):
        res = [{"status": "confident", "packet": "p.pdf"}, {"status": "unsure", "packet": "p.pdf"}]
        self.assertEqual(sw.batch_text(res), "2 packet pages, 1 filed, 1 to unsorted")
        self.assertEqual(sw.batch_text(res + [{"status": "confident"}]),
                         "1 pieces and 2 packet pages, 2 filed, 1 to unsorted")
        self.assertEqual(sw.batch_text([{"status": "confident"}]), "1 pieces, 1 filed, 0 to unsorted")

    def test_inbox_takes_pdf(self):
        self.assertIn(".pdf", sw.INBOX_EXT)
        self.assertTrue(sw.is_packet("Week 3.PDF"))
        self.assertFalse(sw.is_packet("wall.jpg"))


@unittest.skipUnless(PDF, "needs pypdfium2, pypdf and reportlab")
class SelfCheckLine(unittest.TestCase):
    def test_ok_when_present(self):
        self.assertTrue(sw.pdf_parts_text().startswith("ok: PDF packets can be read"))

    def test_warn_never_fail_when_missing(self):
        with hidden("pypdfium2"):
            line = sw.pdf_parts_text()
        self.assertTrue(line.startswith("WARN: PDF packets cannot be read"), line)
        self.assertIn("pypdfium2", line)
        self.assertIn("Photos are sorted as usual", line)


@contextlib.contextmanager
def hidden(*mods):
    """Make `import <mod>` fail, as on a computer that does not have it."""
    saved = {m: sys.modules.get(m) for m in mods}
    for m in mods:
        sys.modules[m] = None
    try:
        yield
    finally:
        for m, v in saved.items():
            if v is None:
                sys.modules.pop(m, None)
            else:
                sys.modules[m] = v


# ------------------------------------------------------------- packets ---

@unittest.skipUnless(PDF, "needs pypdfium2, pypdf and reportlab")
class CorePackets(Work):
    def test_digital_packet_every_page_to_its_child_in_packet_order(self):
        names = NAMES[:5]
        pages = packet_pages(names, [1, 2, 3], corner="tr", numbers=True, mixed=True, seed=4)
        path = self.packet(pages)
        res = self.sort(path)
        self.assertEqual([r["name"] for r in res], [p["name"] for p in pages])
        self.assertTrue(all(r["status"] == "confident" for r in res))
        self.assert_filed_in_order(path, pages, names)
        self.assertEqual([f for f in self.unsorted() if f.endswith(".pdf")], [])
        self.assertEqual(os.path.basename(self.child_pdfs(names[0])[0]), "Reading K.pdf")
        self.assertTrue(any(f"{len(pages)} filed for 5 children" in line for line in self.log), self.log[-1])

    @unittest.skipUnless(READER, "needs the on-device reader")
    def test_scanned_packet_every_page_to_its_child_in_packet_order(self):
        names = NAMES[5:9]
        pages = packet_pages(names, [2, 1, 3], corner="bl", numbers=True, seed=5)
        path = self.packet(pages, kind="scanned")
        res = self.sort(path)
        self.assertEqual([r["name"] for r in res], [p["name"] for p in pages])
        self.assert_filed_in_order(path, pages, names)

    @unittest.skipUnless(READER, "needs the on-device reader")
    def test_reader_alone_files_a_digital_packet(self):
        names = NAMES[:3]
        pages = packet_pages(names, 2, corner="tl", numbers=True, seed=6)
        path = self.packet(pages)
        sw.PACKET_TEXT_LAYER = False
        try:
            res = self.sort(path)
        finally:
            sw.PACKET_TEXT_LAYER = True
        self.assertTrue(all(r["status"] == "confident" for r in res))
        self.assert_filed_in_order(path, pages, names)

    def test_a_second_packet_gets_a_second_file_not_a_merge(self):
        names = NAMES[:2]
        a = self.packet(packet_pages(names, 1, seed=1), name="Week 1.pdf")
        b = self.packet(packet_pages(names, 1, seed=2), name="Week 2.pdf", seed=9)
        self.sort(a)
        self.sort(b)
        self.assertEqual([os.path.basename(p) for p in self.child_pdfs(names[0])], ["Reading K 2.pdf", "Reading K.pdf"])


@unittest.skipUnless(PDF and READER, "needs pypdfium2, pypdf, reportlab and the on-device reader")
class PagesForAPerson(Work):
    def test_unreadable_page_goes_to_a_person_and_the_note_says_where_it_sat(self):
        names = NAMES[:3]
        pages = packet_pages(names, 2, numbers=False, seed=7)
        pages.insert(3, {"name": None, "corner": "br", "number": None, "form": "page"})   # between Jonah's two
        path = self.packet(pages)
        res = self.sort(path)
        self.assertNotEqual(res[3]["status"], "confident")
        guesses = [f for f in self.unsorted() if f.endswith(".pdf")]
        # the body text can give a weak guess ("bridge"); a guess is all it is
        self.assertEqual(len(guesses), 1)
        self.assertRegex(guesses[0], r"^GUESS .+ - Reading K - Packet [0-9a-f]{6} page 004\.pdf$")
        note = self.note()
        self.assertRegex(note, rf"Packet page 4: [^\n]*; between two of {names[1]}'s pages\.")
        self.assertIn("7 in the packet, 6 filed", note)
        # the page is never given to Jonah because of where it sits
        self.assertEqual(len(fingerprints(self.child_pdfs(names[1])[0])), 2)

    def test_missing_page_two_of_three_is_not_filed_and_the_note_says_which(self):
        names = NAMES[:3]
        pages = packet_pages(names, 3, numbers=True, seed=8)
        del pages[4]            # Jonah's page 2 of 3
        path = self.packet(pages)
        res = self.sort(path)
        self.assertEqual(self.child_pdfs(names[1]), [], "a set that is not whole is not filed")
        self.assertEqual(len(self.child_pdfs(names[0])), 1)
        jonah = [r for r in res if r["name"] == names[1]]
        self.assertTrue(all(r["status"] == "unsure" and r["reason"] == sw.PAGES for r in jonah))
        checks = [f for f in self.unsorted() if f.startswith(sw.CHECK_PAGES)]
        self.assertEqual(len(checks), 2)
        note = self.note()
        self.assertIn(f"{names[1]}: page 2 of 3 is missing", note)
        self.assertTrue(any("page 2 of 3 is missing" in line for line in self.log))

    def test_doubled_page_is_not_filed(self):
        names = NAMES[:2]
        pages = packet_pages(names, 2, numbers=True, seed=10)
        pages.insert(1, dict(pages[0]))      # Maya's page 1 of 2 twice
        path = self.packet(pages)
        self.sort(path)
        self.assertEqual(self.child_pdfs(names[0]), [])
        self.assertIn("page 1 of 2 is there 2 times (packet pages 1, 2)", self.note())

    def test_child_with_no_pages_and_a_short_child_are_listed(self):
        names = NAMES[:4]
        pages = packet_pages(names, 3, numbers=False, seed=11)
        pages = [p for i, p in enumerate(pages) if not (p["name"] == names[2] and i % 3 == 2)]     # Sofia: 2
        path = self.packet(pages)
        self.sort(path, roster=names + ["Wren"])
        note = self.note()
        self.assertIn("Children on the class list with no pages in this packet: Wren.", note)
        self.assertIn(f"- {names[2]} has 2 pages; most children have 3.", note)
        self.assertIn(f"- {names[0]}: 3 pages (1, 2, 3)", note)

    def test_a_name_read_only_as_a_guess_is_never_filed(self):
        # two children called Maya and only "Maya" on the page: a tie is never certain
        pages = [{"name": "Maya", "corner": "tl", "number": None, "form": "page"},
                 {"name": NAMES[1], "corner": "tl", "number": None, "form": "page"}]
        path = self.packet(pages)
        res = self.sort(path, roster=["Maya Torres", "Maya R.", NAMES[1]])
        self.assertEqual(res[0]["status"], "unsure")
        self.assertEqual(self.child_pdfs("Maya Torres") + self.child_pdfs("Maya R."), [])
        self.assertTrue(any(f.startswith("GUESS Maya") and f.endswith("page 001.pdf") for f in self.unsorted()))
        self.assertIn("Packet page 1: best guess Maya", self.note())


@unittest.skipUnless(PDF, "needs pypdfium2, pypdf and reportlab")
class FiledOnce(Work):
    def test_a_packet_sorted_twice_gives_no_second_copies(self):
        names = NAMES[:4]
        pages = packet_pages(names, [1, 2], numbers=True, seed=12)
        path = self.packet(pages)
        first = self.sort(path)
        second = self.sort(path)
        self.assertFalse(any(r["already"] for r in first))
        self.assertTrue(all(r["already"] for r in second))
        for child in names:
            self.assertEqual(len(self.child_pdfs(child)), 1, child)
        self.assert_filed_in_order(path, pages, names)
        self.assertTrue(any("already in the children's folders" in line for line in self.log))

    def test_a_deleted_child_pdf_is_filed_again(self):
        names = NAMES[:2]
        path = self.packet(packet_pages(names, 1, seed=13))
        self.sort(path)
        os.remove(self.child_pdfs(names[0])[0])
        res = self.sort(path)
        self.assertEqual(len(self.child_pdfs(names[0])), 1)
        self.assertEqual([r["already"] for r in res], [False, True])

    def test_the_mark_names_nobody(self):
        import pypdf
        names = NAMES[:1]
        path = self.packet(packet_pages(names, 2, seed=14))
        self.sort(path)
        meta = pypdf.PdfReader(self.child_pdfs(names[0])[0]).metadata
        mark = str(meta[sw.PACKET_MARK])
        self.assertRegex(mark, r"^packet [0-9a-f]{16} pages 1 2$")


@unittest.skipUnless(PDF, "needs pypdfium2, pypdf and reportlab")
class ThroughTheInbox(Work):
    def setUp(self):
        super().setUp()
        self.inbox = os.path.join(self.tmp, "Wall Inbox")
        os.makedirs(self.inbox)
        self.saved = sw.is_settled
        sw.is_settled = lambda path, wait=2.0: True
        self.addCleanup(setattr, sw, "is_settled", self.saved)

    def run_inbox(self, **kw):
        return sw.run_inbox(self.inbox, NAMES, self.tmp, "Reading", log=self.log.append, grade="K", **kw)

    def test_two_different_packets_both_called_scan_lose_nothing(self):
        """Found by the review of September 30, 2026: the second "Packet.pdf" in the
        same project overwrote the first one's unreadable page, its note and its copy
        in done. Each packet now keeps all three."""
        names = NAMES[:3]
        first = packet_pages(names[:2], 1, seed=31)
        first.insert(0, {"name": None, "corner": "br", "number": None, "form": "page"})
        self.packet(first, folder=self.inbox)
        self.run_inbox()
        second = packet_pages(names[1:], 1, seed=32)
        second.insert(0, {"name": None, "corner": "br", "number": None, "form": "page"})
        self.packet(second, folder=self.inbox)
        self.run_inbox()
        unsorted = os.listdir(os.path.join(self.tmp, "unsorted"))
        self.assertEqual(len([f for f in unsorted if f.startswith("GUESS") and f.endswith(".pdf")]), 2, unsorted)
        self.assertEqual(len([f for f in unsorted if f.startswith(sw.PACKET_NOTE)]), 2, unsorted)
        done = sorted(f for f in os.listdir(os.path.join(self.inbox, "done")) if f.endswith(".pdf"))
        self.assertEqual(done, ["Packet 2.pdf", "Packet.pdf"])

    def test_the_watcher_takes_a_pdf_like_a_photo(self):
        names = NAMES[:3]
        self.packet(packet_pages(names, 2, seed=15), folder=self.inbox)
        self.assertEqual([os.path.basename(j[0]) for j in sw.inbox_jobs(self.inbox, "Reading")], ["Packet.pdf"])
        res = self.run_inbox()
        self.assertEqual(len(res), 6)
        self.assertTrue(os.path.exists(os.path.join(self.inbox, "done", "Packet.pdf")))
        self.assertFalse(os.path.exists(os.path.join(self.inbox, "Packet.pdf")))
        self.assertEqual(len(self.child_pdfs(names[0])), 1)
        self.assertIn("6 packet pages, 6 filed, 0 to unsorted", sw.batch_text(res))
        report = read(os.path.join(self.tmp, "run-report.md"))
        self.assertIn("| page 1 | confident |", report)

    def test_a_packet_in_a_project_folder_uses_the_folder_name(self):
        names = NAMES[:2]
        folder = os.path.join(self.inbox, "Fall Leaves")
        self.packet(packet_pages(names, 1, seed=16), folder=folder)
        self.run_inbox()
        d = os.path.join(self.tmp, "sorted", names[0], "Fall Leaves")
        self.assertEqual(os.listdir(d), ["Fall Leaves K.pdf"])
        self.assertTrue(os.path.exists(os.path.join(self.inbox, "done", "Fall Leaves", "Packet.pdf")))
        self.assertTrue(any(f.startswith("PACKET - read me - Fall Leaves - Packet") for f in self.unsorted()))

    def test_a_damaged_pdf_goes_to_failed_with_a_plain_line(self):
        with open(os.path.join(self.inbox, "Broken.pdf"), "wb") as f:
            f.write(b"%PDF-1.4\nthis is not really a pdf\n")
        could_not = []
        res = self.run_inbox(could_not=could_not)
        self.assertEqual(res, [])
        self.assertTrue(os.path.exists(os.path.join(self.inbox, "failed", "Broken.pdf")))
        self.assertEqual(sw.photos_in_failed(self.inbox), 1)
        self.assertEqual(could_not[0]["kind"], sw.PACKET_BAD)
        line = [x for x in self.log if "could not be sorted" in x][0]
        self.assertIn("Broken.pdf: this packet could not be sorted, because the file could not be opened as a PDF",
                      line)
        note = read(could_not[0]["note"])
        self.assertIn("Baggage Claim could not sort this packet.", note)
        self.assertIn("Save or scan the packet again", note)

    def test_without_the_pdf_parts_a_packet_waits_in_failed_and_says_why(self):
        self.packet(packet_pages(NAMES[:1], 1, seed=17), folder=self.inbox)
        could_not = []
        with hidden("pypdfium2", "pypdf"):
            self.run_inbox(could_not=could_not)
        self.assertEqual(could_not[0]["kind"], sw.PACKET_PARTS)
        self.assertTrue(os.path.exists(os.path.join(self.inbox, "failed", "Packet.pdf")))
        self.assertIn("pip install pypdfium2 pypdf", read(could_not[0]["note"]))


@unittest.skipUnless(READER, "needs the on-device reader")
class PhotosWithoutThePdfParts(Work):
    def test_photo_sorting_does_not_need_the_pdf_libraries(self):
        from contract_wall import contract_wall
        names = NAMES[:2]
        img, _ = contract_wall(names, 1, 2, seed=3)
        photo = os.path.join(self.tmp, "wall.jpg")
        img.save(photo, quality=92)
        with hidden("pypdfium2", "pypdf"):
            res = sw.process_photo(photo, names, self.tmp, "Art", log=self.log.append, grade="K")
        self.assertEqual(sorted(r["name"] for r in res if r["status"] == "confident"), sorted(names))

    def test_the_program_starts_without_the_pdf_libraries(self):
        import subprocess
        code = ("import sys; sys.modules['pypdfium2'] = None; sys.modules['pypdf'] = None; "
                "import baggage_claim as b; print(b.pdf_parts_text())")
        out = subprocess.run([sys.executable, "-c", code], cwd=os.path.dirname(HERE), capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith("WARN: PDF packets cannot be read"), out.stdout)


if __name__ == "__main__":
    unittest.main()


class TwoPacketsWithOneName(unittest.TestCase):
    """Scanners reuse names like "Scan.pdf". Found by the review of September
    30, 2026: a second packet of the same name in the same project overwrote
    the first one's pages in Unsorted, its note, and its copy in done."""

    def test_a_second_packet_of_the_same_name_overwrites_nothing(self):
        import baggage_claim as bc
        first = bc.free_path
        d = tempfile.mkdtemp(prefix="free-")
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "Scan.pdf")
        self.assertEqual(first(p), p)
        open(p, "w").close()
        self.assertEqual(first(p), os.path.join(d, "Scan 2.pdf"))
        open(os.path.join(d, "Scan 2.pdf"), "w").close()
        self.assertEqual(first(p), os.path.join(d, "Scan 3.pdf"))

"""Set up a class from its class list, on this computer only (class_setup.py).

A screenshot, what was copied, a Word, CSV or text file: each gives the same
list of children, headings and numbering left out, and the build makes one
folder per child and a page of labels. Everything is built in a temporary
folder, never in Google Drive. Invented names only.
Run:  python3 -m unittest tests.test_class_setup
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import baggage_claim as bc  # noqa: E402
import class_setup as cs  # noqa: E402

KIDS = ["Juniper Quill", "Quillon Brambleby", "Wren Fallowmere", "Ines Okonkwo-Dale", "Thaddeus Pim",
        "Juniper Vantreese", "Zofia Larkspur", "Bastien Rook"]
NEW_CLASS = os.path.join(ROOT, "tools", "new_class.py")


def docx_text(path):
    with zipfile.ZipFile(path) as z:
        return cs._text(z.read("word/document.xml").decode("utf-8"))


class Clean(unittest.TestCase):
    def test_numbering_bullets_headings_blanks_and_repeats(self):
        raw = ["Class List", "", "Name", "1. Juniper Quill", "2) Quillon Brambleby", "• Wren Fallowmere",
               "- Thaddeus Pim", "  Zofia   Larkspur  ", "12", "Juniper Quill", "First Name:", "Bastien Rook,"]
        self.assertEqual(cs.clean(raw), ["Juniper Quill", "Quillon Brambleby", "Wren Fallowmere", "Thaddeus Pim",
                                         "Zofia Larkspur", "Bastien Rook"])

    def test_hyphen_and_apostrophe_names_survive(self):
        self.assertEqual(cs.clean(["Ines Okonkwo-Dale", "Ronan O'Leary"]), ["Ines Okonkwo-Dale", "Ronan O'Leary"])

    def test_a_name_that_starts_with_a_dash_word_is_kept(self):
        self.assertEqual(cs.clean(["Marisol"]), ["Marisol"])

    def test_the_readers_usual_slips_on_a_name_are_undone(self):
        cases = {"IVO Pim": "Ivo Pim", "ignatius Ferreira": "Ignatius Ferreira", "lvo Daventry": "Ivo Daventry",
                 "Perpetua OLeary": "Perpetua O'Leary", "Lloyd Banks": "Lloyd Banks", "DJ Park": "DJ Park",
                 "Ines de la Cruz": "Ines de la Cruz", "Bo Li": "Bo Li", "Juniper Quill": "Juniper Quill"}
        for read, meant in cases.items():
            self.assertEqual(cs.tidy_name(read), meant)
        self.assertEqual(cs.clean(["1. IVO Pim", "lvo Daventry"]), ["Ivo Pim", "Ivo Daventry"])


class Labels(unittest.TestCase):
    def test_first_names_unless_two_children_share_one(self):
        self.assertEqual(cs.label_names(KIDS)[:3], ["Juniper Quill", "Quillon", "Wren"])
        self.assertEqual(cs.label_names(KIDS)[5], "Juniper Vantreese")

    def test_labels_page_holds_every_label_in_order(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "labels.docx")
            cs.labels_docx(cs.label_names(KIDS), p)
            with zipfile.ZipFile(p) as z:
                xml = z.read("word/document.xml").decode("utf-8")
            self.assertEqual(xml.count("<w:tr>"), 3)                  # 8 labels, 3 per row
            self.assertEqual(xml.count('w:ascii="Arial"'), len(KIDS))
            self.assertIn('w:pgMar w:top="1080"', xml)
            self.assertEqual(docx_text(p), "".join(cs.label_names(KIDS)))
            out = subprocess.run(["textutil", "-convert", "txt", "-stdout", p], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0)                        # opens as a real Word file


class Sources(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def path(self, name, data):
        p = os.path.join(self.d, name)
        with open(p, "wb" if isinstance(data, bytes) else "w", encoding=None if isinstance(data, bytes) else "utf-8") as f:
            f.write(data)
        return p

    def test_text_file(self):
        p = self.path("list.txt", "Students\n" + "\n".join(KIDS) + "\n")
        self.assertEqual(cs.clean(cs.read_source(p)), KIDS)

    def test_text_file_saved_with_a_byte_order_mark_or_latin1(self):
        self.assertEqual(cs.clean(cs.read_source(self.path("a.txt", "﻿Zofia Larkspur\n"))), ["Zofia Larkspur"])
        self.assertEqual(cs.clean(cs.read_source(self.path("b.txt", "Ren\xe9e Duval\n".encode("latin-1")))),
                         ["Ren\xe9e Duval"])

    def test_csv_first_and_last_in_two_columns(self):
        p = self.path("list.csv", "First,Last\n" + "\n".join(",".join(k.split(" ", 1)) for k in KIDS))
        self.assertEqual(cs.clean(cs.read_source(p)), KIDS)         # the heading row is dropped

    def test_copied_from_a_sheet_arrives_with_tabs(self):
        copied = "\n".join("\t".join(k.split(" ", 1)) for k in KIDS) + "\n"
        with mock.patch.object(cs.subprocess, "run", return_value=mock.Mock(stdout=copied)):
            self.assertEqual(cs.clean(cs.read_source(None)), KIDS)

    def test_a_class_sheet_copied_with_its_side_columns(self):
        copied = ("\t\tSorted by First Name\n"
                  + "".join(f"{side}\t\t{f}\t{l}\t5/24/2019\t7y 4m\n" for side, f, l in [
                      ("Oldest", "Juniper", "Quill Abernathy"), ("", "Wren", "Fallowmere"),
                      ("", "Ines", "Okonkwo-Dale"), ("", "Bastien", "Van Rook"), ("", "Juniper", "Vantreese"),
                      ("Youngest", "Bri-Ann", "Larkspur")]))
        self.assertEqual(cs.clean(cs.lines_from_table_text(copied)),
                         ["Juniper Quill Abernathy", "Wren Fallowmere", "Ines Okonkwo-Dale", "Bastien Van Rook",
                          "Juniper Vantreese", "Bri-Ann Larkspur"])

    def test_copied_from_a_doc(self):
        copied = "My class\n\n" + "\n".join(f"{i}. {k}" for i, k in enumerate(KIDS, 1))
        with mock.patch.object(cs.subprocess, "run", return_value=mock.Mock(stdout=copied)):
            self.assertEqual(cs.clean(cs.read_source(None)), KIDS)      # "My class" is not a name

    def test_nothing_copied(self):
        with mock.patch.object(cs.subprocess, "run", return_value=mock.Mock(stdout="  \n")):
            with self.assertRaisesRegex(cs.SetupError, "nothing has been copied"):
                cs.read_source(None)

    def test_clipboard_cannot_be_read(self):
        with mock.patch.object(cs.subprocess, "run", side_effect=OSError):
            with self.assertRaisesRegex(cs.SetupError, "could not be read"):
                cs.read_source(None)

    def test_word_file_paragraphs_and_a_table(self):
        p = os.path.join(self.d, "list.docx")
        cs.labels_docx(KIDS[:3], p)                                 # a table, one name per cell
        self.assertEqual(cs.clean(cs.read_source(p)), KIDS[:3])     # one full name per cell
        body = ("<w:p><w:r><w:t>Class list</w:t></w:r></w:p>"
                + "".join(f"<w:p><w:r><w:t>{k}</w:t></w:r></w:p>" for k in KIDS[3:])
                + "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Quillon</w:t></w:r></w:p></w:tc>"
                  "<w:tc><w:p><w:r><w:t>Brambleby</w:t></w:r></w:p></w:tc></w:tr></w:tbl>")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", f'<w:document><w:body>{body}</w:body></w:document>')
        self.assertEqual(cs.clean(cs.read_source(p)), KIDS[3:] + ["Quillon Brambleby"])

    def test_damaged_word_file(self):
        with self.assertRaisesRegex(cs.SetupError, "Word file could not be opened"):
            cs.read_source(self.path("bad.docx", b"not a zip"))

    def test_google_doc_shortcut_says_to_copy_instead(self):
        with self.assertRaisesRegex(cs.SetupError, "What I copied"):
            cs.read_source(self.path("list.gdoc", '{"url": ""}'))

    def test_missing_file_and_unknown_kind(self):
        with self.assertRaisesRegex(cs.SetupError, "could not be found"):
            cs.read_source(os.path.join(self.d, "nope.txt"))
        with self.assertRaisesRegex(cs.SetupError, "cannot be read"):
            cs.read_source(self.path("list.xyz", "x"))

    @unittest.skipUnless(sys.platform == "darwin" and os.path.exists(bc.VISION), "the Mac's own reader")
    def test_screenshot_read_by_this_computers_reader(self):
        from PIL import Image, ImageDraw, ImageFont
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 34)
        img = Image.new("RGB", (900, 120 + 60 * len(KIDS)), "white")
        g = ImageDraw.Draw(img)
        g.text((40, 30), "Class List", fill="black", font=font)
        for i, k in enumerate(KIDS, 1):
            first, last = k.split(" ", 1)
            g.text((40, 40 + 60 * i), f"{i}.", fill="black", font=font)
            g.text((120, 40 + 60 * i), first, fill="black", font=font)   # a first-name column
            g.text((460, 40 + 60 * i), last, fill="black", font=font)    # and a last-name column
        p = os.path.join(self.d, "Screenshot.png")
        img.save(p)
        self.assertEqual(cs.clean(cs.read_source(p)), KIDS)

    @unittest.skipUnless(sys.platform == "darwin" and os.path.exists(bc.VISION), "the Mac's own reader")
    def test_screenshot_of_a_class_sheet_keeps_only_the_name_columns(self):
        from PIL import Image, ImageDraw, ImageFont
        f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 26)
        img = Image.new("RGB", (1500, 80 + 52 * len(KIDS)), "white")
        g = ImageDraw.Draw(img)
        g.text((560, 20), "Sorted by First Name", fill="black", font=f)
        for i, k in enumerate(KIDS):
            first, last = k.split(" ", 1)
            y = 70 + 52 * i
            if i == 0:
                g.text((240, y), "Oldest", fill="black", font=f)
            g.text((560, y), first, fill="black", font=f)
            g.text((760, y), last, fill="black", font=f)
            g.text((1010, y), f"{i + 1}/1{i}/2019", fill="black", font=f)   # birthday column
            g.text((1200, y), f"7y {i + 1}m", fill="black", font=f)          # age column
        p = os.path.join(self.d, "sheet.png")
        img.save(p)
        self.assertEqual(cs.clean(cs.read_source(p)), KIDS)

    def test_reader_fails(self):
        p = self.path("shot.png", b"x")
        with mock.patch.object(cs.bc, "run_vision", side_effect=RuntimeError("no reader")):
            with self.assertRaisesRegex(cs.SetupError, "text reader could not read"):
                cs.read_source(p)


@unittest.skipUnless(os.path.isfile(NEW_CLASS), "tools/new_class.py is on this computer only")
class Build(unittest.TestCase):
    """The whole build, in a copy of the program in a temporary folder, so the
    class settings and the protected-names list it writes are thrown away."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.prog = os.path.join(self.d, "prog")
        os.makedirs(os.path.join(self.prog, "tools"))
        shutil.copy(NEW_CLASS, os.path.join(self.prog, "tools"))
        os.symlink(os.path.join(ROOT, "baggage_claim.py"), os.path.join(self.prog, "baggage_claim.py"))
        self.drive = os.path.join(self.d, "My Drive")
        self.desk = os.path.join(self.d, "Desktop")
        os.makedirs(self.drive)
        os.makedirs(self.desk)
        self.list = os.path.join(self.d, "check me.txt")
        with open(self.list, "w", encoding="utf-8") as f:
            f.write("\n".join(KIDS) + "\n")

    def tearDown(self):
        shutil.rmtree(self.d)

    def run_build(self, name="Grade 2 - Room 5"):
        return cs.build(self.list, name, "2", "Artwork", self.drive, self.desk,
                        new_class=os.path.join(self.prog, "tools", "new_class.py"))

    def test_one_folder_per_child_and_labels_in_both_places(self):
        r = self.run_build()
        cls = os.path.join(self.drive, "Grade 2 - Room 5")
        self.assertEqual(r["class_folder"], cls)
        self.assertEqual((r["children"], r["folders"], r["labels"]), (8, 8, 8))
        for k in KIDS:
            self.assertTrue(os.path.isdir(os.path.join(cls, k, "Artwork")))
        self.assertTrue(os.path.isdir(os.path.join(cls, "Arrivals")))
        self.assertTrue(os.path.isdir(os.path.join(cls, "Unsorted - needs a person")))
        self.assertEqual(bc.load_roster(os.path.join(cls, "Class list - one first name per line.txt")), KIDS)
        self.assertEqual(len(r["label_files"]), 2)
        for p in r["label_files"]:
            self.assertTrue(os.path.basename(p).startswith("1 — Grade 2 - Room 5 NAMES to cut out — "))
            self.assertEqual(docx_text(p), "".join(cs.label_names(KIDS)))
        with open(os.path.join(self.prog, ".private-names"), encoding="utf-8") as f:
            protected = f.read().split("\n")
        self.assertTrue(set(KIDS) <= set(protected))                # the names are protected before any push

    def test_running_twice_makes_nothing_twice(self):
        self.run_build()
        r = self.run_build()
        self.assertEqual(r["folders"], 8)
        cls = os.path.join(self.drive, "Grade 2 - Room 5")
        self.assertEqual(sorted(x for x in os.listdir(cls) if os.path.isdir(os.path.join(cls, x))),
                         sorted(KIDS + ["Arrivals", "Unsorted - needs a person"]))

    def test_a_class_name_windows_cannot_open_is_mended_not_refused(self):
        r = self.run_build('Pat and Lum Grade 1st/2nd 2025-2026: "Room" 5? ')
        self.assertEqual(os.path.basename(r["class_folder"]), "Pat and Lum Grade 1st-2nd 2025-2026- Room 5")
        self.assertEqual(r["folders"], 8)
        self.assertEqual(cs.folder_name("Grade 2 ."), "Grade 2")
        with self.assertRaisesRegex(cs.SetupError, "needs a name"):
            self.run_build(' / ')

    def test_empty_list(self):
        open(self.list, "w").close()
        with self.assertRaisesRegex(cs.SetupError, "empty"):
            self.run_build()

    def test_setup_part_missing(self):
        with self.assertRaisesRegex(cs.SetupError, "not on this computer"):
            cs.build(self.list, "X", new_class=os.path.join(self.d, "none.py"))

    def test_main_prints_counts_and_never_a_name(self):
        import contextlib
        import io
        out = io.StringIO()
        real = cs.build
        fake = lambda *a, **k: real(self.list, "Grade 2 - Room 5", "2", "Artwork", self.drive, self.desk,
                                    new_class=os.path.join(self.prog, "tools", "new_class.py"))
        with mock.patch.object(cs, "build", side_effect=fake):
            with contextlib.redirect_stdout(out):
                code = cs.main(["build", "--list", self.list, "--class-name", "Grade 2 - Room 5"])
        self.assertEqual(code, 0)
        self.assertIn("8 of 8 child folders made, 8 name labels.", out.getvalue())
        self.assertIn("The class folder is called: Grade 2 - Room 5", out.getvalue())
        for k in KIDS:
            for part in k.split():
                self.assertNotIn(part, out.getvalue())

    def test_setup_part_gives_no_class_folder(self):
        with mock.patch.object(cs.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="", stderr="")):
            with self.assertRaisesRegex(cs.SetupError, "could not be made"):
                self.run_build()

    def test_main_says_when_a_folder_is_missing_and_when_setup_fails(self):
        import contextlib
        import io
        short = {"children": 8, "folders": 7, "labels": 8, "class_folder": "x", "label_files": []}
        out = io.StringIO()
        with mock.patch.object(cs, "build", return_value=short), contextlib.redirect_stdout(out):
            self.assertEqual(cs.main(["build", "--list", self.list, "--class-name", "X"]), 1)
        self.assertIn("Some folders are missing", out.getvalue())
        err = io.StringIO()
        with mock.patch.object(cs, "build", side_effect=cs.SetupError("the class list is empty")), \
                contextlib.redirect_stderr(err):
            self.assertEqual(cs.main(["build", "--list", self.list, "--class-name", "X"]), 2)
        self.assertIn("Could not set up the class: the class list is empty", err.getvalue())


class Main(unittest.TestCase):
    def test_prepare_prints_a_count_and_never_a_name(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "l.txt")
            with open(src, "w") as f:
                f.write("\n".join(KIDS))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cs.main(["prepare", "--source", src, "--out", os.path.join(d, "o", "check.txt")])
            self.assertEqual((code, out.getvalue().strip()), (0, "8 names found."))
            with open(os.path.join(d, "o", "check.txt")) as f:
                self.assertEqual(f.read().split("\n")[:-1], KIDS)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(cs.main(["prepare", "--source", os.path.join(d, "none.txt"),
                                          "--out", os.path.join(d, "x.txt")]), 2)
            self.assertNotIn("Juniper", err.getvalue())

    def test_no_names_found(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "l.txt")
            with open(src, "w") as f:
                f.write("Class List\n\n1.\n")
            with self.assertRaisesRegex(cs.SetupError, "no names"):
                cs.prepare(src, os.path.join(d, "o.txt"))


if __name__ == "__main__":
    unittest.main()

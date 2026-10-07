"""The contract check for PDF packets.

The rule a teacher is given for a packet: the child's name TYPED in a corner of
the FIRST page of that child's work; the pages scanned after it need no name,
because a page with no name sticker goes with the page before it (October 7,
2026). A name on every page follows the rule too, and is needed when one
child's pages are not next to each other. "page X of Y" beside the name is
optional; "1/2" in a class whose grade is 1-2 is the grade, not a page number.
When a teacher follows it,
every page must land in the right child's folder: one PDF per child, holding
exactly that child's pages in the order they are in the packet, and nothing in
Unsorted. Every packet below follows the rule, so the required score is 100%.
A miss is a bug, however rare the case.

The grid is run twice: once the way the tool runs (the words inside a PDF
made on a computer are used when they name a child), and once with those
words IGNORED, so that every page, digital or scanned, is drawn and read by
this computer's own reader. Both must be 100%.

Run the whole grid:   python3 tests/packet_check.py
Run a few packets:    python3 tests/packet_check.py scanned mixed
Only one way:         python3 tests/packet_check.py --text-only   or   --reader-only
Invented names only (contract_wall NAMES). Which packet page a filed page was
is told by the page itself (make_packet.page_fingerprint), never by the reader."""
import os
import platform
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import baggage_claim as sw  # noqa: E402
from contract_wall import NAMES, FontNotFound  # noqa: E402
from make_packet import make_packet, packet_pages, fingerprints  # noqa: E402

PROJECT = "Contract"


def cases():
    out = []

    def add(name, kind, names, per_child, **kw):
        out.append({"case": f"{kind} {name}", "kind": kind, "names": names, "per_child": per_child,
                    "landscape": kw.pop("landscape", False), "grade": kw.pop("grade", None), "kw": kw})
    for kind in ("digital", "scanned"):
        for k, corner in enumerate(("tl", "tr", "bl", "br")):
            add(f"corner-{corner}", kind, NAMES[k * 2:k * 2 + 8], [1, 2, 3], corner=corner,
                numbers=corner in ("tl", "br"), seed=10 + k)
        add("25 children, 1 page each", kind, NAMES, 1, corner="tr", numbers=False, seed=21)
        add("25 children, 3 pages each, page X of Y", kind, NAMES, 3, corner="br", numbers=True, seed=22)
        add("12 children, 2 pages, 'X of Y'", kind, NAMES[5:17], 2, corner="tl", numbers=True, form="of", seed=23)
        add("25 children, 1-3 pages, 'X/Y'", kind, NAMES, [2, 1, 3], corner="bl", numbers=True, form="slash",
            seed=24)
        add("landscape", kind, NAMES[3:13], [1, 2, 3], corner="tr", numbers=True, landscape=True, seed=25)
        add("landscape, no numbers", kind, NAMES[10:20], [2, 3, 1], corner="bl", numbers=False, landscape=True,
            seed=26)
        add("mixed order", kind, NAMES[:10], [2, 3], corner="br", numbers=True, mixed=True, seed=27)
        add("mixed order, no numbers", kind, NAMES[12:22], [3, 2, 1], corner="tl", numbers=False, mixed=True,
            seed=28)
        add("every corner", kind, NAMES[:12], [1, 2, 3], corners=["tl", "tr", "bl", "br"], numbers=True, seed=29)
        # the name on the first page of each child's work only (October 7, 2026)
        add("name on the first page only, 25 children, 3 pages", kind, NAMES, 3, corner="tr", numbers=False,
            first_only=True, seed=30)
        add("name on the first page only, 1-4 pages", kind, NAMES[2:16], [3, 1, 4, 2], corner="br", numbers=False,
            first_only=True, seed=31)
        add("name on the first page only, 'page 1 of Y'", kind, NAMES[8:20], [2, 3, 1], corner="tl", numbers=True,
            first_only=True, seed=32)
        add("name on the first page only, landscape, every corner", kind, NAMES[:10], [3, 2],
            corners=["tl", "tr", "bl", "br"], numbers=False, first_only=True, landscape=True, seed=33)
        # the class's grade printed beside every name, "1/2": the grade, not "page 1 of 2" (October 7, 2026)
        add("grade 1/2 beside the name, 1 page each", kind, NAMES, 1, corner="tr", numbers=False, seed=34,
            grade=(1, 2))
        add("grade 3/4 beside the name, name on the first page only", kind, NAMES[4:16], [2, 1, 3], corner="tl",
            numbers=False, first_only=True, seed=35, grade=(3, 4))
    return out


def say(*a):
    print(*a, flush=True)


def run_case(c, work):
    pages = packet_pages(c["names"], c["per_child"], **c["kw"])
    grade = "K"
    if c.get("grade"):          # the grade beside every name that is on a page, written with a slash
        grade = "%d-%d" % c["grade"]
        for pg in pages:
            if pg["name"]:
                pg["number"], pg["form"] = c["grade"], "slash"
    path = os.path.join(work, "inbox", f"Packet {c['case']}.pdf".replace("/", "-").replace("'", ""))
    os.makedirs(os.path.dirname(path))
    try:
        make_packet(path, pages, c["kind"], c["landscape"], seed=c["kw"].get("seed", 1))
    except FontNotFound as e:
        return {"case": c["case"], "pages": len(pages), "right": 0, "problems": [], "skipped": str(e)}
    prints = fingerprints(path)
    if len(set(prints)) != len(prints):
        return {"case": c["case"], "pages": len(pages), "right": 0,
                "problems": ["the practice packet has two pages that are the same; the check cannot tell them apart"]}
    out = os.path.join(work, "out")
    os.makedirs(out)
    log = []
    res = sw.process_packet(path, NAMES, out, PROJECT, log=log.append, grade=grade)
    problems = []
    right = 0
    want = {}
    for i, pg in enumerate(pages):
        want.setdefault(pg.get("child") or pg["name"], []).append(i)
    for r in res:
        truth = pages[r["piece"] - 1].get("child") or pages[r["piece"] - 1]["name"]
        if r["status"] != "confident":
            problems.append(f"packet page {r['piece']} ({truth}) went to a person: {r['status']}, read "
                            f"{r.get('text')!r}{', ' + r['why'] if r.get('why') else ''}")
        elif r["name"] != truth:
            problems.append(f"packet page {r['piece']} of {truth} was filed under {r['name']}")
    sroot = os.path.join(out, "sorted")
    for child in NAMES:
        folder = os.path.join(sroot, sw.safe_folder(child), PROJECT)
        pdfs = sorted(f for f in os.listdir(folder) if f.lower().endswith(".pdf")) if os.path.isdir(folder) else []
        if child not in want:
            if pdfs:
                problems.append(f"{child} has no pages in the packet and was given {pdfs}")
            continue
        if len(pdfs) != 1:
            problems.append(f"{child} should have one PDF and has {len(pdfs)}")
            if not pdfs:
                continue
        got = fingerprints(os.path.join(folder, pdfs[0]))
        expect = [prints[i] for i in want[child]]
        if got == expect:
            right += len(expect)
        else:
            index = {fp: i + 1 for i, fp in enumerate(prints)}
            problems.append(f"{child}'s PDF holds packet pages {[index.get(g, '?') for g in got]}, "
                            f"should be {[i + 1 for i in want[child]]}")
            right += sum(1 for a, b in zip(got, expect) if a == b)
    udir = os.path.join(out, "unsorted")
    stray = sorted(f for f in os.listdir(udir) if f.lower().endswith(".pdf")) if os.path.isdir(udir) else []
    if stray:
        problems.append(f"{len(stray)} page(s) in Unsorted: {stray[:3]}")
    return {"case": c["case"], "pages": len(pages), "right": right, "problems": problems,
            "said": [str(x) for x in log]}


def run_grid(todo, text_layer):
    sw.PACKET_TEXT_LAYER = text_layer
    how = "text layer used" if text_layer else "text layer IGNORED, every page read by the reader"
    say(f"\n--- {how} ---")
    t0 = time.time()
    rows = []
    for c in todo:
        work = tempfile.mkdtemp(prefix="packet-")
        t1 = time.time()
        try:
            r = run_case(c, work)
        except Exception as e:
            r = {"case": c["case"], "pages": 0, "right": 0, "problems": [f"crashed: {type(e).__name__}: {e}"]}
        finally:
            shutil.rmtree(work, ignore_errors=True)
        rows.append(r)
        if r.get("skipped"):
            say(f"SKIP  {r['case']:<48}  not run: {r['skipped']}")
            continue
        ok = not r["problems"] and r["right"] == r["pages"]
        say(f"{'PASS' if ok else 'MISS'}  {r['case']:<48} {r['right']:>3}/{r['pages']:<3} "
            f"[{time.time() - t1:.0f} s]  " + "; ".join(r["problems"])[:160])
        if not ok:
            for p in r["problems"]:
                say(f"        problem: {p}")
            for line in r.get("said", []):
                say(f"        the tool said: {line}")
    sw.PACKET_TEXT_LAYER = True
    ran = [r for r in rows if not r.get("skipped")]
    passed = sum(1 for r in ran if not r["problems"] and r["right"] == r["pages"])
    pages = sum(r["pages"] for r in ran)
    right = sum(r["right"] for r in ran)
    line = (f"PACKET CHECK ({how}): {passed} of {len(ran)} packets perfect, {right} of {pages} pages right "
            f"({100.0 * right / max(1, pages):.1f}%), {time.time() - t0:.0f} seconds")
    say(line)
    return ran and passed == len(ran), line


def main(argv):
    if not sw.backend_ready():
        say("The reader is not available on this computer.")
        return 2
    try:
        sw.pdf_parts()
    except sw.PacketError as e:
        say(f"PDF packets cannot be read here: {e}")
        return 2
    say(f"computer: {platform.platform()}, Python {platform.python_version()}")
    say(f"reader: {sw.backend_name()}")
    say(sw.pdf_parts_text())
    want = [a for a in argv if not a.startswith("-")]
    todo = [c for c in cases() if not want or any(w in c["case"] for w in want)]
    ways = [True, False]
    if "--text-only" in argv:
        ways = [True]
    if "--reader-only" in argv:
        ways = [False]
    lines, all_ok = [], True
    for way in ways:
        ok, line = run_grid(todo, way)
        all_ok = all_ok and ok
        lines.append(line)
    say("")
    for line in lines:
        say(line)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

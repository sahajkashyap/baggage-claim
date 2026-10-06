"""Tests for the Mac autostart (launchd) job and the one-watcher-per-class lock.
Run:  python3 -m unittest tests.test_autostart
The launchd job file is produced by mac/autostart.sh, so those tests run only on
a Mac (they need zsh and plist semantics); the lock tests run everywhere.
No launchctl is ever called for real: a stub records what would have been run.
"""
import io
import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import baggage_claim as sw  # noqa: E402

AUTOSTART = os.path.join(ROOT, "mac", "autostart.sh")
LAUNCHER = os.path.join(ROOT, "Baggage Claim.app", "Contents", "MacOS", "Baggage Claim")
IS_MAC = sys.platform == "darwin"
LABEL = "com.sahajkashyap.baggage-claim"


def make_tool_dir(base, name="tool", with_launcher=True):
    """A pretend Baggage Claim folder: watch.sh and, optionally, the helper app."""
    tool = os.path.join(base, name)
    os.makedirs(tool)
    with open(os.path.join(tool, "watch.sh"), "w") as f:
        f.write("#!/bin/zsh\nexit 0\n")
    if with_launcher:
        macos = os.path.join(tool, "Baggage Claim.app", "Contents", "MacOS")
        os.makedirs(macos)
        launcher = os.path.join(macos, "Baggage Claim")
        with open(launcher, "w") as f:
            f.write("#!/bin/zsh\nexit 0\n")
        os.chmod(launcher, 0o755)
    return tool


def autostart(*args, env=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(["/bin/zsh", AUTOSTART, *args], capture_output=True, text=True, env=e)


@unittest.skipUnless(IS_MAC, "launchd job files are a Mac matter")
class PlistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def render(self, tool):
        r = autostart("render", tool)
        self.assertEqual(r.returncode, 0, r.stderr)
        return plistlib.loads(r.stdout.encode("utf-8")), r.stdout

    def test_plist_is_valid_and_points_at_this_folder(self):
        tool = make_tool_dir(self.tmp)
        d, raw = self.render(tool)
        self.assertEqual(d["Label"], LABEL)
        self.assertEqual(d["ProgramArguments"],
                         [os.path.join(tool, "Baggage Claim.app", "Contents", "MacOS", "Baggage Claim"),
                          "/bin/zsh", os.path.join(tool, "watch.sh")])
        self.assertEqual(d["WorkingDirectory"], tool)
        self.assertIs(d["RunAtLoad"], True)
        self.assertIs(d["KeepAlive"], True)
        self.assertEqual(d["ThrottleInterval"], 30)
        self.assertEqual(d["StandardOutPath"], os.path.join(tool, "logs", "launchd.log"))
        self.assertEqual(d["StandardErrorPath"], os.path.join(tool, "logs", "launchd.log"))
        self.assertEqual(d["EnvironmentVariables"], {"BAGGAGE_LAUNCHD": "1"})
        self.assertTrue(raw.startswith('<?xml version="1.0"'))
        self.assertTrue(all(os.path.isabs(p) for p in d["ProgramArguments"]))

    def test_folder_name_with_ampersand_and_spaces_survives(self):
        tool = make_tool_dir(self.tmp, "Maya & Jonah <class> 2026")
        d, raw = self.render(tool)
        self.assertEqual(d["WorkingDirectory"], tool)
        self.assertEqual(d["ProgramArguments"][2], os.path.join(tool, "watch.sh"))
        self.assertIn("&amp;", raw)
        self.assertIn("&lt;class&gt;", raw)

    def test_without_helper_app_runs_the_script_directly(self):
        tool = make_tool_dir(self.tmp, with_launcher=False)
        d, _ = self.render(tool)
        self.assertEqual(d["ProgramArguments"], ["/bin/zsh", os.path.join(tool, "watch.sh")])
        self.assertIs(d["KeepAlive"], True)

    def test_relative_folder_is_made_absolute(self):
        tool = make_tool_dir(self.tmp)
        r = subprocess.run(["/bin/zsh", AUTOSTART, "render", "tool"], capture_output=True, text=True, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        d = plistlib.loads(r.stdout.encode("utf-8"))
        self.assertEqual(d["WorkingDirectory"], os.path.realpath(tool))

    def test_unknown_folder_fails_plainly(self):
        r = autostart("render", os.path.join(self.tmp, "nowhere"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no such folder", r.stderr)


@unittest.skipUnless(IS_MAC, "launchd job files are a Mac matter")
class InstallRemoveTests(unittest.TestCase):
    """install/remove with a stub launchctl that only records its arguments."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.agents = os.path.join(self.tmp, "LaunchAgents")
        self.calls = os.path.join(self.tmp, "launchctl-calls.txt")
        self.stub = os.path.join(self.tmp, "launchctl")
        with open(self.stub, "w") as f:
            # "print" answers "not loaded" until a bootstrap has been recorded
            f.write('#!/bin/zsh\necho "$@" >> "%s"\n' % self.calls)
            f.write('if [ "$1" = print ]; then grep -q "^bootstrap" "%s" || exit 113; '
                    'echo "\tstate = running"; echo "\tpid = 4242"; fi\nexit 0\n' % self.calls)
        os.chmod(self.stub, 0o755)
        self.env = {"BAGGAGE_LAUNCH_AGENTS_DIR": self.agents, "BAGGAGE_LAUNCHCTL": self.stub, "BAGGAGE_TEST": "1"}
        self.plist = os.path.join(self.agents, LABEL + ".plist")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def calls_made(self):
        with open(self.calls) as f:
            return [line.strip() for line in f if line.strip()]

    def test_install_writes_plist_and_bootstraps_it(self):
        tool = make_tool_dir(self.tmp)
        r = autostart("install", tool, env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(self.plist))
        with open(self.plist, "rb") as f:
            d = plistlib.load(f)
        self.assertEqual(d["WorkingDirectory"], tool)
        self.assertIs(d["KeepAlive"], True)
        uid = os.getuid()
        calls = self.calls_made()
        self.assertIn(f"enable gui/{uid}/{LABEL}", calls)
        self.assertIn(f"bootstrap gui/{uid} {self.plist}", calls)
        self.assertIn("starts with the Mac", r.stdout)
        self.assertTrue(os.path.isdir(os.path.join(tool, "logs")))

    def test_install_refuses_a_folder_that_is_not_the_tool(self):
        not_tool = os.path.join(self.tmp, "somewhere")
        os.makedirs(not_tool)
        r = autostart("install", not_tool, env=self.env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not the Baggage Claim folder", r.stderr)
        self.assertFalse(os.path.exists(self.plist))

    def test_remove_boots_out_and_deletes_plist(self):
        tool = make_tool_dir(self.tmp)
        autostart("install", tool, env=self.env)
        r = autostart("remove", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.plist))
        self.assertIn(f"bootout gui/{os.getuid()}/{LABEL}", self.calls_made())
        self.assertIn("no longer start at login", r.stdout)

    def test_loaded_reports_truthfully(self):
        self.assertNotEqual(autostart("loaded", env=self.env).returncode, 0)
        autostart("install", make_tool_dir(self.tmp), env=self.env)
        self.assertEqual(autostart("loaded", env=self.env).returncode, 0)

    def test_status_says_what_is_running_and_reads_the_log(self):
        tool = make_tool_dir(self.tmp)
        r = autostart("status", tool, env=self.env)
        self.assertIn("Starts with the Mac: NO", r.stdout)
        self.assertIn("Log: none yet", r.stdout)
        autostart("install", tool, env=self.env)
        with open(os.path.join(tool, "logs", "watch.log"), "w") as f:
            f.write("Sep 26 01:40 PM: 12 pieces, 11 filed, 1 to unsorted\n")
        r = autostart("status", tool, env=self.env)
        self.assertIn("Starts with the Mac: yes", r.stdout)
        self.assertIn("process 4242", r.stdout)
        self.assertIn("Log last changed", r.stdout)
        self.assertIn("12 pieces, 11 filed", r.stdout)

    def test_status_flags_a_folder_permission_problem(self):
        tool = make_tool_dir(self.tmp)
        os.makedirs(os.path.join(tool, "logs"))
        with open(os.path.join(tool, "logs", "watch.log"), "w") as f:
            f.write("Sep 26 01:40 PM: macOS is not letting this program read the inbox folder. Folder: /x\n")
        r = autostart("status", tool, env=self.env)
        self.assertIn("PERMISSION NEEDED", r.stdout)
        self.assertNotEqual(r.returncode, 0)


@unittest.skipUnless(IS_MAC, "watch.sh is the Mac entry point")
class WatchScriptTests(unittest.TestCase):
    """watch.sh must explain itself in the log instead of exiting silently."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        shutil.copy(os.path.join(ROOT, "watch.sh"), self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_watch(self, env_extra=None):
        env = dict(os.environ, BAGGAGE_LAUNCHD="")      # never sleep in tests
        env.update(env_extra or {})
        return subprocess.run(["/bin/zsh", os.path.join(self.tmp, "watch.sh")], capture_output=True, text=True,
                              env=env, timeout=60)

    def test_missing_settings_is_explained(self):
        vision = os.path.join(self.tmp, "vision")
        with open(vision, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(vision, 0o755)
        r = self.run_watch()
        self.assertEqual(r.returncode, 1)
        self.assertIn("nothing to watch", r.stdout)
        with open(os.path.join(self.tmp, "logs", "watch.log")) as f:
            self.assertIn("No settings.local.json", f.read())

    def test_missing_compiler_is_explained(self):
        # a Mac without Xcode: /usr/bin/swiftc exists but only prints an error
        with open(os.path.join(self.tmp, "vision.swift"), "w") as f:
            f.write("// not compiled in this test\n")
        fakebin = os.path.join(self.tmp, "fakebin")
        os.makedirs(fakebin)
        with open(os.path.join(fakebin, "swiftc"), "w") as f:
            f.write('#!/bin/sh\necho "xcode-select: error: no developer tools were found" >&2\nexit 1\n')
        os.chmod(os.path.join(fakebin, "swiftc"), 0o755)
        r = self.run_watch({"PATH": fakebin + ":/usr/bin:/bin"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("name reader is not built", r.stdout)
        with open(os.path.join(self.tmp, "logs", "watch.log")) as f:
            self.assertIn("xcode-select --install", f.read())


@unittest.skipUnless(IS_MAC and os.path.exists(LAUNCHER), "helper app is built by Setup.command on a Mac")
class LauncherAppTests(unittest.TestCase):
    """The compiled helper passes the child's exit code and signals through."""

    def test_child_exit_code_is_passed_on(self):
        self.assertEqual(subprocess.run([LAUNCHER, "/bin/sh", "-c", "exit 3"]).returncode, 3)
        r = subprocess.run([LAUNCHER, "/bin/echo", "hello"], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "hello"))

    def test_stop_signal_reaches_the_child(self):
        import signal
        import time
        p = subprocess.Popen([LAUNCHER, "/bin/sleep", "300"])
        time.sleep(0.8)
        p.send_signal(signal.SIGTERM)
        code = p.wait(timeout=10)
        self.assertEqual(code, 128 + signal.SIGTERM)
        time.sleep(0.3)
        left = subprocess.run(["pgrep", "-f", "^/bin/sleep 300$"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(left, "", "the child kept running after the launcher was told to stop")


def record(what):
    """A line for the build's own record (tests-on-build-machine.txt in the
    bundle). Nobody here can run Windows, so what Windows did is printed."""
    sys.stderr.write(f"\nEVIDENCE[watcher] {sys.platform}: {what}\n")
    sys.stderr.flush()


HOLD_THE_LOCK = ("import sys, time; sys.path.insert(0, %r); import baggage_claim as bc; "
                 "f, _ = bc.claim_watch_lock(%r); print('held', flush=True); time.sleep(60)")


class WatchLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.lock = os.path.join(self.tmp, "logs", "watch.log.lock")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def written_in_the_lock(self, held):
        """The process number in the lock file while `held` holds the lock.
        A Mac lets anybody read the file, so it is read the way a person or a
        second watcher would, through a handle of its own. Windows refuses
        every other handle while the lock is held (PermissionError, in the
        build of Sep 28 2026), so there it is read through the holder's own."""
        held.seek(0)
        own = held.read().strip()
        if not sw.IS_WIN:
            with open(self.lock) as g:
                self.assertEqual(g.read().strip(), own)
        return own

    def left_in_the_lock(self):
        """The same once the holder has let go: every computer can read it then."""
        with open(self.lock) as g:
            return g.read().strip()

    def test_lock_path_follows_the_log_file(self):
        log = os.path.join(self.tmp, "logs", "watch.log")
        self.assertEqual(sw.watch_lock_path(log), log + ".lock")
        # a log named from the folder the watcher was started in gets the whole
        # path, so a second watcher started from anywhere meets the same lock
        self.assertEqual(sw.watch_lock_path(os.path.join("logs", "watch.log")),
                         os.path.join(os.getcwd(), "logs", "watch.log.lock"))
        if not sw.IS_WIN:       # on Windows a path that starts with a slash gets the drive letter put before it
            self.assertEqual(sw.watch_lock_path("/a/b/logs/watch.log"), "/a/b/logs/watch.log.lock")
        self.assertEqual(sw.watch_lock_path(None, "/out"), os.path.join("/out", ".watch-lock"))
        self.assertEqual(sw.watch_lock_path(None, None), os.path.join(sw.HERE, ".watch-lock"))

    def test_first_watcher_gets_the_lock_and_writes_its_pid(self):
        f, other = sw.claim_watch_lock(self.lock)
        try:
            self.assertIsNotNone(f)
            self.assertIsNone(other)
            self.assertEqual(self.written_in_the_lock(f), str(os.getpid()))
        finally:
            f.close()
        self.assertEqual(self.left_in_the_lock(), str(os.getpid()), "it reached the disk, not only the open file")

    def test_second_watcher_is_refused_while_first_holds_it(self):
        first, _ = sw.claim_watch_lock(self.lock)
        try:
            second, other = sw.claim_watch_lock(self.lock)
            self.assertIsNone(second)
            if not sw.IS_WIN:
                self.assertEqual(other, str(os.getpid()))
        finally:
            first.close()

    def test_second_watcher_in_another_process_is_refused(self):
        holder = subprocess.Popen(
            [sys.executable, "-c",
             "import sys, time; sys.path.insert(0, %r); import baggage_claim as bc; "
             "f, _ = bc.claim_watch_lock(%r); print('held', flush=True); time.sleep(30)" % (ROOT, self.lock)],
            stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            second, other = sw.claim_watch_lock(self.lock)
            self.assertIsNone(second)
            if not sw.IS_WIN:
                self.assertEqual(other, str(holder.pid))
        finally:
            holder.kill()
            holder.wait()
            holder.stdout.close()

    def test_stale_lock_from_a_dead_watcher_is_taken_over(self):
        os.makedirs(os.path.dirname(self.lock))
        with open(self.lock, "w") as g:
            g.write("999999")          # a watcher that is long gone; nothing holds the lock
        f, other = sw.claim_watch_lock(self.lock)
        try:
            self.assertIsNotNone(f)
            self.assertIsNone(other)
            self.assertEqual(self.written_in_the_lock(f), str(os.getpid()))
            again, _ = sw.claim_watch_lock(self.lock)
            self.assertIsNone(again, "taken over for good: the next watcher is refused")
        finally:
            f.close()
        self.assertEqual(self.left_in_the_lock(), str(os.getpid()), "the dead watcher's number is gone")

    def test_lock_is_released_when_the_holder_dies(self):
        holder = subprocess.Popen(
            [sys.executable, "-c",
             "import sys, time; sys.path.insert(0, %r); import baggage_claim as bc; "
             "f, _ = bc.claim_watch_lock(%r); print('held', flush=True); time.sleep(30)" % (ROOT, self.lock)],
            stdout=subprocess.PIPE, text=True)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        holder.kill()
        holder.wait()
        holder.stdout.close()
        f, other = sw.claim_watch_lock(self.lock)
        self.assertIsNotNone(f)
        f.close()

    def test_watch_mode_second_instance_says_so_and_exits(self):
        first, _ = sw.claim_watch_lock(self.lock)
        try:
            inbox = os.path.join(self.tmp, "inbox")
            os.makedirs(inbox)
            roster = os.path.join(self.tmp, "roster.txt")
            with open(roster, "w") as g:
                g.write("Maya Torres\nJonah Lum\n")
            out = io.StringIO()
            with redirect_stdout(out):
                code = sw.main(["--watch", "--log", os.path.join(self.tmp, "logs", "watch.log"),
                                "--inbox", inbox, "--roster", roster, "--out", self.tmp])
            sys.stdout = sys.__stdout__       # main installs a tee when --log is given
            self.assertEqual(code, 0)
            with open(os.path.join(self.tmp, "logs", "watch.log")) as g:
                text = g.read()
            self.assertIn("another control tower is already running for this class", text)
            self.assertIn("so this one is closing. Two control towers would fight over the same photos.", text)
            if sw.IS_WIN:
                # Windows will not let a second watcher read the first one's
                # number out of the locked file, so the line is said without it
                self.assertNotIn("(process", text)
            else:
                self.assertIn(f"(process {os.getpid()})", text)
            self.assertNotIn("Traceback", text)
            self.assertNotIn("control tower for ", text, "the second watcher never started to watch")
        finally:
            first.close()

    def test_a_second_watcher_started_as_a_program_of_its_own_closes_with_its_line(self):
        # The way it happens in a classroom: one watcher is running (started
        # at login), and somebody double-clicks Start Watcher again. Two real
        # programs, not two calls inside one.
        holder = subprocess.Popen([sys.executable, "-c", HOLD_THE_LOCK % (ROOT, self.lock)],
                                  stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            inbox = os.path.join(self.tmp, "inbox")
            os.makedirs(inbox)
            roster = os.path.join(self.tmp, "roster.txt")
            with open(roster, "w") as g:
                g.write("Maya Torres\nJonah Lum\n")
            log = os.path.join(self.tmp, "logs", "watch.log")
            try:
                second = subprocess.run(
                    [sys.executable, os.path.join(ROOT, "baggage_claim.py"), "--watch", "--log", log,
                     "--inbox", inbox, "--roster", roster, "--out", self.tmp],
                    capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired as e:
                record(f"the second watcher did NOT close; it was still running after 120 seconds and said "
                       f"{e.stdout!r} {e.stderr!r}")
                self.fail("a second watcher kept running beside the first")
            with open(log) as g:
                text = g.read()
            record(f"second watcher as a program of its own: exit code {second.returncode}, "
                   f"log {text!r}, errors {second.stderr[-300:]!r}")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("another control tower is already running for this class", text)
            self.assertIn("so this one is closing.", text)
            self.assertIn("another control tower is already running for this class", second.stdout)
            self.assertNotIn("control tower for ", text)
            self.assertNotIn("Traceback", text + second.stderr)
            if not sw.IS_WIN:
                self.assertIn(f"(process {holder.pid})", text)
            self.assertIsNone(holder.poll(), "the first watcher is still running")
        finally:
            holder.kill()
            holder.wait()
            holder.stdout.close()
        # and the moment the first one is gone, the lock it left is taken over
        f, other = sw.claim_watch_lock(self.lock)
        try:
            self.assertIsNotNone(f, "a lock left by a watcher that is gone must not keep the next one out")
            self.assertEqual(self.written_in_the_lock(f), str(os.getpid()))
        finally:
            f.close()

    @unittest.skipUnless(sys.platform == "win32", "prints what Windows itself does with the lock file, for the "
                                                  "build's record; the tests above cover every computer")
    def test_on_windows_the_record_of_what_the_lock_did(self):
        f, other = sw.claim_watch_lock(self.lock)
        self.assertIsNotNone(f, "the first watcher on a Windows PC gets the lock, so the watcher starts")
        try:
            record(f"first claim: got the lock, other={other!r}, holder reads {self.written_in_the_lock(f)!r} "
                   f"through its own handle")
            try:
                with open(self.lock) as g:
                    seen = f"read {g.read()!r}"
            except OSError as e:
                seen = f"was refused: {type(e).__name__} errno={e.errno} winerror={getattr(e, 'winerror', None)}"
            record(f"while the lock is held, a second handle {seen}")
            second, other = sw.claim_watch_lock(self.lock)
            record(f"while the lock is held, a second claim got lock={second!r} other={other!r}")
            self.assertIsNone(second, "a second watcher on the same PC is refused")
        finally:
            f.close()
        record(f"after the holder closed, the file reads {self.left_in_the_lock()!r}")
        self.assertEqual(self.left_in_the_lock(), str(os.getpid()))
        holder = subprocess.Popen([sys.executable, "-c", HOLD_THE_LOCK % (ROOT, self.lock)],
                                  stdout=subprocess.PIPE, text=True)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        refused, _ = sw.claim_watch_lock(self.lock)
        holder.kill()
        holder.wait()
        holder.stdout.close()
        taken, _ = sw.claim_watch_lock(self.lock)
        record(f"a watcher in another process (number {holder.pid}): while it ran, a claim got {refused!r}; "
               f"after it was killed, a claim got {'the lock' if taken else taken!r}"
               + (f" and wrote {self.written_in_the_lock(taken)!r}" if taken else ""))
        if taken:
            taken.close()
        self.assertIsNone(refused)
        self.assertIsNotNone(taken, "a lock left by a dead watcher is taken over on Windows")
        # Not used by the program today; printed so that a later change can be
        # reasoned from this record and not guessed. If the locked byte sat far
        # past the end of the file, could a second watcher read the number?
        try:
            import msvcrt
            probe = os.path.join(self.tmp, "probe.lock")
            with open(probe, "a+", encoding="utf-8") as p:
                p.write("12345")
                p.flush()
                os.lseek(p.fileno(), 1 << 30, os.SEEK_SET)
                msvcrt.locking(p.fileno(), msvcrt.LK_NBLCK, 1)
                try:
                    with open(probe) as g:
                        far = f"a second handle read {g.read()!r}"
                except OSError as e:
                    far = f"a second handle was refused: {type(e).__name__} errno={e.errno}"
                try:
                    with open(probe, "a+") as g:
                        os.lseek(g.fileno(), 1 << 30, os.SEEK_SET)
                        msvcrt.locking(g.fileno(), msvcrt.LK_NBLCK, 1)
                    far += "; a second lock on the same byte was GRANTED"
                except OSError as e:
                    far += f"; a second lock on the same byte was refused (errno={e.errno})"
            record(f"probe, lock on a byte 1 GB past the start: {far}")
        except Exception as e:      # the probe is for the record only and must never fail the build
            record(f"probe could not run: {type(e).__name__}: {e}")


WATCHER_ENTRY = os.path.join(ROOT, "watcher_entry.py")
PROGRAM = os.path.join(ROOT, "baggage_claim.py")
# What a program with no window looks like to Python, on any computer: there
# is nothing where its output would go.
NO_CONSOLE = "import sys; sys.stdout = sys.__stdout__ = sys.stderr = sys.__stderr__ = None; "


class WatcherWithNoWindowTests(unittest.TestCase):
    """On a Windows PC the watcher runs with no window (BaggageClaimWatcher.exe,
    or pythonw for a copy installed from the source). A program with no window
    has no console, and Python then has None in place of sys.__stdout__. The
    watcher wrote every line to the console first and to the log second, so it
    stopped at its first line with nothing in the log. Nobody saw it: every
    test, and every Mac, has a console.
    An invented class in a temporary folder; no photo is sorted."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.cls = os.path.join(self.tmp, "Drive", "Room 3")
        self.tool = os.path.join(self.tmp, "tool")
        os.makedirs(os.path.join(self.cls, "Wall Inbox"))
        os.makedirs(self.tool)
        with open(os.path.join(self.cls, "Class list.txt"), "w", encoding="utf-8") as f:
            f.write("Maya Torres\nJonah Lum\n")
        self.settings = os.path.join(self.tool, "settings.local.json")
        with open(self.settings, "w", encoding="utf-8") as f:
            json.dump({"inbox": os.path.join(self.cls, "Wall Inbox"), "sorted": self.cls,
                       "unsorted": os.path.join(self.cls, "Unsorted - needs a person"),
                       "roster": os.path.join(self.cls, "Class list.txt"), "out": self.tool,
                       "project": "Self-Portrait", "grade": "K", "interval": 1, "priority": 50}, f)
        self.log = os.path.join(self.tool, "logs", "watch.log")
        self.running = []

    def tearDown(self):
        for p in self.running:
            if p.poll() is None:
                p.kill()
            p.wait()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def said(self):
        try:
            with open(self.log, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    def start(self, command, seconds=90):
        """Start a watcher and wait until its log says it is watching, or it
        has stopped, or the time is up. Returns (what the log says, exit code
        or None while it is still running)."""
        p = subprocess.Popen(command, cwd=self.tmp)
        self.running.append(p)
        until = time.time() + seconds
        while time.time() < until and p.poll() is None and "control tower for " not in self.said():
            time.sleep(0.2)
        return self.said(), p.poll()

    def as_the_task_at_login_starts_it(self, python, before=""):
        # install-windows.ps1: pythonw baggage_claim.py --watch --settings ... --log ...
        return [python, "-c", before + "import runpy; sys.argv = %r; runpy.run_path(%r, run_name='__main__')"
                % ([PROGRAM, "--watch", "--settings", self.settings, "--log", self.log], PROGRAM)]

    def as_the_program_with_no_window_starts_it(self, python, before=""):
        # BaggageClaimWatcher.exe is watcher_entry.py, with the folder the
        # program sits in as the place of the settings file and the log
        return [python, "-c", before + "import runpy; sys.path.insert(0, %r); import baggage_claim as bc; bc.HERE = %r; "
                "runpy.run_path(%r, run_name='__main__')" % (ROOT, self.tool, WATCHER_ENTRY)]

    def watching(self, text, code, how):
        record(f"{how}: exit code {code} (None means still running, as it should be); the log has "
               f"{len(text.splitlines())} lines, and of watching or of trouble it says "
               f"{[ln[:200] for ln in text.splitlines() if 'control tower for ' in ln or 'rror' in ln or 'Traceback' in ln][:6]}")
        self.assertIn("control tower for " + os.path.join(self.cls, "Wall Inbox"), text, how)
        self.assertIsNone(code, f"{how}: the watcher stopped")
        self.assertNotIn("watcher error", text)
        self.assertNotIn("Traceback", text)

    def test_a_watcher_with_no_console_writes_its_log_and_watches(self):
        text, code = self.start(self.as_the_task_at_login_starts_it(sys.executable, NO_CONSOLE + "import sys; "))
        self.watching(text, code, "the program itself, with nothing where a console would be")

    def test_the_watcher_with_no_window_writes_its_log_and_watches(self):
        text, code = self.start(self.as_the_program_with_no_window_starts_it(sys.executable, NO_CONSOLE))
        self.watching(text, code, "watcher_entry.py, with nothing where a console would be")

    def test_a_second_watcher_with_no_window_closes_with_its_line_in_the_log(self):
        first_said, code = self.start(self.as_the_program_with_no_window_starts_it(sys.executable, NO_CONSOLE))
        self.watching(first_said, code, "the first watcher")
        second = subprocess.run(self.as_the_program_with_no_window_starts_it(sys.executable, NO_CONSOLE),
                                cwd=self.tmp, timeout=120)
        text = self.said()
        record(f"a second watcher with no window: exit code {second.returncode}; the log then says "
               f"{[ln[:160] for ln in text.splitlines() if 'another watcher' in ln]}")
        self.assertEqual(second.returncode, 0)
        self.assertEqual(text.count("another control tower is already running for this class"), 1, text)
        self.assertIn("so this one is closing. Two control towers would fight over the same photos.", text)
        self.assertEqual(text.count("control tower for " + os.path.join(self.cls, "Wall Inbox")), 1, "one watcher, not two")
        self.assertIsNone(self.running[0].poll(), "the first watcher is still running")

    def test_with_no_settings_file_the_watcher_with_no_window_says_so_in_the_log_and_closes(self):
        os.remove(self.settings)
        p = subprocess.run(self.as_the_program_with_no_window_starts_it(sys.executable, NO_CONSOLE),
                           cwd=self.tmp, timeout=120)
        self.assertEqual(p.returncode, 1)
        self.assertIn("No settings.local.json next to the program; nothing to watch.", self.said())

    def test_inside_this_program_too_a_log_is_written_when_there_is_no_console(self):
        kept = (sys.stdout, sys.__stdout__)
        try:
            sys.stdout = sys.__stdout__ = None
            code = sw.main(["--log", self.log, "--inbox", os.path.join(self.cls, "Wall Inbox"),
                            "--roster", os.path.join(self.cls, "Class list.txt"), "--out", self.tool])
            sys.stdout.flush()
        finally:
            sys.stdout, sys.__stdout__ = kept
        self.assertEqual(code, 0)
        self.assertIn("0 pieces: 0 filed, 0 in unsorted/", self.said())

    def test_the_watcher_with_no_window_gives_python_somewhere_to_write(self):
        sys.path.insert(0, ROOT)
        import watcher_entry
        kept = (sys.stdout, sys.__stdout__, sys.stderr, sys.__stderr__)
        made = []
        try:
            sys.stdout = sys.__stdout__ = sys.stderr = sys.__stderr__ = None
            watcher_entry.no_console_is_fine()
            made = [sys.stdout, sys.__stdout__, sys.stderr, sys.__stderr__]
            for stream in made:
                stream.write("a line nobody reads\n")
                stream.flush()
        finally:
            sys.stdout, sys.__stdout__, sys.stderr, sys.__stderr__ = kept
            for stream in made:
                stream.close()
        self.assertEqual(len(made), 4)
        self.assertIs(made[0], made[1])
        self.assertIs(made[2], made[3])
        # and a program that has a console keeps it
        watcher_entry.no_console_is_fine()
        self.assertEqual((sys.stdout, sys.__stdout__, sys.stderr, sys.__stderr__), kept)

    def test_a_watcher_that_has_a_console_still_writes_to_both(self):
        p = subprocess.Popen(self.as_the_task_at_login_starts_it(sys.executable, "import sys; "), cwd=self.tmp,
                             stdout=subprocess.PIPE, text=True)
        self.running.append(p)
        try:
            first = p.stdout.readline()
        finally:
            p.kill()
            p.wait()
            p.stdout.close()
        self.assertIn("control tower for " + os.path.join(self.cls, "Wall Inbox"), first)
        self.assertIn("control tower for " + os.path.join(self.cls, "Wall Inbox"), self.said())

    @unittest.skipUnless(sys.platform == "win32", "the real thing, pythonw.exe on a real Windows PC, for the "
                                                  "build's record; the tests above cover every computer")
    def test_on_windows_the_record_of_a_watcher_started_with_no_window(self):
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            record(f"there is no pythonw.exe beside {sys.executable}, so the watcher with no window was not tried")
            self.skipTest("no pythonw.exe on this machine")
        seen = subprocess.run([pythonw, "-c", "import sys; open(%r, 'w').write(repr((sys.stdout, sys.__stdout__, "
                               "sys.stderr, sys.__stderr__)))" % os.path.join(self.tmp, "seen.txt")], timeout=120)
        try:
            with open(os.path.join(self.tmp, "seen.txt")) as f:
                record(f"under pythonw.exe, (sys.stdout, sys.__stdout__, sys.stderr, sys.__stderr__) are "
                       f"{f.read()} (exit code {seen.returncode})")
        except OSError as e:
            record(f"pythonw.exe could not say what it has for a console (exit code {seen.returncode}): {e}")
        text, code = self.start(self.as_the_task_at_login_starts_it(pythonw, "import sys; "))
        self.watching(text, code, "pythonw.exe baggage_claim.py --watch, as the task at login starts it")
        self.running[-1].kill()
        self.running[-1].wait()
        os.remove(self.log)
        text, code = self.start(self.as_the_program_with_no_window_starts_it(pythonw, "import sys; "))
        self.watching(text, code, "pythonw.exe and watcher_entry.py, as BaggageClaimWatcher.exe starts")


if __name__ == "__main__":
    unittest.main()

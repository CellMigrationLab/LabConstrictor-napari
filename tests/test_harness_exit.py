"""The exit of a test script (`_paths._leave`, which replaces sys.exit): the exit code still carries the verdict. A script that
fails exits non-zero, a message exits 1, a clean exit is 0, an uncaught exception keeps its traceback and exits 1, and what
was printed is not lost."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import qtpy

HERE = Path(__file__).resolve().parent
# the same rule as `_paths`: PyQt always, PySide6 only on Python < 3.12 (PySide6 6.12.0 loses a reference to None per void Qt call there)
LEAVES_AT_ONCE = qtpy.API_NAME.startswith("PyQt") or sys.version_info < (3, 12)


def run(body: str) -> subprocess.CompletedProcess[str]:
    """Run `body` in a fresh interpreter that imported _paths first, like every test script."""
    code = "import sys\nsys.path.insert(0, %r)\nimport _paths\nprint('printed first', flush=True)\n%s\n" % (
        str(HERE),
        body,
    )
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=HERE)


class Leave(unittest.TestCase):
    def test_exit_zero(self) -> None:
        done = run("sys.exit(0)")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("printed first", done.stdout)

    def test_exit_none_is_success(self) -> None:
        self.assertEqual(run("sys.exit()").returncode, 0)

    def test_a_failing_script_exits_non_zero(self) -> None:
        self.assertEqual(run("sys.exit(1)").returncode, 1)
        self.assertEqual(run("sys.exit(3)").returncode, 3)

    def test_a_message_exits_one_and_is_shown(self) -> None:
        done = run("sys.exit('went wrong')")
        self.assertEqual(done.returncode, 1)
        self.assertIn("went wrong", done.stderr)

    def test_an_uncaught_exception_still_fails_with_its_traceback(self) -> None:
        done = run("raise ValueError('boom')")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("ValueError: boom", done.stderr)

    @unittest.skipUnless(LEAVES_AT_ONCE, "PySide6 on Python 3.12+ keeps the normal exit")
    def test_the_exit_is_immediate_not_through_the_exit_handlers(self) -> None:
        done = run("import atexit\natexit.register(lambda: print('handler ran'))\nsys.exit(0)")
        self.assertEqual(done.returncode, 0)
        self.assertNotIn("handler ran", done.stdout)

    @unittest.skipIf(LEAVES_AT_ONCE, "a PyQt binding, or PySide6 on Python < 3.12, uses _leave")
    def test_a_binding_without_the_problem_exits_normally_through_the_exit_handlers(self) -> None:
        done = run("import atexit\natexit.register(lambda: print('handler ran'))\nsys.exit(0)")
        self.assertEqual(done.returncode, 0)
        self.assertIn("handler ran", done.stdout)

    def test_the_rule_matches_the_harness(self) -> None:
        done = run("print('leaves', sys.exit.__name__ == '_leave')")
        self.assertIn("leaves %s" % LEAVES_AT_ONCE, done.stdout)


class LeaveWaitsForPrune(unittest.TestCase):
    """A `prune` subprocess of the widget is watched by a thread. The process must not end while that thread is inside CreateProcess
    (Windows: access violation after the verdict, CI run 38414096255) or while `prune` still runs: `_leave` and the normal exit wait for it.
    """

    def prune_script(self, tail: str) -> tuple[Path, subprocess.CompletedProcess[str]]:
        marker = Path(tempfile.mkdtemp(prefix="lc_exit_prune_")) / "prune_finished"
        child = "import pathlib, time; time.sleep(1.0); pathlib.Path(%r).write_text('x')" % str(
            marker
        )  # the work `prune` does
        body = (
            "import os\n"
            "from napari_labconstrictor import _retention\n"
            "_retention.prune_argv = lambda python: [sys.executable, '-c', %r]\n"
            "thread = _retention.start_prune(sys.executable, {'features': [_retention.PRUNE_FEATURE]})\n"
            "print('started', thread is not None, flush=True)\n" % child
        ) + tail.replace("MARKER", repr(str(marker)))
        return marker, run(body)

    def test_the_exit_waits_for_a_running_prune_and_keeps_the_verdict(self) -> None:
        marker, done = self.prune_script(
            "real_exit = os._exit\n"
            "def at_exit(code):\n"
            "    print('at exit: watcher alive', thread.is_alive(), 'prune finished', os.path.exists(MARKER), flush=True)\n"
            "    real_exit(code)\n"
            "os._exit = at_exit\n"
            "sys.exit(0)\n"
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("started True", done.stdout)
        self.assertTrue(marker.exists(), "the process ended before prune finished")
        if LEAVES_AT_ONCE:
            self.assertIn("at exit: watcher alive False prune finished True", done.stdout)

    def test_a_failing_verdict_is_kept_while_waiting(self) -> None:
        marker, done = self.prune_script("sys.exit(3)\n")
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertTrue(marker.exists(), "the process ended before prune finished")

    def test_the_normal_exit_waits_too(self) -> None:
        marker, done = self.prune_script("")  # no sys.exit at all: the interpreter ends by itself
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(marker.exists(), "the process ended before prune finished")


if __name__ == "__main__":
    unittest.main()

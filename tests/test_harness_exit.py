"""The exit of a test script (`_paths._leave`, which replaces sys.exit): the exit code still carries the verdict. A script that
fails exits non-zero, a message exits 1, a clean exit is 0, an uncaught exception keeps its traceback and exits 1, and what
was printed is not lost."""

import subprocess
import sys
import unittest
from pathlib import Path

import qtpy

HERE = Path(__file__).resolve().parent


def run(body):
    """Run `body` in a fresh interpreter that imported _paths first, like every test script."""
    code = "import sys\nsys.path.insert(0, %r)\nimport _paths\nprint('printed first', flush=True)\n%s\n" % (
        str(HERE),
        body,
    )
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=HERE)


class Leave(unittest.TestCase):
    def test_exit_zero(self):
        done = run("sys.exit(0)")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("printed first", done.stdout)

    def test_exit_none_is_success(self):
        self.assertEqual(run("sys.exit()").returncode, 0)

    def test_a_failing_script_exits_non_zero(self):
        self.assertEqual(run("sys.exit(1)").returncode, 1)
        self.assertEqual(run("sys.exit(3)").returncode, 3)

    def test_a_message_exits_one_and_is_shown(self):
        done = run("sys.exit('went wrong')")
        self.assertEqual(done.returncode, 1)
        self.assertIn("went wrong", done.stderr)

    def test_an_uncaught_exception_still_fails_with_its_traceback(self):
        done = run("raise ValueError('boom')")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("ValueError: boom", done.stderr)

    @unittest.skipUnless(qtpy.API_NAME.startswith("PyQt"), "PySide6 keeps the normal exit")
    def test_the_exit_is_immediate_not_through_the_exit_handlers(self):
        done = run("import atexit\natexit.register(lambda: print('handler ran'))\nsys.exit(0)")
        self.assertEqual(done.returncode, 0)
        self.assertNotIn("handler ran", done.stdout)

    @unittest.skipIf(qtpy.API_NAME.startswith("PyQt"), "a PyQt binding uses _leave")
    def test_a_non_pyqt_binding_exits_normally_through_the_exit_handlers(self):
        done = run("import atexit\natexit.register(lambda: print('handler ran'))\nsys.exit(0)")
        self.assertEqual(done.returncode, 0)
        self.assertIn("handler ran", done.stdout)


if __name__ == "__main__":
    unittest.main()

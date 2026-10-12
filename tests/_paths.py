"""Import first in every test. Gives the run a private registry (never ~/.labconstrictor) with the example app
`labconstrictor_tools.examples.synthetic` registered against the interpreter running the tests.

Needs: pip install labconstrictor-tools  (+ this package with one Qt6 extra: ".[test-pyqt6]" or ".[test-pyside6]"). Display: xvfb-run on Linux CI.
"""

import faulthandler
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import qtpy

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "evidence"
EVIDENCE.mkdir(exist_ok=True)  # screenshots and reports (git-ignored)
sys.path.insert(0, str(ROOT))

HOME = Path(tempfile.mkdtemp(prefix="lc_napari_test_home_"))
os.environ["LC_HOME"] = str(HOME)
subprocess.run(
    [sys.executable, "-m", "labconstrictor_tools", "register", "--name", "synthetic", "--prefix", sys.prefix,
     "--module", "labconstrictor_tools.examples.synthetic", "--version", "0.0"],
    check=True, capture_output=True,
)  # fmt: skip


def _leave(code=None):
    """`sys.exit` for a test script: the verdict is already printed and decides the exit code, so leave at once (`os._exit`).

    Why: running the exit handlers crashes with the PyQt bindings. PyQt5's own handler (`_qtcore_cleanup`) segfaults at exit with a
    napari window open, intermittently (about 1 run in 10 of test_parity_region.py on Linux) and in any script; seen on Linux, Windows
    and macOS CI, where it turned a passed script into a failed job. PyQt6 6.11 (the latest) still does it, and more often: 37 of 60
    runs of test_parity_region.py on Linux (napari 0.9.2, offscreen under Xvfb), a segfault after the verdict with no Python frame.
    PySide6 6.12 did not: 0 of 60 runs of the same script, so PySide6 runs keep the normal exit and the exit handlers are tested too.
    A worker needs no handler: it exits when its input closes with this process.

    Narrow by design: only `sys.exit`, and only under a PyQt binding. A failed script still exits non-zero (its `sys.exit(1)`), and an
    uncaught exception is not touched (traceback, exit 1). Retire this with the PyQt5 legacy path once the PyQt6 crash is fixed
    upstream (issue #41); check by looping a script ~60 times without it (see the README, Development and tests).
    """
    if code is None:
        code = 0
    elif not isinstance(code, int):
        print(code, file=sys.stderr)
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


faulthandler.enable()  # a crash prints the Python stack of every thread
if qtpy.API_NAME.startswith("PyQt"):  # PySide6 exits normally (see _leave)
    sys.exit = _leave

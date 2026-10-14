"""Import first in every test. Gives the run a private registry (never ~/.labconstrictor) with the example app
`labconstrictor_tools.examples.synthetic` registered against the interpreter running the tests.

Needs: pip install labconstrictor-tools  (+ this package with one Qt6 extra: ".[test-pyqt6]" or ".[test-pyside6]"). Display: xvfb-run on Linux CI.
"""

import atexit
import faulthandler
import gc
import os
import subprocess
import sys
import tempfile
import threading
import time
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


def _prunes_have_ended() -> bool:
    """True when no `prune` watcher thread of the widget is left (a run that ends starts one, and closing a widget during a run ends it).

    Why `_leave` waits for them: `os._exit` is `ExitProcess` on Windows, and a thread that is inside `CreateProcess` at that moment (the
    watcher starting `labconstrictor-tools prune`) takes the whole process down with an access violation AFTER the verdict was printed
    ("FAILURES: none", then "Windows fatal exception: access violation" with `_execute_child` in the watcher and `_leave` in the main thread,
    exit code 0xC0000005): CI run 38414096255, windows-latest PySide6, test_async_close.py. So the exit code did not carry the verdict.
    Waiting for the watcher (not just for the start) also leaves no orphan `prune` writing into the test's LC_HOME after it is gone.
    """
    retention = sys.modules.get(
        "napari_labconstrictor._retention"
    )  # not imported: no prune can have been started
    return retention is None or retention.wait_idle(120)


def _reap_workers(timeout: float = 10.0) -> None:
    """Shut down every Tools worker of this process the way closing the widget does, and wait for its pipe-reader threads.

    Why: `os._exit` is `ExitProcess` on Windows. CI run 38518804532 (windows-latest PySide6, test_calibration_transitions.py, attempt 1)
    printed "FAILURES: none" and then died with a fatal access violation inside `os._exit` (in `_leave`) while the `_read_responses` and
    `_read_stderr` threads of a worker that was still alive sat blocked on its pipes (3 of 47 Windows PySide6 jobs, 0 of PyQt6). That
    this is the cause is a hypothesis; it is not the prune watcher (`_prunes_have_ended`). So no worker may outlive the verdict:
    each `WorkerCache` (what the widget owns) gets `shutdown(final=True)`, the call `destroyed` makes; any worker not in a cache is
    closed; then the reader threads are joined (a line on stderr names one that does not end within `timeout`).
    """
    deadline = time.monotonic() + timeout
    workers_module = sys.modules.get("napari_labconstrictor._workers")
    client_module = sys.modules.get("labconstrictor_tools.client")
    if client_module is None:  # not imported: no worker can exist
        return
    objects = gc.get_objects()
    if workers_module is not None:
        for cache in [o for o in objects if isinstance(o, workers_module.WorkerCache)]:
            cache.shutdown(final=True)
    for worker in [o for o in objects if isinstance(o, client_module.WorkerProcess)]:
        if worker.proc.poll() is None:
            worker.close(timeout=max(1.0, deadline - time.monotonic()))
    del objects
    for thread in threading.enumerate():
        if thread.name.endswith(("(_read_responses)", "(_read_stderr)")):
            thread.join(max(0.1, deadline - time.monotonic()))
            if thread.is_alive():
                print("worker reader thread did not end: %s" % thread.name, file=sys.stderr)


def _leave(code: int | str | None = None) -> None:
    """`sys.exit` for a test script: the verdict is already printed and decides the exit code, so leave at once (`os._exit`).

    Why: running the exit handlers crashes with the PyQt bindings. PyQt6 6.11 (the latest) segfaults at exit with a napari window open:
    37 of 60 runs of test_parity_region.py on Linux (napari 0.9.2, offscreen under Xvfb), a segfault after the verdict with no Python frame.
    PySide6 6.12 did not crash that way: 0 of 60 runs of the same script (its own, different exit problem is described below).
    PySide6 on Python 3.11 needs it as well, for another reason (found by the coordinate-frame tests on Linux, CI run of PR #52):
    PySide6 6.12.0 loses one reference to `None` on EVERY void Qt call (measured: `sys.getrefcount(None)` falls by 1 per `setText`,
    `setVisible`, `update`, `processEvents`, `QTableWidget.setItem` ..., and not for calls that return a value). That is harmless until
    the interpreter tears down: a test that makes enough Qt calls (hundreds of layers, long `pump` loops) then dies in finalisation with
    `Fatal Python error: none_dealloc: deallocating None` AFTER it printed "FAILURES: none" (abort, exit 134). Python 3.12 made `None`
    immortal, so only `sys.version_info < (3, 12)` is affected. The checks themselves have already run when it happens.
    A worker needs no handler: it exits when its input closes with this process.

    Narrow by design: only `sys.exit`, and only under a PyQt binding or on Python < 3.12. A failed script still exits non-zero (its
    `sys.exit(1)`), and an uncaught exception is not touched (traceback, exit 1). Retire this once the PyQt6 crash and the PySide6
    refcount bug are fixed upstream; check by looping a script ~60 times without it (see the README, Development and tests).
    """
    if code is None:
        code = 0
    elif not isinstance(code, int):
        print(code, file=sys.stderr)
        code = 1
    if not _prunes_have_ended():
        print("a `prune` subprocess of the widget is still running at exit", file=sys.stderr)
        code = code or 1
    _reap_workers()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


faulthandler.enable()  # a crash prints the Python stack of every thread
atexit.register(
    _prunes_have_ended
)  # the scripts that exit normally (PySide6 on Python 3.12+) end no sooner than their prune
_LEAVE_AT_ONCE = qtpy.API_NAME.startswith("PyQt") or sys.version_info < (
    3,
    12,
)  # PySide6 on Python 3.12+ exits normally
if _LEAVE_AT_ONCE:
    sys.exit = _leave

"""Closing the widget and leaving the process never end inside the start of a `prune` subprocess.

A run that ends starts `labconstrictor-tools prune` in a watcher thread (`_retention.start_prune`), and closing a widget during a run
ends it. On Windows a process that ends (`ExitProcess`) while a thread is inside `CreateProcess` dies with an access violation, after the
verdict was printed (CI run 38414096255: test_async_close.py, windows-latest, PySide6; the watcher in `_execute_child`, the main thread in
`os._exit`). So: `wait_spawned` returns only when every prune has its subprocess, the widget's `closeEvent` calls it, and `wait_idle`
returns only when the watchers are gone.

The start of the subprocess is held by a gate the test opens (the same hook as the worker start in test_async_close.py): no clock decides
the outcome; the timer only opens the gate while the code under test is waiting.
"""

import subprocess
import sys
import threading
from typing import TYPE_CHECKING

import _async
import _paths  # noqa: F401  (must come first)
from _harness import expect, finish, pump, viewer
from _harness import widget as w

from napari_labconstrictor import LabConstrictorWidget, _retention

if TYPE_CHECKING:
    from typing import Any

_async.register("exitapp")
w.rescan()

real_popen = subprocess.Popen
entered = threading.Event()
gate = threading.Event()
made = []  # every subprocess that was really made, in order


class GatedPopen(real_popen):
    """The `prune` watcher holds here, inside the start of the subprocess, until the test opens the gate."""

    def __init__(self, *args: "Any", **kwargs: "Any") -> None:
        is_prune = list(args[0]) in PRUNE_ARGVS  # the workers of the widget start through this class too
        if is_prune:
            entered.set()
            gate.wait(60)
        super().__init__(*args, **kwargs)
        if is_prune:
            made.append(self.pid)


PRUNE_ARGV = [sys.executable, "-c", "pass"]
NO_SUCH_ARGV = ["/no/such/python-interpreter"]
PRUNE_ARGVS = [PRUNE_ARGV, NO_SUCH_ARGV]
subprocess.Popen = GatedPopen
_retention.prune_argv = lambda python: list(PRUNE_ARGV)
SCHEMA = {"features": [_retention.PRUNE_FEATURE]}


def reset() -> None:
    entered.clear()
    gate.clear()
    made.clear()


def opened_soon() -> "Any":
    """Open the gate while the code under test is waiting for the start (a timer, never what decides the result)."""
    timer = threading.Timer(0.5, gate.set)
    timer.start()
    return timer


# (1) wait_spawned: returns only when the subprocess exists; gives up (False) when it does not
reset()
thread = _retention.start_prune(sys.executable, SCHEMA)
expect("a prune watcher was started", thread is not None and entered.wait(60))
expect("the watcher is inside the start and no subprocess exists", not made and thread.is_alive())
expect(
    "a start that does not finish is reported, not waited for for ever", _retention.wait_spawned(0.2) is False
)
opened_soon()
expect("wait_spawned returns True", _retention.wait_spawned(60) is True)
expect("... and then the subprocess exists", len(made) == 1, made)
expect(
    "wait_idle returns when the watcher is gone", _retention.wait_idle(60) is True and not thread.is_alive()
)
expect("nothing is left in the registry", not _retention._running_prunes())

# (2) a prune that cannot start is not waited for
reset()
gate.set()
_retention.prune_argv = lambda python: list(NO_SUCH_ARGV)
thread = _retention.start_prune(sys.executable, SCHEMA)
expect(
    "a prune that cannot start ends the wait",
    _retention.wait_spawned(60) is True and _retention.wait_idle(60),
)
_retention.prune_argv = lambda python: list(PRUNE_ARGV)

# (3) closing the widget during a run ends the run, which starts prune: close() returns after the subprocess exists
reset()
widget = LabConstrictorWidget(napari_viewer=viewer)
widget.show()
widget.app_box.value = "exitapp"
pump(0.2)
widget.tool_box.value = "Slow run"
pump(0.3)
folder = _async.folder("run")
widget.gui.gate.value = str(folder)
widget.gui()
_async.wait_for(lambda: (folder / "run_started").exists(), pump, 90)
expect("a run is going", (folder / "run_started").exists() and widget.task is not None)
opened_soon()
widget.close()
expect("close() returns with the prune subprocess made", len(made) == 1 and entered.is_set(), made)
expect("the watcher of that close was started", widget.last_prune is not None)
expect("wait_idle finishes it", _retention.wait_idle(60) and not widget.last_prune.is_alive())
expect("nothing is left in the registry after the close", not _retention._running_prunes())

subprocess.Popen = real_popen
finish()

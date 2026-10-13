"""A form that was left is deleted by the GUI thread, never by whichever thread runs the cyclic garbage collector.

The old form sits in reference cycles. Python's collector runs in the thread that allocates next: once a run ended that is often the
`prune` watcher or a worker reader. A form that Python owns (a parentless widget) was then deleted by that thread while the GUI thread was
handling events for it: napari's event filter raised "Internal C++ object already deleted" and the process crashed with a segmentation
fault (macOS PySide6 CI, test_number_run.py, 2 of 26 runs, with the prune watcher the only other busy thread; here reproduced on Linux
in 10 of 12 runs of the loop below with `gc.collect()` in a thread).

(1) the thread that deletes the left form, observed through `destroyed`; (2) switching tools while another thread keeps collecting.
"""

import gc
import threading
from typing import TYPE_CHECKING

import _paths  # noqa: F401  (must come first)
import qtpy
from _numhelpers import choose, expect, finish, pump, until, w
from qtpy.QtCore import QCoreApplication, QEvent, Qt

if TYPE_CHECKING:
    from qtpy.QtWidgets import QWidget

deleted_by = []


def note_deletion(*_: object) -> None:
    deleted_by.append(threading.current_thread().name)


def collect_in_a_thread() -> None:
    thread = threading.Thread(target=gc.collect, name="collector")
    thread.start()
    thread.join()


def python_owns(widget: "QWidget") -> bool:
    """Does Python own the C++ object (so that freeing the wrapper, in any thread, deletes the widget)?"""
    if qtpy.API_NAME.startswith("PySide"):
        import shiboken6

        return shiboken6.ownedByPython(widget)
    from PyQt6 import sip

    return sip.ispyowned(widget)


choose("Free integer")
left = w.gui.native
left.destroyed.connect(note_deletion, Qt.ConnectionType.DirectConnection)  # runs in the thread that deletes
choose("Free float")  # the form of "Free integer" is left
expect(
    "the left form is not owned by Python (a collection in any thread would delete it)", not python_owns(left)
)
expect(
    "... it is a hidden child of the widget, so Qt owns it",
    left.parent() is w and not left.isVisible(),
    left.parent(),
)
collect_in_a_thread()
expect("a collection in another thread does not delete it", not deleted_by, deleted_by)
# a test pumps the loop by hand, and `processEvents` leaves deferred deletions alone: ask for them (a running loop does it by itself)
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
del left
until(lambda: len(deleted_by) == 1, timeout=30)
expect("the GUI thread deletes it", deleted_by == [threading.main_thread().name], deleted_by)

stop = threading.Event()


def collect_all_the_time() -> None:
    while not stop.is_set():
        gc.collect()
        stop.wait(0.001)


collector = threading.Thread(target=collect_all_the_time, name="collector", daemon=True)
collector.start()
for _ in range(60):
    choose("Free integer")
    choose("Free float")
stop.set()
collector.join(30)
pump(0.5)
expect(
    "forms switched 120 times while another thread collects", not collector.is_alive() and w.gui is not None
)
finish()

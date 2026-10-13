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

import _paths  # noqa: F401  (must come first)
from _numhelpers import choose, expect, finish, pump, until, w

deleted_by = []


def note_deletion(*_):
    deleted_by.append(threading.current_thread().name)


def collect_in_a_thread():
    thread = threading.Thread(target=gc.collect, name="collector")
    thread.start()
    thread.join()


gc.disable()  # only the collector thread collects: when the garbage is freed is then decided by the test, not by an allocation
choose("Free integer")
w.gui.native.destroyed.connect(note_deletion)
choose("Free float")  # the form of "Free integer" is left
collect_in_a_thread()
until(lambda: deleted_by)
expect("the left form is deleted", len(deleted_by) == 1, deleted_by)
expect("... by the GUI thread", deleted_by == [threading.main_thread().name], deleted_by)

stop = threading.Event()


def collect_all_the_time():
    while not stop.is_set():
        gc.collect()
        stop.wait(0.001)


collector = threading.Thread(target=collect_all_the_time, name="collector", daemon=True)
collector.start()
for _ in range(40):
    choose("Free integer")
    choose("Free float")
stop.set()
collector.join(30)
pump(0.5)
expect("forms switched 80 times while another thread collects", not collector.is_alive() and w.gui is not None)
gc.enable()
finish()

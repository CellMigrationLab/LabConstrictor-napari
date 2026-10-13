"""ASY-07 (SPEC_WRONG_SCIENCE 5.6): closing the widget leaves no worker process and no thread of the widget, also when a lookup is in
flight, when a worker is being started, or when a run is going. Real worker processes."""

import threading

import _async
import _paths  # noqa: F401  (must come first)
from _harness import expect, finish, pump, viewer
from _harness import widget as w

from napari_labconstrictor import LabConstrictorWidget, _workers

_async.register("asyapp")
w.rescan()
started, Counting = _async.counting(_workers.client)
_async.case("ASY-07", "close the widget with a lookup in flight")


def make():
    widget = LabConstrictorWidget(napari_viewer=viewer)
    widget.show()
    widget.app_box.value = "asyapp"
    pump(0.2)
    return widget


def gone(pids):
    return _async.wait_for(lambda: not any(_async.alive(p) for p in pids), pump, 20)


# (1) a lookup is running in its worker
w1 = make()
w1.tool_box.value = "Pick one"
pump(0.3)
d1 = _async.folder("one")
w1.gui.folder.value = str(d1)
_async.wait_for(lambda: _async.started(d1, "mode"), pump, 90)
pids = [s[1] for s in started]
expect(
    "ASY-07 a lookup is in flight",
    _async.started(d1, "mode")
    and w1._lookups.counts()[0] == 1
    and pids
    and all(_async.alive(p) for p in pids),
    started,
)
w1.close()
expect("ASY-07 close leaves no worker process", gone(pids), pids)
expect(
    "ASY-07 close leaves no thread of the widget",
    not _async.live_threads("lc-lookups", "lc-run"),
    _async.live_threads("lc-lookups", "lc-run"),
)
expect("ASY-07 nothing is kept or active", not w1._workers._workers and not w1._workers._active)

# (2) a worker is being started when the widget closes: the thread that made it closes it
w2 = make()
w2.tool_box.value = "Pick one"
pump(0.3)
Counting.entered.clear()
Counting.gate = threading.Event()
n = len(started)
w2.gui.folder.value = str(_async.folder("two"))
_async.wait_for(Counting.entered.is_set, pump, 60)  # the lookup thread is inside WorkerProcess(...)
threading.Timer(0.7, Counting.gate.set).start()  # the start finishes while close() waits for the thread
w2.close()
Counting.gate = None
pids2 = [s[1] for s in started[n:]]
expect(
    "ASY-07 a worker created after close does not survive",
    len(pids2) == 1 and gone(pids2) and not w2._workers._active and not w2._workers._workers,
    (started[n:], w2._workers._active),
)
expect(
    "ASY-07 no thread of the widget after that either",
    not _async.live_threads("lc-lookups", "lc-run"),
    _async.live_threads("lc-lookups", "lc-run"),
)

# (3) a run is going: its worker and its thread are gone after close
w3 = make()
w3.tool_box.value = "Slow run"
pump(0.3)
d3 = _async.folder("three")
w3.gui.gate.value = str(d3)
n = len(started)
w3.gui()
_async.wait_for(lambda: (d3 / "run_started").exists(), pump, 90)
pids3 = [s[1] for s in started[n:]]
expect(
    "ASY-07 a run is going",
    (d3 / "run_started").exists() and len(pids3) == 1 and _async.live_threads("lc-run") == ["lc-run"],
    (started[n:], _async.live_threads("lc-run")),
)
w3.close()
expect(
    "ASY-07 close during a run leaves no worker process and no thread",
    gone(pids3) and not _async.live_threads("lc-lookups", "lc-run"),
    (pids3, _async.live_threads("lc-lookups", "lc-run")),
)
finish()

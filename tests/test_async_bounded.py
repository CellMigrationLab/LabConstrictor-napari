"""ASY-04 and ASY-05 (SPEC_WRONG_SCIENCE 5.4): the lookups of a widget are bounded, and share one worker process.

Real worker processes (a source tool that waits for a barrier file); the process count is of `WorkerProcess` instances made.
"""

import _async
import _paths  # noqa: F401  (must come first)
from _harness import expect, finish, pump
from _harness import widget as w

from napari_labconstrictor import _workers

_async.register("asyapp")
w.rescan()
started, Counting = _async.counting(_workers.client)
w.app_box.value = "asyapp"
pump(0.3)


def settled():
    return _async.wait_for(w.choices_settled, pump, 90)


def shown(x):
    return not x.native.isHidden()


# ---- ASY-05: two ChoicesFrom parameters asked at once -----------------------------------------------------------------------------
_async.case("ASY-05", "two parameters each with ChoicesFrom")
w.tool_box.value = "Pick two"
pump(0.3)
two = _async.folder("two")
_async.release(two)
before = len(started)
w.gui.folder.value = str(two)  # one debounce, two questions
ok = settled()
mode, kind = w._choice_boxes["mode"], w._choice_boxes["kind"]
expect("ASY-05 both answered", ok and _async.started(two, "mode") and _async.started(two, "kind"))
expect(
    "ASY-05 each reply goes to its own control",
    list(mode.choices) == ["", "m1", "m2"]
    and list(kind.choices) == ["", "k1", "k2"]
    and shown(mode)
    and shown(kind),
    (list(mode.choices), list(kind.choices)),
)
expect(
    "ASY-05 one worker process",
    len(started) - before == 1 and w._lookups.peak_in_flight == 1,
    (started[before:], w._lookups.peak_in_flight),
)

# ---- ASY-04: a dependency changed 50 times in a second ----------------------------------------------------------------------------
_async.case("ASY-04", "change a dependency 50 times in 1 s")
w.tool_box.value = "Pick one"
pump(0.3)
w._workers.close_all()  # a worker of its own to count: nothing cached from above
dirs = [_async.folder("d%d" % i) for i in range(50)]
before = len(started)
issued_before = w._request_id
for i, d in enumerate(dirs):
    w.gui.folder.value = str(d)
    if i % 5 == 4:
        w._choice_timer.stop()
        w._resolve_choices()  # as if the debounce had fired on a slow machine
    pump(0.02)
in_flight, pending = w._lookups.counts()
expect(
    "ASY-04 at most 1 in flight, 1 pending for the parameter",
    in_flight <= 1 and pending <= 1 and w._lookups.peak_in_flight <= 1 and w._lookups.peak_pending <= 1,
    (w._lookups.counts(), w._lookups.peak_in_flight, w._lookups.peak_pending),
)
expect("ASY-04 the requests were really made", w._request_id - issued_before >= 50)
expect(
    "ASY-04 one lookup thread", len(_async.live_threads("lc-lookups")) == 1, _async.live_threads("lc-lookups")
)
_async.release(dirs[-1])
ok = settled()
box = w._choice_boxes["mode"]
expect(
    "ASY-04 the last value is answered",
    ok and shown(box) and list(box.choices) == ["", "m1", "m2"],
    list(box.choices),
)
expect("ASY-04 worker processes started <= 1", len(started) - before <= 1, started[before:])
finish()

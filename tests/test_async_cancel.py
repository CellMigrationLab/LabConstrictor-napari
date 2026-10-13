"""A lookup that is cancelled or runs too long is said in the status line and the field's tooltip; its worker is not kept
(SPEC_WRONG_SCIENCE 5.4: over the time limit it is cancelled and its worker discarded). Real worker processes.
"""

from typing import TYPE_CHECKING

import _async
import _paths  # noqa: F401  (must come first)
from _harness import expect, finish, pump
from _harness import widget as w

from napari_labconstrictor import _lookups, _workers

if TYPE_CHECKING:
    from magicgui.widgets import Widget

_async.register("asyapp")
w.rescan()
started, Counting = _async.counting(_workers.client)
real_execute = _lookups.execute
limits = {"timeout_s": 1.0, "grace_s": 1.0}
_lookups.execute = lambda job, workers: real_execute(job, workers, **limits)
w.app_box.value = "asyapp"
pump(0.3)


def settled() -> object:
    return _async.wait_for(w.choices_settled, pump, 90)


def shown(x: "Widget") -> bool:
    return not x.native.isHidden()


# a tool that honours the cancel: cancelled at the limit, its worker discarded
w.tool_box.value = "Pick one"
pump(0.3)
folder = _async.folder("slow")
w.gui.folder.value = str(folder)
ok = settled()
text = "the choices for mode took more than 1 s and were cancelled"
expect(
    "cancel: a lookup over the limit is said in the status line",
    ok and text in w.status.text(),
    w.status.text(),
)
expect(
    "cancel: and in the tooltip, the text field stays",
    text + ": type the value" in w.gui.mode.native.toolTip()
    and shown(w.gui.mode)
    and not shown(w._choice_boxes["mode"]),
    w.gui.mode.native.toolTip(),
)
expect(
    "cancel: its worker is not kept",
    not w._workers._workers and not w._workers._active and not _async.alive(started[0][1]),
    (w._workers._workers, started),
)

# a tool that ignores the cancel: killed after the grace time
w.status.setText("")
w.tool_box.value = "Pick stubborn"
pump(0.3)
w.gui.folder.value = str(_async.folder("stubborn"))
ok = settled()
expect(
    "cancel: a tool that ignores it is killed and the lookup is said",
    ok and "took more than 1 s" in w.status.text() and len(started) == 2 and not _async.alive(started[1][1]),
    (w.status.text(), started),
)

# a tool that finishes within the limit is unaffected, and its worker is kept
limits["timeout_s"] = 60.0
w.status.setText("")
w.tool_box.value = "Pick one"
pump(0.3)
quick = _async.folder("quick")
_async.release(quick)
w.gui.folder.value = str(quick)
ok = settled()
expect(
    "cancel: an answer in time is shown and its worker kept",
    ok and shown(w._choice_boxes["mode"]) and w.status.text() == "" and "asyapp" in w._workers._workers,
    (w.status.text(), w._workers._workers),
)
finish()

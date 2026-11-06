"""A form taller than the dock scrolls (advanced settings of a big tool), and the Run button / status stay reachable: Run is
the host's own button under the scrolling form, beside Cancel, not magicgui's call button at the end of the form (#72).
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import _paths  # noqa: F401  (must come first)
import napari
from _paths import EVIDENCE
from qtpy.QtWidgets import QApplication, QPushButton, QWidget

tools = Path(tempfile.mkdtemp(prefix="lcscroll_"))
params = "".join(
    "    p%02d: Annotated[float, Group('G%d'), Advanced()] = 1.0,\n" % (i, i // 10) for i in range(40)
)
(tools / "tall_lc_tools.py").write_text(
    "from typing import Annotated\n"
    "from labconstrictor_tools import Advanced, Group, Label, Scalars, tool\n"
    "@tool('Tall')\n"
    "def tall(\n    base: float = 1.0,\n" + params + ") -> Scalars:\n    return {'base': base}\n"
    "from typing import Literal\n"
    "@tool('Wide')\n"
    "def wide(choice: Annotated[Literal['"
    + "x" * 110
    + "', 'y'], Label('A very long label ' * 6)] = 'y') -> Scalars:\n    return {'choice': choice}\n"
)
subprocess.run(
    [sys.executable, "-m", "labconstrictor_tools", "register", "--name", "tall", "--prefix", sys.prefix,
     "--module", "tall_lc_tools", "--pythonpath", str(tools)],
    check=True, capture_output=True,
)  # fmt: skip

v = napari.Viewer(show=True)
v.window._qt_window.resize(1300, 700)
qa = QApplication.instance()
_, w = v.window.add_plugin_dock_widget("napari-labconstrictor", "LabConstrictor tools")
report, failures = {}, []


def pump(sec: float = 0.3) -> None:
    end = time.time() + sec
    while time.time() < end:
        qa.processEvents()
        time.sleep(0.02)


def expect(name: str, condition: object, detail: object = "") -> None:
    report[name] = bool(condition)
    if not condition:
        failures.append("%s %s" % (name, detail))


def run_in_view() -> bool:
    """Run is shown, can be clicked, and no part of it is hidden (a button scrolled away has an empty visible region)."""
    region = w.run_button.visibleRegion().boundingRect()
    return bool(
        w.run_button.isVisible() and w.run_button.isEnabled() and region.size() == w.run_button.size()
    )


def top_in_dock(widget: QWidget) -> int:
    return int(widget.mapTo(w, widget.rect().topLeft()).y())


def middle_in_dock(widget: QWidget) -> int:
    return int(widget.mapTo(w, widget.rect().center()).y())


w.app_box.value = "tall"
pump(0.3)
w.tool_box.value = "Tall"
pump(0.8)
bar = w.form_scroll.verticalScrollBar()
expect(
    "short_form_does_not_need_scrolling_until_advanced_is_open",
    bar.maximum() == 0 or bar.maximum() < 200,
    bar.maximum(),
)
w.advanced_toggle.value = True
pump(0.8)
expect("form_scrolls_when_advanced_is_open", bar.maximum() > 200, bar.maximum())
expect(
    "buttons_stay_in_view",
    w.details_button.isVisible() and w.cancel_button.isVisible() and w.status.isVisible(),
)
form_buttons = [b.text() for b in w.form_scroll.widget().findChildren(QPushButton)]
expect("the_form_has_no_run_button_of_its_own", "Run" not in form_buttons, form_buttons)
expect("run_is_not_in_the_scrolling_form", not w.form_scroll.isAncestorOf(w.run_button))
bottom_of_form = top_in_dock(w.form_scroll) + w.form_scroll.height()
expect(
    "run_is_under_the_form",
    top_in_dock(w.run_button) >= bottom_of_form,
    (top_in_dock(w.run_button), bottom_of_form),
)
expect(
    "cancel_is_beside_run",  # same row: same vertical centre (napari draws a disabled button 2 px taller, with a border)
    abs(middle_in_dock(w.cancel_button) - middle_in_dock(w.run_button)) <= 1
    and w.cancel_button.x() > w.run_button.x(),
    (w.run_button.geometry(), w.cancel_button.geometry()),
)
expect("run_in_view_at_the_top_of_a_long_form", run_in_view(), w.run_button.visibleRegion().boundingRect())
run_top = top_in_dock(w.run_button)
bar.setValue(bar.maximum())
pump(0.4)
expect(
    "run_in_view_and_still_at_the_end_of_a_long_form",
    run_in_view() and top_in_dock(w.run_button) == run_top,
    (w.run_button.visibleRegion().boundingRect(), top_in_dock(w.run_button), run_top),
)
last = w.gui["p39"]
visible_rect = w.form_scroll.viewport().rect()
top = last.native.mapTo(w.form_scroll.viewport(), last.native.rect().topLeft())
expect("last_parameter_reachable_by_scrolling", visible_rect.contains(top), (top, visible_rect))
# a form wider than the dock scrolls sideways instead of being clipped
v.window._qt_window.resize(700, 700)  # a narrow dock
w.tool_box.value = "Wide"
pump(1.0)
viewport = w.form_scroll.viewport().width()
expect(
    "precondition_the_form_is_wider_than_the_dock",
    w.gui.native.minimumSizeHint().width() > viewport,
    (w.gui.native.minimumSizeHint().width(), viewport),
)
hbar = w.form_scroll.horizontalScrollBar()
expect(
    "wide_form_has_a_visible_horizontal_scrollbar",
    hbar.isVisible() and hbar.maximum() > 0,
    (hbar.isVisible(), hbar.maximum(), w.form_scroll.viewport().width()),
)
hbar.setValue(hbar.maximum())
pump(0.4)
box = w.gui["choice"]
right = box.native.mapTo(w.form_scroll.viewport(), box.native.rect().topRight()).x()
expect(
    "right_edge_reachable_by_scrolling",
    right <= w.form_scroll.viewport().width() + 1,
    (right, w.form_scroll.viewport().width()),
)
v.screenshot(str(EVIDENCE / "widget_scroll.png"), canvas_only=False)
print(json.dumps(report, indent=2))
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)

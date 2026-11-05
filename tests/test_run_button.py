"""The Run button is greyed out, and Cancel is available, from the click until the run ends: a second click starts nothing.
Run and Cancel sit side by side under the scrolling form, so Run stays in view however long the form is (#72).
Real mouse clicks on the real button, a tool that runs for a few seconds."""

import _paths  # noqa: F401  (must come first)
from _harness import choose, expect, finish, pump, until
from _harness import widget as w
from napari.utils.theme import get_theme
from qtpy.QtCore import Qt
from qtpy.QtTest import QTest


def click_run() -> None:
    QTest.mouseClick(w.run_button, Qt.MouseButton.LeftButton)
    pump(0.5)


def run_enabled() -> bool:
    return bool(w.run_button.isEnabled())


def theme_colour_on_run(theme_id: str) -> bool:
    """Run is coloured with the theme's highlight (`current`) colour while it is usable."""
    return get_theme(theme_id).current.as_rgb() in w.run_button.styleSheet()


choose("synthetic", "Slow with progress")
w.gui.seconds.value = 3
expect("idle_run_enabled_cancel_disabled", run_enabled() and not w.cancel_button.isEnabled())
expect(
    "run_has_the_theme_highlight",
    theme_colour_on_run(w.viewer.theme),
    (w.viewer.theme, w.run_button.styleSheet()),
)
first_theme = w.viewer.theme
w.viewer.theme = "light" if first_theme == "dark" else "dark"
pump(0.3)
expect(
    "run_follows_a_theme_change",
    theme_colour_on_run(w.viewer.theme),
    (w.viewer.theme, w.run_button.styleSheet()),
)
w.viewer.theme = first_theme
pump(0.3)

w.last_task = None
click_run()
first = w.task
expect("click_started_a_run", first is not None and not first.done.is_set(), w.status.text())
expect("running_run_disabled", not run_enabled(), "Run is enabled while the tool runs")
expect("running_cancel_enabled", w.cancel_button.isEnabled())

click_run()  # a double click: the second press is blocked and starts nothing
expect(
    "second_click_started_nothing", w.task is first and not w.status.text().startswith("⚠"), w.status.text()
)
expect("still_disabled_after_second_click", not run_enabled() and w.cancel_button.isEnabled())

until(lambda: w.last_task is not None and w.task is w.last_task)
expect("run_completed", w.last_task.status == "COMPLETE", w.status.text())
expect("after_run_run_enabled", run_enabled())
expect("after_run_cancel_disabled", not w.cancel_button.isEnabled())

# cancelled: Run is back, Cancel is off
w.gui.seconds.value = 30
w.last_task = None
click_run()
expect("cancel_run_disabled_while_running", not run_enabled())
QTest.mouseClick(w.cancel_button, Qt.MouseButton.LeftButton)
until(lambda: w.last_task is not None and w.task is w.last_task)
expect("after_cancel_run_enabled", run_enabled() and not w.cancel_button.isEnabled(), w.status.text())

# refused before it starts: nothing runs and Run stays usable
w.gui.seconds.value = 3
real_prepare = w._prepare_inputs


def refuse(*_a: object, **_k: object) -> None:
    w.status.setText("⚠ refused for the test")


w._prepare_inputs = refuse  # type: ignore[method-assign]  # stands in for a refusal of the inputs
w.last_task = None
click_run()
expect("refused_run_enabled", run_enabled() and not w.cancel_button.isEnabled(), w.status.text())
w._prepare_inputs = real_prepare  # type: ignore[method-assign]

finish()

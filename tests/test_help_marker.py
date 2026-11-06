"""Input help marker (Tools #147): an ⓘ after the label of every input with a description; hover shows it, keyboard focus of the
input shows it, a click keeps it open. Inputs without one (none, or a blank Description) get an empty slot, so the fields line up.
Real mouse clicks and real focus changes on the dock widget, the app of lctest_help.py."""

import subprocess
import sys
from pathlib import Path

import _paths  # noqa: F401  (must come first)
from _harness import choose, expect, finish, pump, until
from _harness import widget as w
from qtpy.QtCore import QEvent, QPoint, Qt
from qtpy.QtGui import QFocusEvent
from qtpy.QtTest import QTest
from qtpy.QtWidgets import QApplication, QToolButton, QToolTip, QWhatsThis, QWidget

from napari_labconstrictor._help import HELP_PROPERTY, MARKER, MARKER_NAME

THRESHOLD = "Fraction of the intensity range that separates blobs from background"
subprocess.run(
    [sys.executable, "-m", "labconstrictor_tools", "register", "--name", "helpapp", "--prefix", sys.prefix,
     "--module", "lctest_help", "--pythonpath", str(Path(__file__).resolve().parent), "--version", "0.0"],
    check=True, capture_output=True,
)  # fmt: skip
w.rescan()
choose("helpapp", "Help")


def marker_of(name: str) -> QToolButton | None:
    """The ⓘ (or empty slot) in the row of input `name`."""
    row = w.gui[name]._labeled_widget()
    return row.native.findChild(QToolButton, MARKER_NAME) if row is not None else None


def shown(name: str) -> bool:
    button = marker_of(name)
    return button is not None and not button.isHidden() and button.text() == MARKER


def field_x(name: str) -> int:
    """Where the input's cell starts in its row (the cell, not the widget's inner parts, which differ per kind)."""
    row = w.gui[name]._labeled_widget()
    return int(row.native.layout().itemAt(2).geometry().x())


def marker_at(name: str) -> QToolButton:
    button = marker_of(name)
    if button is None:
        raise SystemExit("no marker slot in the row of %r" % name)
    return button


def kept_open() -> bool:
    """A "What's this?" popup is on screen (Qt's own top-level QWhatsThat window)."""
    return "QWhatsThat" in windows()


def windows() -> list[str]:
    """Qt's class names of the visible top-level windows (a private Qt class is a plain QWidget to Python)."""
    names = [t.metaObject() for t in QApplication.topLevelWidgets() if t.isVisible()]
    return [m.className() for m in names if m is not None]


# which rows have an ⓘ: Description and Args: count, a blank Description and none do not
expect("described_inputs_have_the_marker", all(shown(n) for n in ("image", "threshold", "documented")))
expect(
    "undescribed_inputs_have_none",
    not any(shown(n) for n in ("blank", "plain")),
    [(n, not marker_at(n).isHidden()) for n in ("blank", "plain")],
)
expect(
    "markers_listed_per_input",
    sorted(w.help_markers) == ["documented", "flag", "image", "threshold"],
    sorted(w.help_markers),
)
# a check box has no label row (its own text is its label): its ⓘ sits right after it
expect("check_box_has_no_label_row", w.gui.bare._labeled_widget() is None)


def beside(name: str) -> QToolButton | None:
    """The ⓘ right after a check box (in the small row that took the check box's place)."""
    holder = w.gui[name].native.parentWidget()
    if holder is None:
        return None
    return holder.findChild(QToolButton, MARKER_NAME, Qt.FindChildOption.FindDirectChildrenOnly)


flag = beside("flag")
expect(
    "described_check_box_has_the_marker",
    flag is not None and flag.toolTip() == "Also count the blobs touching the edge",
)
expect("undescribed_check_box_has_none", beside("bare") is None)
expect("advanced_check_box_marker_hidden", flag is not None and not flag.isVisible())
w.advanced_toggle.value = True
pump(0.3)
expect(
    "advanced_check_box_marker_shown_with_it",
    flag is not None and flag.isVisible() and w.gui.flag.native.isVisible(),
    flag and (flag.isVisible(), w.gui.flag.native.isVisible()),
)
flag_row = w.gui.flag.native.parentWidget()
expect(
    "marker_right_after_the_check_box",
    flag is not None and 0 <= flag.x() - w.gui.flag.native.geometry().right() < 30,
    flag and (flag.x(), w.gui.flag.native.geometry().right()),
)
w.advanced_toggle.value = False
pump(0.3)
expect(
    "advanced_check_box_row_hidden_again",
    flag_row is not None and flag_row.isHidden() and flag is not None and not flag.isVisible(),
)
threshold = marker_at("threshold")
expect("hover_text_is_the_description", threshold.toolTip() == THRESHOLD, threshold.toolTip())
expect(
    "docstring_description_used", marker_at("documented").toolTip() == "How many rounds, from the docstring."
)
expect(
    "accessible_name_says_help", threshold.accessibleName() == "Help: Threshold", threshold.accessibleName()
)
expect("slot_keeps_its_width", marker_at("plain").sizePolicy().retainSizeWhenHidden())
expect(
    "fields_line_up",
    len({field_x(n) for n in ("threshold", "documented", "blank", "plain")}) == 1,
    {n: field_x(n) for n in ("threshold", "documented", "blank", "plain")},
)
expect(
    "marker_sits_after_the_label",
    threshold.mapTo(w.gui.native, QPoint(0, 0)).x() < field_x("threshold"),
    (threshold.mapTo(w.gui.native, QPoint(0, 0)).x(), field_x("threshold")),
)
expect("marker_takes_no_tab_stop", threshold.focusPolicy() == Qt.FocusPolicy.NoFocus)
file_row = w.file_sources["image"]._labeled_widget()
file_slot = file_row.native.findChild(QToolButton, MARKER_NAME) if file_row is not None else None
expect(
    "file_row_of_an_image_keeps_a_slot_only",
    file_slot is not None and file_slot.isHidden() and file_slot.property(HELP_PROPERTY) == "",
)

# a click keeps the help open: a "What's this?" popup that stays after the mouse leaves, until the next key
QTest.mouseClick(threshold, Qt.MouseButton.LeftButton, pos=threshold.rect().center())
pump(0.5)
expect("click_keeps_the_help_open", kept_open(), windows())
QTest.mouseMove(w.gui.native, pos=QPoint(2, 2))
pump(0.5)
expect("help_stays_after_the_mouse_leaves", kept_open(), windows())
QWhatsThis.hideText()
pump(0.3)
expect("help_closes", not kept_open(), windows())


# keyboard focus of the input shows the help; a mouse click into it does not. The focus event is delivered to the part of the input
# that takes focus, as Qt does on Tab; sent directly, because whether the window is the active one (needed for setFocus to deliver
# it) depends on the desktop the test runs on.
def focus(name: str, reason: Qt.FocusReason) -> None:
    field = w.gui[name].native
    parts = [p for p in [field, *field.findChildren(QWidget)] if p.focusPolicy() != Qt.FocusPolicy.NoFocus]
    QToolTip.hideText()
    until(
        lambda: not QToolTip.isVisible(), 3
    )  # Qt hides a tooltip after a short delay: never test the old one
    QApplication.sendEvent(parts[0], QFocusEvent(QEvent.Type.FocusIn, reason))
    pump(0.4)


focus("threshold", Qt.FocusReason.TabFocusReason)
expect("tab_focus_shows_the_help", QToolTip.isVisible() and QToolTip.text() == THRESHOLD, QToolTip.text())
focus("threshold", Qt.FocusReason.BacktabFocusReason)
expect(
    "shift_tab_focus_shows_the_help", QToolTip.isVisible() and QToolTip.text() == THRESHOLD, QToolTip.text()
)
focus("plain", Qt.FocusReason.TabFocusReason)
expect("focus_on_an_undescribed_input_shows_nothing", not QToolTip.isVisible(), QToolTip.text())
focus("threshold", Qt.FocusReason.MouseFocusReason)
expect("mouse_focus_shows_nothing", not QToolTip.isVisible(), QToolTip.text())
QToolTip.hideText()

# a ChoicesFrom input: its dropdown, which takes the field's place once the source answers, has its own ⓘ
choose("helpapp", "Help choices")
until(lambda: w._choice_boxes["mode"].visible, 60)
markers = w.help_markers.get("mode", [])
expect("choices_field_and_dropdown_both_marked", len(markers) == 2, len(markers))
box_row = w._choice_boxes["mode"]._labeled_widget()
box_marker = box_row.native.findChild(QToolButton, MARKER_NAME)
expect(
    "dropdown_marker_shown_with_the_description",
    box_marker is not None and box_marker.isVisible() and box_marker.toolTip() == "Which way to count",
    box_marker and (box_marker.isVisible(), box_marker.toolTip()),
)
expect("markers_of_the_old_form_are_gone", "threshold" not in w.help_markers, sorted(w.help_markers))
finish()

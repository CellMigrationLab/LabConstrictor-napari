"""The input help marker (Tools #147, HOST_FEATURES row "Input help marker"): an ⓘ after the label of each input that has a description.

The description is the input's help. It shows on hover over the ⓘ (a tooltip), on keyboard focus of the input (Tab moves into it), and a
click on the ⓘ keeps it open (a "What's this?" popup that stays until the next click or key). An input without a description gets no ⓘ:
its row keeps an empty slot of the same width, so every field of the form still starts in the same column. A check box (a boolean input)
has no label row, its own text being its label: its ⓘ sits right after it.
"""

from __future__ import annotations

from typing import Any

from qtpy.QtCore import QEvent, QObject, QPoint, Qt
from qtpy.QtGui import QFocusEvent
from qtpy.QtWidgets import QHBoxLayout, QSizePolicy, QToolButton, QToolTip, QWhatsThis, QWidget

MARKER = "ⓘ"  # U+24D8 CIRCLED LATIN SMALL LETTER I
# object name of every marker (the empty slots too), for the tests
MARKER_NAME = "lc_help_marker"
HELP_PROPERTY = "lc_help"  # the description a marker shows ("" for an empty slot)
_FOCUS_REASONS = (
    Qt.FocusReason.TabFocusReason,
    Qt.FocusReason.BacktabFocusReason,
    Qt.FocusReason.ShortcutFocusReason,
)


def marker(label: str, description: str) -> QToolButton:
    """The ⓘ for one row. An empty `description` gives the empty slot: hidden, but keeping its width."""
    button = QToolButton()
    button.setObjectName(MARKER_NAME)
    button.setText(MARKER)
    button.setAutoRaise(True)
    button.setCursor(Qt.CursorShape.WhatsThisCursor)
    # no tab stop of its own: keyboard users get the help when the input itself takes focus
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setProperty(HELP_PROPERTY, description)
    policy = button.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    policy.setHorizontalPolicy(QSizePolicy.Policy.Fixed)
    button.setSizePolicy(policy)
    if description:
        button.setToolTip(description)
        button.setAccessibleName("Help: %s" % label)
        button.setAccessibleDescription(description)
        button.clicked.connect(lambda *_: show_kept_open(button, description))
    else:
        button.setVisible(False)
    return button


def show_kept_open(anchor: QWidget, text: str) -> None:
    """The click: the help stays on screen until the next click or key press (unlike a tooltip, which leaves with the mouse)."""
    QWhatsThis.showText(anchor.mapToGlobal(QPoint(0, anchor.height())), text, anchor)


class HelpOnFocus(QObject):
    """Shows the description as a tooltip under the input when the keyboard moves into it (Tab, Shift+Tab, a shortcut); a mouse click
    into the input shows nothing (the ⓘ and the hover already do). Installed on the input and on every focusable part inside it.
    """

    def __init__(self, field: QWidget, text: str) -> None:
        super().__init__(field)  # lives and dies with the input
        self._field, self._text = field, text

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:  # Qt API name
        if (
            isinstance(event, QFocusEvent)
            and event.type() == QEvent.Type.FocusIn
            and event.reason() in _FOCUS_REASONS
        ):
            QToolTip.showText(
                self._field.mapToGlobal(QPoint(0, self._field.height())), self._text, self._field
            )
        return False


def add_help(row: Any, field: Any, label: str, description: str) -> QToolButton | None:
    """Put the marker into a labelled row of the form (magicgui wraps each labelled widget in a row: [label, widget]).

    `row` is that wrapper, `field` the magicgui widget of the input. Returns the marker, or None for a widget without a label row.
    """
    layout = row.native.layout()
    if layout is None:
        return None
    button = marker(label, description)
    layout.insertWidget(1, button)  # after the label, before the input
    if description:
        _show_on_focus(field.native, description)
    return button


def add_help_beside(check: Any, label: str, description: str) -> QToolButton | None:
    """A check box (a boolean input) has no label row: its own text is its label. Its ⓘ goes right after it, in a small row that
    takes the check box's place in the form and is shown and hidden with it (advanced settings, folded groups).
    """
    native = check.native
    parent = native.parentWidget()
    layout = parent.layout() if parent is not None else None
    if layout is None or layout.indexOf(native) < 0:
        return None
    index = layout.indexOf(native)
    holder = QWidget(parent)
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    button = marker(label, description)
    row.addWidget(native)  # takes it out of the form's layout
    row.addWidget(button)
    row.addStretch(1)
    layout.insertWidget(index, holder)
    holder.setHidden(native.isHidden())
    native.installEventFilter(_FollowVisibility(native, holder))
    _show_on_focus(native, description)
    return button


class _FollowVisibility(QObject):
    """Hides and shows the check box's row with the check box (magicgui hides the check box itself, which Qt reports to it as
    HideToParent / ShowToParent even while the row is hidden)."""

    def __init__(self, check: QWidget, holder: QWidget) -> None:
        super().__init__(check)
        self._holder = holder

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:  # Qt API name
        if event is not None and event.type() == QEvent.Type.HideToParent:
            self._holder.setHidden(True)
        elif event is not None and event.type() == QEvent.Type.ShowToParent:
            self._holder.setHidden(False)
        return False


def _show_on_focus(field: QWidget, description: str) -> None:
    watcher = HelpOnFocus(field, description)
    for part in [field, *field.findChildren(QWidget)]:
        if part.focusPolicy() != Qt.FocusPolicy.NoFocus:
            part.installEventFilter(watcher)

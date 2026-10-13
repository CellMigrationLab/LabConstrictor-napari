"""Shared helpers of the number-field tests (import after `_paths`): the form, what a click would send, typing like a person.
The check is on the REQUEST (`_prepare_inputs`, the function a click uses) and on what a real worker received. Not a test.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import _paths  # noqa: F401  (must come first)
from _harness import expect, finish, pump, until, viewer  # noqa: F401
from _harness import widget as w
from labconstrictor_tools import conformance
from qtpy.QtCore import Qt
from qtpy.QtTest import QTest

if TYPE_CHECKING:
    from typing import Any

C = conformance.load()
NUM = {case["id"]: case for case in C["wrong_science"]["number_limits"]["cases"]}
MESSAGES = C["messages"]
INT_MAX = C["limits"]["form_integer_max"]["value"]
FLOAT_MAX = C["limits"]["unbounded_float"]["value"]
HERE = Path(__file__).resolve().parent

subprocess.run(
    [sys.executable, "-m", "labconstrictor_tools", "register", "--name", "numapp", "--prefix", sys.prefix,
     "--module", "lctest_numbers", "--pythonpath", str(HERE), "--version", "0.0"],
    check=True, capture_output=True,
)  # fmt: skip
w.rescan()


def above(label: str, maximum: float) -> str:
    return "⚠ " + MESSAGES["number_above_maximum"]["template"].format(label=label, maximum=maximum)


def below(label: str, minimum: float) -> str:
    return "⚠ " + MESSAGES["number_below_minimum"]["template"].format(label=label, minimum=minimum)


def choose(tool: str) -> None:
    """The form of `tool`, built afresh (a form that is already showing is left first, so no typed text or ticked box carries over)."""
    w.app_box.value = "numapp"
    pump(0.1)
    if w.tool_box.value == tool:
        w.tool_box.value = next(c for c in w.tool_box.choices if c != tool)
        pump(0.1)
    w.tool_box.value = tool
    pump(0.3)


def type_text(name: str, text: str) -> None:
    """The person selects the box, types `text` key by key and presses Enter: Qt's own edit signals fire, nothing is set from code."""
    edit = w.gui[name].native
    edit.setFocus()
    edit.selectAll()
    if not text:
        QTest.keyClick(edit, Qt.Key.Key_Backspace)  # delete the selection
    elif text.isascii() and len(text) <= 40:
        QTest.keyClicks(edit, text)
    else:  # no ASCII key code, or very long: such text arrives the way pasted text does (a key press costs about 20 void Qt calls, which
        # PySide6 on Python 3.11 pays for in references to None: 5000 keys exhaust them; see _paths._leave)
        edit.insert(text)
    QTest.keyClick(edit, Qt.Key.Key_Return)


def paste_text(name: str, text: str) -> None:
    """Pasted or dropped text: set as a whole into the box's line edit, the way the clipboard arrives."""
    edit = w.gui[name].native
    edit.selectAll()
    edit.insert(text)


def request() -> "tuple[Any, str | None]":
    """(inputs, None) the form would send to the worker, or (None, the status sentence) when the click refuses (the first half of a click)."""
    seen = []
    w._launch = lambda form_values: seen.append(form_values)
    try:
        w.gui()
    finally:
        del w._launch
    job_dir = Path(tempfile.mkdtemp(prefix="lcin_"))
    w.status.setText("")
    prepared = w._prepare_inputs(seen[0], job_dir)
    if prepared is None:
        return None, w.status.text()
    shutil.rmtree(job_dir, ignore_errors=True)
    return prepared[0], None


def run() -> "Any":
    """Press Run for real and wait for the end of the task; returns it."""
    w.last_task = None
    w.gui()
    until(lambda: w.last_task is not None and w.task is w.last_task)
    pump(0.3)
    return w.last_task


def received() -> str:
    """What the tool said it received (the message output), from the status or message area of the finished run."""
    return w.status.text() + "\n" + (w.message_label.text() if w.message_label.isVisible() else "")


def sends(tag: str, tool: str, name: str, text: str, value: float) -> None:
    """Type `text`; the click sends exactly `value` (same type) and the box still shows the text as typed."""
    choose(tool)
    type_text(name, text)
    inputs, refused = request()
    got = None if inputs is None else inputs.get(name)
    expect(tag, inputs is not None and got == value and type(got) is type(value), (text, inputs, refused))
    expect(tag + "_text_unchanged", w.gui[name].native.text() == text, w.gui[name].native.text())


def refuses(tag: str, tool: str, name: str, text: str, sentence: str) -> None:
    """Type `text`; the click refuses with `sentence` (after the warning sign) and sends nothing."""
    choose(tool)
    type_text(name, text)
    inputs, refused = request()
    expect(tag, inputs is None and refused == "⚠ " + sentence, (text, inputs, refused))

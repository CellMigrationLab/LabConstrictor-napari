"""Shared set-up of the linked pixel-size number tests (import after `_paths`): the numbers app's three linked tools, an image that has no
calibration and ones that have, and a way to enter text the way a person does. Not a test (CI runs only test_*.py).

Long texts are pasted (one `textEdited` for the whole text, like the clipboard), not typed key by key: a key press costs about 20 void Qt
calls, which PySide6 on Python 3.11 pays for in references to None (see _paths._leave). The Enter that ends the entry is a key press.
"""

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import _paths  # noqa: F401  (must come first)
import numpy as np
import tifffile
from _numhelpers import (  # noqa: F401  (re-exported for the tests)
    FLOAT_MAX,
    NUM,
    above,
    below,
    choose,
    expect,
    finish,
    paste_text,
    received,
    request,
    run,
    viewer,
    w,
)
from napari.layers import Image
from qtpy.QtCore import Qt
from qtpy.QtTest import QTest

if TYPE_CHECKING:
    from typing import Any

    from qtpy.QtWidgets import QLineEdit

FIELD = "pixel_size"
LABEL = "Pixel size"
NOT_POSITIVE = "⚠ [invalid_parameter] '%s' must be greater than 0 (um per pixel)" % LABEL
DATA = np.zeros((4, 4), np.uint16)
NOCAL = Image(DATA, name="nocal")  # napari's default: pixels, no length: not calibrated
UM = Image(DATA, name="um", scale=(0.25, 0.25), units="micrometer")
UM2 = Image(DATA, name="um2", scale=(0.5, 0.5), units="micrometer")


def start(tool: str, layer: Image = NOCAL) -> None:
    """A fresh form of `tool` with `layer` chosen as its image (the layers are added to the viewer once)."""
    for item in (NOCAL, UM, UM2):
        if item not in viewer.layers:
            viewer.add_layer(item)
    choose(tool)
    w.gui.image.value = layer


def box() -> "QLineEdit":
    return w.gui[FIELD].native


def shown() -> str:
    return box().text()


def link() -> "Any":
    return w.cal_links[FIELD]


def enter(text: str, confirm: bool = True) -> None:
    """The person puts `text` into the box (selected first, then pasted as a whole) and presses Enter unless `confirm` is False."""
    edit = box()
    edit.setFocus()
    edit.selectAll()
    if text:
        edit.insert(text)
    else:
        QTest.keyClick(edit, Qt.Key.Key_Backspace)  # delete the selection
    if confirm:
        QTest.keyClick(edit, Qt.Key.Key_Return)


def sends(tag: str, text: str, value: float, source: str = "user") -> None:
    """Enter `text`: the click sends exactly `value` (a float) and `_calibration`, and the box still shows the text as typed."""
    enter(text)
    inputs, refused = request()
    got = None if inputs is None else inputs.get(FIELD)
    expect(tag + "_sent_exactly", got == value and type(got) is float, (text, inputs, refused))
    expect(tag + "_text_kept", shown() == text, shown())
    expect(tag + "_state", link().state == "user", link().state)
    if inputs is not None:
        entry = inputs["_calibration"][FIELD]
        axes = entry["axes"]
        expect(
            tag + "_entry",
            entry["source"] == source and axes["x"]["value"] == value and axes["y"]["value"] == value,
            entry,
        )


def refuses(tag: str, text: str, sentence: str) -> None:
    """Enter `text`: the click refuses with `sentence`, sends nothing, and the box still shows the text (never clamped or rounded)."""
    enter(text)
    inputs, refused = request()
    expect(
        tag + "_refused_with_the_sentence", inputs is None and refused == sentence, (text, inputs, refused)
    )
    expect(tag + "_text_kept", shown() == text, shown())
    expect(tag + "_state_is_user", link().state == "user", link().state)


TMP = Path(tempfile.mkdtemp(prefix="lclinked_"))


def start_with_file(tool: str, scale: float, name: str) -> None:
    """A fresh form of `tool` whose image is an OME-TIFF with this physical size in micrometres (a napari layer cannot hold every scale)."""
    path = TMP / (name + ".tif")
    meta = {
        "axes": "YX",
        "PhysicalSizeX": scale,
        "PhysicalSizeY": scale,
        "PhysicalSizeXUnit": "µm",
        "PhysicalSizeYUnit": "µm",
    }
    tifffile.imwrite(path, DATA.astype(np.uint8), ome=True, metadata=meta)
    start(tool)
    w.file_sources["image"].value = path

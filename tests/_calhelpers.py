"""Shared set-up of the calibration tests (import after `_paths`): the viewer with the dock, sources (layers, TIFF and OME files), and the
checks that read the REQUEST a worker would receive. Not a test (CI runs only test_*.py)."""

import json
import shutil
import tempfile
from pathlib import Path

import _paths  # noqa: F401  (must come first)
import _runtools as R
import numpy as np
import tifffile
from _harness import _qa as qa
from _harness import (
    expect,
    finish,  # noqa: F401  (re-exported for the tests)
    viewer,
    widget,
)
from labconstrictor_tools import conformance
from napari.layers import Image
from qtpy.QtCore import Qt
from qtpy.QtTest import QTest

w = widget
C = conformance.load()
CAL = C["wrong_science"]["calibration"]
CASES = {c["id"]: c for c in CAL["cases"]}
REQUIRED = C["messages"]["calibration_required"]["template"]
TOOLTIP_UNKNOWN = C["messages"]["calibration_unknown_tooltip"]["template"]
TMP = Path(tempfile.mkdtemp(prefix="lccal_"))
R.use_recorder()
DATA = np.zeros((6, 6), np.uint16)
FIELD = "pixel_size"


def ome_file(scale, unit):
    """An OME-TIFF whose physical size is `scale` (y, x) in the unit text `unit` (None: no unit attribute at all)."""
    scale = scale if isinstance(scale, list | tuple) else (scale, scale)
    meta = {"axes": "YX", "PhysicalSizeY": scale[0], "PhysicalSizeX": scale[1]}
    if unit is not None:
        meta.update(PhysicalSizeYUnit=unit, PhysicalSizeXUnit=unit)
    ome_file.count += 1
    return tiff("ome%d.tif" % ome_file.count, ome=True, metadata=meta)


ome_file.count = 0


def pint_layer(scale, unit, name="src"):
    """A real napari layer with these units, or None when napari (pint) does not accept the text."""
    scale = tuple(scale) if isinstance(scale, list | tuple) else (scale, scale)
    try:
        return Image(DATA, name=name, scale=scale, **({} if unit is None else {"units": unit}))
    except ValueError:
        return None


def settle():
    """Let Qt deliver what is queued. Not `pump`: the loops of `pump` make thousands of Qt calls, and PySide6 on Python 3.11 loses a
    reference to None on each of them (see _paths._leave): a test with this many steps would abort the interpreter before it ends.
    """
    qa.processEvents()


def fresh(tool="Pixel size required", rebuild=True):
    """No layers, no file. `rebuild`: also a new form (a user value or a state left by the last scenario is gone with it)."""
    viewer.layers.clear()
    if w.tool_box.value != tool or w.app_box.value != R.APP:
        R.pick(tool)
    elif rebuild:
        w._on_tool_changed()  # picking the tool that is already chosen would keep the last scenario's state
    w.file_sources["image"].value = None
    settle()


def choose(layer):
    if layer not in viewer.layers:
        viewer.add_layer(layer)
    w.gui.image.value = layer
    settle()


def tiff(name, **kwargs):
    path = TMP / name
    tifffile.imwrite(path, DATA.astype(np.uint8), **kwargs)
    return path


def link():
    return w.cal_links[FIELD]


def field():
    return w.gui[FIELD].value


def request():
    """(inputs, None) the form would send to the worker, or (None, the sentence) when the run is refused (what a click does first)."""
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


def type_value(text, enter=True):
    """The person types into the box (a line of text) key by key, and presses Enter unless `enter` is False: Qt's own edit signals fire."""
    edit = w.gui[FIELD].native
    edit.setFocus()
    edit.selectAll()
    if text:
        QTest.keyClicks(edit, text)
    else:
        QTest.keyClick(edit, Qt.Key.Key_Backspace)  # delete the selection
    if enter:
        QTest.keyClick(edit, Qt.Key.Key_Return)
    settle()


def shown():
    """The text in the box, exactly as it is."""
    return w.gui[FIELD].native.text()


def not_set():
    """The box is empty and says '(not set)' (the display of an unset field), and holds no value."""
    box = w.gui[FIELD]
    return box.native.text() == "" and box.native.placeholderText() == "(not set)" and box.value is None


def known(value, expected):
    return value is not None and abs(value - expected) <= 1e-9 * abs(expected)


def check_known(tag, expected, source="image", raw_unit=None):
    """The field, its state and the request all say `expected` micrometres per pixel, from `source`."""
    inputs, refused = request()
    ok = inputs is not None and known(inputs.get(FIELD), expected)
    expect(tag + "_request_value", ok, (inputs, refused))
    expect(tag + "_field_shows_it", known(field(), expected), field())
    expect(tag + "_state", link().state in ("auto", "user"), link().state)
    if not ok:
        return
    entry = inputs["_calibration"][FIELD]
    expect(tag + "_entry_names_the_image_parameter", entry["of"] == "image", entry)
    expect(tag + "_entry_source", entry["source"] == source, entry)
    for axis in ("x", "y"):
        a = entry["axes"][axis]
        expect(tag + "_axis_" + axis, a["unit"] == "um" and a["source"] == source and a["value"] > 0, a)
    expect(tag + "_axes_only_x_and_y", sorted(entry["axes"]) == ["x", "y"], entry["axes"])
    if raw_unit is not None:
        expect(tag + "_raw_unit_kept", entry["axes"]["x"]["raw"]["unit"] == raw_unit, entry["axes"]["x"])


def check_unknown(tag, warning=None):
    """The field is empty and unset, the run is refused with the sentence of 2.3.1, and nothing is sent."""
    inputs, refused = request()
    expect(
        tag + "_refused_with_the_spec_sentence",
        refused == "⚠ " + REQUIRED.format(param=FIELD, of="image"),
        refused,
    )
    expect(tag + "_nothing_sent", inputs is None)
    expect(tag + "_field_cleared", not_set() and link().state == "unset", (shown(), link().state))
    expect(tag + "_tooltip", w.gui[FIELD].tooltip == TOOLTIP_UNKNOWN.format(of="image"), w.gui[FIELD].tooltip)
    if warning is not None:
        w.status.setText("")
        w._cal_refresh[FIELD]()
        expect(tag + "_warning", warning in w.status.text(), w.status.text())


def run_real():
    w.last_task = None
    w.gui()
    R.wait_done()
    values = next(r["values"] for r in w.last_task.outputs["results"] if r["type"] == "values")
    return values, json.loads((w.last_record / "run.json").read_text(encoding="utf-8"))

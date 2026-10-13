"""Calibration through the real widget (docs/SPEC_WRONG_SCIENCE.md section 2; issues #35 and #38).

Every CAL case and transition of conformance.json is driven through the form, and the check is on the REQUEST a worker would receive
(`_prepare_inputs`, the function a click uses), the reserved `_calibration` input, and, for real runs, what the tool received and what
`run.json` recorded, not only on the number in the field. Sources are real napari layers and real files given as the "or file" input.
A napari layer only holds units pint can parse, so every unit TEXT of the fixtures (`UM`, ` um`, the damaged micro sign, ...) arrives the way
it does in practice: as the unit of an OME-TIFF, which keeps the text exactly; a layer is used as well wherever pint accepts the text.
"""

import json
import shutil
import tempfile
from pathlib import Path

import _paths  # noqa: F401  (must come first)
import _runtools as R
import numpy as np
import tifffile
from _harness import expect, finish, pump, viewer, widget
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


def fresh(tool="Pixel size required"):
    """No layers, no file, the tool's form rebuilt: nothing left over from the last scenario."""
    viewer.layers.clear()
    pump(0.1)
    R.pick(tool)
    w._on_tool_changed()  # a new form: picking the tool that is already chosen would keep the last scenario's state
    w.file_sources["image"].value = None
    pump(0.1)


def choose(layer):
    if layer not in viewer.layers:
        viewer.add_layer(layer)
    w.gui.image.value = layer
    pump(0.05)


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


def type_value(text):
    """The person types into the box and presses Enter: key events, so Qt's own edit signals fire."""
    spin = w.gui[FIELD].native
    edit = spin.lineEdit()
    edit.selectAll()
    QTest.keyClicks(edit, text)
    QTest.keyClick(spin, Qt.Key.Key_Return)
    pump(0.05)


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
    expect(tag + "_field_cleared", field() == 0 and link().state == "unset", (field(), link().state))
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


# ---- the cases of conformance.json, through the form -----------------------------------------------------------------------------
def scenario(tag, build, expected, warning=None, source="image"):
    fresh()
    kind, thing = build
    if kind == "layer":
        choose(thing)
    else:
        w.file_sources["image"].value = thing
        pump(0.1)
    if expected == "unknown":
        check_unknown(tag, warning)
    else:
        check_known(tag, expected, source)


def layer_scenarios(ident, scale, unit, expected, warning=None, suffix=""):
    """One source text, every way it can arrive: as the units of a napari layer (when pint accepts it) and as an OME-TIFF given as a file."""
    unit = unit[0] if isinstance(unit, list | tuple) else unit
    layer = pint_layer(scale, unit)
    # pint rewrites the text before the host sees it (' um' and the damaged micro sign become real units): such a layer says nothing about
    # the text, so it is used only when the text survives, or when the fixture expects a calibration anyway (micro sign, Angstrom)
    if layer is not None and (expected != "unknown" or [str(u) for u in layer.units] == [unit, unit]):
        scenario("%s%s_layer" % (ident, suffix), ("layer", layer), expected, warning)
    scenario("%s%s_file" % (ident, suffix), ("file", ome_file(scale, unit)), expected, warning, source="file")


c = CASES
layer_scenarios("CAL-01", [1, 1], ["micrometer"] * 2, c["CAL-01"]["expect"]["um_per_px"])
layer_scenarios("CAL-02", [1, 1], ["pixel"] * 2, "unknown")
layer_scenarios("CAL-03", [1, 1], ["millimeter"] * 2, c["CAL-03"]["expect"]["um_per_px"])
for i, units in enumerate(c["CAL-04"]["input"]["units"]):
    layer_scenarios("CAL-04", c["CAL-04"]["input"]["scale"], units, "unknown", suffix="_%d" % i)
for i, v in enumerate(c["CAL-05"]["input"]["variants"]):
    layer_scenarios("CAL-05", v["scale"], v["unit"], c["CAL-05"]["expect"]["um_per_px"], suffix="_%d" % i)
layer_scenarios(
    "CAL-06", c["CAL-06"]["input"]["scale"], ["um", "um"], "unknown", c["CAL-06"]["expect"]["warning"]
)
layer_scenarios("CAL-07", [1, 1], ["second"] * 2, "unknown", c["CAL-07"]["expect"]["warning"])
for i, (v, e) in enumerate(
    zip(c["CAL-08"]["input"]["variants"], c["CAL-08"]["expect"]["um_per_px_each"], strict=True)
):
    layer_scenarios("CAL-08", v["pixelWidth"], v["unit"], e, suffix="_%d" % i)
print("unsupported (a QuPath source): CAL-09, CAL-T7")

# CAL-10..14: TIFF files given as the "or file" input
files = {
    "CAL-10_0": (
        tiff("c10a.tif", imagej=True, resolution=(1.0, 1.0), metadata={"unit": "micron"}),
        1.0,
        "file",
    ),
    "CAL-10_1": (tiff("c10b.tif"), "unknown", "file"),
    "CAL-10_2": (tiff("c10c.tif", resolution=(1.0, 1.0), resolutionunit="NONE"), "unknown", "file"),
    "CAL-11": (tiff("c11.tif", resolution=(72, 72), resolutionunit="INCH"), "unknown", "file"),
    "CAL-12": (tiff("c12.tif", resolution=(96, 96), resolutionunit="INCH"), "unknown", "file"),
    "CAL-13_0": (tiff("c13a.tif", resolution=(28.35, 28.35), resolutionunit="CENTIMETER"), "unknown", "file"),
    "CAL-13_1": (tiff("c13b.tif", resolution=(37.8, 37.8), resolutionunit="CENTIMETER"), "unknown", "file"),
    "CAL-14": (
        tiff("c14.tif", resolution=(25400, 25400), resolutionunit="INCH"),
        c["CAL-14"]["expect"]["um_per_px"],
        "file",
    ),
}
for tag, (path, expected, source) in files.items():
    scenario(tag, ("file", path), expected, source=source)
expect("CAL-14_the_source_is_the_file", c["CAL-14"]["expect"]["source"] == "file")

for i, (v, e) in enumerate(
    zip(c["CAL-15"]["input"]["variants"], c["CAL-15"]["expect"]["um_per_px_each"], strict=True)
):
    layer_scenarios("CAL-15", v["scale"], v["unit"], e, suffix="_%d" % i)
layer_scenarios(
    "CAL-16",
    c["CAL-16"]["input"]["scale"],
    c["CAL-16"]["input"]["unit"],
    "unknown",
    c["CAL-16"]["expect"]["warning"],
)
for i, (v, e) in enumerate(
    zip(c["CAL-17"]["input"]["variants"], c["CAL-17"]["expect"]["um_per_px_each"], strict=True)
):
    layer_scenarios("CAL-17", v["scale"], v["unit"], e, suffix="_%d" % i)
within, beyond = c["CAL-18"]["input"]["variants"]
layer_scenarios("CAL-18", within["scale"], within["unit"], 0.5002, suffix="_within")
layer_scenarios(
    "CAL-18", beyond["scale"], beyond["unit"], "unknown", "pixels are not square", suffix="_beyond"
)
for i, name in enumerate(CAL["unit_match_refused"]):
    layer_scenarios("CAL-19", 1.0, name, "unknown", suffix="_%d" % i)
for i, (v, e) in enumerate(
    zip(c["CAL-20"]["input"]["variants"], c["CAL-20"]["expect"]["um_per_px_each"], strict=True)
):
    layer_scenarios("CAL-20", v["scale"], v["unit"], e, suffix="_%d" % i)

# a stock napari layer with pint units (the common case, and issue #38)
fresh()
choose(Image(DATA, name="mm", scale=(1, 1), units="millimeter"))
check_known("issue38_millimetre_layer", 1000.0, raw_unit="millimeter")
fresh()
choose(Image(DATA, name="um", scale=(1, 1), units="micrometer"))
check_known("issue38_micrometre_layer", 1.0, raw_unit="micrometer")
fresh()
choose(Image(DATA, name="px", scale=(1, 1)))
check_unknown("issue38_default_pixel_layer")

# ---- transitions ---------------------------------------------------------------------------------------------------------------
A = Image(DATA, name="A", scale=(0.25, 0.25), units="micrometer")
B = Image(DATA, name="B", scale=(0.5, 0.5), units="micrometer")
U = Image(
    DATA, name="U", scale=(0.25, 0.25)
)  # a scale without units: not calibrated (the old code read it as micrometres)
uncalibrated_file = tiff("uncal.tif")


def start(*layers):
    fresh()
    for layer in layers:
        viewer.add_layer(layer)
    pump(0.1)


start(A, B, U)
choose(A)
check_known("CAL-T1_A", 0.25, raw_unit="micrometer")
choose(B)
check_known("CAL-T1_B", 0.5, raw_unit="micrometer")
expect("CAL-T1_A_is_in_no_request", "0.25" not in json.dumps(request()[0]))

# T2 (and issue #35): A -> uncalibrated B. Required: refused. Optional: null, and A's value is in no request.
start(A, U)
choose(A)
check_known("CAL-T2_before", 0.25)
choose(U)
check_unknown("CAL-T2_required")
fresh("Pixel size optional")
viewer.add_layer(A)
viewer.add_layer(U)
choose(A)
inputs, refused = request()
expect("CAL-T2_optional_A_is_sent", inputs is not None and known(inputs[FIELD], 0.25), (inputs, refused))
choose(U)
inputs, refused = request()
expect("CAL-T2_optional_runs", inputs is not None, refused)
expect("CAL-T2_optional_sends_null", inputs is not None and FIELD in inputs and inputs[FIELD] is None, inputs)
expect(
    "CAL-T2_optional_no_calibration_entry",
    inputs is not None and FIELD not in inputs.get("_calibration", {}),
    inputs,
)
expect("CAL-T2_A_is_in_no_request", "0.25" not in json.dumps(inputs))

# T3: A, the person types 0.3, switch to B -> stays 0.3, source user
start(A, B)
choose(A)
type_value("0.3")
expect("CAL-T3_typing_makes_it_user", link().state == "user" and known(field(), 0.3), (link().state, field()))
choose(B)
check_known("CAL-T3", 0.3, source="user")
entry = request()[0]["_calibration"][FIELD]
expect(
    "CAL-T3_both_axes_are_user",
    entry["axes"]["x"]["source"] == "user" and entry["axes"]["y"]["source"] == "user",
    entry,
)
expect(
    "CAL-T3_tooltip_names_the_value",
    "0.3" in w.gui[FIELD].tooltip and "overrides" in w.gui[FIELD].tooltip,
    w.gui[FIELD].tooltip,
)

# T4: user(0.3), the person clears the field (types 0, or presses the button), source B -> auto 0.5
type_value("0")
expect("CAL-T4_clearing_by_typing_zero", link().state == "auto", link().state)
check_known("CAL-T4_zero", 0.5)
type_value("0.3")
expect("CAL-T4_user_again", link().state == "user")
for button in w.gui:
    if getattr(button, "text", "") == "use the image's calibration":
        button.native.click()
pump(0.1)
expect("CAL-T4_button_state", link().state == "auto", link().state)
check_known("CAL-T4_button", 0.5)

# T5: open image A (0.25), file B uncalibrated -> unset, run refused (not A's value); T6: file cleared -> auto 0.25 (A)
start(A)
choose(A)
check_known("CAL-T5_before", 0.25)
w.file_sources["image"].value = uncalibrated_file
pump(0.1)
check_unknown("CAL-T5")
w.file_sources["image"].value = None
pump(0.1)
check_known("CAL-T6", 0.25)

# the file is the exported source and wins over the open image when it is calibrated
w.file_sources["image"].value = tiff(
    "cal05.tif", imagej=True, resolution=(2.0, 2.0), metadata={"unit": "micron"}
)
pump(0.1)
check_known("file_wins_over_the_open_image", 0.5, source="file")

# T8: a required linked field with the declared default 1.0 and a source that is unknown: refused, the default is not sent
start()
expect(
    "CAL-T8_no_image_at_all_shows_not_set", field() == 0 and link().state == "unset", (field(), link().state)
)
choose(U)
check_unknown("CAL-T8")
inputs, _ = request()
expect("CAL-T8_the_default_is_not_sent", inputs is None)

# T9: the person types 0.25, the value the field already shows as the automatic one, then the image becomes uncalibrated
start(A, U)
choose(A)
expect("CAL-T9_field_shows_the_auto_value", link().state == "auto" and known(field(), 0.25))
type_value("0.25")
expect("CAL-T9_typing_the_same_value_is_still_an_edit", link().state == "user", link().state)
choose(U)
check_known("CAL-T9", 0.25, source="user")
expect("CAL-T9_state_stays_user", link().state == "user")

# a programmatic change of the source never makes the field `user`
start(A, B)
choose(A)
choose(B)
expect("programmatic_set_is_not_user", link().state == "auto", link().state)

# ---- the whole path: a real worker receives it, and run.json records it ----------------------------------------------------------
start(A)
choose(A)
values, record = run_real()
expect(
    "real_run_the_tool_received_the_pixel_size",
    w.last_task.status == "COMPLETE" and values["pixel_size"] == 0.25,
    values,
)
entry = record["inputs"]["_calibration"][FIELD]
expect(
    "real_run_json_has_the_per_axis_entry",
    entry["axes"]["x"]["value"] == 0.25 and entry["source"] == "image",
    entry,
)
expect("real_run_json_inputs_have_the_value", record["inputs"][FIELD] == 0.25, record["inputs"])

start(A)
choose(A)
type_value("0.3")
values, record = run_real()
expect("real_run_user_value", values["pixel_size"] == 0.3, values)
expect(
    "real_run_user_value_is_recorded_as_user",
    record["inputs"]["_calibration"][FIELD]["source"] == "user",
    record["inputs"],
)

start()
w.file_sources["image"].value = tiff(
    "real.tif", imagej=True, resolution=(1 / 0.325, 1 / 0.325), metadata={"unit": "um"}
)
pump(0.1)
values, record = run_real()
expect("real_run_file_calibration", abs(values["pixel_size"] - 0.325) < 1e-9, values)
expect(
    "real_run_file_source_is_recorded",
    record["inputs"]["_calibration"][FIELD]["source"] == "file",
    record["inputs"],
)
expect(
    "real_run_file_raw_is_recorded",
    record["inputs"]["_calibration"][FIELD]["axes"]["x"]["raw"]["unit"] == "um",
    record["inputs"],
)

fresh("Pixel size optional")
viewer.add_layer(U)
choose(U)
values, record = run_real()
expect("real_run_optional_receives_none", values["was_none"] == 1.0, values)
expect(
    "real_run_optional_records_null",
    record["inputs"][FIELD] is None and FIELD not in record["inputs"].get("_calibration", {}),
    record["inputs"],
)

# a required field with no calibration never reaches a worker
fresh()
viewer.add_layer(U)
choose(U)
w.last_task = None
before, task_before = len(R.folders("runs")), w.task
w.gui()
pump(0.3)
expect("blocked_run_starts_no_worker", w.last_task is None and w.task is task_before, w.status.text())
expect(
    "blocked_run_says_why",
    w.status.text() == "⚠ " + REQUIRED.format(param=FIELD, of="image"),
    w.status.text(),
)
expect("blocked_run_leaves_no_record", len(R.folders("runs")) == before)

finish()

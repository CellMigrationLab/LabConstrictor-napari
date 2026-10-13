"""Calibration transitions CAL-T1..T9 and the whole path (docs/SPEC_WRONG_SCIENCE.md 2.2, 2.3; issue #35), through the real widget.
Each step checks the field, its state AND the request a worker receives; real runs check what the tool received and `run.json`.
test_calibration.py drives CAL-01..20 (the same helpers, in _calhelpers.py)."""

import json

import _paths  # noqa: F401  (must come first)
import _runtools as R
from _calhelpers import (
    FIELD,
    REQUIRED,
    check_known,
    check_unknown,
    choose,
    expect,
    field,
    finish,
    fresh,
    known,
    link,
    request,
    run_real,
    settle,
    tiff,
    type_value,
    viewer,
    w,
)
from napari.layers import Image

DATA = __import__("numpy").zeros((6, 6), "uint16")

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
    settle()


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
settle()
expect("CAL-T4_button_state", link().state == "auto", link().state)
check_known("CAL-T4_button", 0.5)

# T5: open image A (0.25), file B uncalibrated -> unset, run refused (not A's value); T6: file cleared -> auto 0.25 (A)
start(A)
choose(A)
check_known("CAL-T5_before", 0.25)
w.file_sources["image"].value = uncalibrated_file
settle()
check_unknown("CAL-T5")
w.file_sources["image"].value = None
settle()
check_known("CAL-T6", 0.25)

# the file is the exported source and wins over the open image when it is calibrated
w.file_sources["image"].value = tiff(
    "cal05.tif", imagej=True, resolution=(2.0, 2.0), metadata={"unit": "micron"}
)
settle()
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
settle()
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
settle()
expect("blocked_run_starts_no_worker", w.last_task is None and w.task is task_before, w.status.text())
expect(
    "blocked_run_says_why",
    w.status.text() == "⚠ " + REQUIRED.format(param=FIELD, of="image"),
    w.status.text(),
)
expect("blocked_run_leaves_no_record", len(R.folders("runs")) == before)

finish()

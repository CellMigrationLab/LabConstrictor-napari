"""Run identity (SPEC_WRONG_SCIENCE section 4; conformance.json fixtures RUN-01..RUN-06), through the real napari widget and a real worker.

A run is frozen at the click (`RunSnapshot`): the layer objects it names, the selection geometry by value, the app and the tool. Each
case below changes something while the run is going (a gate file holds the tool) and checks what the person would see.
"""

import dataclasses
import uuid

import _paths  # noqa: F401  (must come first)
import _runtools as R
import numpy as np
from _harness import expect, finish, pump, viewer, widget
from labconstrictor_tools import conformance

from napari_labconstrictor import _snapshot, _widget

w = widget
C = conformance.load()
WS = C["wrong_science"]
M = WS["retention"]["markers"]
R.use_recorder()
unsupported = []

ids = {f["id"] for f in WS["run_identity"]["fixtures"]}
for needed in ("RUN-01", "RUN-02", "RUN-03", "RUN-04", "RUN-05", "RUN-06"):
    expect("fixture_%s_is_in_conformance_json" % needed, needed in ids)
expect(
    "target_unavailable_sentence_is_the_conformance_text",
    C["messages"]["target_unavailable"]["template"] == _snapshot.TARGET_UNAVAILABLE_TEXT,
    _snapshot.TARGET_UNAVAILABLE_TEXT,
)
expect("target_unavailable_is_a_host_internal_code", _snapshot.TARGET_UNAVAILABLE in C["host_internal_codes"])


def fresh(scale_a=(2.0, 2.0), scale_b=(5.0, 5.0)):
    viewer.layers.clear()
    pump(0.2)
    a = viewer.add_image(np.ones((8, 8), np.uint8), name="A", scale=scale_a)
    b = viewer.add_image(np.full((8, 8), 2, np.uint8), name="B", scale=scale_b)
    return a, b


def start_on(layer, tool="Gated points"):
    """Start the delayed tool on `layer`; returns the gate that releases it once the worker is running."""
    R.pick(tool)
    w.gui.image.value = layer
    gate = R.new_gate()
    w.gui.gate.value = str(gate)
    R.start()
    R.wait_until(lambda: w.task is not None and not w.task.done.is_set())
    pump(0.4)
    return gate


def drawn(run_id=None):
    out = [layer for layer in viewer.layers if layer.name.startswith("runapp:")]
    if run_id is not None:
        out = [layer for layer in out if layer.metadata.get("labconstrictor", {}).get("run_id") == run_id]
    return out


def points_of(run_id):
    return next((layer for layer in drawn(run_id) if layer.name.startswith("runapp:spots")), None)


def newest_results():
    return R.folders("results")[-1]


# ---- the snapshot itself: immutable, copies by value ------------------------------------------------------------------------------
A, B = fresh()
rect = np.array([[4.5, 4.5], [4.5, 15.5], [15.5, 15.5], [15.5, 4.5]])
F = viewer.add_image(np.full((40, 40), 3, np.uint8), name="F")
shapes = viewer.add_shapes([rect], shape_type="rectangle", name="sel")
R.pick("Region stats")
w.gui.image.value = F
viewer.layers.selection = {shapes}
w.region_toggles["region"].value = True
snap = w._take_snapshot({"image": F, "region": None, "gate": ""})
expect("snapshot_has_a_uuid4_run_id", uuid.UUID(snap.run_id).version == 4, snap.run_id)
expect("snapshot_names_the_layer_object", snap.sources["image"].layer is F)
try:
    snap.run_id = "other"
    changed = True
except dataclasses.FrozenInstanceError:
    changed = False
expect("snapshot_is_frozen", not changed)


def assign(mapping, key):
    mapping[key] = "x"  # a read-only mapping refuses this with a TypeError


for label, mapping, key in (("values", snap.values, "gate"), ("tool", snap.tool, "id")):
    try:
        assign(mapping, key)
        changed = True
    except TypeError:
        changed = False
    expect("snapshot_%s_cannot_be_assigned_to" % label, not changed)
expect("snapshot_tool_is_a_copy", snap.tool is not w.tool and dict(snap.tool) == dict(w.tool))
before = snap.selection.vertices[0].copy()
shapes.data = [rect + 10]
expect(
    "selection_is_copied_by_value",
    np.array_equal(snap.selection.vertices[0], before)
    and not np.array_equal(np.asarray(shapes.data[0]), before),
)
expect("selection_copy_is_read_only", not snap.selection.vertices[0].flags.writeable)
expect(
    "selection_holds_its_layer_object_and_shape_types",
    snap.selection.layer is shapes and snap.selection.shape_types == ("rectangle",),
)
w.region_toggles["region"].value = False

# ---- RUN-01: start on A, activate B: the result is on A's frame, nothing on B -----------------------------------------------------
A, B = fresh()
gate = start_on(A)
run_id = w.snapshot.run_id
w.gui.image.value = B  # activate B in the form ...
viewer.layers.selection = {B}  # ... and in the layer list
R.release(gate)
R.wait_done()
points = points_of(run_id)
expect("RUN-01_points_are_drawn", points is not None, [layer.name for layer in viewer.layers])
expect(
    "RUN-01_points_are_on_A_not_B",
    points is not None and tuple(points.scale) == (2.0, 2.0),
    points and points.scale,
)
expect("RUN-01_nothing_took_B_s_frame", all(tuple(layer.scale) != (5.0, 5.0) for layer in drawn(run_id)))
expect("RUN-01_B_is_untouched", tuple(B.scale) == (5.0, 5.0) and not B.metadata)
expect("RUN-01_status_is_a_plain_success", w.status.text().startswith("✔ done"), w.status.text())
expect(
    "every_drawn_result_carries_the_run_id",
    len(drawn(run_id)) >= 2
    and all(layer.metadata["labconstrictor"]["run_id"] == run_id for layer in drawn(run_id)),
    [(layer.name, layer.metadata) for layer in drawn()],
)
expect(
    "a_table_dock_carries_the_run_id",
    w._docks[("runapp", "stats")].property("labconstrictor_run_id") == run_id,
)
expect(
    "the_run_record_carries_the_run_id",
    R.read_json(w.last_record / "run.json")["run_id"] == run_id,
)

# ---- RUN-04: start on A, close A: outputs kept, status names the run and the path, no exception ------------------------------------
A, B = fresh()
gate = start_on(A)
run_id = w.snapshot.run_id
viewer.layers.remove(A)
R.release(gate)
R.wait_done()
folder = newest_results()
expected = C["messages"]["target_unavailable"]["template"].format(run_id=run_id, source="A", path=folder)
expect(
    "RUN-04_nothing_is_drawn_for_the_closed_source", drawn(run_id) == [], [layer.name for layer in drawn()]
)
expect("RUN-04_status_names_run_id_source_and_path", expected in w.status.text(), (expected, w.status.text()))
expect(
    "RUN-04_outputs_are_kept",
    (folder / "spots.csv").is_file() and (folder / "mask.tif").is_file(),
    list(folder.iterdir()),
)
expect(
    "RUN-04_outputs_are_in_an_owned_results_folder",
    R.valid_owner(folder, "result", M) == [] and R.done_status(folder, M) == "ok",
)
record = R.read_json(w.last_record / "run.json")
expect(
    "RUN-04_run_record_points_at_the_kept_files",
    all(
        str(folder) in r["path"]
        for r in record["results"]
        if "path" in r and r["type"] in ("points", "labels")
    ),
    record["results"],
)
expect("RUN-04_run_record_is_ok", R.done_status(w.last_record, M) == "ok")
expect(
    "RUN-04_results_that_need_no_source_are_still_shown",
    ("runapp", "stats") in w._docks and w.message_label.isVisible(),
)
expect("RUN-04_job_folder_is_gone", not w._job_dir.exists())
expect("RUN-04_widget_is_usable_after", w.gui.call_button.enabled and w.app_box.enabled)

# identity is the object, not the name: a new layer called "A" is not the source
A, B = fresh()
gate = start_on(A)
run_id = w.snapshot.run_id
viewer.layers.remove(A)
viewer.add_image(np.ones((8, 8), np.uint8), name="A", scale=(2.0, 2.0))
R.release(gate)
R.wait_done()
expect(
    "RUN-04_a_new_layer_with_the_same_name_is_not_the_source",
    drawn(run_id) == [] and "no longer open" in w.status.text(),
    w.status.text(),
)

# the source is still open but its data changed size: not drawn either (the spec has one sentence for 'gone'; this is the conservative reading)
A, B = fresh()
gate = start_on(A)
run_id = w.snapshot.run_id
A.data = np.ones((9, 9), np.uint8)
R.release(gate)
R.wait_done()
expect(
    "RUN-04_a_source_that_changed_size_is_not_drawn_on",
    drawn(run_id) == [] and "changed size" in w.status.text(),
    w.status.text(),
)

# ---- RUN-02: the selection and the image are those of the click ---------------------------------------------------------------------
A, B = fresh()
F = viewer.add_image(np.full((40, 40), 3, np.uint8), name="F")
G = viewer.add_image(np.full((40, 40), 7, np.uint8), name="G")
shapes = viewer.add_shapes([rect], shape_type="rectangle", name="sel")  # 11 x 11 pixel centres inside
R.pick("Region stats")
w.gui.image.value = F
viewer.layers.selection = {shapes}
w.region_toggles["region"].value = True
real_export = _widget.export_layer


def tampering(layer, picked, path):
    real_export(layer, picked, path)
    shapes.data = [
        np.array([[20.5, 20.5], [20.5, 24.5], [24.5, 24.5], [24.5, 20.5]])
    ]  # the person edits the selection ...
    viewer.layers.selection = {G}  # ... selects another layer ...
    w.gui.image.value = G  # ... and picks another image, all while the export is going


_widget.export_layer = tampering
R.quick_run()
_widget.export_layer = real_export
values = next(r["values"] for r in w.last_task.outputs["results"] if r["type"] == "values")
expect(
    "RUN-02_mask_is_the_selection_of_the_click",
    values["mask_pixels"] == 121 and values["mask_max"] == 1,
    values,
)
expect("RUN-02_image_is_the_image_of_the_click", values["image_sum"] == 3 * 40 * 40, values)
expect(
    "RUN-02_the_selection_really_changed_meanwhile",
    len(shapes.data) == 1 and np.asarray(shapes.data[0])[0][0] == 20.5,
)

# ---- RUN-03: switch the app and the tool while it runs: the result is still the tool that was started -------------------------------
A, B = fresh()
gate = start_on(A)
run_id = w.snapshot.run_id
w.app_box.value = "synthetic"
pump(0.2)
w.tool_box.value = "Scalar echo"
pump(0.4)
R.release(gate)
R.wait_done()
points = points_of(run_id)
expected_meta = {"labconstrictor": {"run_id": run_id, "app": "runapp", "tool": "gated_points"}}
expect(
    "RUN-03_result_metadata_is_the_started_tool",
    points is not None and dict(points.metadata) == expected_meta,
    points and points.metadata,
)
expect(
    "RUN-03_layer_name_is_the_started_app",
    points is not None and points.name.startswith("runapp:"),
    points and points.name,
)
record = R.read_json(w.last_record / "run.json")
expect(
    "RUN-03_run_record_is_the_started_tool",
    record["tool"] == "gated_points" and record["app"] == "runapp",
    (record["app"], record["tool"]),
)
expect("RUN-03_the_form_shows_the_new_tool", w.tool_box.value == "Scalar echo")

# ---- RUN-05: the layer is moved during the run: points follow the CURRENT transform of the same layer ------------------------------
R.pick("Gated points")
A, B = fresh()
gate = start_on(A)
run_id = w.snapshot.run_id
A.scale = (3.0, 3.0)
R.release(gate)
R.wait_done()
points = points_of(run_id)
expect(
    "RUN-05_points_follow_the_current_scale_of_A",
    points is not None and tuple(points.scale) == (3.0, 3.0),
    points and points.scale,
)
unsupported.append(
    "RUN-05 translate / rotate / shear / affine: UNSUPPORTED here - placement carries only the scale until the coordinate-frame "
    "change (issue #33); the scale half is tested above"
)

# ---- RUN-06: two runs in a row, A then B: each result has its own run id and lands on its own source --------------------------------
A, B = fresh()
R.pick("Gated points")
w.gui.image.value = A
R.quick_run()
first = w.snapshot.run_id
w.gui.image.value = B
R.quick_run()
second = w.snapshot.run_id
expect(
    "RUN-06_two_different_uuid4_run_ids",
    first != second and uuid.UUID(first).version == uuid.UUID(second).version == 4,
)
pa, pb = points_of(first), points_of(second)
expect("RUN-06_first_result_is_on_A", pa is not None and tuple(pa.scale) == (2.0, 2.0), pa and pa.scale)
expect("RUN-06_second_result_is_on_B", pb is not None and tuple(pb.scale) == (5.0, 5.0), pb and pb.scale)
runs = R.folders("runs")[-2:]
expect(
    "RUN-06_each_record_has_its_own_run_id",
    [R.read_json(p / "run.json")["run_id"] for p in runs] == [first, second],
)

for line in unsupported:
    print(line)
finish()

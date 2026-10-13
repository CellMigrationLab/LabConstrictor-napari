"""RegionOf: 'use the selection' sends the selected Shapes layer as labels 1..N of the image size (and refuses what it cannot send)."""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import _paths  # noqa: F401  (must come first)
import napari
import numpy as np
import tifffile
from _paths import EVIDENCE
from qtpy.QtWidgets import QApplication

subprocess.run(
    [sys.executable, "-m", "labconstrictor_tools", "register", "--name", "interactions", "--prefix", sys.prefix,
     "--module", "labconstrictor_tools.examples.interactions", "--version", "0.0"],
    check=True, capture_output=True,
)  # fmt: skip

v = napari.Viewer(show=True)
v.window._qt_window.resize(1500, 850)
qa = QApplication.instance()
_, w = v.window.add_plugin_dock_widget("napari-labconstrictor", "LabConstrictor tools")
report, failures = {}, []


def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        qa.processEvents()
        time.sleep(0.02)


def until(condition, timeout=120):
    end = time.time() + timeout
    while not condition() and time.time() < end:
        qa.processEvents()
        time.sleep(0.05)
    pump(0.4)


def run():
    w.last_task = None
    w.gui()
    until(lambda: w.last_task is not None and w.task is w.last_task)
    pump(0.8)


def expect(name, condition, detail=""):
    report[name] = bool(condition)
    if not condition:
        failures.append("%s %s" % (name, detail))


image = np.zeros((60, 80), np.uint8)
image[5:15, 5:15] = 255  # two bright squares: one in the top-left, one bottom-right
image[40:50, 60:70] = 255
v.add_image(image, name="field")
w.app_box.value = "interactions"
pump(0.3)
w.tool_box.value = "Find bright spots"
pump(1.0)
w.gui["threshold"].value = 0.5
toggle = w.region_toggles.get("region")
expect("use_the_selection_box_exists", toggle is not None and not toggle.value)
expect("chooser_is_active_while_off", w.gui["region"].enabled)

run()
everywhere = len(v.layers["interactions:spots"].data)
expect(
    "without_the_selection_the_whole_image_is_searched",
    everywhere > 0 and w.last_task.status == "COMPLETE",
    everywhere,
)

# a selected Shapes layer around the top-left square only
shapes = v.add_shapes(
    [np.array([[0, 0], [0, 25], [25, 25], [25, 0]])], shape_type="polygon", name="my region"
)
v.layers.selection = {shapes}
toggle.value = True
pump(0.3)
expect("chooser_yields_to_the_selection", not w.gui["region"].enabled)
run()
spots = v.layers["interactions:spots"].data
expect(
    "only_the_region_is_searched",
    w.last_task.status == "COMPLETE"
    and 0 < len(spots) < everywhere
    and spots[:, 0].max() < 25
    and spots[:, 1].max() < 25,
    (w.status.text(), len(spots), spots.max(axis=0).tolist()),
)

# several shapes arrive as labels 1..N
shapes.add([np.array([[35, 55], [35, 75], [55, 75], [55, 55]])], shape_type="polygon")
v.layers.selection = {shapes}
inputs = w._export_inputs({"image": v.layers["field"], "region": None}, Path(tempfile.mkdtemp()))
mask = tifffile.imread(inputs["region"])
expect(
    "mask_has_the_image_size_and_labels_1_to_N",
    mask.shape == (60, 80) and sorted(set(mask.flat)) == [0, 1, 2],
    (mask.shape, sorted(set(mask.flat))),
)

# refusals are explained, not guessed around
v.layers.selection = {v.layers["field"]}
try:
    w._export_inputs({"image": v.layers["field"], "region": None}, Path(tempfile.mkdtemp()))
    expect("no_shapes_layer_selected_is_refused", False, "no error")
except ValueError as error:
    expect("no_shapes_layer_selected_is_refused", "select a Shapes layer" in str(error), str(error))
empty = v.add_shapes(name="empty")
v.layers.selection = {empty}
try:
    w._export_inputs({"image": v.layers["field"], "region": None}, Path(tempfile.mkdtemp()))
    expect("empty_shapes_layer_is_refused", False, "no error")
except ValueError as error:
    expect("empty_shapes_layer_is_refused", "has no shapes" in str(error), str(error))
outside = v.add_shapes(
    [np.array([[200, 200], [200, 220], [220, 220], [220, 200]])], shape_type="polygon", name="outside"
)
v.layers.selection = {outside}
try:
    w._export_inputs({"image": v.layers["field"], "region": None}, Path(tempfile.mkdtemp()))
    expect("shapes_outside_the_image_are_refused", False, "no error")
except ValueError as error:
    expect("shapes_outside_the_image_are_refused", "outside the image" in str(error), str(error))
scaled = v.add_shapes(
    [np.array([[0, 0], [0, 25], [25, 25], [25, 0]])], shape_type="polygon", name="scaled", scale=(2, 2)
)
v.layers.selection = {scaled}
# SPEC_WRONG_SCIENCE 1.2 / 1.4 (issue #31): a Shapes layer with another transform is CONVERTED through the world, never refused and never
# rasterised in its own raw coordinates. The same vertices at scale 2 cover world 0..50, i.e. image pixels 0..49 (not 0..24)
inputs = w._export_inputs({"image": v.layers["field"], "region": None}, Path(tempfile.mkdtemp()))
mask = tifffile.imread(inputs["region"])
expect(
    "a_shapes_layer_with_another_scale_is_converted_not_refused",
    mask.shape == (60, 80)
    and mask[40, 40] == 1
    and mask[10, 10] == 1
    and mask[55, 10] == 0
    and mask[10, 55] == 0
    and (mask > 0).sum() > 2000,
    (mask.shape, int((mask > 0).sum())),
)

# copy as command says that a selection cannot be copied
v.layers.selection = {shapes}
text = w.copy_as_command("terminal")
expect(
    "copy_notes_the_selection", "the selection cannot be copied" in text and "region=region.tif" in text, text
)

v.layers.remove(empty)
v.layers.remove(outside)
v.layers.remove(scaled)
v.layers.selection = {shapes}
pump(1.0)
v.screenshot(str(EVIDENCE / "widget_region.png"), canvas_only=False)
print(json.dumps(report, indent=2))
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)

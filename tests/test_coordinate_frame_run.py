"""The coordinate frame through the real widget and a real worker (SPEC_WRONG_SCIENCE section 1; CF-02, 04, 05, 07, 08, 11 and RUN-02).

test_coordinate_frame.py checks every case of conformance.json against the presenter and the export; here the whole path runs: the form,
the snapshot, the export of the image and of the RegionOf mask, a worker process that reports what it RECEIVED, the result files and
the layers that appear. Fixture data (ASYM, the rectangle, the cases) is read from `labconstrictor_tools.conformance`.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING

import _paths  # noqa: F401  (must come first)
import _runtools as R
import numpy as np
import tifffile
from _harness import expect, finish, pump, viewer, widget
from labconstrictor_tools import conformance

from napari_labconstrictor import _widget

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any

    from napari.layers import Image

w = widget
C = conformance.load()
WS = C["wrong_science"]["coordinate"]
CASES = {c["id"]: c for c in WS["cases"]}
ROWS, COLUMNS = WS["image"]["shape"]
ASYM = np.fromfunction(lambda y, x: 100 * y + x, (ROWS, COLUMNS)).astype(np.uint16)
RECT = np.array(WS["rect"], float)
R.use_recorder()


def close(a: "Any", b: "Any", tol: float = 1e-9) -> bool:
    return bool(np.allclose(np.asarray(a, float), np.asarray(b, float), atol=tol))


def fresh() -> None:
    viewer.layers.clear()
    pump(0.2)


def source(case: "dict[str, Any]", name: str = "ASYM") -> "Image":
    spec = case["source"]
    return viewer.add_image(
        ASYM, name=name, **{k: spec[k] for k in ("scale", "translate", "affine") if k in spec}
    )


def result_values() -> "Any":
    return next(r["values"] for r in w.last_task.outputs["results"] if r["type"] == "values")


def plain_world(point: "Sequence[float]", spec: "dict[str, Any]") -> list[float]:
    """Napari data (y, x) -> world for a fixture's `source`, plain Python (an oracle that does not use napari)."""
    y, x = point
    if "affine" in spec:
        m = spec["affine"]
        return [m[0][0] * y + m[0][1] * x + m[0][2], m[1][0] * y + m[1][1] * x + m[1][2]]
    scale, translate = spec.get("scale", [1, 1]), spec.get("translate", [0, 0])
    return [y * scale[0] + translate[0], x * scale[1] + translate[1]]


def of_this_run(prefix: str) -> "Any":
    """The layer the last run drew whose name starts with `prefix` (several runs may have drawn layers of the same name)."""
    run_id = w.snapshot.run_id
    return next(
        layer
        for layer in viewer.layers
        if layer.name.startswith(prefix) and layer.metadata.get("labconstrictor", {}).get("run_id") == run_id
    )


def world_vertices(layer: "Any", vertices: "Sequence[Sequence[float]] | np.ndarray") -> np.ndarray:
    return np.array([layer.data_to_world(tuple(v)) for v in vertices])


# ---- RegionOf: what the worker RECEIVED is the exported image and the mask on the right pixels (CF-01, 02, 04) --------------------------
for ident in ("CF-01", "CF-02", "CF-04"):
    case = CASES[ident]
    fresh()
    image = source(case)
    spec = case.get("shapes_layer", {})
    vertices = spec.get("vertices_world", "rect")
    data = (
        RECT
        if vertices == "rect"
        else RECT + np.array([100, 0]) if isinstance(vertices, str) else np.array(vertices, float)
    )
    shapes = viewer.add_shapes([data], shape_type="polygon", name="selection")
    R.pick("Region values")
    w.gui.image.value = image
    viewer.layers.selection = {shapes}
    w.region_toggles["region"].value = True
    R.quick_run()
    values = result_values()
    expect("%s_run_completes" % ident, w.last_task.status == "COMPLETE", w.status.text())
    expect("%s_worker_got_the_exported_image_size" % ident, values["image_shape"] == [ROWS, COLUMNS], values)
    expect("%s_worker_got_a_mask_of_that_size" % ident, values["mask_shape"] == [ROWS, COLUMNS], values)
    expect(
        "%s_worker_got_the_fixture_mask_pixels" % ident,
        values["mask_pixels"] == len(WS["rect_mask_pixels"]),
        values,
    )
    expect(
        "%s_worker_sees_the_fixture_values_under_the_mask" % ident,
        values["values"] == WS["rect_mask_values"],
        values,
    )

# equal scale, different origin: the old code painted the raw coordinates; the layers agree in the world, not in their data (issue #31)
fresh()
image = source(CASES["CF-02"])
shapes = viewer.add_shapes([RECT + np.array([100, 0])], shape_type="polygon", name="selection")
raw = shapes.to_labels(labels_shape=(ROWS, COLUMNS))
expect("the_raw_coordinates_would_have_missed_the_image_entirely", not raw.any())

# ---- RUN-02 with the transform: moving the image or the selection after the click changes neither the export nor the mask -------------
fresh()
image = source(CASES["CF-02"])
shapes = viewer.add_shapes([RECT + np.array([100, 0])], shape_type="polygon", name="selection")
other = viewer.add_image(ASYM, name="other")
R.pick("Region values")
w.gui.image.value = image
viewer.layers.selection = {shapes}
w.region_toggles["region"].value = True
real_export = _widget.export_layer


def tampering(layer: "Image", picked: "Any", path: Path) -> None:
    real_export(layer, picked, path)
    shapes.translate = (30, 30)  # the person drags the selection ...
    shapes.rotate = 45
    image.translate = (0, 0)  # ... and the image ...
    viewer.layers.selection = {other}  # ... and selects something else, all while the export is going


_widget.export_layer = tampering
R.quick_run()
_widget.export_layer = real_export
values = result_values()
expect(
    "RUN-02_mask_follows_the_transform_of_the_click",
    values["mask_pixels"] == 6 and values["values"] == WS["rect_mask_values"],
    values,
)

# ---- points, outlines and labels of a real worker land where the source is, for every transform (CF-02..CF-05, #33, #34) --------------
for ident in ("CF-02", "CF-03", "CF-04", "CF-05"):
    case = CASES[ident]
    fresh()
    image = source(case)
    R.pick("Gated points")
    w.gui.image.value = image
    R.quick_run()
    spots = viewer.layers["runapp:spots"]
    mask = viewer.layers["runapp:mask"]
    drawn = spots.data_to_world(tuple(spots.data[0]))
    expect("%s_run_completes" % ident, w.last_task.status == "COMPLETE", w.status.text())
    # the test tool always reports the pixel (2, 3); CF-05's own point is (2, 4), so its answer is computed from the fixture's matrix
    want_world = case["expect"]["world"] if case["point"] == [2, 3] else plain_world([2, 3], case["source"])
    expect(
        "%s_worker_points_land_on_the_fixture_world_position" % ident,
        close(drawn, want_world),
        (drawn, want_world),
    )
    expect(
        "%s_labels_overlay_the_image_pixel_for_pixel" % ident,
        all(close(mask.data_to_world(p), image.data_to_world(p)) for p in [(0, 0), (2, 3), (7, 11)]),
    )
    R.pick("Outline and mark")
    w.gui.image.value = image
    R.quick_run()
    outline = viewer.layers["runapp:outline"]
    got = world_vertices(outline, np.asarray(outline.data[0]))
    want = world_vertices(image, RECT)
    expect(
        "%s_outline_of_the_worker_lies_on_the_rectangle_of_the_image" % ident,
        close(np.sort(got, axis=0), np.sort(want, axis=0)),
        (got, want),
    )

# a rotated, sheared, scaled and translated source all at once: the same 'point at pixel (2, 3)' follows napari's own conversion
fresh()
image = viewer.add_image(
    ASYM,
    name="everything",
    scale=(0.5, 0.25),
    translate=(10, 20),
    rotate=30,
    shear=[0.2],
    affine=[[1, 0.1, 3], [0, 1, 4], [0, 0, 1]],
)
R.pick("Gated points")
w.gui.image.value = image
R.quick_run()
spots = viewer.layers["runapp:spots"]
expect(
    "everything_points_follow_data_to_world",
    close(spots.data_to_world(tuple(spots.data[0])), image.data_to_world((2, 3))),
)
mask = viewer.layers["runapp:mask"]
expect(
    "everything_labels_follow_data_to_world", close(mask.data_to_world((5, 9)), image.data_to_world((5, 9)))
)

# ---- CF-08: run A (an image result shown), then run B with a file input: the points land in the file's pixel frame ---------------------
fresh()
asym_file = R.WORK / "ASYM.tif"
tifffile.imwrite(asym_file, ASYM)
image = viewer.add_image(ASYM, name="A", translate=(100, 0), scale=(0.5, 0.5))
R.pick("Gated points")
w.gui.image.value = image
R.quick_run()
first_mask = viewer.layers["runapp:mask"]
w.file_sources["image"].value = asym_file  # run B: the chooser still says A, but a file was chosen
pump(0.4)
R.quick_run()
spots = of_this_run("runapp:spots")
expect("CF-08_run_B_completes", w.last_task.status == "COMPLETE", w.status.text())
expect(
    "CF-08_points_are_in_the_pixel_frame_of_the_file",
    close(spots.data_to_world(tuple(spots.data[0])), (2, 3)) and tuple(spots.scale) == (1.0, 1.0),
    (spots.data_to_world(tuple(spots.data[0])), spots.scale),
)
expect(
    "CF-08_no_image_layer_was_added_for_the_file",
    all(layer.name == "A" or layer.name.startswith("runapp:") for layer in viewer.layers),
    [layer.name for layer in viewer.layers],
)
expect(
    "CF-08_the_image_of_run_A_is_untouched",
    close(image.translate, (100, 0)) and tuple(image.scale) == (0.5, 0.5) and not image.metadata,
)
w.file_sources["image"].value = None
pump(0.3)

# ---- CF-11: the result has another size than the exported image --------------------------------------------------------------------
fresh()
image = viewer.add_image(ASYM, name="A", translate=(100, 0))
R.pick("Half size labels")
w.gui.image.value = image
R.quick_run()
mask = viewer.layers["runapp:mask"]
expect(
    "CF-11_status_says_not_aligned",
    "not aligned" in w.status.text() and "'mask' is 6 x 4 but 'A' was exported as 12 x 8" in w.status.text(),
    w.status.text(),
)
expect(
    "CF-11_shown_at_the_pixel_origin",
    close(mask.data_to_world((0, 0)), (0, 0)) and tuple(mask.scale) == (1.0, 1.0),
)
expect("CF-11_the_source_is_not_moved", close(image.translate, (100, 0)))

# ---- points and outlines of a tool with no image input are NOT drawn at the pixel origin (1.1.5, 1.1.6) -------------------------------
fresh()
before_files = set(R.folders("results"))
R.pick("Marks without an image")
R.quick_run()
text = w.status.text()
expect("noimage_run_completes", w.last_task.status == "COMPLETE", text)
expect(
    "noimage_no_points_layer_is_drawn",
    not any(layer.name.startswith("runapp:") for layer in viewer.layers),
    [layer.name for layer in viewer.layers],
)
expect(
    "noimage_the_points_are_a_table",
    "table 'spots' (2 rows)" in text and ("runapp", "spots") in w._docks,
    text,
)
expect("noimage_the_outline_is_listed_as_a_file", "outlines 'outline' (not drawn" in text, text)
new = [p for p in R.folders("results") if p not in before_files]
files = sorted(f.name for p in new for f in p.iterdir() if not f.name.startswith("."))
expect(
    "noimage_both_files_are_kept_in_an_owned_folder",
    len(new) == 1 and files == ["outline.geojson", "spots.csv"],
    files,
)
expect(
    "noimage_the_status_names_the_kept_files", all(str(p) in text for p in new if any(p.glob("*.csv"))), text
)
kept_csv = next(iter(new[0].glob("*.csv")), None) if new else None
expect(
    "noimage_the_kept_points_have_their_contents",
    kept_csv is not None and kept_csv.read_text().split() == ["y,x", "2.0,3.0", "4.0,5.0"],
    kept_csv and kept_csv.read_text(),
)
geo = next(iter(new[0].glob("*.geojson")), None) if new else None
expect(
    "noimage_the_kept_outline_has_its_contents",
    geo is not None and len(json.loads(geo.read_text())["features"]) == 1,
)
expect("noimage_the_job_folder_is_gone", not Path(w._job_dir).exists())

for line in (
    "affine overlays (the Affine result type) still use the target's scale only: not part of #31, #33, #34 (not a points, shapes, image or labels result)",
):
    print("NOT COVERED:", line)
finish()

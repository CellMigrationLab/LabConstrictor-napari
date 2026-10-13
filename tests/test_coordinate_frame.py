"""The coordinate frame (SPEC_WRONG_SCIENCE section 1; conformance.json CF-01..CF-14), with real napari layers and real affines.

The fixtures come from `labconstrictor_tools.conformance` (never copied here): the ASYM image, the rectangle, the cases and their expected
world coordinates. For each Napari case a real Image layer is built with the case's transform; then

* the RegionOf mask is made by the real export (`selection_mask` on a run snapshot) and its actual pixels are read back from the TIFF the
  worker would get, next to the pixels of the exported image;
* a points result, an outline result and a labels result are drawn by the real `ResultPresenter` and their world coordinates are
  compared with the numbers of the fixture AND with napari's own `source.data_to_world(c - 0.5)` (the formula of 1.1.3).

No worker runs here (test_coordinate_frame_run.py does that); a presenter is given the result files the worker would have written.
"""

import json
import tempfile
from pathlib import Path

import _paths  # noqa: F401  (must come first)
import numpy as np
import tifffile
from _harness import expect, finish, pump, viewer
from labconstrictor_tools import conformance

from napari_labconstrictor import _export, _frame, _results, _snapshot

C = conformance.load()
WS = C["wrong_science"]["coordinate"]
CASES = {c["id"]: c for c in WS["cases"]}
WORK = Path(tempfile.mkdtemp(prefix="lcframe_"))
unsupported: list[str] = []

for ident in CASES.keys() | {"CF-%02d" % i for i in range(1, 15)}:
    expect("fixture_%s_is_in_conformance_json" % ident, ident in CASES)
expect(
    "size_mismatch_sentence_is_the_conformance_text",
    C["messages"]["size_mismatch"]["template"] == _frame.SIZE_MISMATCH_TEXT,
)
expect(
    "refusal_suffix_is_the_conformance_text",
    C["messages"]["refusal_suffix"]["template"] == _frame.REFUSAL_SUFFIX,
)
for code in (_frame.FRAME_UNSUPPORTED, _frame.SELECTION_MIXED_PLANES):
    expect("%s_is_a_host_internal_code" % code, code in C["host_internal_codes"])

ROWS, COLUMNS = WS["image"]["shape"]
ASYM = np.fromfunction(lambda y, x: 100 * y + x, (ROWS, COLUMNS)).astype(np.uint16)
expect(
    "ASYM_is_the_fixture_image",
    WS["image"]["value"] == "100*y + x" and ASYM[2, 3] == 203 and ASYM.dtype == np.uint16,
)
RECT = np.array(WS["rect"], float)  # [y, x] per vertex (decided, section 8)
MASK = [tuple(p) for p in WS["rect_mask_pixels"]]
TOOL = {
    "id": "t",
    "label": "t",
    "inputs": [
        {"name": "image", "type": "image", "label": "Image"},
        {"name": "region", "type": "labels", "label": "Region", "region_of": "image"},
    ],
    "outputs": [{"name": "mask", "type": "labels", "display": {"apply_to": "image"}}],
}
PARAM = {"label": "Region", "name": "region", "region_of": "image"}


def make_source(spec: "dict[str, Any]", name: str = "source") -> "Image":
    """A real Image layer with the transform of a fixture's `source`."""
    kwargs = {k: spec[k] for k in ("scale", "translate", "affine") if k in spec}
    data = [np.zeros(s, np.uint16) for s in spec["levels"]] if "levels" in spec else ASYM
    if "levels" in spec:
        data[0] = ASYM
    layer = viewer.add_image(data, name=name, multiscale="levels" in spec, **kwargs)
    return layer


def snapshot_for(layer: "Image | None" = None, shapes: "Any" = None, files: "Any" = None) -> "RunSnapshot":
    values = {"image": layer, "region": None}
    return _snapshot.take(
        "app",
        TOOL,
        values,
        files=files or {},
        regions=["region"] if shapes is not None else [],
        selection_layer=shapes,
    )


def region_mask(layer: "Image", shapes: "Any") -> tuple[np.ndarray, np.ndarray]:
    """(the mask pixels as (y, x) tuples, the exported image) of the real export of this selection."""
    snap = snapshot_for(layer, shapes)
    job = Path(tempfile.mkdtemp(dir=WORK))
    path = _export.selection_mask(snap.selection, PARAM, None, snap.sources["image"], job, "Image")
    _export.export_layer(layer, None, job / "image.tif")
    mask = tifffile.imread(path)
    image = tifffile.imread(job / "image.tif")
    return mask, image


def csv_points(name: str, rows: "Sequence[Sequence[float]]") -> "dict[str, Any]":
    path = WORK / (name + ".csv")
    path.write_text("y,x\n" + "".join("%s,%s\n" % tuple(r) for r in rows), encoding="utf-8")
    return {"type": "points", "name": name, "path": str(path), "n": len(rows), "apply_to": "image"}


def geojson_rect(name: str, vertices_yx: "Sequence[Sequence[float]] | np.ndarray") -> "dict[str, Any]":
    ring = [[x, y] for y, x in vertices_yx]
    ring.append(ring[0])
    path = WORK / (name + ".geojson")
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [ring]}}]}),
        encoding="utf-8",
    )  # fmt: skip
    return {"type": "shapes", "name": name, "path": str(path), "n": 1, "apply_to": "image"}


def labels_result(name: str, array: np.ndarray) -> "dict[str, Any]":
    path = WORK / (name + ".tif")
    tifffile.imwrite(path, array)
    return {"type": "labels", "name": name, "path": str(path), "apply_to": "image"}


def presenter_for(snap: "RunSnapshot", app: str = "cf", replace: "Iterable[str]" = ()) -> "ResultPresenter":
    return _results.ResultPresenter(
        viewer,
        app,
        {k: v for k, v in snap.values.items()},
        replace=replace,
        image_inputs=["image"],
        snapshot=snap,
    )


def close(a: "Any", b: "Any", tol: float = 1e-9) -> bool:
    return bool(np.allclose(np.asarray(a, float), np.asarray(b, float), atol=tol))


def fresh() -> None:
    viewer.layers.clear()
    pump(0.1)


def check_placement(ident: str, case: "dict[str, Any]", layer: "Image") -> "RunSnapshot":
    """Points, an outline and a labels result for the case's source: drawn coordinates against the fixture and against napari."""
    expected_world = case["expect"]["world"]
    point = case["point"]
    snap = snapshot_for(layer)
    presenter = presenter_for(snap, app="pl_" + ident.replace("-", ""))
    presenter.show(csv_points("p", [point]))
    points = viewer.layers["pl_%s:p" % ident.replace("-", "")]
    drawn = points.data_to_world(tuple(points.data[0]))
    expect("%s_points_world_is_the_fixture" % ident, close(drawn, expected_world), (drawn, expected_world))
    # the formula of 1.1.3: result.data_to_world(p) == source.data_to_world(c - 0.5), c = x0 + (x + 0.5) * downsample
    c = [0.0 + (v + 0.5) * 1.0 for v in point]
    napari_world = layer.data_to_world(tuple(v - 0.5 for v in c))
    expect("%s_points_follow_source_data_to_world" % ident, close(drawn, napari_world), (drawn, napari_world))
    back = layer.world_to_data(drawn)
    expect(
        "%s_target_px_is_the_pixel_of_the_source" % ident,
        close(back, case["expect"].get("target_px", point)),
        (back, case["expect"]),
    )
    # the outline: every vertex of the rectangle lands where the source sends it
    presenter.show(geojson_rect("o", RECT))
    outline = viewer.layers["pl_%s:o" % ident.replace("-", "")]
    ring = np.asarray(outline.data[0])
    got = np.array([outline.data_to_world(tuple(v)) for v in ring])
    want = np.array([layer.data_to_world(tuple(v)) for v in RECT])
    expect(
        "%s_outline_vertices_follow_the_source" % ident,
        close(np.sort(got, axis=0), np.sort(want, axis=0)),
        (got, want),
    )
    # image and labels results of the exported size carry the whole transform (#34)
    presenter.show(labels_result("m", np.ones((ROWS, COLUMNS), np.int32)))
    mask = viewer.layers["pl_%s:m" % ident.replace("-", "")]
    ok = all(
        close(mask.data_to_world(p), layer.data_to_world(p))
        for p in [(0, 0), (2, 3), (ROWS - 1, COLUMNS - 1), (1, 7)]
    )
    expect("%s_labels_overlay_the_source_pixel_for_pixel" % ident, ok)
    return snap


# ---- CF-01 .. CF-06: every Napari case with a real layer and the case's transform ----------------------------------------------------
for ident in ("CF-01", "CF-02", "CF-03", "CF-04", "CF-05", "CF-06"):
    case = CASES[ident]
    fresh()
    layer = make_source(case["source"])
    check_placement(ident, case, layer)
    if ident == "CF-06":
        expect("CF-06_the_layer_is_multiscale", layer.multiscale and len(layer.data) == 2)
        mask_probe = None
        job = Path(tempfile.mkdtemp(dir=WORK))
        _export.export_layer(layer, None, job / "image.tif")
        exported = tifffile.imread(job / "image.tif")
        expect(
            "CF-06_export_is_level_0",
            list(exported.shape) == case["expect"]["export_shape"] and (exported == ASYM).all(),
            exported.shape,
        )
    if "mask" in case["expect"] or ident == "CF-06":
        # the selection: the fixture's world vertices (or the rect itself) on a layer with an identity transform
        spec = case.get("shapes_layer", {})
        vertices = spec.get("vertices_world", "rect")
        if vertices == "rect":
            data = RECT
        elif vertices == "rect + [100, 0]":
            data = RECT + np.array([100, 0])
        else:
            data = np.array(vertices, float)
        if ident == "CF-06":
            data = RECT + np.array([100, 0])
        shapes = viewer.add_shapes([data], shape_type="polygon", name="selection")
        mask, image = region_mask(layer, shapes)
        got = sorted(zip(*np.nonzero(mask), strict=True))
        expect("%s_mask_pixels_are_the_fixture" % ident, got == sorted(MASK), got)
        expect(
            "%s_mask_is_the_size_of_the_exported_image" % ident,
            list(mask.shape) == [ROWS, COLUMNS],
            mask.shape,
        )
        expect("%s_exported_image_is_ASYM" % ident, (image == ASYM).all())
        values = sorted(int(v) for v in image[mask > 0])
        expect(
            "%s_pixels_under_the_mask_are_the_fixture_values" % ident,
            values == WS["rect_mask_values"],
            values,
        )

# the same selection, but the Shapes layer has its OWN transform (the layers agree in the world, not in their data): the mask is the same
fresh()
layer = make_source(CASES["CF-04"]["source"])
world_rect = np.array(CASES["CF-04"]["shapes_layer"]["vertices_world"], float)
shapes = viewer.add_shapes(
    [world_rect], shape_type="polygon", name="moved", translate=(7, -3), scale=(2, 2), rotate=15
)
shapes.data = [
    np.array([shapes.world_to_data(tuple(v)) for v in world_rect])
]  # same world position, other data
mask, _ = region_mask(layer, shapes)
expect(
    "a_shapes_layer_with_its_own_transform_gives_the_same_mask",
    sorted(zip(*np.nonzero(mask), strict=True)) == sorted(MASK),
    sorted(zip(*np.nonzero(mask), strict=True)),
)

# ---- every shape type survives a rotated and sheared image (rectangle, polygon, ellipse: the outline is what it was) ------------------------
from napari.layers import Shapes  # noqa: E402

fresh()
layer = make_source({"affine": [[0.8, -0.5, 30], [0.4, 1.1, -12], [0, 0, 1]], "scale": [1, 1]})
inside = np.array([[3.0, 4.0], [3.0, 8.0], [5.0, 8.0], [5.0, 4.0]])  # rect in image pixels
world_of = lambda lay, arr: np.array([lay.data_to_world(tuple(v)) for v in arr])  # noqa: E731
for kind in ("rectangle", "polygon"):
    shapes = viewer.add_shapes([world_of(layer, inside)], shape_type=kind, name="k_" + kind)
    mask, _ = region_mask(layer, shapes)
    reference = Shapes([inside], shape_type=kind).to_labels(labels_shape=(ROWS, COLUMNS)) > 0
    differing = int((reference != (mask > 0)).sum())
    expect(
        "%s_under_an_affine_image_gives_the_pixels_of_the_untransformed_shape" % kind,
        differing == 0,
        differing,
    )

# an ellipse on a strongly sheared image: the reference is the ellipse in the image's own pixels, sampled finely (an independent polygon)
fresh()
big = viewer.add_image(
    np.zeros((60, 80), np.uint16), name="big", affine=[[1, 0.8, 0], [0.3, 1, 0], [0, 0, 1]]
)
corners = np.array([[10.0, 10.0], [10.0, 40.0], [30.0, 40.0], [30.0, 10.0]])
ellipse = viewer.add_shapes([world_of(big, corners)], shape_type="ellipse", name="k_ellipse")
mask, _ = region_mask(big, ellipse)
angle = np.linspace(0, 2 * np.pi, 720, endpoint=False)[:, None]
outline = (
    corners.mean(0)
    + np.cos(angle) * (corners[1] - corners[0]) / 2
    + np.sin(angle) * (corners[2] - corners[1]) / 2
)
truth = Shapes([outline], shape_type="polygon").to_labels(labels_shape=(60, 80)) > 0
expect(
    "ellipse_under_a_sheared_image_is_the_ellipse_of_the_image_pixels",
    truth.sum() > 300 and int((truth != (mask > 0)).sum()) == 0,
    (int(truth.sum()), int((truth != (mask > 0)).sum())),
)

# ---- a 2D plane of a stack: the leading axes must not move the plane (1.3 note) ------------------------------------------------------
fresh()
stack = viewer.add_image(
    np.zeros((3, ROWS, COLUMNS), np.uint16), name="stack", translate=(0, 100, 20), scale=(1, 0.5, 0.5)
)
kwargs = _frame.result_transform(stack, 2)
probe = _results.ResultPresenter(viewer, "nd", {}, image_inputs=["image"])
expect(
    "a_plane_of_a_stack_is_placed_by_its_trailing_axes",
    close(
        viewer.add_points(np.zeros((1, 2)), **kwargs).data_to_world((2, 3)),
        stack.data_to_world((0, 2, 3))[1:],
    ),
)
viewer.layers.pop()
for label, moved in (
    ("scaled", {"scale": (2, 1, 1)}),
    ("shifted", {"translate": (5, 0, 0)}),
    ("coupled", {"affine": np.array([[1, 0, 0, 0], [0.5, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])}),
):
    bad = viewer.add_image(np.zeros((3, ROWS, COLUMNS), np.uint16), name="bad_" + label, **moved)
    try:
        _frame.result_transform(bad, 2)
        expect("a_stack_whose_%s_leading_axis_moves_the_plane_is_refused" % label, False, "no error")
    except _frame.FrameError as error:
        expect(
            "a_stack_whose_%s_leading_axis_moves_the_plane_is_refused" % label,
            error.code == "frame_unsupported_transform",
            error,
        )
try:
    _frame.result_transform(viewer.add_image(ASYM, name="flat"), 3)
    expect("a_3d_result_on_a_2d_image_is_refused", False, "no error")
except _frame.FrameError as error:
    expect("a_3d_result_on_a_2d_image_is_refused", error.code == "frame_unsupported_transform", error)

# ---- a source with everything at once: scale, translate, rotate, shear, affine, units ------------------------------------------------
fresh()
layer = viewer.add_image(
    ASYM, name="everything", scale=(0.5, 0.25), translate=(10, 20), rotate=30, shear=[0.2],
    affine=[[1, 0.1, 3], [0, 1, 4], [0, 0, 1]], units=("micrometer", "micrometer"),
)  # fmt: skip
snap = snapshot_for(layer)
presenter = presenter_for(snap, app="all")
presenter.show(csv_points("p", [[2, 3], [7, 11], [0, 0]]))
points = viewer.layers["all:p"]
got = np.array([points.data_to_world(tuple(v)) for v in points.data])
want = np.array([layer.data_to_world(tuple(v)) for v in ([2, 3], [7, 11], [0, 0])])
expect("scale_translate_rotate_shear_affine_all_carried", close(got, want), (got, want))
expect(
    "the_units_are_carried_too",
    tuple(str(u) for u in points.units) == ("micrometer", "micrometer"),
    points.units,
)
expect("a_scale_only_check_would_fail_here", not close(got, np.array([[1.0, 0.75], [3.5, 2.75], [0, 0]])))

# ---- CF-07, CF-08: a file input is its own pixel frame; no layer is looked for ---------------------------------------------------------
fresh()
asym_file = WORK / "ASYM.tif"
tifffile.imwrite(asym_file, ASYM)
decoy = viewer.add_image(ASYM, name="DECOY", translate=(100, 0))
snap = snapshot_for(decoy, files={"image": asym_file})
expect(
    "CF-07_the_snapshot_frame_is_the_file",
    snap.frame("image").is_file and snap.frame("image").label == "ASYM.tif",
)
expect(
    "CF-07_the_file_frame_has_the_files_size",
    snap.frame("image").shape == (ROWS, COLUMNS),
    snap.frame("image").shape,
)
presenter = presenter_for(snap, app="f7")
presenter.show(csv_points("p", [CASES["CF-07"]["point"]]))
points = viewer.layers["f7:p"]
expect(
    "CF-07_napari_world_is_the_pixel",
    close(points.data_to_world(tuple(points.data[0])), CASES["CF-07"]["expect"]["napari_world"]),
)
expect(
    "CF-07_no_units_and_identity",
    tuple(points.scale) == (1.0, 1.0)
    and not np.any(points.translate)
    and np.allclose(points.affine.affine_matrix, np.eye(3)),
)
expect(
    "CF-07_the_decoy_gets_nothing",
    close(decoy.translate, (100, 0))
    and not decoy.metadata
    and [layer.name for layer in viewer.layers] == ["DECOY", "f7:p"],
    [layer.name for layer in viewer.layers],
)
presenter.show(labels_result("m", np.ones((ROWS, COLUMNS), np.int32)))
expect(
    "CF-07_a_labels_result_lies_in_the_files_pixels",
    close(viewer.layers["f7:m"].data_to_world((2, 3)), (2, 3)),
)
# a different size next to a file is stated, too
text = presenter.show(labels_result("m2", np.ones((ROWS // 2, COLUMNS // 2), np.int32)))
expect("CF-07_size_mismatch_against_a_file_is_stated", "not aligned" in text and "ASYM.tif" in text, text)

fresh()
other = viewer.add_image(ASYM, name="A", translate=(50, 50), scale=(2, 2))
snap_a = snapshot_for(other)
presenter_for(snap_a, app="s8a").show(
    labels_result("shown", np.ones((ROWS, COLUMNS), np.int32))
)  # run A: ImageOut shown
last_shown = viewer.layers["s8a:shown"]
snap_b = snapshot_for(other, files={"image": asym_file})  # run B: file input; the chooser still says A
presenter_for(snap_b, app="s8b").show(csv_points("p", [[2, 3]]))
points = viewer.layers["s8b:p"]
expect("CF-08_points_land_in_the_file_frame", close(points.data_to_world(tuple(points.data[0])), (2, 3)))
expect(
    "CF-08_the_last_shown_image_gets_nothing",
    tuple(last_shown.scale) == (2.0, 2.0)
    and close(last_shown.translate, (50, 50))
    and len(viewer.layers) == 3,
)

# ---- CF-11: a labels result of another size -------------------------------------------------------------------------------------------
fresh()
layer = make_source({"translate": [100, 0]})
snap = snapshot_for(layer)
presenter = presenter_for(snap, app="c11")
case = CASES["CF-11"]
small = np.ones(case["result"]["shape"], np.int32)
text = presenter.show(labels_result("m", small))
expected = C["messages"]["size_mismatch"]["template"].format(name="m", w=6, h=4, source="source", w2=12, h2=8)
expect("CF-11_the_sentence_is_the_conformance_one", text == expected, text)
expect(case["id"] + "_status_says_not_aligned", case["expect"]["status_contains"] in text)
shown = viewer.layers["c11:m"]
expect(
    "CF-11_identity_transform",
    tuple(shown.scale) == (1.0, 1.0)
    and not np.any(shown.translate)
    and close(shown.data_to_world((0, 0)), (0, 0)),
)
expect(
    "CF-11_said_once", text.count("not aligned") == 1 and not presenter.messages, (text, presenter.messages)
)

# ---- CF-12: Replace() recomputes the transform ---------------------------------------------------------------------------------------
fresh()
first = make_source({"translate": [100, 0]}, name="first")
second = make_source({"translate": [0, 0]}, name="second")
big = np.ones((ROWS, COLUMNS), np.int32)
presenter_for(snapshot_for(first), app="c12", replace={"m"}).show(labels_result("m", big))
mask = viewer.layers["c12:m"]
expect("CF-12_first_result_is_on_translate_100", close(mask.data_to_world((0, 0)), (100, 0)))
presenter_for(snapshot_for(second), app="c12", replace={"m"}).show(labels_result("m", big))
expect("CF-12_same_layer_replaced_in_place", viewer.layers["c12:m"] is mask)
expect(
    "CF-12_world_of_0_0_is_the_fixture",
    close(mask.data_to_world((0, 0)), CASES["CF-12"]["expect"]["world_of_0_0"]),
    mask.data_to_world((0, 0)),
)
presenter_for(snapshot_for(first), app="c12", replace={"m"}).show(labels_result("m", big))  # and back
expect("CF-12_and_back", close(mask.data_to_world((0, 0)), (100, 0)))
# a scaled, rotated source then no source: back to the documented default, never the previous transform
rotated = make_source({"affine": [[0, -1, 0], [1, 0, 0], [0, 0, 1]], "scale": [3, 3]}, name="rot")
no_source = {**labels_result("m", big)}
no_source.pop("apply_to")
presenter_for(snapshot_for(rotated), app="c12", replace={"m"}).show(labels_result("m", big))
expect("CF-12_rotated_source_is_carried", close(mask.data_to_world((2, 3)), rotated.data_to_world((2, 3))))
plain = _results.ResultPresenter(viewer, "c12", {}, replace={"m"})
plain.show(no_source)
expect(
    "CF-12_no_source_means_the_default_not_the_old_transform",
    close(mask.data_to_world((2, 3)), (2, 3)) and tuple(mask.scale) == (1.0, 1.0),
    mask.data_to_world((2, 3)),
)

# ---- CF-13: a transform that cannot be inverted is refused, nothing is drawn -------------------------------------------------------
fresh()
# napari itself cannot hold such a layer in a viewer (adding it raises LinAlgError), so the real Image class carries the fixture's affine
# outside the viewer: the host's refusal is what is tested, for every kind of result and for a selection
from typing import TYPE_CHECKING

from napari.layers import Image as ImageLayer

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from typing import Any

    from napari.layers import Image

    from napari_labconstrictor._results import ResultPresenter
    from napari_labconstrictor._snapshot import RunSnapshot

layer = ImageLayer(ASYM, name="flat", affine=CASES["CF-13"]["source"]["affine"])
snap = snapshot_for(layer)
presenter = presenter_for(snap, app="c13")
before = len(viewer.layers)
text = presenter.show(csv_points("p", [[2, 3]]))
expect(
    "CF-13_points_are_not_drawn",
    len(viewer.layers) == before and text.startswith(_results.COULD_NOT_DISPLAY),
    (text, len(viewer.layers)),
)
expect(
    "CF-13_the_sentence_names_the_image_and_the_files",
    "'flat'" in text and "nothing was changed; files are in " in text and ".csv" in text,
    text,
)
text = presenter.show(geojson_rect("o", RECT))
expect(
    "CF-13_outlines_are_not_drawn",
    len(viewer.layers) == before and text.startswith(_results.COULD_NOT_DISPLAY),
    text,
)
text = presenter.show(labels_result("m", np.ones((ROWS, COLUMNS), np.int32)))
expect(
    "CF-13_labels_are_not_drawn",
    len(viewer.layers) == before and text.startswith(_results.COULD_NOT_DISPLAY),
    (text, [x.name for x in viewer.layers]),
)
shapes = viewer.add_shapes([RECT], shape_type="polygon", name="sel")
try:
    region_mask(layer, shapes)
    expect("CF-13_a_selection_is_refused", False, "no error")
except _frame.FrameError as error:
    expect(
        "CF-13_a_selection_is_refused_with_the_code",
        error.code == CASES["CF-13"]["expect"].split()[-1],
        error,
    )
expect("CF-13_the_code_is_declared", CASES["CF-13"]["expect"].split()[-1] in C["host_internal_codes"])

# ---- CF-14: downsample and offset (the formula; no host exports at a factor other than 1 here) ------------------------------------
for variant in CASES["CF-14"]["variants"]:
    oy, ox = variant["offset_yx"]
    frame = _frame.Frame(
        "image",
        "x",
        None,
        None,
        (ROWS, COLUMNS),
        None,
        (0.0, 0.0, oy, ox),
        (0, 0),
        float(variant["downsample"]),
    )
    y, x = frame.to_data(*variant["point"])
    c = (float(y) + 0.5, float(x) + 0.5)  # `to_data` is c - 0.5
    expect(
        "CF-14_formula_d%d_offset_%s" % (variant["downsample"], variant["offset_yx"]),
        close(c, variant["expect"]["c_yx"]),
        (c, variant["expect"]),
    )
    if variant["downsample"] != 1:
        unsupported.append(
            "CF-14 downsample %s offset %s: UNSUPPORTED as a host behaviour (this host exports at downsample 1 only); the arithmetic above is the formula"
            % (variant["downsample"], variant["offset_yx"])
        )

for ident in ("CF-09", "CF-10"):
    unsupported.append("%s: QuPath only (crop offset / planes); not applicable to Napari" % ident)
unsupported.append(
    "selection_mixed_planes (1.2.5) and Napari N-D / time axes: Wave 2, not implemented (2D plane only)"
)

for line in unsupported:
    print("UNSUPPORTED:", line)
finish()

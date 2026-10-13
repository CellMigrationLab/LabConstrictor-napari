"""Host parity H05 (NP-6): points and outlines without `apply_to` are placed on the FIRST IMAGE input (PROTOCOL.md), not on the
first input of any type."""

import json
import tempfile
from pathlib import Path

import _paths  # noqa: F401  (must come first)
import numpy as np
from _harness import choose, expect, finish, pump, register, viewer, widget

from napari_labconstrictor._results import FileInput, ResultPresenter

register("roundtrip", "labconstrictor_tools.examples.roundtrip")
work = Path(tempfile.mkdtemp(prefix="lcframe_"))
(work / "pts.csv").write_text("y,x\n1,2\n3,4\n")
(work / "one.geojson").write_text(
    json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [0, 4], [0, 0]]]},
                }
            ],
        }
    )
)
layer = viewer.add_image(np.zeros((8, 8)), name="img", scale=(2.0, 3.0))
points = {"type": "points", "name": "p", "path": str(work / "pts.csv"), "n": 2}
outline = {"type": "shapes", "name": "o", "path": str(work / "one.geojson"), "n": 1}

# the first parameter is a number, the image comes second: the number has no frame
presenter = ResultPresenter(viewer, "a", {"threshold": 0.5, "img": layer}, image_inputs=["img"])
presenter.show(points)
presenter.show(outline)
expect(
    "points_use_the_first_image", tuple(viewer.layers["a:p"].scale) == (2.0, 3.0), viewer.layers["a:p"].scale
)
expect(
    "outlines_use_the_first_image",
    tuple(viewer.layers["a:o"].scale) == (2.0, 3.0),
    viewer.layers["a:o"].scale,
)

# a file given for the image counts as the image, but it is its own PIXEL frame (SPEC_WRONG_SCIENCE 1.3): identity, no units. Its header
# scale is not applied (the layers of the file are never searched and the scale of the file is not a transform of the result)
file_input = FileInput.__new__(FileInput)
file_input.path, file_input.name, file_input.scale = work / "x.tif", "x.tif", (0.5, 0.25)
presenter = ResultPresenter(viewer, "b", {"n": 3, "img": file_input}, image_inputs=["img"])
presenter.show(points)
expect(
    "a_file_image_is_a_pixel_frame_not_its_header_scale",
    tuple(viewer.layers["b:p"].scale) == (1.0, 1.0),
    viewer.layers["b:p"].scale,
)

# apply_to wins over the first image
other = viewer.add_image(np.zeros((8, 8)), name="other", scale=(5.0, 7.0))
presenter = ResultPresenter(viewer, "c", {"img": layer, "other": other}, image_inputs=["img", "other"])
presenter.show({**points, "apply_to": "other"})
expect("apply_to_wins", tuple(viewer.layers["c:p"].scale) == (5.0, 7.0), viewer.layers["c:p"].scale)

# no image input at all: the points are NOT drawn at the pixel origin (SPEC_WRONG_SCIENCE 1.1.5, 1.1.6): a table, and the file is named
presenter = ResultPresenter(viewer, "d", {"threshold": 0.5}, image_inputs=[])
text = presenter.show(points)
expect("no_image_means_no_layer", "d:p" not in viewer.layers, [layer.name for layer in viewer.layers])
expect("no_image_means_a_table", "table 'p' (2 rows)" in text and ("d", "p") in presenter.docks, text)
expect(
    "no_image_the_sentence_names_the_file",
    str(work / "pts.csv") in text and presenter.file_results == [points],
    text,
)
text = presenter.show(outline)
expect("no_image_outlines_are_a_file", "d:o" not in viewer.layers and str(work / "one.geojson") in text, text)
# an apply_to that names something that is not an image is not an image either: no fallback to another layer
presenter = ResultPresenter(viewer, "e", {"threshold": 0.5, "img": layer}, image_inputs=["img"])
presenter.show({**points, "apply_to": "threshold"})
expect("apply_to_a_number_is_not_an_image", "e:p" not in viewer.layers)

# the widget gives the presenter the image parameters of the tool, in the tool's order
choose("roundtrip", "Region box")
widget._begin_run({"image": layer, "region": None}, {}, Path(tempfile.mkdtemp()))
expect(
    "widget_passes_image_inputs",
    widget.presenter.image_inputs == ("image", "region"),
    widget.presenter.image_inputs,
)
widget._set_running(False)
choose("roundtrip", "Echo points")
widget._begin_run({"points": None}, {}, Path(tempfile.mkdtemp()))
expect("a_table_tool_has_no_image_input", widget.presenter.image_inputs == (), widget.presenter.image_inputs)
widget._set_running(False)
pump(0.2)
finish()

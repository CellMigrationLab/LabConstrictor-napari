"""Where a result lands, asserted from the layer data and the fixture file's own TIFF metadata (not from any state of the panel).

The cases of the apps name fixture files. Two ways to hand one to the form (LC_UI_INPUT):
* `layer` (default, what a person does after File > Open): a 2D TIFF is opened as a layer whose scale THIS module computes from the file's
  tags (`fixture_scale`: ImageJ `unit` micron / um with XResolution, or ResolutionUnit centimetre / inch; no resolution or the 72 / 96 dpi
  default is not calibrated: scale 1). A result that belongs to that image must come back with that scale, translate 0 and its pixel grid.
* `file` (the 'or file' row; also used for stacks and non-TIFF files in `layer` mode): SPEC_WRONG_SCIENCE.md 1.3 says results are placed in
  the pixel frame of the file: identity (scale 1, translate 0, no units); the pixel size field is still derived from the file's tags.
Not a test."""

from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import tifffile
from ui_audit_core import AppCtx, pump

TIFF_SUFFIXES = (".tif", ".tiff")
MICRON_UNITS = ("micron", "um", "µm")
CM, INCH = 3, 2  # TIFF ResolutionUnit values


def fixture_scale(path: Path) -> tuple[float, float]:
    """(y, x) micrometres per pixel of a TIFF fixture, or (1, 1) when it states none."""
    with tifffile.TiffFile(path) as tif:
        page = tif.pages[0]
        xres, yres = page.tags.get("XResolution"), page.tags.get("YResolution")
        if xres is None or yres is None:
            return 1.0, 1.0
        per_x, per_y = xres.value[0] / xres.value[1], yres.value[0] / yres.value[1]
        unit = str((tif.imagej_metadata or {}).get("unit", "")).lower()
        code = page.tags["ResolutionUnit"].value if "ResolutionUnit" in page.tags else 1
        if unit in MICRON_UNITS:
            factor = 1.0
        elif int(code) == CM:
            factor = 1e4
        elif int(code) == INCH and round(per_x) not in (72, 96):
            factor = 25400.0
        else:
            return 1.0, 1.0
        return factor / per_y, factor / per_x


def fixture_shape(path: Path) -> tuple[int, int]:
    with tifffile.TiffFile(path) as tif:
        return tuple(tif.pages[0].shape[-2:])  # type: ignore[return-value]


class Frame(NamedTuple):
    """The image an input parameter was given as: its file, the layer scale (y, x) results must come back with, and how it was given."""

    path: Path
    scale: tuple[float, float]
    how: str  # "layer" | "file"


def open_fixture_layer(ctx: AppCtx, name: str, path: Path, kind: str) -> Any | None:
    """Open a 2D TIFF fixture as an image/labels layer with the scale of the file's own tags; None for anything else (stack, other format)."""
    if path.suffix.lower() not in TIFF_SUFFIXES:
        return None
    with tifffile.TiffFile(path) as tif:
        if len(tif.pages[0].shape) != 2 or len(tif.pages) != 1:
            return None
    viewer = ctx.host.viewer
    data, scale = tifffile.imread(path), fixture_scale(path)
    layer_name = path.stem if kind == "image" else path.stem + "_labels"
    if layer_name in viewer.layers:
        return viewer.layers[layer_name]
    layer = (
        viewer.add_labels(data.astype(np.int32), name=layer_name, scale=scale)
        if kind == "labels"
        else viewer.add_image(data, name=layer_name, scale=scale)
    )
    pump(0.2)
    return layer


def calibration_problems(
    ctx: AppCtx, tool: dict[str, Any], inputs: dict[str, Any], frames: dict[str, Frame]
) -> list[str]:
    """A pixel size field the case does not set must show the micrometres per pixel of the image's file tags (x axis); empty when the
    file states none. Read from the form right after it was filled."""
    problems = []
    for param in tool["inputs"]:
        of, name = param.get("pixel_size_of"), param["name"]
        if not of or name in inputs or of not in frames:
            continue
        want = frames[of].path
        scale = fixture_scale(want)[1] if want.suffix.lower() in TIFF_SUFFIXES else 1.0
        text = ctx.host.widget.gui[name].native.text().strip()
        if scale == 1.0 and text not in ("", "1", "1.0"):
            problems.append("%s: the fixture states no calibration but the field shows %r" % (name, text))
        elif scale != 1.0 and (not text or abs(float(text) - scale) > 1e-6 * scale):
            problems.append("%s: shows %r, the fixture's tags give %.6g um per pixel" % (name, text, scale))
    return problems


def placement_problems(ctx: AppCtx, tool: dict[str, Any], frames: dict[str, Frame]) -> list[str]:
    """For every image/labels/points/shapes output that belongs to an input image: scale, translate and pixel grid of its layer."""
    layers = {layer.name: layer for layer in ctx.host.viewer.layers}
    problems = []
    first = next((p["name"] for p in tool["inputs"] if p["type"] in ("image", "labels")), None)
    for out in tool["outputs"]:
        if out["type"] not in ("image", "labels", "points", "shapes"):
            continue
        target = out.get("display", {}).get("apply_to") or (
            first if out["type"] in ("points", "shapes") else None
        )
        frame, layer = frames.get(target) if target else None, layers.get("%s:%s" % (ctx.app, out["name"]))
        if frame is None or layer is None:
            continue  # not tied to an input image the audit knows, or not drawn as a layer (a table or a file: shown_problems asks)
        height, width = fixture_shape(frame.path) if frame.path.suffix.lower() in TIFF_SUFFIXES else (0, 0)
        name = out["name"]
        if not np.allclose(layer.scale[-2:], frame.scale, rtol=1e-6):
            problems.append(
                "%s: layer scale %s, expected %s (%s input)"
                % (name, list(layer.scale[-2:]), list(frame.scale), frame.how)
            )
        if not np.allclose(layer.translate[-2:], 0.0, atol=1e-9):
            problems.append("%s: layer translate %s, expected 0" % (name, list(layer.translate[-2:])))
        if not height:
            continue
        if out["type"] in ("image", "labels") and layer.data.shape[-2:] != (height, width):
            problems.append(
                "%s: %s pixels, the fixture has %s" % (name, layer.data.shape[-2:], (height, width))
            )
        if out["type"] == "points" and len(layer.data):
            ys, xs = np.asarray(layer.data)[:, -2], np.asarray(layer.data)[:, -1]
            if ys.min() < -0.5 or xs.min() < -0.5 or ys.max() > height - 0.5 or xs.max() > width - 0.5:
                problems.append("%s: points outside the %dx%d fixture" % (name, height, width))
        if out["type"] == "shapes" and len(layer.data):
            every = np.concatenate([np.asarray(s)[:, -2:] for s in layer.data])
            if every.min() < -0.5 or every[:, 0].max() > height - 0.5 or every[:, 1].max() > width - 0.5:
                problems.append("%s: outline vertices outside the %dx%d fixture" % (name, height, width))
    return problems

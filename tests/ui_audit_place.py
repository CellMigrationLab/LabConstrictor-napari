"""Where a result lands, asserted from the layer data and the fixture file's own TIFF metadata (not from any state of the panel).

The audit gives a tool its image as a FILE (the 'or file' row), because the cases of the apps name fixture files. The calibration source
is then the file's tags, and the expected layer scale is computed here from them, independently of the plugin's unit code: ImageJ `unit`
(micron / um) with XResolution, or ResolutionUnit centimetre / inch; no resolution, or the 72 / 96 dpi default, is not calibrated
(scale 1, pixels). Translate must be 0 and the pixel grid of a result that belongs to the image must be the image's. Not a test.
"""

from pathlib import Path
from typing import Any

import numpy as np
import tifffile
from ui_audit_core import AppCtx

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


def placement_problems(
    ctx: AppCtx, tool: dict[str, Any], inputs: dict[str, Any], kinds: dict[str, str]
) -> list[str]:  # fmt: skip
    """For every image/labels/points/shapes output that belongs to a TIFF fixture input: scale, translate and pixel grid of its layer."""
    layers = {layer.name: layer for layer in ctx.host.viewer.layers}
    problems = []
    first = next((p["name"] for p in tool["inputs"] if p["type"] in ("image", "labels")), None)
    for out in tool["outputs"]:
        if out["type"] not in ("image", "labels", "points", "shapes"):
            continue
        target = out.get("display", {}).get("apply_to") or (
            first if out["type"] in ("points", "shapes") else None
        )
        value = inputs.get(target) if target else None
        layer = layers.get("%s:%s" % (ctx.app, out["name"]))
        if (
            value is None
            or kinds.get(target) not in ("image", "labels")
            or not str(value).lower().endswith(TIFF_SUFFIXES)
        ):
            continue
        if layer is None:
            continue  # points / outlines that were not drawn (a table or a file) have no layer to place; shown_problems asks for the rest
        path = Path(str(value))
        scale = fixture_scale(path)
        height, width = fixture_shape(path)
        name = out["name"]
        if not np.allclose(layer.scale[-2:], scale, rtol=1e-6):
            problems.append(
                "%s: layer scale %s, the fixture's calibration gives %s"
                % (name, list(layer.scale[-2:]), list(scale))
            )
        if not np.allclose(layer.translate[-2:], 0.0, atol=1e-9):
            problems.append("%s: layer translate %s, expected 0" % (name, list(layer.translate[-2:])))
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

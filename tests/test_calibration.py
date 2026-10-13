"""Calibration through the real widget (docs/SPEC_WRONG_SCIENCE.md section 2; issues #35 and #38).

Every CAL case and transition of conformance.json is driven through the form, and the check is on the REQUEST a worker would receive
(`_prepare_inputs`, the function a click uses), the reserved `_calibration` input, and, for real runs, what the tool received and what
`run.json` recorded, not only on the number in the field. Sources are real napari layers and real files given as the "or file" input.
A napari layer only holds units pint can parse, so every unit TEXT of the fixtures (`UM`, ` um`, the damaged micro sign, ...) arrives the way
it does in practice: as the unit of an OME-TIFF, which keeps the text exactly; a layer is used as well wherever pint accepts the text.
"""

from typing import TYPE_CHECKING

import _paths  # noqa: F401  (must come first)
from _calhelpers import (
    CAL,
    CASES,
    DATA,
    check_known,
    check_unknown,
    choose,
    expect,
    finish,
    fresh,
    ome_file,
    pint_layer,
    settle,
    tiff,
    w,
)
from napari.layers import Image

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any


# ---- the cases of conformance.json, through the form -----------------------------------------------------------------------------
def scenario(
    tag: str,
    build: "tuple[str, Any]",
    expected: float | str,
    warning: str | None = None,
    source: str = "image",
) -> None:
    fresh(rebuild=False)  # nothing is typed here: the source alone decides, so the form is reused
    kind, thing = build
    if kind == "layer":
        choose(thing)
    else:
        w.file_sources["image"].value = thing
        settle()
    if expected == "unknown":
        check_unknown(tag, warning)
    else:
        check_known(tag, expected, source)


def layer_scenarios(
    ident: str,
    scale: "float | Sequence[float]",
    unit: str | list[str] | tuple[str, ...],
    expected: float | str,
    warning: str | None = None,
    suffix: str = "",
) -> None:
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

finish()

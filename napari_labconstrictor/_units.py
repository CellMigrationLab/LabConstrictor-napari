"""Calibration (docs/SPEC_WRONG_SCIENCE.md section 2.1): what a layer or a file says about the length of a pixel, in micrometres.

Units are read from ONE catalog, `wrong_science.calibration.length_units` of `labconstrictor_tools/conformance.json` (this module keeps no
list of its own): symbols match as exact text (case-sensitive, nothing trimmed), words case-insensitively after trimming. Text that is
not in the catalog is an unknown unit and gives UNKNOWN calibration; the number alone (1.0, 0.25) is never evidence, so a bare scale with
napari's default 'pixel' unit is unknown, never assumed to be micrometres. Anisotropic pixels (Y and X differ by more than 1e-3,
relative to the larger) and units that are not a length are unknown too, with a warning.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, cast

from labconstrictor_tools import conformance, log

# What reading a TIFF header can realistically raise: a file that is missing or unreadable (OSError), not a TIFF
# (tifffile.TiffFileError is a ValueError), a damaged or odd tag (ValueError/KeyError/IndexError/TypeError/struct.error).
TIFF_READ_ERRORS = (OSError, ValueError, KeyError, IndexError, TypeError, struct.error)

SQUARE_PIXEL_TOLERANCE = 1e-3  # Y and X pixel sizes closer than this (relative to the larger) count as square (conformance.json too)

# sentences of conformance.json `messages` (tests compare them with the file)
NOT_SQUARE_TEXT = "pixels are not square"
NOT_A_LENGTH_TEXT = "unit '{unit}' is not a length"
DAMAGED_TEXT = "unit text '{unit}' is damaged; enter the pixel size"
DAMAGED_PREFIX = "�"  # the replacement character: a micro sign that was damaged on its way here

# Text that says "no physical unit" (napari's default is 'pixel'; Fiji says 'pixel' or ''): unknown, and not worth a warning.
_NO_UNIT = frozenset({"", "pixel", "pixels", "px", "dimensionless", "none"})

_RESOLUTION_UNIT_NONE, _RESOLUTION_UNIT_INCH, _RESOLUTION_UNIT_CM = 1, 2, 3
_UM_PER_RESOLUTION_UNIT = {_RESOLUTION_UNIT_INCH: 25400.0, _RESOLUTION_UNIT_CM: 10000.0}
_UNIT_NAME_OF_RESOLUTION = {_RESOLUTION_UNIT_INCH: "inch", _RESOLUTION_UNIT_CM: "centimeter"}


@cache
def _catalog() -> tuple[dict[str, float], dict[str, float]]:
    """(symbols, words) -> micrometres per unit, read from conformance.json once."""
    units = conformance.load()["wrong_science"]["calibration"]["length_units"]
    symbols: dict[str, float] = {}
    words: dict[str, float] = {}
    for entry in units.values():
        factor = float(entry["um_per_unit"])
        symbols.update({symbol: factor for symbol in entry["symbols"]})
        words.update({word: factor for word in entry["words"]})
    return symbols, words


def unit_factor(unit: Any) -> tuple[float | None, str | None]:
    """-> (micrometres per unit, warning) for a unit text (or pint unit). (None, None) means "no unit" (pixel, empty); (None, warning)
    a unit that is not in the catalog or is damaged. The factor is never guessed.
    """
    text = "" if unit is None else str(unit)
    if DAMAGED_PREFIX in text:
        return None, DAMAGED_TEXT.format(unit=text)
    symbols, words = _catalog()
    if text in symbols:  # exact: 'UM', ' um', 'mms' are not symbols
        return symbols[text], None
    word = text.strip().lower()
    if word in words:
        return words[word], None
    if word in _NO_UNIT:
        return None, None
    return None, NOT_A_LENGTH_TEXT.format(unit=text)


@dataclass(frozen=True)
class Raw:
    """What the source said about one axis, kept for the run record: the number and the unit text, as found."""

    scale: float | None
    unit: str | None


@dataclass(frozen=True)
class Calibration:
    """The pixel size of one source. `yx` is (y, x) micrometres per pixel, or None when unknown (`warning` may say why)."""

    yx: tuple[float, float] | None
    raw: tuple[Raw, Raw]  # (y, x)
    warning: str | None = None

    @property
    def square(self) -> bool:
        if self.yx is None:
            return False
        y, x = self.yx
        return abs(y - x) <= SQUARE_PIXEL_TOLERANCE * max(abs(y), abs(x))

    @property
    def value(self) -> float | None:
        """What the scalar pixel-size field takes: the mean of X and Y when they agree within the tolerance, else None (unknown).
        The field is never filled from one axis."""
        if self.yx is None or not self.square:
            return None
        return (self.yx[0] + self.yx[1]) / 2

    @property
    def note(self) -> str | None:
        """The warning to show: why the source is unknown, when it is a problem and not just 'no calibration'."""
        if self.warning:
            return self.warning
        if self.yx is not None and not self.square:
            return NOT_SQUARE_TEXT
        return None


UNKNOWN = Calibration(None, (Raw(None, None), Raw(None, None)))


def calibrate(y: tuple[Any, Any], x: tuple[Any, Any]) -> Calibration:
    """Each axis is (scale, unit text): scale times the unit's size in micrometres, or unknown."""
    raw = (_raw(*y), _raw(*x))
    sizes: list[float] = []
    for scale, unit in (y, x):
        factor, warning = unit_factor(unit)
        number = _number(scale)
        if factor is None or number is None or number <= 0:
            return Calibration(None, raw, warning)
        sizes.append(number * factor)
    return Calibration((sizes[0], sizes[1]), raw)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _raw(scale: Any, unit: Any) -> Raw:
    return Raw(_number(scale), None if unit is None else str(unit))


def calibration_of_layer(layer: Any) -> Calibration:
    """A napari layer's `scale` + `units` (the last two axes: Y, X)."""
    scale = [float(v) for v in layer.scale]
    units = list(getattr(layer, "units", None) or [])
    scale_y, scale_x = (scale[-2], scale[-1]) if len(scale) >= 2 else (scale[-1], scale[-1])
    unit_y, unit_x = (
        (units[-2], units[-1]) if len(units) >= 2 else ((units[-1],) * 2 if units else (None, None))
    )
    return calibrate((scale_y, unit_y), (scale_x, unit_x))


# ---- TIFF files -------------------------------------------------------------------------------------------------------------


def _default_looking(resolution: float, code: int) -> bool:
    """72 or 96 dpi (28.35 or 37.80 per cm), within 0.5 %: what software writes when nobody calibrated the image."""
    rule = conformance.load()["wrong_science"]["calibration"]["default_resolution_dpi"]
    defaults = rule["values"] if code == _RESOLUTION_UNIT_INCH else rule["per_cm"]
    return any(abs(resolution - d) <= rule["tolerance_relative"] * d for d in defaults)


def _tag(tags: Any, name: str) -> tuple[float, float] | None:
    """(pixels per resolution unit, size of one pixel in that unit) of a TIFF resolution tag; None when absent."""
    if name not in tags:
        return None
    numerator, denominator = tags[name].value
    if not numerator or not denominator:
        return None
    return numerator / denominator, denominator / numerator


def _ome_pixel_sizes(tif: Any) -> tuple[tuple[Any, Any], tuple[Any, Any]] | None:
    """((size_y, unit_y), (size_x, unit_x)) of the first image's OME Pixels, or None without OME physical sizes. A missing
    PhysicalSizeY means square; a size without a unit text is read as unknown by the caller (the number alone is no evidence).
    """
    import tifffile

    if not getattr(tif, "is_ome", False) or not tif.ome_metadata:
        return None
    root = tifffile.xml2dict(tif.ome_metadata).get("OME", {})
    image = root.get("Image")
    image = image[0] if isinstance(image, list) else image
    pixels = (image or {}).get("Pixels") or {}
    if "PhysicalSizeX" not in pixels:
        return None
    x = (pixels["PhysicalSizeX"], pixels.get("PhysicalSizeXUnit"))
    y = (
        pixels.get("PhysicalSizeY", x[0]),
        pixels.get("PhysicalSizeYUnit", x[1]) if "PhysicalSizeY" in pixels else x[1],
    )
    return y, x


def calibration_from_tiff(path: str | Path) -> tuple[Calibration, str | None]:
    """-> (calibration, problem): `problem` is a sentence when the file could not be read (the calibration is then unknown).
    Precedence (2.1.6): an OME physical size or an ImageJ `unit=` in the file wins over the resolution tags; tags alone count only
    when ResolutionUnit is INCH or CENTIMETER and the resolution does not look like a 72 / 96 dpi default. A failure is logged here.
    """
    import tifffile

    try:
        with tifffile.TiffFile(str(path)) as tif:
            tags = cast(
                tifffile.TiffPage, tif.pages[0]
            ).tags  # the first page of a TIFF is a full page, not a TiffFrame
            ome = _ome_pixel_sizes(tif)
            if ome is not None:
                return calibrate(*ome), None
            x_tag = _tag(tags, "XResolution")
            if x_tag is None:
                return UNKNOWN, None
            per_x, size_x = x_tag
            per_y, size_y = _tag(tags, "YResolution") or x_tag  # a missing YResolution means square
            unit = (tif.imagej_metadata or {}).get("unit") if getattr(tif, "is_imagej", False) else None
            if unit not in (None, ""):  # ImageJ's own unit text: it names the unit, the tags give the number
                return calibrate((size_y, unit), (size_x, unit)), None
            code = int(tags["ResolutionUnit"].value) if "ResolutionUnit" in tags else _RESOLUTION_UNIT_INCH
            if code not in _UM_PER_RESOLUTION_UNIT:  # NONE (or odd): the number has no unit
                return UNKNOWN, None
            name = _UNIT_NAME_OF_RESOLUTION[code]
            raw = (Raw(size_y, name), Raw(size_x, name))
            if _default_looking(per_x, code) or _default_looking(per_y, code):
                return Calibration(None, raw), None
            factor = _UM_PER_RESOLUTION_UNIT[code]
            return Calibration((size_y * factor, size_x * factor), raw), None
    except (
        *TIFF_READ_ERRORS,
        tifffile.TiffFileError,
    ) as error:  # not a TIFF / unreadable: the person types the value
        log.warning("napari: cannot read the calibration of %s (%s: %s)", path, type(error).__name__, error)
        return UNKNOWN, "could not read the pixel size from %s (%s): type it" % (path, error)


def microns_yx_from_tiff_checked(path: str | Path) -> tuple[tuple[float, float] | None, str | None]:
    """-> (yx, problem): the per-axis size stored in a TIFF (None when unknown), and the sentence when the file could not be read."""
    calibration, problem = calibration_from_tiff(path)
    return calibration.yx, problem


def microns_yx_from_tiff(path: str | Path) -> tuple[float, float] | None:
    """(y, x) pixel size (um) stored in a TIFF, or None when absent / unknown. A missing YResolution means square."""
    return microns_yx_from_tiff_checked(path)[0]


def microns_from_tiff(path: str | Path) -> float | None:
    """Pixel size (um) along X stored in a TIFF, or None when absent / unknown."""
    yx = microns_yx_from_tiff(path)
    return None if yx is None else yx[1]

"""The state of a linked pixel-size field (docs/SPEC_WRONG_SCIENCE.md 2.2) and the `_calibration` entry of a request (2.3.4). No Qt.

A `PixelSizeOf` field is `unset`, `auto(source, value)` or `user(value)`. The state is a flag set by the person's edit events
(`user_edit`), never inferred by comparing the field with the last automatic value, and a programmatic set (`source_changed`) never
makes it `user`. The value a run sends is read from here, not from the spin box.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._units import Calibration, Raw

UNSET, AUTO, USER = "unset", "auto", "user"
CANONICAL_UNIT = "um"  # micrometres per pixel: the contract of PixelSizeOf

CALIBRATION_REQUIRED = "'{param}' needs a value: '{of}' has no pixel size. Enter it in um."  # conformance.json messages.calibration_required
NOT_CALIBRATED_TOOLTIP = "not calibrated: '{of}' has no pixel size"  # messages.calibration_unknown_tooltip


@dataclass(frozen=True)
class Derived:
    """What the current source says: a calibration and where it came from ('image' = the chosen layer, 'file' = the file input)."""

    calibration: Calibration
    source: str  # "image" | "file"


def _axis(value: float, source: str, raw: Raw | None) -> dict[str, Any]:
    entry: dict[str, Any] = {"value": value, "unit": CANONICAL_UNIT, "source": source}
    if raw is not None and (raw.scale is not None or raw.unit is not None):
        entry["raw"] = {"scale": raw.scale, "unit": raw.unit}
    return entry


class LinkState:
    """One linked field: `param` is the manifest parameter, `of` the image parameter it describes."""

    def __init__(self, param: str, of: str) -> None:
        self.param, self.of = param, of
        self.state = UNSET
        self.derived: Derived | None = None  # the source the AUTO value came from
        self.user: float | None = None

    # ---- events -------------------------------------------------------------------------------------------------------
    def source_changed(self, derived: Derived | None) -> bool:
        """The image, the file or the project image changed (or the field is being derived again). True when the field value changed.
        A `user` value stays; otherwise the field takes the new source's value, or is cleared when the source is unknown.
        """
        if self.state == USER:
            return False
        if derived is not None and derived.calibration.value is not None:
            self.state, self.derived = AUTO, derived
        else:
            self.state, self.derived = UNSET, None
        return True

    def user_edit(self, value: float | None) -> None:
        """The person typed or pasted a value. A cleared field (None, or 0, the box's empty position) is the person asking for the
        image's calibration again: `unset`, and the caller derives it from the current source."""
        if value is None or not value > 0:
            self.state, self.user, self.derived = UNSET, None, None
        else:
            self.state, self.user = USER, float(value)

    # ---- what a run sends ---------------------------------------------------------------------------------------------
    @property
    def value(self) -> float | None:
        if self.state == USER:
            return self.user
        if self.state == AUTO and self.derived is not None:
            return self.derived.calibration.value
        return None

    @property
    def source(self) -> str | None:
        return USER if self.state == USER else (self.derived.source if self.derived else None)

    def entry(self) -> dict[str, Any] | None:
        """The `_calibration` entry of this field (2.3.4), or None while it has no value. Phase 1: x and y only."""
        value = self.value
        if value is None:
            return None
        derived = self.derived
        if self.state == USER or derived is None or derived.calibration.yx is None:
            axes = {"x": _axis(value, USER, None), "y": _axis(value, USER, None)}
        else:
            yx, (raw_y, raw_x) = derived.calibration.yx, derived.calibration.raw
            axes = {
                "x": _axis(yx[1], derived.source, raw_x),
                "y": _axis(yx[0], derived.source, raw_y),
            }
        return {"of": self.of, "source": self.source, "axes": axes}

    def tooltip(self) -> str:
        value = self.value
        if self.state == USER and value is not None:
            return "%g um per pixel, entered by you: it overrides the calibration of '%s'" % (value, self.of)
        if self.state == AUTO and self.derived is not None and value is not None:
            what = "the file" if self.derived.source == "file" else "'%s'" % self.of
            return "%g um per pixel, from the calibration of %s" % (value, what)
        return NOT_CALIBRATED_TOOLTIP.format(of=self.of)

    def required_message(self) -> str:
        return CALIBRATION_REQUIRED.format(param=self.param, of=self.of)

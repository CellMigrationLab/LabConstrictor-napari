"""A tiny app for the regression test of the UI audit driver (test_ui_audit_regressions.py): one tool of each shape that tripped the driver
once. Hosts import this file to list the tools."""

from typing import Annotated, Literal

from labconstrictor_tools import EnabledWhen, Image, Min, PixelSizeOf, Scalars, tool


@tool("Segment")
def segment(
    image: Image,
    pixel_size_um: Annotated[float | None, PixelSizeOf("image"), Min(0)] = None,
    segmentation: Literal["threshold", "cellpose"] = "threshold",
    diameter_px: Annotated[float | None, EnabledWhen("segmentation", "cellpose")] = None,
) -> Scalars:
    """Measure the image; `diameter_px` only means something for `cellpose` (the optional field behind an enabled_when rule)."""
    return {"mean": float(image.mean())}


@tool("Count")
def count(image: Image) -> Scalars:
    """An image tool without a pixel size, audited after `segment` (its prerequisites are replayed inside its row)."""
    return {"pixels": int(image.size)}


@tool("Devices")
def devices() -> Scalars:
    """A tool without parameters."""
    return {"devices": ["cpu"]}

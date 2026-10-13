"""A small LabConstrictor app for the retention and run-identity tests (registered by the tests with --pythonpath; the worker imports it).

`gate` parameters: the tool waits until that file exists (a barrier the test releases), so a test can do things "during the run".
"""

import sys
import time
from pathlib import Path
from typing import Annotated, Optional

from labconstrictor_tools import (
    ApplyTo,
    Axes,
    FileOut,
    Image,
    ImageOut,
    Labels,
    LabelsOut,
    MessageOut,
    Name,
    PointsOut,
    RegionOf,
    Scalars,
    ShapesOut,
    TableOut,
    check_cancel,
    tool,
)


def _wait_for(gate: str, seconds: float = 90.0) -> None:
    end = time.time() + seconds
    while gate and not Path(gate).exists() and time.time() < end:
        check_cancel()
        time.sleep(0.05)


def _job_dir() -> Path:
    """The host-owned output folder of this task. A tool has no API for it (the worker consumes `_job_dir`), so the test tool reads the
    worker's own variable from the call stack: a real tool would write wherever it likes, and the host keeps only what is in here.
    """
    frame = sys._getframe()
    while frame is not None:
        found = frame.f_locals.get("job_dir")
        if isinstance(found, Path):
            return found
        frame = frame.f_back
    raise RuntimeError("no job folder found in the call stack")


@tool("Gated points")
def gated_points(image: Annotated[Image, Axes("YX")], gate: str = "") -> tuple[
    Annotated[PointsOut, Name("spots"), ApplyTo("image")],
    Annotated[LabelsOut, Name("mask"), ApplyTo("image")],
    Annotated[TableOut, Name("stats")],
    Annotated[MessageOut, Name("note")],
]:
    import numpy as np

    _wait_for(gate)
    return (
        [{"y": 2.0, "x": 3.0}],
        (np.asarray(image) > 0).astype(np.int32),
        [{"n": 1}],
        "gated points done",
    )


@tool("Region stats")
def region_stats(
    image: Annotated[Image, Axes("YX")],
    region: Annotated[Optional[Labels], Axes("YX"), RegionOf("image")] = None,  # noqa: UP045
    gate: str = "",
) -> Scalars:
    import numpy as np

    _wait_for(gate)
    return {
        "image_sum": float(np.asarray(image).sum()),
        "mask_pixels": int((np.asarray(region) > 0).sum()) if region is not None else -1,
        "mask_max": int(np.asarray(region).max()) if region is not None else -1,
    }


@tool("Report file")
def report_file(gate: str = "") -> Annotated[FileOut, Name("report")]:
    """Writes report.txt ('data') into the job folder and returns it as a FileOut (RET-10)."""
    _wait_for(gate)
    path = _job_dir() / "report.txt"
    path.write_text("data", encoding="utf-8")
    return path


@tool("Outside file")
def outside_file(path: str) -> Annotated[FileOut, Name("report")]:
    """Returns a file that already exists somewhere else (never moved or modified by the host)."""
    return Path(path)


@tool("Big picture")
def big_picture() -> Annotated[ImageOut, Name("picture")]:
    import numpy as np

    return np.arange(16, dtype=np.uint8).reshape(4, 4)


@tool("Echo")
def echo(a: float = 1.0) -> Scalars:
    return {"a": a}


@tool("Region values")
def region_values(
    image: Annotated[Image, Axes("YX")],
    region: Annotated[Optional[Labels], Axes("YX"), RegionOf("image")] = None,  # noqa: UP045
) -> Scalars:
    """What the worker received: the shape of the image and, under the region, how many pixels, their sum and their sorted values."""
    import numpy as np

    pixels = np.asarray(image)
    mask = np.asarray(region) if region is not None else np.zeros(pixels.shape, int)
    return {
        "image_shape": list(pixels.shape),
        "mask_shape": list(mask.shape),
        "mask_pixels": int((mask > 0).sum()),
        "values": sorted(int(v) for v in pixels[mask > 0]) if mask.shape == pixels.shape else [],
    }


@tool("Outline and mark")
def outline_and_mark(image: Annotated[Image, Axes("YX")]) -> tuple[
    Annotated[PointsOut, Name("spots"), ApplyTo("image")],
    Annotated[ShapesOut, Name("outline"), ApplyTo("image")],
]:
    """One point and one rectangle (pixel coordinates; centres of pixels are integers) on the image."""
    return [{"y": 2.0, "x": 3.0}], [[[1.5, 2.5], [1.5, 5.5], [3.5, 5.5], [3.5, 2.5]]]


@tool("Half size labels")
def half_size_labels(
    image: Annotated[Image, Axes("YX")],
) -> Annotated[LabelsOut, Name("mask"), ApplyTo("image")]:
    """A labels result with half the rows and columns of the input (the exported frame does not fit it)."""
    import numpy as np

    pixels = np.asarray(image)
    return np.ones((pixels.shape[0] // 2, pixels.shape[1] // 2), np.int32)


@tool("Marks without an image")
def marks_without_an_image(gate: str = "") -> tuple[
    Annotated[PointsOut, Name("spots")],
    Annotated[ShapesOut, Name("outline")],
]:
    """A tool with no image input that still reports points and an outline."""
    _wait_for(gate)
    return [{"y": 2.0, "x": 3.0}, {"y": 4.0, "x": 5.0}], [[[1.5, 2.5], [1.5, 5.5], [3.5, 5.5], [3.5, 2.5]]]

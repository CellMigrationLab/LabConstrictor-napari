"""Extracting one channel of a TIFF file reads that channel, not the file (issue #40). No Qt, no worker.

The whole series is never decoded to pick one channel of it: the test counts the calls of `TiffPageSeries.asarray` / `TiffFile.asarray` (must be
zero) and of the page decoders (only the pages of the channel), measures the peak allocation with tracemalloc (the channel plus a page, not
the series), and checks the budget: a file that cannot be read one channel at a time is refused before a pixel is read when the whole
series would not fit, and a channel that alone would not fit is refused as well. Layouts: CYX, ImageJ CYX and TZCYX hyperstacks, OME-TIFF,
compressed, RGB (S axis), and a long contiguous run of pixels that tifffile exposes as a single page (memory map).
"""

import json
import sys
import tempfile
import tracemalloc
from pathlib import Path
from typing import TYPE_CHECKING

import _paths  # noqa: F401  (must come first)
import numpy as np
import tifffile

from napari_labconstrictor import _export

if TYPE_CHECKING:
    from typing import Any

report, failures = {}, []


def expect(name: str, ok: object, detail: object = "") -> None:
    report[name] = bool(ok)
    if not ok:
        failures.append("%s %s" % (name, detail))


work = Path(tempfile.mkdtemp(prefix="lcmem_"))
calls = {"series": 0, "file": 0, "pages": 0}
decoded = set()  # page numbers: a frame decodes through its key page, which must not count twice


def counted(cls: type, name: str, key: str) -> None:
    original = getattr(cls, name)

    def wrapper(self: "Any", *args: object, **kwargs: object) -> object:
        if key == "pages":
            decoded.add(self.index)
            calls[key] = len(decoded)
        else:
            calls[key] += 1
        return original(self, *args, **kwargs)

    setattr(cls, name, wrapper)


counted(tifffile.TiffPageSeries, "asarray", "series")
counted(tifffile.TiffFile, "asarray", "file")
counted(tifffile.TiffPage, "asarray", "pages")
counted(tifffile.TiffFrame, "asarray", "pages")


def reset() -> None:
    decoded.clear()
    for key in calls:
        calls[key] = 0


def extract(path: Path, index: int, label: str = "Image") -> tuple[np.ndarray, dict[str, int]]:
    target = work / "channel.tif"
    reset()
    result = _export.channel_file(path, index, label, target)
    seen = dict(calls)  # before the test reads the result back
    return tifffile.imread(result), seen


rng = np.random.default_rng(7)
hyper = rng.integers(0, 60000, (2, 3, 4, 20, 24), dtype=np.uint16)  # T Z C Y X: 24 pages
cyx = rng.integers(0, 250, (3, 20, 24), dtype=np.uint8)
layouts = {
    "imagej_TZCYX": (hyper, dict(imagej=True, metadata={"axes": "TZCYX"}), "TZCYX", 6),
    "imagej_TZCYX_deflate": (
        hyper,
        dict(imagej=True, metadata={"axes": "TZCYX"}, compression="zlib"),
        "TZCYX",
        6,
    ),
    "ome_TZCYX": (hyper, dict(ome=True, metadata={"axes": "TZCYX"}), "TZCYX", 6),
    "ome_TZCYX_deflate": (hyper, dict(ome=True, metadata={"axes": "TZCYX"}, compression="zlib"), "TZCYX", 6),
    "imagej_CYX": (cyx, dict(imagej=True, metadata={"axes": "CYX"}), "CYX", 1),
    "plain_CYX_one_page": (
        cyx,
        dict(metadata={"axes": "CYX"}),
        "CYX",
        1,
    ),  # the channels share one page: a page is the unit
}
for name, (array, kwargs, axes, pages_needed) in layouts.items():
    path = work / (name + ".tif")
    tifffile.imwrite(path, array, **kwargs)
    with tifffile.TiffFile(path) as tif:
        expect("%s_fixture_axes" % name, tif.series[0].axes == axes, tif.series[0].axes)
        total_pages = len(tif.series[0].pages)
    for index in range(array.shape[axes.index("C")]):
        got, seen = extract(path, index)
        want = np.take(array, index, axis=axes.index("C"))
        expect(
            "%s_channel_%d_pixels" % (name, index + 1),
            got.shape == want.shape and got.dtype == want.dtype and np.array_equal(got, want),
            (got.shape, want.shape),
        )
        expect(
            "%s_channel_%d_never_reads_the_series" % (name, index + 1),
            seen["series"] == 0 and seen["file"] == 0,
            seen,
        )
        expect(
            "%s_channel_%d_decodes_only_its_pages" % (name, index + 1),
            seen["pages"] == pages_needed <= total_pages,
            (seen, pages_needed, total_pages),
        )
    if total_pages > 1 and axes.startswith("TZ"):
        expect("%s_is_selective" % name, pages_needed < total_pages, (pages_needed, total_pages))

# RGB (S axis): the page is the unit, the samples are inside it
rgb = rng.integers(0, 250, (3, 20, 24, 3), dtype=np.uint8)  # three planes of YXS
tifffile.imwrite(work / "rgb_stack.tif", rgb, photometric="rgb")
for index in range(3):
    got, seen = extract(work / "rgb_stack.tif", index)
    expect(
        "rgb_stack_sample_%d" % index,
        np.array_equal(got, rgb[..., index]) and seen["series"] == 0 and seen["file"] == 0,
        (got.shape, seen),
    )

# peak memory: one channel of a larger file costs about the channel, not the file
big = np.zeros((6, 20, 256, 256), np.uint16)  # C-major: 6 channels of 20 planes
big[...] = rng.integers(0, 60000, (6, 20, 1, 1), dtype=np.uint16)
tifffile.imwrite(
    work / "big.tif",
    big.reshape(6, 20, 256, 256).transpose(1, 0, 2, 3).copy(),
    imagej=True,
    metadata={"axes": "ZCYX"},
)
channel_bytes = 20 * 256 * 256 * 2
for compressed in (False, True):
    tag = "deflate" if compressed else "plain"
    path = work / ("big_%s.tif" % tag)
    kwargs = dict(imagej=True, metadata={"axes": "ZCYX"}, **({"compression": "zlib"} if compressed else {}))
    tifffile.imwrite(path, big.transpose(1, 0, 2, 3).copy(), **kwargs)
    tracemalloc.start()
    tracemalloc.reset_peak()
    got, seen = extract(path, 4)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    expect("peak_%s_pixels" % tag, np.array_equal(got, big[4]), got.shape)
    expect(
        "peak_%s_is_about_one_channel_not_the_file" % tag,
        peak < 2.5 * channel_bytes < 6 * channel_bytes,
        (peak, channel_bytes),
    )


# a long run of pixels that tifffile shows as one page: it is memory-mapped, the series is never decoded
class Series:
    """What tifffile gives for an ImageJ file whose pages after the first are implied: `pages` has one entry, `asarray` must not be used."""

    def __init__(self, series: "Any", pages: "Any", big_dtype: object = None) -> None:
        self.shape, self.axes, self.dtype = series.shape, series.axes, series.dtype
        self.pages = pages

    def asarray(self) -> None:
        raise AssertionError("the whole series was decoded")


path = work / "imagej_TZCYX.tif"
with tifffile.TiffFile(path) as tif:
    series = tif.series[0]
    stub = Series(series, [series.pages[0]])
    reset()
    got = _export.read_channel(tif, stub, 2, 3, "Image")
    expect(
        "implied_pages_use_a_memory_map",
        np.array_equal(got, hyper[:, :, 3]) and calls["series"] == 0 and calls["pages"] == 0,
        (got.shape, calls),
    )

# budget
original_budget = _export.MAX_EXPORT_BYTES
try:
    full = hyper.nbytes
    channel = full // 4
    # selective reading: the series is far over the budget, the channel is not
    _export.MAX_EXPORT_BYTES = channel * 2
    got, seen = extract(work / "imagej_TZCYX.tif", 1)
    expect(
        "series_over_the_budget_is_fine_when_read_one_channel_at_a_time",
        np.array_equal(got, hyper[:, :, 1]) and seen["series"] == 0,
        seen,
    )
    # a channel that alone does not fit is refused, before any page is decoded
    _export.MAX_EXPORT_BYTES = channel - 1
    reset()
    try:
        _export.channel_file(work / "imagej_TZCYX.tif", 1, "Image", work / "never.tif")
        refused = None
    except _export.ChannelError as error:
        refused = str(error)
    expect(
        "a_channel_over_the_budget_is_refused",
        refused is not None
        and refused.startswith("'Image': extracting one channel needs ")
        and "more than" in refused,
        refused,
    )
    expect(
        "refusal_reads_nothing",
        calls == {"series": 0, "file": 0, "pages": 0} and not (work / "never.tif").exists(),
        calls,
    )
    # no way to read one channel only (not regular, not mappable): the whole series is needed, so it must fit with the copy of the channel
    with tifffile.TiffFile(work / "imagej_TZCYX_deflate.tif") as tif:
        series = tif.series[0]
        stub = Series(series, [series.pages[0]])
        _export.MAX_EXPORT_BYTES = full  # the series alone fits, with the copy of the channel it does not
        reset()
        try:
            _export.read_channel(tif, stub, 2, 1, "Image")
            refused = None
        except _export.ChannelError as error:
            refused = str(error)
        except AssertionError as error:
            refused = "READ: %s" % error
        expect(
            "whole_series_needed_and_too_big_is_refused_before_reading",
            refused is not None and "cannot be read one channel at a time" in refused,
            refused,
        )
        _export.MAX_EXPORT_BYTES = (
            full * 2
        )  # fits: the fallback is allowed (and the stub would refuse the read, so it is a real series here)
        got = _export.read_channel(tif, series, 2, 1, "Image")
        expect(
            "small_enough_file_without_selective_reading_still_works",
            np.array_equal(got, hyper[:, :, 1]),
            got.shape,
        )
finally:
    _export.MAX_EXPORT_BYTES = original_budget

# the layout is read from the tags only
reset()
layout = _export.channel_layout(work / "imagej_TZCYX.tif", "Image")
expect(
    "layout_reads_no_pixel",
    layout == ("C", ["Channel 1", "Channel 2", "Channel 3", "Channel 4"])
    and calls == {"series": 0, "file": 0, "pages": 0},
    (layout, calls),
)

print(json.dumps(report, indent=2))
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)

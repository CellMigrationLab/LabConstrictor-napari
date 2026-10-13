"""Form values -> files for the worker: layers and selections written as TIFF, channel extraction. Pure helpers (no widget state)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from ._frame import Frame, selection_vertices

if TYPE_CHECKING:  # napari and magicgui ship no usable stubs here: their objects are annotated by name only
    from napari.layers import Image, Labels

    from ._snapshot import SelectionRef, SourceRef

MAX_EXPORT_BYTES = 4 * 1024**3  # refuse to write a layer larger than this to a temporary TIFF
MAX_REGION_OBJECTS = 65_535  # shapes in a RegionOf selection: the labels of the region image are 16 bit (same limit as Fiji and QuPath)


def is_set(path: Any) -> bool:
    """True when a FileEdit/Path value names something (an empty FileEdit gives None, "" or ".")."""
    return path is not None and str(path) not in ("", ".")


def _region_frame(label: str, image_label: str, file: Path | None, image: SourceRef | None) -> Frame:
    """The frame of the open layer a region belongs to, as the run snapshot recorded it at the click. The selection is drawn on a layer,
    so an image given as a file is refused: nothing says where the selection lies on an unknown file.
    """
    if file is not None:
        raise ValueError(
            "'%s': the selection belongs to an open image, but a file was chosen for '%s': open the image, or untick the selection"
            % (label, image_label)
        )
    if image is not None and image.frame is not None:
        return image.frame
    raise ValueError("'%s': choose the image it belongs to first" % label)


def selection_mask(
    selection: SelectionRef | None,
    param: dict[str, Any],
    file: Path | None,
    image: SourceRef | None,
    job_dir: Path,
    image_label: str | None = None,
) -> str:
    """The shapes of the selection as a label image the size of the exported image named by `param["region_of"]` (labels 1..N, at most
    MAX_REGION_OBJECTS), written to `job_dir`. `selection` is the Shapes layer as it was at the click, copied by value with its full
    transform (SPEC_WRONG_SCIENCE section 4: editing or moving the shapes during the export changes nothing), `file` the file chosen
    for that image (or None), `image` its layer as it was at the click, with its frame (or None), `image_label` its label for the
    messages. The shapes go through the world (`shapes.data_to_world`, then `image.world_to_data`, SPEC 1.2.3) into the pixel grid of
    the exported image and are rasterised there, never in their own raw coordinates (1.2.4). Anything that makes this impossible is
    said to the person, never guessed around.
    """
    from napari.layers import Shapes
    from tifffile import imwrite

    label = param["label"]
    frame = _region_frame(label, image_label or param["region_of"], file, image)
    if selection is None:
        raise ValueError(
            "'%s': select a Shapes layer in the layer list, or untick 'use the selection'" % label
        )
    if len(selection.vertices) == 0:
        raise ValueError("'%s': the selected Shapes layer '%s' has no shapes" % (label, selection.name))
    count = len(selection.vertices)
    if count > MAX_REGION_OBJECTS:
        raise ValueError(
            "'%s': %d objects are selected; at most %d are supported" % (label, count, MAX_REGION_OBJECTS)
        )
    transform = frame.transform
    if transform is None or transform.shape != (3, 3):
        # SPEC GAP (Wave 2): which plane of a stack the selection lies on needs the t/z axes of the frame; Wave 1 is the 2D plane
        raise ValueError(
            "'%s': the image '%s' is not a 2D image; a selection on a stack is not supported yet"
            % (label, frame.label)
        )
    vertices, kinds = selection_vertices(
        selection.matrix, selection.vertices, selection.shape_types, transform, frame.label
    )
    mask = np.asarray(Shapes(vertices, shape_type=kinds).to_labels(labels_shape=frame.shape), dtype=np.uint16)
    if not mask.any():
        raise ValueError("'%s': the shapes of '%s' lie outside the image" % (label, selection.name))
    path = job_dir / (param["name"] + ".tif")
    imwrite(path, mask)
    return str(path)


class ChannelError(ValueError):
    """A channel that cannot be picked: said to the person (tifffile's own errors, also ValueErrors, are not this)."""


SAMPLE_NAMES = ("Red", "Green", "Blue")  # the colour samples (S axis) of an RGB TIFF


def channel_layout(path: Path, label: str) -> tuple[str, list[str]] | None:
    """What PickChannel can choose from in the TIFF `path`, read from its tags only (no pixels): `(axis, names)` for a file with a
    channel axis `C` (acquisition channels) or a colour-sample axis `S` (RGB), None for a file with neither.

    Policy for what cannot be chosen from (said, never guessed): a file with both `C` and `S`, and an `S` axis that is not exactly
    three colours (an alpha channel or another sample count) is refused with a sentence.
    """
    import tifffile

    with tifffile.TiffFile(str(path)) as tif:
        series = tif.series[0]
        axes, shape = series.axes, series.shape
    if "C" in axes and "S" in axes:
        raise ChannelError(
            "'%s': the file has both channels (C) and colour samples (S); picking one is not supported: save one of them as its own file"
            % label
        )
    if "S" in axes:
        samples = shape[axes.index("S")]
        if samples == 1:
            return "S", ["Channel 1"]
        if samples != len(SAMPLE_NAMES):
            raise ChannelError(
                "'%s': the file has %d colour samples (S); only plain RGB (3) can be picked from, and an alpha channel is not interpreted"
                % (label, samples)
            )
        return "S", list(SAMPLE_NAMES)
    if "C" in axes:
        return "C", ["Channel %d" % (i + 1) for i in range(shape[axes.index("C")])]
    return None


def _check_budget(label: str, series: Any, axis: int, selective: bool) -> None:
    """Refuse before reading a pixel when the memory this extraction needs passes `MAX_EXPORT_BYTES` (same budget as a layer)."""
    itemsize = np.dtype(series.dtype).itemsize
    full = int(np.prod(series.shape, dtype=object)) * itemsize
    picked = full // series.shape[axis]
    need = (
        picked if selective else full + picked
    )  # without selective reading the whole series is in memory with the copy of the channel
    if need > MAX_EXPORT_BYTES:
        raise ChannelError(
            "'%s': extracting one channel needs %.1f GB (the image is %.1f GB%s); more than %.0f GB is not supported"
            % (
                label,
                need / 1024**3,
                full / 1024**3,
                "" if selective else " and this file cannot be read one channel at a time",
                MAX_EXPORT_BYTES / 1024**3,
            )
        )


def read_channel(tif: Any, series: Any, axis: int, index: int, label: str) -> np.ndarray:
    """Channel `index` along `axis` of `series` as an array, reading only what that channel occupies where the file allows it: one
    page at a time (peak memory: the channel plus one page), else a memory map; only a file that offers neither is read whole, and
    only when it fits the budget. The whole series is never decoded (`series.asarray()`) just to pick one channel of it.
    """
    shape = tuple(series.shape)
    pages = series.pages
    page = pages[0] if len(pages) else None
    page_dims = len(page.shape) if page is not None else 0
    lead = shape[: len(shape) - page_dims]
    if (
        page is not None
        and tuple(shape[len(lead) :]) == tuple(page.shape)
        and int(np.prod(lead, dtype=object)) == len(pages)
    ):
        _check_budget(label, series, axis, selective=True)
        out_shape = shape[:axis] + shape[axis + 1 :]
        out = np.empty(out_shape, dtype=series.dtype)
        if axis < len(lead):  # the channels lie in different pages: decode only the pages of this channel
            numbers = np.arange(len(pages)).reshape(lead)
            wanted = np.take(numbers, index, axis=axis).ravel()
            for slot, number in enumerate(wanted):
                out.reshape((-1, *page.shape))[slot] = pages[int(number)].asarray()
        else:  # the channels lie inside every page: decode a page, keep its channel
            inner = axis - len(lead)
            flat = out.reshape((-1, *out_shape[len(lead) :]))
            for number in range(len(pages)):
                flat[number] = np.take(pages[number].asarray(), index, axis=inner)
        return out
    import tifffile

    try:  # one long contiguous run of pixels (e.g. an ImageJ hyperstack): map it, and copy only the channel
        mapped = tifffile.memmap(str(tif.filehandle.path), series=0)
    except (ValueError, TypeError, OSError, NotImplementedError):
        mapped = None
    if mapped is not None and tuple(mapped.shape) == shape:
        _check_budget(label, series, axis, selective=True)
        return np.array(np.take(mapped, index, axis=axis))
    _check_budget(label, series, axis, selective=False)
    return np.take(series.asarray(), index, axis=axis)


def channel_file(path: Path, index: int, label: str, target: Path) -> Path:
    """One channel of a TIFF (a `C` channel or an `S` colour of an RGB file) written as its own TIFF, or `path` itself when the file
    has neither axis. The choice is validated against the layout first (`channel_layout`)."""
    import tifffile

    layout = channel_layout(path, label)
    if layout is None:
        return path
    letter, names = layout
    if index >= len(names):
        raise ChannelError(
            "'%s': channel %d was asked for, but the image has %d channels" % (label, index + 1, len(names))
        )
    with tifffile.TiffFile(str(path)) as tif:
        series = tif.series[0]
        data = read_channel(tif, series, series.axes.index(letter), index, label)
    tifffile.imwrite(target, data)
    return target


def export_layer(layer: Image | Labels, picked: int | None, path: Path) -> None:
    """Write an image/labels layer to `path` as TIFF (full resolution; one colour of an RGB layer when `picked` is an index)."""
    from tifffile import imwrite

    data = layer.data[0] if getattr(layer, "multiscale", False) else layer.data  # multiscale: full resolution
    size = int(np.prod(data.shape)) * np.dtype(data.dtype).itemsize
    if size > MAX_EXPORT_BYTES:
        raise ValueError(
            "layer '%s' is %.1f GB; exporting more than %.0f GB is not supported"
            % (layer.name, size / 1024**3, MAX_EXPORT_BYTES / 1024**3)
        )
    data = np.asarray(data)
    if picked is not None and getattr(layer, "rgb", False):  # PickChannel on an RGB layer: one colour
        data = data[..., picked]
    imwrite(path, data)

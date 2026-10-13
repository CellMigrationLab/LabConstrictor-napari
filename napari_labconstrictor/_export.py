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


def channel_file(path: Path, index: int, label: str, target: Path) -> Path:
    """One channel of a multi-channel TIFF, written as its own TIFF."""
    import tifffile

    with tifffile.TiffFile(str(path)) as tif:
        series = tif.series[0]
        data, axes = series.asarray(), series.axes
    if "C" not in axes:
        return path
    if index >= data.shape[axes.index("C")]:
        raise ValueError(
            "'%s': channel %d was asked for, but the image has %d channels"
            % (label, index + 1, data.shape[axes.index("C")])
        )
    tifffile.imwrite(target, np.take(data, index, axis=axes.index("C")))
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

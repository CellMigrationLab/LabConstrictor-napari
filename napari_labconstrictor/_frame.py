"""The coordinate frame (docs/SPEC_WRONG_SCIENCE.md section 1), for napari.

A tool works on the PIXELS of the image file the host exported and never sees a world coordinate. The host owns the mapping back:

* `Frame` is what the run snapshot records at the click for each exported image (1.1.2): the source (the layer object, or a file),
  the exported Y/X `shape`, `axes_offset` (t, z, y, x), the exported `plane`, `downsample` and the source's `transform` (its full
  data -> world matrix at the click). Wave 1 exports the whole 2D plane at full resolution: offset 0, plane (0, 0), downsample 1.
* Placement (1.1.3): a result coordinate `x` is in exported-pixel units with the centre of pixel i at integer i, so its continuous
  full-resolution coordinate is `c = x0 + (x + 0.5) * downsample` and napari draws at the data coordinate `c - 0.5`; the layer's own
  transform does the rest: `result.data_to_world(p) == source.data_to_world(c - 0.5)`. `result_transform` gives a new layer the
  source's scale, translate, rotate, shear, affine and units, always read from the live layer, so a result follows the layer (4.4).
* A selection (1.2): vertices go `shapes.data_to_world`, then `image.world_to_data` (the full transform of both layers), and only
  then are rasterised on the exported image's pixel grid (`selection_vertices`).
* A transform with no exact mapping is refused, never approximated (1.4): `frame_unsupported_transform`.

Every matrix here is read through napari's own `Layer.data_to_world`, so napari stays the single owner of how scale, translate, rotate,
shear and affine compose. Pure numpy apart from that; no Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

FRAME_UNSUPPORTED = (
    "frame_unsupported_transform"  # the host-internal codes of SPEC_WRONG_SCIENCE 1.4 (conformance.json)
)
SELECTION_MIXED_PLANES = "selection_mixed_planes"
REFUSAL_SUFFIX = "(nothing was changed; files are in {path})"  # conformance.json messages.refusal_suffix
SIZE_MISMATCH_TEXT = (
    "'{name}' is {w} x {h} but '{source}' was exported as {w2} x {h2}; shown at the pixel origin, not aligned"
)
CONDITION_LIMIT = 1e12  # a Y/X block this ill-conditioned (or singular, or not finite) has no usable inverse


class FrameError(ValueError):
    """A coordinate-frame refusal: one sentence for the person, and the host-internal code of SPEC_WRONG_SCIENCE 1.4 in `code`."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(text)
        self.code = code


def _readonly(array: Any) -> np.ndarray:
    copy_ = np.array(array, dtype=float, copy=True)
    copy_.setflags(write=False)
    return copy_


def world_matrix(layer: Any) -> np.ndarray:
    """The homogeneous (n+1, n+1) matrix of `layer.data_to_world` (n = layer.ndim): column j is the world image of data axis j,
    the last column the world position of the data origin. Exact for every napari transform, because they are all affine.
    """
    n = int(layer.ndim)
    matrix = np.eye(n + 1)
    origin = np.asarray(layer.data_to_world(tuple([0.0] * n)), dtype=float)
    matrix[:n, n] = origin
    for axis in range(n):
        unit = [0.0] * n
        unit[axis] = 1.0
        matrix[:n, axis] = np.asarray(layer.data_to_world(tuple(unit)), dtype=float) - origin
    return matrix


def yx_block_problem(matrix: np.ndarray) -> str | None:
    """None when the Y/X block of a homogeneous matrix can be inverted, else why not."""
    block = np.asarray(matrix, dtype=float)[-3:-1, -3:-1]
    if not np.all(np.isfinite(block)):
        return "its transform is not a finite number"
    with np.errstate(all="ignore"):
        condition = np.linalg.cond(block)
    if not np.isfinite(condition) or condition > CONDITION_LIMIT:
        return "its transform cannot be inverted (it flattens the image)"
    return None


@dataclass(frozen=True)
class Frame:
    """What the host knows about one exported image: where a result in its pixels goes (SPEC_WRONG_SCIENCE 1.1.2)."""

    name: str  # the parameter name, for sentences
    label: str  # what the person calls it: the layer name or the file name
    layer: Any | None  # the layer object (identity, not a name); None for a file
    file: Path | None
    shape: tuple[int, int]  # exported (Y, X)
    transform: (
        np.ndarray | None
    )  # data -> world at the click (n+1, n+1); None for a file (identity, no units)
    axes_offset: tuple[float, float, float, float] = (
        0.0,
        0.0,
        0.0,
        0.0,
    )  # (t, z, y, x): origin of the exported area
    plane: tuple[int, int] = (0, 0)  # exported (t, z)
    downsample: float = 1.0  # exported pixels -> full-resolution pixels

    @property
    def is_file(self) -> bool:
        return self.layer is None

    def to_data(self, y: Any, x: Any) -> tuple[np.ndarray, np.ndarray]:
        """Result pixel coordinates -> the napari data coordinates of the source (1.1.3): `c - 0.5`, `c = x0 + (x + 0.5) * downsample`."""
        _, _, y0, x0 = self.axes_offset
        return (
            y0 + (np.asarray(y, dtype=float) + 0.5) * self.downsample - 0.5,
            x0 + (np.asarray(x, dtype=float) + 0.5) * self.downsample - 0.5,
        )


def exported_yx(layer: Any) -> tuple[int, int]:
    """The Y/X shape of the image that is written for `layer` (level 0 of a multiscale one; a colour axis is not a spatial one)."""
    data = layer.data[0] if getattr(layer, "multiscale", False) else layer.data
    shape = tuple(int(s) for s in data.shape)
    yx = shape[-3:-1] if getattr(layer, "rgb", False) else shape[-2:]
    return (yx[0], yx[1])


def frame_of_layer(name: str, layer: Any) -> Frame:
    """The frame of an open layer as it is now (the snapshot calls this at the click)."""
    return Frame(
        name=name,
        label=str(getattr(layer, "name", name)),
        layer=layer,
        file=None,
        shape=exported_yx(layer),
        transform=_readonly(world_matrix(layer)),
    )


def frame_of_file(name: str, path: Path) -> Frame:
    """A file input is its own pixel frame: identity, no units, and no layer is ever looked for (1.3, CF-07)."""
    return Frame(
        name=name,
        label=getattr(path, "name", str(path)),
        layer=None,
        file=Path(path),
        shape=file_yx(path) or (0, 0),
        transform=None,
    )


def file_yx(path: Path) -> tuple[int, int] | None:
    """(Y, X) of a TIFF, from its first series; None when it cannot be read or has no Y and X axes."""
    try:
        import tifffile

        with tifffile.TiffFile(str(path)) as tif:
            series = tif.series[0]
            axes, shape = series.axes, series.shape
        if "Y" in axes and "X" in axes:
            return (int(shape[axes.index("Y")]), int(shape[axes.index("X")]))
    except Exception:  # noqa: BLE001 - an unreadable file only means the size cannot be compared
        return None
    return None


def refusal(frame_label: str, reason: str) -> FrameError:
    return FrameError(FRAME_UNSUPPORTED, "'%s': %s" % (frame_label, reason))


def result_transform(layer: Any, ndim: int = 2) -> dict[str, Any]:
    """The keyword arguments that give a new `ndim`-dimensional result layer the world placement of the source `layer` NOW (1.3).

    Same dimensions: scale, translate, rotate, shear, affine and units are the layer's own, so a person who looks at the result sees the
    source's transform. Fewer dimensions (a plane of a stack): the leading axes must not move the plane (identity scale and translate
    and no coupling to Y/X, 1.3 note), and the trailing block of the composed transform goes into `affine`. Anything else is refused
    (`frame_unsupported_transform`); the result is checked against `layer.data_to_world` before it is returned, so a mismatch can not
    be drawn.
    """
    n = int(layer.ndim)
    label = str(getattr(layer, "name", "image"))
    if n < ndim:
        raise refusal(label, "a %d-dimensional result cannot be placed on a %d-dimensional image" % (ndim, n))
    full = world_matrix(layer)
    problem = yx_block_problem(full)
    if problem:
        raise refusal(label, problem)
    lead = n - ndim
    for axis in range(lead):  # the dropped axes must not move the plane
        row_ok = np.allclose(full[axis, :], np.eye(n + 1)[axis, :], atol=1e-9)
        column_ok = np.allclose(full[lead:n, axis], 0.0, atol=1e-9)
        if not (row_ok and column_ok):
            raise refusal(
                label,
                "its transform moves the plane (axis %d is scaled, shifted or coupled to Y/X) "
                "so a %d-dimensional result cannot be placed exactly" % (axis, ndim),
            )
    if lead == 0:
        kwargs: dict[str, Any] = {
            "scale": tuple(float(s) for s in layer.scale),
            "translate": tuple(float(s) for s in layer.translate),
            "rotate": np.array(layer.rotate, dtype=float),
            "shear": np.array(layer.shear, dtype=float),
            "affine": np.array(layer.affine.affine_matrix, dtype=float),
        }
    else:
        matrix = np.eye(ndim + 1)
        matrix[:ndim, :ndim] = full[lead:n, lead:n]
        matrix[:ndim, ndim] = full[lead:n, n]
        kwargs = {"affine": matrix}
    units = tuple(getattr(layer, "units", ()))
    if len(units) == n:
        kwargs["units"] = units[lead:]
    _check(layer, kwargs, ndim, full, label)
    return kwargs


def _check(layer: Any, kwargs: dict[str, Any], ndim: int, full: np.ndarray, label: str) -> None:
    """The result transform must send the corners and the unit steps of the plane where the source sends them."""
    from napari.layers import Points

    try:
        probe = Points(np.empty((0, ndim)), **kwargs)
        n = full.shape[0] - 1
        for point in ([0.0] * ndim, *np.eye(ndim).tolist(), [3.0, -2.0] + [1.0] * (ndim - 2)):
            expected = full @ np.array([0.0] * (n - ndim) + list(point) + [1.0])
            got = np.asarray(probe.data_to_world(tuple(point)), dtype=float)
            if not np.allclose(got, expected[n - ndim : n], atol=1e-6, rtol=1e-9):
                raise refusal(label, "its transform could not be copied exactly")
    except FrameError:
        raise
    except Exception as error:
        raise refusal(label, "its transform could not be copied (%s)" % error) from error


def identity_transform(ndim: int = 2) -> dict[str, Any]:
    """The documented default of a result with no source: pixel origin, identity transform, no units (1.1.6)."""
    return {
        "scale": (1.0,) * ndim,
        "translate": (0.0,) * ndim,
        "rotate": np.eye(ndim),
        "shear": np.zeros(ndim * (ndim - 1) // 2),
        "affine": np.eye(ndim + 1),
        "units": ("pixel",) * ndim,
    }


def set_transform(layer: Any, kwargs: dict[str, Any]) -> None:
    """Set the transform of an existing layer from `result_transform` or `identity_transform` (Replace recomputes it, 1.1.8)."""
    defaults = identity_transform(int(layer.ndim))
    for key in ("scale", "translate", "rotate", "shear", "affine", "units"):
        setattr(layer, key, kwargs.get(key, defaults[key]))


def selection_vertices(
    selection_matrix: np.ndarray,
    vertices: tuple[np.ndarray, ...],
    shape_types: tuple[str, ...],
    image_matrix: np.ndarray,
    image_label: str,
) -> tuple[list[np.ndarray], list[str]]:
    """The shapes of a selection in the PIXEL GRID of the image (1.2.3): `shapes.data_to_world`, then `image.world_to_data`, for a
    2D image. Rectangles and ellipses become polygons first (an ellipse is sampled from its bounding corners, exact under any affine),
    so the outline stays what it was under rotation and shear. Lines and paths keep their type. Never the raw vertices (1.2.4).
    """
    problem = yx_block_problem(image_matrix)
    if problem:
        raise refusal(image_label, problem)
    inverse = np.linalg.inv(image_matrix)
    out: list[np.ndarray] = []
    kinds: list[str] = []
    for points, kind in zip(vertices, shape_types, strict=True):
        points = np.asarray(points, dtype=float)
        if kind == "ellipse" and len(points) == 4:
            angle = np.linspace(0.0, 2.0 * np.pi, 180, endpoint=False)[:, None]
            centre = points.mean(axis=0)
            points = (
                centre
                + np.cos(angle) * (points[1] - points[0]) / 2
                + np.sin(angle) * (points[2] - points[1]) / 2
            )
            kind = "polygon"
        elif kind == "rectangle":
            kind = "polygon"
        homogeneous = np.hstack([points, np.ones((len(points), 1))])
        world = (selection_matrix @ homogeneous.T).T[:, :-1]
        world_yx = np.hstack(
            [world[:, -2:], np.ones((len(world), 1))]
        )  # a 2D image lies in the trailing world axes
        data = (inverse @ world_yx.T).T[:, :2]
        out.append(data)
        kinds.append(kind)
    return out, kinds

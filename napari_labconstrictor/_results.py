"""Show typed tool results in napari. Switches on the result *type* only; knows nothing about any app."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from labconstrictor_tools import log
from qtpy.QtWidgets import QTableWidget, QTableWidgetItem

from ._frame import (
    FRAME_UNSUPPORTED,
    SIZE_MISMATCH_TEXT,
    Frame,
    FrameError,
    frame_of_file,
    frame_of_layer,
    identity_transform,
    result_transform,
    set_transform,
)
from ._snapshot import RunSnapshot

if TYPE_CHECKING:  # napari and Qt objects are annotated by name only (no usable stubs)
    from napari import Viewer
    from qtpy.QtWidgets import QWidget

Result = dict[str, Any]  # one typed result of a tool: {"type": ..., "name": ..., ...}

COULD_NOT_DISPLAY = "(could not display "
NOT_FINITE = "(not a finite number)"  # a null in `values`: PROTOCOL.md says hosts read it as a number that is not finite
MAX_DISPLAY_BYTES = (
    4 * 1024**3
)  # a result image larger than this (uncompressed) is not loaded into the viewer
MAX_TABLE_ROWS = 100_000  # rows shown in a table dock; the file itself always has all of them


MAX_SHAPES = 50_000  # outlines shown; the rest are counted in a message
POINT_SIZE = 8  # display size of a point result (napari points are drawn this many pixels wide)
OUTLINE_EDGE_WIDTH = 1  # line width of a shapes result
AFFINE_OPACITY = 0.8  # an alignment overlay stays see-through, so the image under it can be compared


class FileInput:
    """Stands in for a layer when an image parameter was given as a file (needed to place affine results). Results that lie in the
    pixels of such a file are placed in the pixel frame of the file: identity, no units (SPEC_WRONG_SCIENCE 1.3), not by this scale.
    """

    def __init__(self, path: Path) -> None:
        from ._units import microns_yx_from_tiff

        self.path, self.name = path, getattr(path, "name", str(path))
        self.scale = microns_yx_from_tiff(path) or (1.0, 1.0)  # (y, x)

    @property
    def data(self) -> np.ndarray:
        from tifffile import imread

        return imread(self.path)


class ResultPresenter:
    """`show(result)` adds layers/docks to the viewer and returns a short text for the status line."""

    def __init__(
        self,
        viewer: Viewer,
        app_name: str,
        inputs: dict[Any, Any],  # looked up with .get(None) when a result names no input
        replace: Any = (),
        docks: dict[tuple[str, str], QWidget] | None = None,
        image_inputs: Sequence[str] = (),
        snapshot: RunSnapshot | None = None,
    ) -> None:
        self.viewer, self.app, self.inputs = viewer, app_name, inputs  # inputs: the layers chosen in the form
        self.snapshot = snapshot  # the run these results belong to (run id, app, tool, source layers); None in older callers
        self.image_inputs = tuple(image_inputs)  # names of the image/labels parameters, in the tool's order
        self.replace = set(replace)  # output names whose previous result this run replaces (Replace())
        self.docks = docks if docks is not None else {}  # (app, table name) -> dock widget kept between runs
        self.tables: dict[str, list[list[str]]] = {}
        self.messages: list[str] = []  # texts of message results, shown by the widget below the status line
        self.file_results: list[Result] = (
            []
        )  # points / outlines with no image to be placed on: a table or a file, kept by the widget
        self._handlers = {
            "image": self._image,
            "labels": self._image,
            "affine": self._affine,
            "table": self._table,
            "values": self._values,
            "message": self._message,
            "points": self._points,
            "shapes": self._shapes,
            "file": self._file,
        }

    def _metadata(self) -> dict[str, Any]:
        """`layer.metadata` of everything drawn: the run id and the app and tool of the SNAPSHOT, never of the widget (RUN-03)."""
        return self.snapshot.metadata() if self.snapshot is not None else {}

    def _source_names(self, result: Result) -> list[str]:
        """The inputs a result is placed on: `apply_to` (and `relative_to` of an alignment), else for points and outlines the first
        image input (PROTOCOL.md). Image and labels results are placed on a source only when they declare `apply_to`.
        """
        kind = result.get("type")
        if kind == "affine":
            return [n for n in (result.get("apply_to"), result.get("relative_to")) if n]
        if kind in ("points", "shapes"):
            name = result.get("apply_to") or next(iter(self.image_inputs), None)
            return [name] if name else []
        if kind in (
            "image",
            "labels",
        ):  # the association of an image result is declared in the tool's schema, not in the result
            name = result.get("apply_to") or self._declared_apply_to(result.get("name"))
            return [name] if name else []
        return []

    def _declared_apply_to(self, output_name: Any) -> str | None:
        """`ApplyTo` that the tool declared for its output `output_name` (schema `display.apply_to`), else None."""
        if self.snapshot is None:
            return None
        for output in self.snapshot.tool.get("outputs", []):
            if output.get("name") == output_name:
                return (output.get("display") or {}).get("apply_to")
        return None

    def placement_problem(self, result: Any) -> tuple[str, str] | None:
        """(name of the source, CLOSED or RESIZED) when the source layer of this result is no longer the one that was exported, else
        None (SPEC_WRONG_SCIENCE 4.4). Such a result is not drawn: nothing may land on another image. A file input has no layer and is
        never a problem here. Without a snapshot (an old caller) nothing is checked."""
        if self.snapshot is None or self.viewer is None or not isinstance(result, dict):
            return None
        for name in self._source_names(result):
            reason = self.snapshot.problem_with(name, self.viewer.layers)
            if reason is not None:
                return self.snapshot.sources[name].name, reason
        return None

    def show(self, result: Any) -> str:
        kind = result.get("type", "<no type>") if isinstance(result, dict) else "<not an object>"
        if isinstance(result, dict) and "type" in result and kind not in self._handlers:
            return self._unknown(kind, result)
        try:
            return self._handlers[kind](result) or ""
        except (
            FrameError
        ) as error:  # SPEC 1.4: not drawn, one sentence, the file is kept (the widget moves it, see COULD_NOT_DISPLAY)
            log.warning("napari: a %s result was not drawn (%s): %s", kind, error.code, error)
            path = result.get("path") if isinstance(result, dict) else None
            where = " (nothing was changed; files are in %s)" % path if path else ""
            return "%s%s: %s%s)" % (COULD_NOT_DISPLAY, kind, error, where)
        except Exception as error:  # noqa: BLE001 - a display problem must not hide the other results
            log.error("napari: could not display a %s result", kind, exc_info=True)
            return "%s%s: %s)" % (
                COULD_NOT_DISPLAY,
                kind,
                repr(error) if isinstance(error, KeyError) else error,
            )

    def _unknown(self, kind: Any, result: Result) -> str:
        """A result type this version does not know: say so in one sentence, with its name and the file to look in."""
        log.warning("napari: a result of the unknown type %r (%s)", kind, result.get("name"))
        where = " (name '%s'%s)" % (
            result.get("name"),
            ", file %s" % result["path"] if "path" in result else "",
        )
        return "%s%s: the tool returned a result of the type '%s', which this version of napari LabConstrictor cannot show%s)" % (
            COULD_NOT_DISPLAY, kind, kind, where,
        )  # fmt: skip

    def _frame_for(self, result: Result) -> Frame | None:
        """The frame a result is placed in (SPEC_WRONG_SCIENCE 1.1): that of the input `apply_to` names, else for points and outlines
        the FIRST IMAGE input (PROTOCOL.md), never the first input of some other type, never the active or the last shown layer. It
        comes from the run snapshot (the layer object of the click, or the file chosen). None when there is no such image.
        """
        names = self._source_names(result)
        if not names:
            return None
        name = names[0]
        if self.snapshot is not None:
            frame = self.snapshot.frame(name)
            if frame is not None:
                return frame
        source = self.inputs.get(name)
        if isinstance(source, FileInput):
            return frame_of_file(name, source.path)
        if source is not None and hasattr(source, "data_to_world"):
            return frame_of_layer(name, source)
        return None

    @staticmethod
    def _transform_for(frame: Frame | None, ndim: int) -> dict[str, Any]:
        """How a new layer of `ndim` dimensions sits in the world: the source layer's CURRENT transform (a result follows its layer, 4.4),
        the pixel frame of a file or no source (identity, no units). Raises FrameError when no exact mapping exists.
        """
        if frame is None or frame.is_file:
            return identity_transform(ndim)
        return result_transform(frame.layer, ndim)

    def _without_frame(self, result: Result) -> str:
        """Points and outlines whose tool had no image input are NOT drawn at the pixel origin (SPEC 1.1.5, 1.1.6): points are shown as a
        table, outlines are listed as a file, and the file is kept (the widget moves it to an owned folder and the sentence names it).
        """
        self.file_results.append(result)
        if result["type"] == "points":
            return "%s (not drawn: there is no image input to place it on; the points are in %s)" % (
                self._table(result),
                result["path"],
            )
        return "outlines '%s' (not drawn: there is no image input to place them on; the file is %s)" % (
            result["name"],
            result["path"],
        )

    def _layer_name(self, result: Result) -> str:
        return "%s:%s" % (self.app, result["name"])

    def _image(self, result: Result) -> str | None:
        import tifffile

        with tifffile.TiffFile(
            result["path"]
        ) as tif:  # look before loading: a huge result must not freeze the viewer
            series = tif.series[0]
            size = int(np.prod(series.shape)) * np.dtype(series.dtype).itemsize
        if size > MAX_DISPLAY_BYTES:
            raise ValueError(
                "the image is %.1f GB; showing more than %.0f GB is not supported (it is in %s)"
                % (size / 1024**3, MAX_DISPLAY_BYTES / 1024**3, result["path"])
            )
        data = tifffile.imread(result["path"])
        add = self.viewer.add_labels if result["type"] == "labels" else self.viewer.add_image
        name = self._layer_name(result)
        frame = self._frame_for(result)  # only an image result that declares `apply_to` has one (1.1.6)
        # napari treats a trailing axis of 3 or 4 as colour (it is not a spatial axis); the transform is made for the spatial ones
        rgb = result["type"] == "image" and data.ndim > 2 and data.shape[-1] in (3, 4)
        ndim = data.ndim - 1 if rgb else data.ndim
        if result["name"] in self.replace and name in self.viewer.layers:
            old = self.viewer.layers[name]
            kind = type(old).__name__
            if kind == ("Labels" if result["type"] == "labels" else "Image") and old.data.ndim == data.ndim:
                kwargs, note = self._image_transform(result, frame, data.shape, ndim, rgb)
                old.data = data  # same layer: the view and contrast the user chose stay ...
                set_transform(
                    old, kwargs
                )  # ... but its place is recomputed from this result, never kept from the previous one (1.1.8)
                old.metadata = {**old.metadata, **self._metadata()}  # ... and it now belongs to this run
                return note
            self.viewer.layers.remove(old)
        kwargs, note = self._image_transform(
            result, frame, data.shape, ndim, rgb
        )  # before drawing: a refusal draws nothing
        layer = add(data, name=name, metadata=self._metadata(), **kwargs)
        if (
            layer is not None and int(layer.ndim) != ndim
        ):  # napari read the axes differently: the transform would not fit
            self.viewer.layers.remove(layer)
            raise FrameError(
                FRAME_UNSUPPORTED,
                "'%s': the result has %d spatial axes, not %d" % (result["name"], int(layer.ndim), ndim),
            )
        return note

    def _image_transform(
        self, result: Result, frame: Frame | None, shape: tuple[int, ...], ndim: int, rgb: bool
    ) -> tuple[dict[str, Any], str | None]:
        """(the transform of an image or labels result, the sentence to show or None). With a source of the same Y/X size it is the
        source's transform; with another size, or no source, the default pixel origin, and the size mismatch is said once (1.1.7).
        """
        if frame is None:
            return identity_transform(ndim), None
        w, h = (shape[-2], shape[-3]) if rgb else (shape[-1], shape[-2])
        if frame.shape != (0, 0) and (h, w) != frame.shape:
            note = SIZE_MISMATCH_TEXT.format(
                name=result["name"], w=w, h=h, w2=frame.shape[1], h2=frame.shape[0], source=frame.label
            )
            return identity_transform(ndim), note
        return self._transform_for(frame, ndim), None

    def _affine(self, result: Result) -> None:
        source = self.inputs[result["apply_to"]]
        target = self.inputs.get(result.get("relative_to"))
        matrix = np.array(result["matrix_yx"])
        # The matrix maps SOURCE pixels -> TARGET pixels. napari applies layer.scale first and layer.affine after,
        # so keep the source in pixel units (scale=1) and left-multiply by the target's calibration.
        if target is not None:
            matrix = np.diag([target.scale[-2], target.scale[-1], 1.0]) @ matrix
        name = self._layer_name(result)
        if result["name"] in self.replace and name in self.viewer.layers:
            self.viewer.layers.remove(
                self.viewer.layers[name]
            )  # Replace(): the new alignment takes the place of the previous overlay
        self.viewer.add_image(
            source.data,
            name=name,
            metadata=self._metadata(),
            affine=matrix,
            scale=(1, 1),
            colormap="magenta",
            blending="additive",
            opacity=AFFINE_OPACITY,
        )

    def _table(self, result: Result) -> str:
        import itertools

        with open(result["path"], encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            rows = list(itertools.islice(reader, MAX_TABLE_ROWS + 1))  # header + the rows that are shown
            hidden = sum(1 for _ in reader)  # counted, not kept
        self.tables[result["name"]] = rows
        widget = QTableWidget(len(rows) - 1, len(rows[0]))
        widget.setHorizontalHeaderLabels(rows[0])
        for i, row in enumerate(rows[1:]):
            for j, cell in enumerate(row):
                widget.setItem(i, j, QTableWidgetItem(cell))
        key = (self.app, result["name"])
        if result["name"] in self.replace and key in self.docks:
            try:
                self.viewer.window.remove_dock_widget(self.docks.pop(key))
            except (
                LookupError,
                RuntimeError,
            ) as error:  # the user closed it already (not found / Qt object deleted)
                log.warning(
                    "napari: the old '%s' table was already gone (%s: %s)",
                    result["name"],
                    type(error).__name__,
                    error,
                )
                self.docks.pop(key, None)
        if self.snapshot is not None:
            widget.setProperty(
                "labconstrictor_run_id", self.snapshot.run_id
            )  # a dock is not a layer: the run id is a Qt property
        self.viewer.window.add_dock_widget(widget, name=result["name"], area="bottom")
        self.docks[key] = widget
        shown = (
            "%d rows" % (len(rows) - 1)
            if not hidden
            else "%d rows, first %d shown" % (len(rows) - 1 + hidden, len(rows) - 1)
        )
        return "table '%s' (%s)" % (result["name"], shown)

    def _message(self, result: Result) -> None:
        self.messages.append(result["text"])

    def _points(self, result: Result) -> str:
        import pandas as pd

        frame = pd.read_csv(result["path"])
        data = frame[["y", "x"]].to_numpy(dtype=float)
        properties = {c: frame[c].to_numpy() for c in frame.columns[2:]}
        where = self._frame_for(result)
        if where is None:
            return self._without_frame(result)
        kwargs = self._transform_for(
            where, 2
        )  # before anything is removed: a refusal leaves the previous layer alone
        data = np.column_stack(where.to_data(data[:, 0], data[:, 1])) if len(data) else data
        name = self._layer_name(result)
        if result["name"] in self.replace and name in self.viewer.layers:
            self.viewer.layers.remove(
                self.viewer.layers[name]
            )  # Replace(): the new points take the place of the previous ones
        self.viewer.add_points(
            data,
            name=name,
            properties=properties or None,
            **kwargs,
            metadata=self._metadata(),
            size=POINT_SIZE,
            face_color="yellow",
            border_color="black",
        )
        return "points '%s' (%d)" % (result["name"], len(frame))

    def _shapes(self, result: Result) -> str:
        """GeoJSON outlines -> one polygon per part (Napari polygons have no holes: the outer boundary is drawn, and a note says so)."""
        import json

        where = self._frame_for(result)
        if where is None:
            return self._without_frame(result)
        kwargs = self._transform_for(
            where, 2
        )  # before anything is removed: a refusal leaves the previous layer alone
        collection = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        features = collection.get("features", [])
        total = len(
            features
        )  # what is counted and capped is the tool's objects (features), not their polygon parts
        polygons: list[np.ndarray] = []
        rows: list[dict[str, Any]] = []
        with_holes = 0
        for feature in features[:MAX_SHAPES]:
            geometry = feature["geometry"]
            parts = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
            for part in parts:
                ring = np.asarray(part[0], dtype=float)[:-1]  # closed ring: drop the repeated last vertex
                polygons.append(
                    np.column_stack(where.to_data(ring[:, 1], ring[:, 0]))
                )  # GeoJSON [x, y] -> exported-pixel (y, x) -> the data coordinate of the source (1.1.3)
                rows.append(feature.get("properties") or {})
                with_holes += len(part) > 1
        keys = sorted({k for row in rows for k in row})
        properties = {k: np.array([row.get(k, "") for row in rows]) for k in keys}
        name = self._layer_name(result)
        if result["name"] in self.replace and name in self.viewer.layers:
            self.viewer.layers.remove(
                self.viewer.layers[name]
            )  # Replace(): the new outlines take the place of the previous ones
        if polygons:
            self.viewer.add_shapes(
                polygons, shape_type="polygon", name=name, properties=properties or None, **kwargs,
                metadata=self._metadata(), edge_color="yellow", face_color="transparent", edge_width=OUTLINE_EDGE_WIDTH,
            )  # fmt: skip
        else:
            self.viewer.add_shapes(name=name, **kwargs, metadata=self._metadata())
        if total > MAX_SHAPES:
            self.messages.append(
                "**%s**: showing the first %d of %d outlines." % (result["name"], MAX_SHAPES, total)
            )
        if with_holes:
            self.messages.append(
                "**%s**: %d outline(s) have holes; the layer draws only the outer boundary."
                % (result["name"], with_holes)
            )
        return "outlines '%s' (%d)" % (result["name"], min(total, MAX_SHAPES))

    @staticmethod
    def _values(result: Result) -> str:
        return ", ".join(
            "%s=%s"
            % (key, NOT_FINITE if value is None else round(value, 4) if isinstance(value, float) else value)
            for key, value in result["values"].items()
        )

    @staticmethod
    def _file(result: Result) -> str:
        if not Path(result["path"]).is_file():
            raise FileNotFoundError("the tool reported the file %s but it does not exist" % result["path"])
        return "file: " + result["path"]

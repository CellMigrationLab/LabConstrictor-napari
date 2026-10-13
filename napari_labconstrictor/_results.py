"""Show typed tool results in napari. Switches on the result *type* only; knows nothing about any app."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from labconstrictor_tools import log
from qtpy.QtWidgets import QTableWidget, QTableWidgetItem

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
    """Stands in for a layer when an image parameter was given as a file (needed to place affine results)."""

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

    def _frame_scale(self, result: Result) -> tuple[float, float]:
        """The (y, x) scale of the image a points/shapes result is placed on: the image named by `apply_to`, else the
        FIRST IMAGE input (PROTOCOL.md), never the first input of some other type. (1, 1) when there is no such image.
        """
        name = result.get("apply_to") or next(iter(self.image_inputs), None)
        source = self.inputs.get(name) if name is not None else None
        if source is None or not hasattr(source, "scale"):
            return (1.0, 1.0)
        return (float(source.scale[-2]), float(source.scale[-1]))

    def _layer_name(self, result: Result) -> str:
        return "%s:%s" % (self.app, result["name"])

    def _image(self, result: Result) -> None:
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
        if result["name"] in self.replace and name in self.viewer.layers:
            old = self.viewer.layers[name]
            kind = type(old).__name__
            if kind == ("Labels" if result["type"] == "labels" else "Image") and old.data.ndim == data.ndim:
                old.data = data  # same layer: the view, contrast and position the user chose stay
                old.metadata = {**old.metadata, **self._metadata()}  # ... but it now belongs to this run
                return
            self.viewer.layers.remove(old)
        add(data, name=name, metadata=self._metadata())

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
        scale = self._frame_scale(result)
        name = self._layer_name(result)
        if result["name"] in self.replace and name in self.viewer.layers:
            self.viewer.layers.remove(
                self.viewer.layers[name]
            )  # Replace(): the new points take the place of the previous ones
        self.viewer.add_points(
            data,
            name=name,
            properties=properties or None,
            scale=scale,
            metadata=self._metadata(),
            size=POINT_SIZE,
            face_color="yellow",
            border_color="black",
        )
        return "points '%s' (%d)" % (result["name"], len(frame))

    def _shapes(self, result: Result) -> str:
        """GeoJSON outlines -> one polygon per part (Napari polygons have no holes: the outer boundary is drawn, and a note says so)."""
        import json

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
                polygons.append(ring[:, ::-1])  # GeoJSON [x, y] -> Napari (y, x)
                rows.append(feature.get("properties") or {})
                with_holes += len(part) > 1
        keys = sorted({k for row in rows for k in row})
        properties = {k: np.array([row.get(k, "") for row in rows]) for k in keys}
        scale = self._frame_scale(result)
        name = self._layer_name(result)
        if result["name"] in self.replace and name in self.viewer.layers:
            self.viewer.layers.remove(
                self.viewer.layers[name]
            )  # Replace(): the new outlines take the place of the previous ones
        if polygons:
            self.viewer.add_shapes(
                polygons, shape_type="polygon", name=name, properties=properties or None, scale=scale,
                metadata=self._metadata(), edge_color="yellow", face_color="transparent", edge_width=OUTLINE_EDGE_WIDTH,
            )  # fmt: skip
        else:
            self.viewer.add_shapes(name=name, scale=scale, metadata=self._metadata())
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

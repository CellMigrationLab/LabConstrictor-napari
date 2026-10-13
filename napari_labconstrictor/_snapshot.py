"""One run, frozen at the click (docs/SPEC_WRONG_SCIENCE.md section 4, run identity).

The widget builds ONE `RunSnapshot` on the UI thread before anything is exported or sent to a worker, and carries it through the
export, the worker call, the result placement and the run record. Nothing after the click reads the form again:

* RUN identity: `run_id` (a uuid4), `app`, `tool`: what the result metadata and the run record say come from here, so switching the
  chooser to another tool while this one runs cannot rebind them (4.5).
* Source identity is the LAYER OBJECT, never its name (4.2). At placement the host asks `still_open` (is that very object still in
  `viewer.layers`) and `shape_changed` (is its data still the shape that was exported) (4.4).
* The selection (the Shapes layer chosen for a `RegionOf` input) is copied BY VALUE: its vertices and shape types are arrays of
  their own, so editing or deleting shapes during the export cannot change the mask that is written (4.1, 4.3).

Pure data and two helpers; no Qt. Written for Napari: `layer` is a napari Image, Labels or Shapes layer.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from ._frame import Frame, frame_of_file, frame_of_layer, world_matrix

TARGET_UNAVAILABLE = "target_unavailable"  # the host-internal code of SPEC_WRONG_SCIENCE 1.4 / 4.4
# the sentence of conformance.json `messages.target_unavailable` (tests compare it with the file)
TARGET_UNAVAILABLE_TEXT = "run {run_id} on '{source}': '{source}' is no longer open; results are in {path}"
# SPEC GAP: the spec gives one sentence ("no longer open"); a source that is still open but whose data changed size needs its own
TARGET_RESIZED_TEXT = (
    "run {run_id} on '{source}': '{source}' changed size while the tool ran; results are in {path}"
)
CLOSED, RESIZED = "closed", "resized"


def level0(layer: Any) -> Any:
    """The full-resolution data of an image or labels layer (level 0 of a multiscale one)."""
    return layer.data[0] if getattr(layer, "multiscale", False) else layer.data


@dataclass(frozen=True)
class SourceRef:
    """An image or labels input as it was when the run started."""

    param: str
    layer: Any  # the layer object itself: identity, not a name
    name: str  # for sentences only
    shape: tuple[int, ...]  # data shape at the click (level 0)
    scale: tuple[float, ...]
    frame: (
        Frame | None
    )  # the exported image's frame (SPEC_WRONG_SCIENCE 1.1.2): shape and the full transform at the click


@dataclass(frozen=True)
class SelectionRef:
    """The selected Shapes layer at the click, copied by value."""

    layer: Any
    name: str
    vertices: tuple[
        np.ndarray, ...
    ]  # one read-only copy per shape (rows are the shape's vertices, last two columns y, x)
    shape_types: tuple[str, ...]
    scale: tuple[float, ...]
    matrix: (
        np.ndarray
    )  # the layer's full data -> world matrix at the click (read-only): scale, translate, rotate, shear, affine


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    app: str
    tool: Mapping[str, Any]  # a deep copy of the tool's schema entry
    values: Mapping[str, Any]  # copies of the plain form values (layers are in `sources`)
    sources: Mapping[str, SourceRef]
    files: Mapping[str, Path]  # image parameter -> the file chosen instead of a layer
    regions: frozenset[str]  # RegionOf parameters whose "use the selection" box was ticked
    unset: frozenset[str]  # optional parameters left unset (omitted from the request)
    channels: Mapping[str, int | None]  # image parameter -> the channel picked (or None)
    selection: SelectionRef | None
    frames: Mapping[str, Frame] = field(
        default_factory=dict
    )  # image parameter -> the frame of its exported image (layer or file)
    started: str = field(default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))

    @property
    def tool_id(self) -> str:
        return str(self.tool["id"])

    def value(self, name: str) -> Any:
        """The value of parameter `name` as it was at the click: the layer object for an image or labels input."""
        source = self.sources.get(name)
        return source.layer if source is not None else self.values.get(name)

    def frame(self, name: str) -> Frame | None:
        """The frame recorded at the click for image or labels input `name` (a layer's, or a file's pixel frame), else None."""
        return self.frames.get(name)

    def metadata(self) -> dict[str, dict[str, str]]:
        """What every layer drawn for this run carries in `layer.metadata`: app and tool come from the snapshot, never the widget."""
        return {"labconstrictor": {"run_id": self.run_id, "app": self.app, "tool": self.tool_id}}

    # ---- placement (4.4) --------------------------------------------------------------------------------------
    def problem_with(self, name: str, layers: Iterable[Any]) -> str | None:
        """None when input `name` is still what was exported, else CLOSED (that layer object is not in `layers`) or RESIZED."""
        source = self.sources.get(name)
        if source is None:  # a file, or not a layer: nothing to look up
            return None
        if not any(layer is source.layer for layer in layers):
            return CLOSED
        try:
            shape = tuple(level0(source.layer).shape)
        except (
            AttributeError,
            IndexError,
            TypeError,
        ):  # data that cannot be looked at any more counts as changed
            return RESIZED
        return RESIZED if shape != source.shape else None


def unavailable_sentence(run_id: str, source: str, reason: str, path: Any) -> str:
    """The one sentence for a result that was not drawn because its source is gone (`target_unavailable`)."""
    template = TARGET_RESIZED_TEXT if reason == RESIZED else TARGET_UNAVAILABLE_TEXT
    return template.format(run_id=run_id, source=source, path=path)


def _readonly(array: Any) -> np.ndarray:
    copy_ = np.array(array, dtype=float, copy=True)
    copy_.setflags(write=False)
    return copy_


def selection_of(layer: Any | None) -> SelectionRef | None:
    """Copy a Shapes layer's geometry by value (None when there is no layer)."""
    if layer is None:
        return None
    return SelectionRef(
        layer,
        str(layer.name),
        tuple(_readonly(vertices) for vertices in layer.data),
        tuple(str(kind) for kind in layer.shape_type),
        tuple(float(s) for s in layer.scale),
        _readonly(world_matrix(layer)),
    )


def take(
    app: str,
    tool: Mapping[str, Any],
    form_values: Mapping[str, Any],
    *,
    files: Mapping[str, Path] | None = None,
    regions: Iterable[str] = (),
    unset: Iterable[str] = (),
    channels: Mapping[str, int | None] | None = None,
    selection_layer: Any | None = None,
) -> RunSnapshot:
    """Freeze a run: what the form said, which layer objects it named, the selection geometry. Call it on the UI thread first."""
    files = dict(files or {})
    sources: dict[str, SourceRef] = {}
    frames: dict[str, Frame] = {}
    values: dict[str, Any] = {}
    layer_params = {p["name"] for p in tool["inputs"] if p["type"] in ("image", "labels")}
    for name in layer_params & files.keys():  # a file is its own pixel frame, whatever else is open (CF-07)
        frames[name] = frame_of_file(name, files[name])
    for name, value in form_values.items():
        if name in layer_params and value is not None and name not in files:
            data = level0(value)
            frame = (
                frame_of_layer(name, value) if hasattr(value, "data_to_world") else None
            )  # None: not a napari layer
            if frame is not None:
                frames[name] = frame
            sources[name] = SourceRef(
                name,
                value,
                str(getattr(value, "name", name)),
                tuple(data.shape),
                tuple(float(s) for s in getattr(value, "scale", ())),
                frame,
            )
        elif name in layer_params:
            values[name] = None if name in files else value  # a file wins over the layer chooser
        else:
            values[name] = copy.deepcopy(value)
    return RunSnapshot(
        run_id=str(uuid.uuid4()),
        app=app,
        tool=MappingProxyType(copy.deepcopy(dict(tool))),
        values=MappingProxyType(values),
        sources=MappingProxyType(sources),
        files=MappingProxyType(files),
        regions=frozenset(regions),
        unset=frozenset(unset),
        channels=MappingProxyType(dict(channels or {})),
        selection=selection_of(selection_layer),
        frames=MappingProxyType(frames),
    )

"""ONE napari dock widget for every installed LabConstrictor app.

registry (cached JSON) -> app/tool choosers -> schema -> synthesized signature -> magicgui form -> worker -> typed results
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from labconstrictor_tools import log, registry
from labconstrictor_tools import runs as tools_runs
from labconstrictor_tools.protocol import JOB_DIR_KEY
from magicgui import magicgui
from magicgui import widgets as mw
from magicgui.types import FileDialogMode
from qtpy.QtCore import QObject, Qt, QTimer, Signal
from qtpy.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import _calibration, _lookups, _numbers, _retention, _snapshot
from ._calibration import UNSET, USER, Derived, LinkState
from ._export import ChannelError, channel_file, channel_layout, export_layer, selection_mask
from ._export import is_set as _is_set
from ._frame import FrameError
from ._lookups import Lookup, LookupQueue, Reply, next_form_gen, snapshot_deps
from ._results import COULD_NOT_DISPLAY, FileInput, ResultPresenter
from ._schema import Param, Tool, presentation_order, rule_satisfied, signature_from_schema
from ._units import TIFF_READ_ERRORS, calibration_from_tiff, calibration_of_layer
from ._workers import WorkerCache

if TYPE_CHECKING:  # annotation only; at runtime napari passes a proxy under the name `napari_viewer`
    from napari import Viewer

CANCEL_GRACE_S = 3.0  # how long a tool gets to honour Cancel before its worker is killed
REAP_INTERVAL_MS = 30_000  # how often idle workers are looked for (see WorkerCache.reap_idle)
CHOICES_DEBOUNCE_MS = 400  # wait after a controlling value changes before asking for new ChoicesFrom options
CHOICES_RETRY_MS = 1500  # a run is using the worker: ask again after this long
CHOICES_AFTER_RUN_MS = 200  # a finished run may have changed what the source tool answers: ask again
FORM_MIN_HEIGHT_PX = 180  # the form area never shrinks below this, however small the dock
OUTCOME_MIN_HEIGHT_PX = 110  # the status/message box: at least a few lines ...
OUTCOME_MAX_HEIGHT_PX = 320  # ... and at most this tall (longer text scrolls) so it never squeezes the form
STDERR_TAIL_CHARS = 3000  # worker output kept in the Details report
_FINISH_TEXT = {"CANCELED": "cancelled"}
CALIBRATION_KEY = (
    "_calibration"  # reserved input (SPEC_WRONG_SCIENCE 2.3.4): per-axis pixel size with provenance
)
_OMIT = object()  # "leave this parameter out" (None is a real value)
_NO_RESULT_CODES = ("no_match", "no_result")  # an outcome ("nothing found"), not a fault: shown as a notice


def _tool_names(schema: dict[str, Any]) -> list[tuple[str, Tool]]:
    """[(name shown in the chooser, tool)]: the label, or `label (id)` when two tools share a label (never pick the wrong one)."""
    labels = [t["label"] for t in schema["tools"]]
    return [
        (t["label"] if labels.count(t["label"]) == 1 else "%s (%s)" % (t["label"], t["id"]), t)
        for t in schema["tools"]
    ]


def _failure_line(first_line: str) -> str:
    return "✖ %s  - click Details… for the full report (log: %s)" % (first_line, log.log_path())


def _unfinished_text(task: Any) -> str:
    """The status line for a task that did not complete (failed, cancelled or crashed)."""
    first_line = (task.error or "").splitlines()[0] if task.error else task.status
    if task.status == "FAILED" and getattr(task, "code", None) in _NO_RESULT_CODES:
        return "⚠ " + first_line.split("] ", 1)[-1]
    if task.status == "CRASHED" and getattr(task, "cancel_requested", False):
        return "cancelled (worker stopped)"
    if task.status == "CRASHED" or task.status not in _FINISH_TEXT:
        return _failure_line(first_line)
    return _FINISH_TEXT[task.status]


class _Signals(QObject):
    progress = Signal(object, object)
    done = Signal(object)
    choices = Signal(
        object
    )  # a _lookups.Reply (plain data, built on the lookup thread, applied on the main thread)


# `cast(Tool, ...)` below: `tool` is None only before a tool is chosen, and these methods run only from a built form;
# the cast is a no-op at run time (the behaviour on None is unchanged).


class LabConstrictorWidget(QWidget):
    """The one dock widget: owns the form of the chosen tool and the state of the run in progress (task, worker, job folder).

    Qt and magicgui objects are typed `Any` below because neither ships stubs mypy can use; the schema dicts are `Tool`/`Param`.
    """

    def __init__(self, napari_viewer: Viewer | None = None) -> None:
        super().__init__()
        self.viewer = napari_viewer
        self._init_state()
        self._workers = WorkerCache()
        self._lookups = LookupQueue(self._run_lookup)
        self._signals = _Signals()
        self._signals.progress.connect(self._on_progress)
        self._signals.done.connect(self._on_done)
        self._signals.choices.connect(self._on_choices)
        self._choice_timer = QTimer(self)
        self._choice_timer.setSingleShot(True)
        self._choice_timer.timeout.connect(self._resolve_choices)
        self._build_layout()
        if self.viewer is not None:
            # Layer choosers must follow the layer list even if this widget was built before it was docked.
            self.viewer.layers.events.inserted.connect(self._refresh_layer_choices)
            self.viewer.layers.events.removed.connect(self._refresh_layer_choices)
        self.rescan()

    def _init_state(self) -> None:
        # `Any` below: magicgui/Qt widgets and the Task/WorkerProcess objects of labconstrictor_tools have no stubs, and
        # the run-state attributes are None until a run starts (then set together by _begin_run / _start_worker)
        self.apps: dict[str, Any] = {}
        self.schemas: dict[str, Any] = {}
        self.gui: Any = None  # the magicgui form of the current tool
        self.file_sources: dict[str, Any] = {}  # image parameter -> "or file" widget
        self._cal_commit: dict[str, Callable[[], None]] = (
            {}
        )  # PixelSizeOf parameter -> handle the entry still being typed
        self.cal_links: dict[str, LinkState] = {}  # PixelSizeOf parameter -> its state (unset / auto / user)
        self._cal_refresh: dict[str, Any] = (
            {}
        )  # PixelSizeOf parameter -> derive its value from the current source again
        self.unset_toggles: dict[str, Any] = {}  # nullable parameter -> "set" checkbox
        self.region_toggles: dict[str, Any] = {}  # RegionOf parameter -> "use the selection" checkbox
        self.channel_boxes: dict[str, Any] = {}  # PickChannel image parameter -> its channel chooser
        self.advanced_toggle: Any = (
            None  # "Show advanced settings" checkbox (only when a tool has advanced parameters)
        )
        self._members: dict[str, list[Any]] = (
            {}
        )  # parameter -> its widgets (value widget, "or file" row, "set" box)
        self.task: Any = None
        self.worker: Any = None
        self.last_task: Any = None
        self.presenter: Any = None  # a ResultPresenter once a run has started
        self.last_record: Any = None
        self.last_details = ""
        self.snapshot: _snapshot.RunSnapshot | None = (
            None  # the run in progress (or the last one), frozen at the click
        )
        self._record: _retention.RunRecord | None = None  # its run record folder (markers)
        self._results: _retention.ResultsFolder | None = (
            None  # its results folder, made only when a file must be kept
        )
        self._show_problem = ""  # why its results could not be shown completely (goes into the details)
        self.last_prune: threading.Thread | None = (
            None  # the thread watching the last `prune` subprocess (tests join it)
        )
        self._closed = (
            False  # True once the widget was closed during the current run: closeEvent already ended that run
        )
        self._request: dict[str, Any] = {}
        # what the running task was started with (the choosers may change meanwhile)
        self._run_app: Any = None
        self._run_tool: Any = None
        self.timings: dict[str, float] = {}
        self._choice_boxes: dict[str, Any] = {}  # ChoicesFrom parameter -> its dropdown
        self._choice_latest: dict[str, int] = (
            {}
        )  # parameter -> request_id of its newest question (advanced the moment a dependency changes); older answers are dropped
        self._choice_pending: set[str] = (
            set()
        )  # parameters whose choices are not known yet (SPEC_WRONG_SCIENCE 5.3)
        self._choice_dependents: dict[str, list[str]] = (
            {}
        )  # controlling parameter -> ChoicesFrom parameters that use it
        self._choice_base_tip: dict[str, str] = (
            {}
        )  # parameter -> its tooltip before a lookup problem was added
        self._form_gen = (
            next_form_gen()
        )  # process-wide, never reset: changes whenever a form is built or destroyed (5.1)
        self._request_id = 0  # per widget, never reset
        self._lookup_note = (
            ""  # the status line text a lookup problem put there (so that the next one replaces it)
        )
        self._shut_down = False  # True while closeEvent runs: nothing is started or applied meanwhile
        self._was_closed = False  # closeEvent ran: the next showEvent asks the dropped questions again
        self._run_thread: threading.Thread | None = None
        self._docks: dict[tuple[str, str], Any] = (
            {}
        )  # (app, table name) -> dock widget, so that Replace can swap it
        self._group_members: dict[str, list[Any]] = {}  # collapsible group -> widgets

    # ---- layout -------------------------------------------------------
    def _build_layout(self) -> None:
        self._create_controls()
        layout = QVBoxLayout(self)
        for widget in (self.app_box.native, self.tool_box.native, self.description):
            layout.addWidget(widget)
        layout.addWidget(self._build_form_area(), 1)
        layout.addWidget(self.bar)
        layout.addWidget(self._build_outcome_area(), 1)
        layout.addWidget(self.reuse_box)
        layout.addLayout(self._button_row())
        self._connect_controls()

    def _create_controls(self) -> None:
        self.app_box = mw.ComboBox(label="Application")
        self.tool_box = mw.ComboBox(label="Tool")
        self.description = QLabel("")
        self.description.setWordWrap(True)
        self.form_holder = QVBoxLayout()
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.status = QLabel("idle")
        self.status.setWordWrap(True)
        self.message_label = QLabel(
            ""
        )  # message results of the last run (markdown); hidden when there is none
        self.message_label.setWordWrap(True)
        self.message_label.setTextFormat(Qt.TextFormat.MarkdownText)
        self.message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message_label.setStyleSheet("QLabel { border-left: 3px solid #5a9fd4; padding: 4px 8px; }")
        self.message_label.setVisible(False)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.rescan_button = QPushButton("Rescan apps")
        self.reuse_box = QCheckBox("Keep the worker running between runs (faster repeat runs)")
        self.reuse_box.setChecked(True)
        self.restart_button = QPushButton("Restart worker")
        self.details_button = QPushButton("Details…")
        self.details_button.setEnabled(False)
        self.details_button.setToolTip("Error details, worker output and the run record of the last run")
        self.copy_button = QPushButton("Copy as command")
        self.copy_button.setToolTip(
            "Copy what repeats this run outside Napari: a terminal line or a Python snippet"
        )
        copy_menu = QMenu(self.copy_button)
        for label, kind in (("Terminal command", "terminal"), ("Python snippet", "python")):
            action = copy_menu.addAction(label)
            if action is None:  # Qt's stubs allow it; addAction(str) never returns None in practice
                raise RuntimeError("Qt could not create the menu entry %r" % label)
            action.triggered.connect(self._copy_handler(kind))
        self.copy_button.setMenu(copy_menu)

    def _copy_handler(self, kind: str) -> Callable[..., None]:
        """A menu-entry slot that copies as `kind` (a slot returns nothing; the copied text is for tests/callers)."""

        def copy(*_: object) -> None:
            self.copy_as_command(kind)

        return copy

    def _button_row(self) -> QHBoxLayout:
        buttons = QHBoxLayout()
        for button in (
            self.cancel_button,
            self.rescan_button,
            self.restart_button,
            self.details_button,
            self.copy_button,
        ):
            buttons.addWidget(button)
        return buttons

    def _build_form_area(self) -> QScrollArea:
        """The form can be taller than the dock (advanced settings of a big tool): it scrolls, while the progress bar, status and
        buttons below stay in view."""
        form_container = QWidget()
        form_container.setLayout(self.form_holder)
        self.form_holder.setContentsMargins(0, 0, 0, 0)
        self.form_holder.addStretch(1)  # a short form sits at the top instead of being spread over the dock
        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.form_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )  # a form wider than the dock scrolls sideways: nothing is clipped out of reach
        self.form_scroll.setMinimumHeight(FORM_MIN_HEIGHT_PX)
        self.form_scroll.setWidget(form_container)
        return self.form_scroll

    def _build_outcome_area(self) -> QScrollArea:
        """Status and message can be long (a readout, many values): they scroll in a box of limited height, so they never
        squeeze the form."""
        outcome = QWidget()
        outcome_layout = QVBoxLayout(outcome)
        outcome_layout.setContentsMargins(0, 0, 0, 0)
        outcome_layout.addWidget(self.message_label)  # the readout first: it is what the person came for
        outcome_layout.addWidget(self.status)
        outcome_layout.addStretch(1)
        self.outcome_scroll = QScrollArea()
        self.outcome_scroll.setWidgetResizable(True)
        self.outcome_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.outcome_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.outcome_scroll.setMaximumHeight(OUTCOME_MAX_HEIGHT_PX)
        self.outcome_scroll.setMinimumHeight(OUTCOME_MIN_HEIGHT_PX)
        self.outcome_scroll.setWidget(outcome)
        return self.outcome_scroll

    def _connect_controls(self) -> None:
        self.cancel_button.clicked.connect(self.cancel)
        self.details_button.clicked.connect(self._show_details)
        self.rescan_button.clicked.connect(self.rescan)
        self.restart_button.clicked.connect(lambda *_: self._workers.discard(self.app_box.value))
        self._stderr_mark: int | None = 0  # how much worker output existed when the current run started
        self._reaper = QTimer(self)
        self._reaper.timeout.connect(self._workers.reap_idle)
        self._reaper.start(REAP_INTERVAL_MS)
        # closing the Napari window deletes this widget without calling closeEvent: stop the workers then too (not only when the
        # whole Python process ends); bound to the cache object, which outlives the widget
        self.destroyed.connect(
            lambda *_, lookups=self._lookups, workers=self._workers: (
                lookups.close(final=True),
                workers.shutdown(final=True),
            )
        )
        self.app_box.changed.connect(self._on_app_changed)
        self.tool_box.changed.connect(self._on_tool_changed)

    def showEvent(self, event: Any) -> None:  # Qt API name
        super().showEvent(event)
        if (
            self._was_closed
        ):  # closed earlier and shown again: the questions that closing dropped are asked again
            self._was_closed = False
            self._reaper.start(REAP_INTERVAL_MS)
            self._mark_choices_pending()
            self._schedule_choices(0)
        if not getattr(self, "_shown_once", False):
            self._shown_once = True
            self._on_tool_changed()  # rebuild once now that a viewer ancestor exists

    # ---- discovery: cached JSON only (no Python subprocess, no scientific imports) ----
    def rescan(self, *_: Any) -> None:
        started = time.perf_counter()
        self.schemas, problems = registry.load_schemas()  # one broken app must not hide the others
        self.apps = {name: entry for name, entry in registry.load_all().items() if name in self.schemas}
        self.timings["discovery_ms"] = (time.perf_counter() - started) * 1000
        self.app_box.choices = sorted(self.apps) or ["(none registered)"]
        self._on_app_changed()
        if problems:
            self.status.setText("⚠ skipped: " + "; ".join("%s (%s)" % problem for problem in problems))

    def _on_app_changed(self, *_: Any) -> None:
        schema = self.schemas.get(self.app_box.value)
        self.tool_box.choices = [name for name, _ in _tool_names(schema)] if schema else []
        self._on_tool_changed()

    @property
    def tool(self) -> Tool | None:
        schema = self.schemas.get(self.app_box.value)
        if not schema:
            return None
        return next((t for name, t in _tool_names(schema) if name == self.tool_box.value), None)

    # ---- form ---------------------------------------------------------
    def _on_tool_changed(self, *_: Any) -> None:
        self._remove_form()
        tool = self.tool
        if not tool:
            self.description.setText("")
            return
        started = time.perf_counter()
        self.description.setText(tool.get("description", ""))
        try:
            self.gui = self._make_form(tool)
        except (
            ValueError
        ) as error:  # a schema this host cannot show (e.g. an unknown parameter type): say so, no guessed form
            log.error("napari: cannot build the form for %s: %s", tool.get("id"), error)
            self.status.setText("⚠ this tool cannot be shown: %s" % error)
            return
        self._form_gen = next_form_gen()  # a form was built (5.1)
        self._freeze_slider_readouts()
        self.file_sources = self._add_file_sources(tool)
        self.channel_boxes = self._add_channel_choosers(tool)
        self.unset_toggles = self._add_unset_toggles(tool)
        self.region_toggles = self._add_region_toggles(tool)
        self._apply_presentation(tool)
        self._add_choice_boxes(tool)
        self.gui.native.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.form_holder.insertWidget(0, self.gui.native)
        self._schedule_choices(0)
        for param in tool["inputs"]:
            if param.get("pixel_size_of"):
                self._link_calibration(param["pixel_size_of"], param["name"])
        self.timings["gui_construction_ms"] = (time.perf_counter() - started) * 1000

    def _freeze_slider_readouts(self) -> None:
        """A slider's number box beside it shows the position and takes no typing: a Qt spin box would clamp or round a typed value
        (SPEC_WRONG_SCIENCE 6.2); a person who wants to type a number is given a text field by the tool (no `widget: slider`).
        """
        for widget in self.gui or []:
            readout = getattr(getattr(widget, "_widget", None), "_readout_widget", None)
            if readout is not None:
                readout.lineEdit().setReadOnly(True)

    def _remove_form(self) -> None:
        self._form_gen = next_form_gen()  # a form was destroyed (5.1): every answer on its way is void
        self._lookups.drop_all()  # pending lookups forgotten, the one in flight cancelled
        self._choice_latest, self._choice_pending = {}, set()
        self._choice_dependents, self._choice_base_tip = {}, {}
        if self.gui is not None:
            self.form_holder.removeWidget(self.gui.native)
            self.gui.native.setParent(None)
            self.gui = None
            self.file_sources = {}
            self.cal_links, self._cal_refresh, self._cal_commit = {}, {}, {}
            self.unset_toggles = {}
            self.region_toggles = {}
            self.channel_boxes = {}
            self.advanced_toggle, self._members = None, {}
            self._choice_boxes, self._group_members = {}, {}

    def _make_form(self, tool: Tool) -> Any:
        from napari.layers import Image, Labels

        def run(**form_values: Any) -> None:
            self._launch(form_values)

        signature = signature_from_schema(tool, {"image": Image, "labels": Labels})
        run.__signature__ = signature  # type: ignore[attr-defined]  # typeshed omits __signature__ on functions; magicgui reads it
        run.__name__ = tool["id"]
        return magicgui(run, call_button="Run", persist=False, auto_call=False)

    def _add_file_sources(self, tool: Tool) -> dict[str, Any]:
        """Every image/labels parameter can also come from a file: an 'or file' row under its layer chooser.
        A chosen file wins over the layer (which is greyed out); empty it to go back to the layer."""
        sources = {}
        for param in tool["inputs"]:
            if param["type"] not in ("image", "labels"):
                continue
            layer_widget = self.gui[param["name"]]
            edit = mw.FileEdit(
                mode=FileDialogMode.EXISTING_FILE,  # "r"
                nullable=True,
                label="  or file",
                tooltip="Read the image from a file instead of a layer (leave empty to use the layer above)",
                gui_only=True,
            )
            self.gui.insert(list(self.gui).index(layer_widget) + 1, edit)

            edit.changed.connect(lambda *_: self._refresh_enabled())
            sources[param["name"]] = edit
        return sources

    def _add_channel_choosers(self, tool: Tool) -> dict[str, Any]:
        """PickChannel: a Channel chooser under the image. It lists the channels it can see (the colours of an RGB layer, the C axis of a
        TIFF given as a file) and is hidden when there is only one; the tool then receives just the chosen channel.
        """
        boxes = {}
        for param in tool["inputs"]:
            if not param.get("pick_channel") or param["name"] not in self.file_sources:
                continue
            name = param["name"]
            box = mw.ComboBox(
                choices=[""], label="  channel", tooltip="The tool receives only this channel", gui_only=True
            )
            box.visible = False
            edit = self.file_sources[name]
            self.gui.insert(list(self.gui).index(edit) + 1, box)
            boxes[name] = box
            self.gui[name].changed.connect(lambda *_, n=name: self._refresh_channels(n))
            edit.changed.connect(lambda *_, n=name: self._refresh_channels(n))
            self.channel_boxes[name] = box
            self._refresh_channels(name)
        return boxes

    def _channel_names(self, name: str) -> list[str]:
        """The channels of what is chosen for image parameter `name`: names, or [] when the image is a single channel."""
        source = self.file_sources.get(name)
        if source is not None and _is_set(source.value):
            import tifffile

            label = next((p["label"] for p in cast(Tool, self.tool)["inputs"] if p["name"] == name), name)
            try:  # the file's tags only: no pixel is read to fill the chooser
                layout = channel_layout(Path(str(source.value)), label)
                if layout is not None:
                    return layout[1]
            except (
                ChannelError
            ) as error:  # a layout nothing can be picked from (C and S together, alpha): said now, refused at Run
                self.status.setText("⚠ %s" % error)
            except (
                *TIFF_READ_ERRORS,
                tifffile.TiffFileError,
            ) as error:  # unreadable: no channels to choose from
                log.warning(
                    "napari: cannot read the channels of %s (%s: %s)",
                    source.value,
                    type(error).__name__,
                    error,
                )
                self.status.setText("⚠ could not read the channels of %s: %s" % (source.value, error))
            return []
        layer = self.gui[name].value
        if layer is not None and getattr(layer, "rgb", False):
            return ["Red", "Green", "Blue"]
        return []

    def _refresh_channels(self, name: str) -> None:
        box = self.channel_boxes.get(name)
        if box is None:
            return
        names = self._channel_names(name)
        box.choices = names or [""]
        box.value = names[0] if names else ""
        box.visible = len(names) > 1

    def _add_unset_toggles(self, tool: Tool) -> dict[str, Any]:
        """A number, text or yes/no that is optional and has no default may be left UNSET (the tool then receives None). These
        widgets cannot show "nothing" (an unchecked box would mean False), so each gets a 'set' checkbox: unchecked = greyed
        out and left out of the request."""
        toggles = {}
        for param in tool["inputs"]:
            if (
                param.get("pixel_size_of")
                or not param.get("nullable")
                or param["type"]
                not in (
                    "integer",
                    "float",
                    "string",
                    "choice",
                    "boolean",
                )
            ):
                continue
            widget = self.gui[param["name"]]
            if param["type"] == "string" and getattr(widget, "value", None) == "None":
                widget.value = ""
            toggle = mw.CheckBox(
                value=False,
                text="set",
                label="  (optional)",
                tooltip="Leave unchecked to not set this value",
                gui_only=True,
            )
            self.gui.insert(list(self.gui).index(widget) + 1, toggle)
            widget.enabled = False
            toggle.changed.connect(lambda *_: self._refresh_enabled())
            toggles[param["name"]] = toggle
        return toggles

    def _add_region_toggles(self, tool: Tool) -> dict[str, Any]:
        """RegionOf: an optional Labels input that the host fills from the selection. A 'use the selection' box (off by default)
        decides whether the selected Shapes layer is sent as the region; when on it takes the place of the layer chooser.
        """
        toggles = {}
        for param in tool["inputs"]:
            if not param.get("region_of"):
                continue
            toggle = mw.CheckBox(
                value=False,
                text="use the selection",
                label="  (region)",
                tooltip="Send the shapes of the selected Shapes layer as the region (several shapes are labels 1, 2, 3...)",
                gui_only=True,
            )
            self.gui.insert(list(self.gui).index(self.gui[param["name"]]) + 1, toggle)
            toggle.changed.connect(lambda *_: self._refresh_enabled())
            toggles[param["name"]] = toggle
        return toggles

    def _selection_mask(self, param: Param, snapshot: _snapshot.RunSnapshot, job_dir: Path) -> str:
        """The shapes of the selection AS THEY WERE AT THE CLICK as a label image (see `_export.selection_mask`)."""
        name = param["region_of"]
        return selection_mask(
            snapshot.selection,
            param,
            snapshot.files.get(name),
            snapshot.sources.get(name),
            job_dir,
            image_label=self._label_of(name, snapshot),
        )

    def _label_of(self, name: str, snapshot: _snapshot.RunSnapshot | None = None) -> str:
        """The label the person sees for parameter `name` (of the tool that was started, when a run snapshot is given)."""
        tool = snapshot.tool if snapshot is not None else cast(Tool, self.tool)
        return next((p["label"] for p in tool["inputs"] if p["name"] == name), name)

    # ---- presentation hints: group headings, advanced settings, enabled_when ----
    def _apply_presentation(self, tool: Tool) -> None:
        inputs = presentation_order(tool)["inputs"]
        self._members = {
            p["name"]: [
                w
                for w in (
                    self.gui[p["name"]],
                    self.file_sources.get(p["name"]),
                    self.channel_boxes.get(p["name"]),
                    self.unset_toggles.get(p["name"]),
                )
                if w is not None
            ]
            for p in inputs
        }
        advanced_widgets = self._insert_headings(inputs)
        for widget in advanced_widgets:
            widget.visible = False
        for group, widgets in self._group_members.items():  # accordion sections start folded
            self._set_group_open(group, widgets, False)
        for p in inputs:  # a parameter's rule is re-evaluated whenever its controlling parameter changes
            rule = p.get("enabled_when")
            if rule:
                controller = self.gui[rule["param"]]
                controller.changed.connect(lambda *_: self._refresh_enabled())
        self._refresh_enabled()

    def _insert_headings(self, inputs: list[Param]) -> list[Any]:
        """Put the group headings (and the 'Show advanced settings' box) into the form; returns the advanced widgets."""
        advanced_widgets: list[Any] = []
        previous_group = None
        for p in inputs:
            first = self._members[p["name"]][0]
            if p.get("advanced") and self.advanced_toggle is None:
                self._add_advanced_toggle(first, advanced_widgets)
            group = p.get("group")
            if group and group != previous_group:
                heading = self._group_heading_widget(group, p.get("group_collapsed"))
                self.gui.insert(list(self.gui).index(first), heading)
                if p.get("advanced"):
                    advanced_widgets.append(heading)
            previous_group = group or previous_group
            if p.get("group_collapsed") and group:
                self._group_members.setdefault(group, []).extend(self._members[p["name"]])
            if p.get("advanced"):
                advanced_widgets.extend(self._members[p["name"]])
        return advanced_widgets

    def _add_advanced_toggle(self, first: Any, advanced_widgets: list[Any]) -> None:
        self.advanced_toggle = mw.CheckBox(
            value=False, text="Show advanced settings", label="", gui_only=True
        )
        self.gui.insert(list(self.gui).index(first), self.advanced_toggle)

        def show_advanced(shown: Any) -> None:
            for w in advanced_widgets:
                w.visible = bool(shown)

        self.advanced_toggle.changed.connect(show_advanced)

    def _group_heading_widget(self, group: str, collapsed: Any) -> Any:
        if collapsed:
            return self._accordion_heading(group)
        heading = mw.Label(value=group, label="")
        heading.native.setStyleSheet("font-weight: bold; padding-top: 6px;")
        return heading

    # ---- accordion groups (Collapsed) ----
    def _accordion_heading(self, group: str) -> Any:
        button = mw.PushButton(text="\u25b8 " + group, label="", gui_only=True)
        button.native.setFlat(True)
        button.native.setStyleSheet("font-weight: bold; text-align: left; padding-top: 6px;")
        button.native.setProperty("lc_group", group)
        button.changed.connect(lambda *_: self._toggle_group(group, button))
        self._group_heading = getattr(self, "_group_heading", {})
        self._group_heading[group] = button
        return button

    def _toggle_group(self, group: str, button: Any) -> None:
        widgets = self._group_members[group]
        self._set_group_open(group, widgets, not all(w.visible for w in widgets))

    def _set_group_open(self, group: str, widgets: list[Any], opened: bool) -> None:
        for w in widgets:
            w.visible = opened
        button = getattr(self, "_group_heading", {}).get(group)
        if button is not None:
            button.text = ("\u25be " if opened else "\u25b8 ") + group

    # ---- dynamic choices (ChoicesFrom) ----
    def _add_choice_boxes(self, tool: Tool) -> None:
        """A dropdown beside the text field of a ChoicesFrom parameter. The text field stays the value (what is sent); the
        dropdown, when the source tool could answer, hides it and writes into it. When it cannot answer, the text field shows.
        """
        self._choice_boxes = {}
        self._choice_dependents = {}
        for p in tool["inputs"]:
            src = p.get("choices_from")
            if not src:
                continue
            field = self.gui[p["name"]]
            box = mw.ComboBox(choices=[""], label=p["label"], tooltip=p.get("description", ""), gui_only=True)
            box.visible = False
            self.gui.insert(list(self.gui).index(field) + 1, box)
            box.changed.connect(lambda value, f=field, n=p["name"]: self._choice_picked(n, f, value))
            self._choice_boxes[p["name"]] = box
            for name in src["depends"]:
                self._choice_dependents.setdefault(name, []).append(p["name"])
        for name in self._choice_dependents:
            self.gui[name].changed.connect(lambda *_, n=name: self._dependency_changed(n))
        self._mark_choices_pending()

    def _choice_picked(self, name: str, field: Any, value: str | None) -> None:
        """Picking an option is the value (the text field behind it) and, for an optional parameter, also 'set'; the blank entry unsets it."""
        field.value = value or ""
        toggle = self.unset_toggles.get(name)
        if toggle is not None:
            toggle.value = bool(value)

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _mark_choices_pending(self) -> None:
        """Every ChoicesFrom parameter of the form waits for its first answer (no choices shown until it arrives)."""
        for name in self._choice_boxes:
            self._invalidate_choice(name)

    def _dependency_changed(self, dependency: str) -> None:
        """A controlling value changed: the answers to the old value are void NOW; the debounce only delays the new question (5.3)."""
        for name in self._choice_dependents.get(dependency, []):
            self._invalidate_choice(name)
        self._schedule_choices(CHOICES_DEBOUNCE_MS)

    def _invalidate_choice(self, name: str) -> None:
        self._choice_latest[name] = self._next_request_id()
        self._choice_pending.add(name)
        self._lookups.drop(name)
        box = self._choice_boxes.get(name)
        if box is not None and self.gui is not None:
            box.visible = False  # never the choices of the old value
            self.gui[name].visible = True

    def choices_settled(self) -> bool:
        """True when no ChoicesFrom question is waiting, asked or still to be asked (what a test, or a script, can wait for)."""
        return not self._choice_pending and not self._lookups.busy and not self._choice_timer.isActive()

    def _schedule_choices(self, delay_ms: int) -> None:
        if self._choice_boxes and not self._shut_down:
            self._choice_timer.start(delay_ms)

    def _choice_inputs(self, source: str, depends: list[str], tool: Tool) -> dict[str, Any] | None:
        """The request for the source tool from the current form, or None while a needed value is missing."""
        values = {}
        by_name = {p["name"]: p for p in tool["inputs"]}
        for name in depends:
            value = self._control_value(name)
            if value is None or str(value) in ("", "."):
                return None
            if by_name[name]["type"] == "folder" and not Path(value).is_dir():
                return None
            values[name] = str(value) if isinstance(value, Path) else value
        return values

    def _resolve_choices(self) -> None:
        tool = self.tool
        if not tool or self.gui is None or not self._choice_boxes or self._shut_down:
            return
        if self.task is not None and not self.task.done.is_set():
            self._schedule_choices(CHOICES_RETRY_MS)  # the worker is busy with a run; ask again afterwards
            return
        app = self.app_box.value
        for p in tool["inputs"]:
            src = p.get("choices_from")
            if not src or p["name"] not in self._choice_boxes:
                continue
            inputs = self._choice_inputs(src["tool"], src["depends"], tool)
            request_id = self._choice_latest[p["name"]] = self._next_request_id()
            self._lookups.drop(p["name"])
            job = Lookup(
                form_gen=self._form_gen,
                app=app,
                tool=tool["id"],
                param=p["name"],
                deps=snapshot_deps(inputs),
                request_id=request_id,
                source=src["tool"],
                output=src["field"],
                inputs=inputs or {},
            )
            if inputs is None:  # a needed value is missing: no question, no list
                self._on_choices(Reply(job, None))
            else:
                self._choice_pending.add(p["name"])
                for dropped in self._lookups.submit(
                    job
                ):  # more than 8 waiting: the oldest is told, not left hanging
                    self._on_choices(
                        Reply(dropped, None, "too many choice lookups were waiting for %s" % dropped.param)
                    )

    def _run_lookup(self, job: Lookup) -> None:
        """On the lookup thread: ask, then hand the plain-data reply to the main thread (never touch a widget from here)."""
        reply = _lookups.execute(job, self._workers)
        if not self._shut_down:
            self._signals.choices.emit(reply)

    def _reply_applies(self, job: Lookup) -> bool:
        """5.2: the form, app, tool, newest request for the parameter, and the dependencies NOW (recomputed) are all still the same."""
        tool = self.tool
        if self._shut_down or self.gui is None or tool is None or job.param not in self._choice_boxes:
            return False
        if job.form_gen != self._form_gen or job.app != self.app_box.value or job.tool != tool["id"]:
            return False
        if job.request_id != self._choice_latest.get(job.param):
            return False
        src = next((p.get("choices_from") for p in tool["inputs"] if p["name"] == job.param), None)
        if not src:
            return False
        return snapshot_deps(self._choice_inputs(src["tool"], src["depends"], tool)) == job.deps

    def _on_choices(self, reply: Reply) -> None:
        job, options = reply.lookup, reply.options
        if not self._reply_applies(job):
            return  # a late answer for another question, another form, or other values: dropped with its problem
        name = job.param
        box = self._choice_boxes[name]
        field = self.gui[name]
        self._choice_pending.discard(
            name
        )  # last: everything below is in place when a waiting script sees it settled
        self._show_choice_problem(name, field, reply.problem if not options else "")
        if not options:
            box.visible = False
            field.visible = True
            return
        current = field.value or ""
        param: Param = next((p for p in cast(Tool, self.tool)["inputs"] if p["name"] == name), {})
        # A blank entry means "no answer" (unset for an optional parameter, or when the field is empty). A value the field already
        # holds (its default, or what was typed) stays selectable even when the source tool does not list it: never silently dropped.
        entries = (
            ([""] if param.get("nullable") or not current else [])
            + ([current] if current and current not in options else [])
            + options
        )
        box.choices = entries
        box.value = current if current in entries else entries[0]
        field.visible = False
        box.visible = True

    def _show_choice_problem(self, name: str, field: Any, problem: str) -> None:
        """Say why there is no list: in the field's tooltip and in the status line (the text field stays, the person types the value).
        The tooltip is the field's own text plus the newest problem; a good answer takes the problem back."""
        base = self._choice_base_tip.setdefault(name, field.native.toolTip())
        if not problem:
            field.native.setToolTip(base)
            return
        text = "%s: type the value" % problem
        field.native.setToolTip((base + "\n" if base else "") + text)
        current = self.status.text()
        if not current or current == self._lookup_note:
            self.status.setText("⚠ " + text)
            self._lookup_note = self.status.text()
        elif text not in current:  # an outcome of a run stays; the lookup problem is added behind it
            self.status.setText(current + "\n⚠ " + text)
            self._lookup_note = ""

    def _control_value(self, name: str) -> Any:
        source = self.file_sources.get(name)
        if source is not None and _is_set(source.value):
            return Path(
                source.value
            )  # an image chosen as a file is a value too (EnabledWhen("image") must see it)
        toggle = self.unset_toggles.get(name)
        if toggle is not None and not toggle.value:
            return None  # a nullable parameter that is not "set"
        return self.gui[name].value

    def _refresh_enabled(self) -> None:
        """One place decides what is greyed out: a failed enabled_when rule, an unticked 'set', or an image given as a file."""
        tool = self.tool
        if not tool or self.gui is None:
            return
        for p in tool["inputs"]:
            name = p["name"]
            rule = p.get("enabled_when")
            applies = rule is None or rule_satisfied(rule, self._control_value(rule["param"]))
            region_on = name in self.region_toggles and bool(self.region_toggles[name].value)
            if name in self.region_toggles:
                self.region_toggles[name].enabled = applies
            if (
                name in self.file_sources
            ):  # image/labels: the layer chooser yields to a chosen file (or to the selection)
                self.gui[name].enabled = (
                    applies and not region_on and not _is_set(self.file_sources[name].value)
                )
                self.file_sources[name].enabled = applies and not region_on
            elif name in self.unset_toggles:
                self.unset_toggles[name].enabled = applies
                self.gui[name].enabled = applies and bool(self.unset_toggles[name].value)
            else:
                self.gui[name].enabled = applies

    def _refresh_layer_choices(self, *_: Any) -> None:
        for widget in self.gui or []:
            if hasattr(widget, "reset_choices"):
                widget.reset_choices()

    def _link_calibration(self, image_name: str, pixel_name: str) -> None:
        """The pixel-size field follows the file chosen for its image, else the layer chosen for it, until the person types a value
        (SPEC_WRONG_SCIENCE 2.2). Its state (unset / auto / user) lives in a `LinkState`; the box only shows it. The box is a line of
        text like every number field (6.2): what the person types stays as typed and is checked at Run, an automatic value shows its
        exact digits, and a source without a calibration clears the field (it never keeps the previous image's value).
        """
        image, pixel = self.gui[image_name], self.gui[pixel_name]
        file_edit = self.file_sources.get(image_name)
        link = LinkState(pixel_name, image_name)
        self.cal_links[pixel_name] = link
        self._cal_refresh[pixel_name] = lambda: refresh()
        self._cal_commit[pixel_name] = lambda: entry_finished()
        pixel.native.setPlaceholderText("(not set)")  # the empty box is "not set"
        typing = [False]  # True from a keystroke in the box until that entry is handled

        def show(value: float | str | None) -> None:
            typing[0] = False  # the host replaces the text: no entry of the person is pending any more
            pixel.set_value(_numbers.as_text(value))
            pixel.tooltip = link.tooltip()

        def refresh(*_: Any) -> None:
            derived = self._derive_calibration(image, file_edit)
            if link.source_changed(derived):
                show(link.value)  # a `user` value stays: its text is never rewritten
            pixel.tooltip = link.tooltip()

        def edited() -> None:
            typing[0] = False
            link.user_edit(pixel.native.text())
            if link.state == UNSET:  # cleared (or typed 0): the image's calibration again
                refresh()
            else:
                pixel.tooltip = link.tooltip()

        def typed_text(*_: Any) -> None:
            typing[0] = (
                True  # only the person's keystrokes and pastes send `textEdited`; a text set by the host does not
            )

        def entry_finished() -> None:
            # One edit per entry (Enter, or the box losing focus, or a click on Run), not one per keystroke: "0" on the way to "0.3" is not
            # a clear. Typing the text the box already shows is an edit too: the flag, not a comparison, decides.
            if typing[0]:
                edited()

        pixel.native.textEdited.connect(typed_text)
        pixel.native.editingFinished.connect(entry_finished)
        image.changed.connect(refresh)
        if file_edit is not None:
            file_edit.changed.connect(refresh)
        button = mw.PushButton(
            text="use the image's calibration",
            tooltip="Forget the value typed above and take the pixel size from the file or image again",
            gui_only=True,
        )
        button.changed.connect(lambda *_: edited_clear())
        self.gui.insert(list(self.gui).index(pixel) + 1, button)

        def edited_clear() -> None:
            typing[0] = False
            link.user_edit(None)
            refresh()

        refresh()

    def _derive_calibration(self, image: Any, file_edit: Any) -> Derived | None:
        """The calibration of the chosen file, else of the chosen layer (what is exported wins), or None; says what is wrong in the
        status line. A file that has none is unknown: the open image's value is never used for it."""
        if file_edit is not None and _is_set(file_edit.value):  # calibration stored in the file
            calibration, problem = calibration_from_tiff(file_edit.value)
            if problem:
                self.status.setText("⚠ %s" % problem)
            elif calibration.note:
                self.status.setText("⚠ %s" % calibration.note)
            return Derived(calibration, "file")
        layer = image.value
        if layer is None:
            return None
        calibration = calibration_of_layer(layer)
        if calibration.note:
            self.status.setText("⚠ %s" % calibration.note)
        return Derived(calibration, "image")

    # ---- run ----------------------------------------------------------
    def _launch(self, form_values: dict[str, Any]) -> None:
        if (
            self.task is not None and not self.task.done.is_set()
        ):  # a run is in progress: never start a second one
            return
        job_dir = Path(tempfile.mkdtemp(prefix="lcin_"))
        prepared = self._prepare_inputs(form_values, job_dir)
        if prepared is None:
            return
        inputs, snapshot = prepared
        self._begin_run(form_values, inputs, job_dir, snapshot)
        self._start_worker(inputs, job_dir)

    def _take_snapshot(self, form_values: dict[str, Any]) -> _snapshot.RunSnapshot:
        """Freeze the run (SPEC_WRONG_SCIENCE section 4): one record of the form, the layer objects it names and the selection's
        geometry, taken on the UI thread before anything is exported. Export, worker call, placement and run record read this.
        """
        regions = [name for name, toggle in self.region_toggles.items() if toggle.value]
        calibration = {}
        for name, link in self.cal_links.items():
            self._cal_commit[
                name
            ]()  # an entry typed but not yet confirmed (no Enter, the focus still in the box) counts
            if (
                link.state != USER
            ):  # the layer's scale or units may have been edited since it was chosen: read it again
                self._cal_refresh[name]()
            calibration[name] = {"value": link.value, "entry": link.entry(), "of": link.of}
        layer = None
        if regions and self.viewer is not None:
            from napari.layers import Shapes

            layer = next((item for item in self.viewer.layers.selection if isinstance(item, Shapes)), None)
        return _snapshot.take(
            self.app_box.value,
            cast(Tool, self.tool),
            form_values,
            files={name: Path(edit.value) for name, edit in self.file_sources.items() if _is_set(edit.value)},
            regions=regions,
            unset=[name for name, toggle in self.unset_toggles.items() if not toggle.value],
            channels={name: self._picked_channel(name) for name in self.channel_boxes},
            selection_layer=layer,
            calibration=calibration,
        )

    def _prepare_inputs(
        self, form_values: dict[str, Any], job_dir: Path
    ) -> tuple[dict[str, Any], _snapshot.RunSnapshot] | None:
        """(the worker inputs, the run snapshot), or None after telling the person why they could not be made (the job dir is removed)."""
        try:
            snapshot = self._take_snapshot(form_values)
            return self._export_inputs(form_values, job_dir, snapshot), snapshot
        except ValueError as error:  # something the user can fix: say it plainly
            _retention.discard_job_dir(job_dir)
            if isinstance(
                error, FrameError
            ):  # a refusal of SPEC_WRONG_SCIENCE 1.4: the code goes to the log, the sentence to the person
                log.warning("napari: run refused (%s): %s", error.code, error)
            self.status.setText("⚠ %s" % error)
        # BLE001: e.g. the disk is full while saving a layer - clean up, say so, log it
        except Exception as error:  # noqa: BLE001
            log.error("napari: cannot prepare the inputs for %s", self.app_box.value, exc_info=True)
            _retention.discard_job_dir(job_dir)
            self._show_failure("could not prepare the inputs: %s" % error, error)
        return None

    def _begin_run(
        self,
        form_values: dict[str, Any],
        inputs: dict[str, Any],
        job_dir: Path,
        snapshot: _snapshot.RunSnapshot | None = None,
    ) -> None:
        """Remember what this run was started with and get the result presenter and the running state ready."""
        snapshot = snapshot or self._take_snapshot(form_values)
        inputs[JOB_DIR_KEY] = str(
            job_dir / "out"
        )  # host-owned: removed by the host whatever happens to the worker
        self._job_dir = job_dir
        self._request = {k: v for k, v in inputs.items() if k != JOB_DIR_KEY}
        self.snapshot = snapshot
        self._run_app, self._run_tool = snapshot.app, self.tool
        self._show_problem = ""
        self._closed = False
        self._record = _retention.RunRecord.start(
            snapshot.app, snapshot.tool_id, snapshot.run_id
        )  # owner marker first
        self._results = _retention.ResultsFolder(snapshot.app, snapshot.tool_id)
        shown_inputs = {
            **form_values,
            **{n: FileInput(Path(e.value)) for n, e in self.file_sources.items() if _is_set(e.value)},
        }
        replace = {o["name"] for o in snapshot.tool["outputs"] if o.get("replace")}
        self.message_label.setVisible(False)
        images = [p["name"] for p in snapshot.tool["inputs"] if p["type"] in ("image", "labels")]
        self.presenter = ResultPresenter(
            self.viewer,
            snapshot.app,
            shown_inputs,
            replace,
            self._docks,
            image_inputs=images,
            snapshot=snapshot,
        )
        self._set_running(True)
        self._started = time.perf_counter()

    def _start_worker(self, inputs: dict[str, Any], job_dir: Path) -> None:
        worker = None
        try:
            worker = self._workers.acquire(self._run_app, reuse=self.reuse_box.isChecked())
            self.worker = worker
            self._stderr_mark = getattr(
                worker.stderr, "total", None
            )  # None with an older labconstrictor-tools: then the whole tail is shown
            task = worker.task(
                self._run_tool["id"],
                inputs,
                on_update=lambda message, fraction: self._signals.progress.emit(message, fraction),
            )
            self.task = task

            def wait_then_signal() -> None:
                task.wait()
                self._signals.done.emit(task)

            self._run_thread = threading.Thread(target=wait_then_signal, name="lc-run", daemon=True)
            self._run_thread.start()
        # BLE001: e.g. the app's Python is gone or the worker died at once - undo the start
        except Exception as error:  # noqa: BLE001
            log.error("napari: cannot start %s for %s", self._run_tool["id"], self._run_app, exc_info=True)
            if worker is not None:
                self._workers.release(self._run_app, worker, keep=False)
            self.task = None
            _retention.discard_job_dir(job_dir)
            self._end_markers(
                "failed", {"status": "FAILED", "error": "could not start the worker: %s" % error}
            )
            self._set_running(False)
            self._show_failure(str(error), error)

    def _show_failure(self, text: str, error: BaseException) -> None:
        """A failure that never reached a task: status line plus the Details report."""
        self.status.setText("✖ %s" % text)
        self.last_details = "%s\n\nlog file: %s" % (
            error,
            log.log_path(),
        )  # the file holds the full story; its tail may be of other runs
        self.details_button.setEnabled(True)

    def _export_inputs(
        self, form_values: dict[str, Any], job_dir: Path, snapshot: _snapshot.RunSnapshot | None = None
    ) -> dict[str, Any]:
        """The run snapshot -> worker inputs (layers are saved as TIFF; calibration travels as explicit parameters). The export reads
        the snapshot, never the live form or the live selection (SPEC_WRONG_SCIENCE 4.3); without one it takes it now.
        """
        snapshot = snapshot or self._take_snapshot(form_values)
        inputs = {}
        for param in snapshot.tool["inputs"]:
            exported = self._export_param(param, snapshot, job_dir)
            if exported is not _OMIT:
                inputs[param["name"]] = exported
        calibration = {
            name: picked["entry"]
            for name, picked in snapshot.calibration.items()
            if picked["entry"] is not None and inputs.get(name) is not None
        }
        if calibration:  # reserved input, like _job_dir: per axis, with provenance; tools never see it
            inputs[CALIBRATION_KEY] = calibration
        return inputs

    def _export_param(self, param: Param, snapshot: _snapshot.RunSnapshot, job_dir: Path) -> Any:
        """The worker input for one parameter, or `_OMIT` when it is left out of the request."""
        name = param["name"]
        value = snapshot.value(name)
        file = snapshot.files.get(name)
        if name in snapshot.regions:  # RegionOf: the selection is the value
            return self._selection_mask(param, snapshot, job_dir)
        if name in snapshot.calibration:  # PixelSizeOf: what the field's state says, never a stand-in (2.3)
            return self._calibrated_value(param, snapshot)
        if file is not None:  # file chosen: the worker reads it directly
            return self._export_file_source(param, snapshot, file, job_dir)
        if name in snapshot.unset:  # nullable and not set: omit it
            return _OMIT
        if (
            param["type"] in ("integer", "float") and name in snapshot.values
        ):  # what was typed, checked as typed: refused beyond a limit, never clamped (SPEC 6.2)
            return _numbers.check(param, value)
        if value is None or (isinstance(value, Path) and str(value) in ("", ".")):
            if param["required"]:
                hint = ": open an image or choose a file" if param["type"] in ("image", "labels") else ""
                raise ValueError("[missing_parameter] '%s' is required%s" % (param["label"], hint))
            return _OMIT
        if param["type"] in ("image", "labels"):
            path = job_dir / (name + ".tif")
            export_layer(value, snapshot.channels.get(name), path)
            return str(path)
        if param["type"] in ("table", "file", "folder"):
            return str(value)
        return value

    def _calibrated_value(self, param: Param, snapshot: _snapshot.RunSnapshot) -> Any:
        """The value of a linked PixelSizeOf field at the click (SPEC_WRONG_SCIENCE 2.3): the person's entry or the source's calibration.
        An unset one blocks a required field and sends null for an Optional one; the declared default is never a stand-in.
        """
        picked = snapshot.calibration[param["name"]]
        value = picked["value"]
        if value is None:
            if param.get("nullable"):  # Optional[float]: null, nothing is blocked
                return None
            raise ValueError(_calibration.CALIBRATION_REQUIRED.format(param=param["name"], of=picked["of"]))
        value = _numbers.check(
            param, value
        )  # what was typed, exactly: refused beyond a limit or when not a number, never clamped
        if value <= 0:
            raise ValueError(
                "[invalid_parameter] '%s' must be greater than 0 (um per pixel)" % param["label"]
            )
        return value

    def _export_file_source(
        self, param: Param, snapshot: _snapshot.RunSnapshot, path: Path, job_dir: Path
    ) -> str:
        if not path.is_file():
            raise ValueError("[file_not_found] image file not found: %s" % path)
        if param.get("pick_channel"):
            # PickChannel: the file's chosen channel (the first when there is nothing to choose) is written for the worker; a file that
            # has a channel axis never goes to the tool whole, and a layout nothing can be picked from is refused here
            import tifffile

            picked = snapshot.channels.get(param["name"]) or 0
            try:
                path = channel_file(path, picked, param["label"], job_dir / (param["name"] + ".tif"))
            except ChannelError:
                raise
            except (
                *TIFF_READ_ERRORS,
                tifffile.TiffFileError,
            ):  # not a TIFF the host can look into: the worker reads or refuses it
                log.info("napari: %s is not read for channels by the host; sent as it is", path)
        return str(path)

    def current_values(self) -> dict[str, Any]:
        """The form as the values a command line needs: unset optional parameters are omitted; an image or labels input is the
        file it came from (a file chosen in the form, else the layer's source file) or None, which becomes a placeholder.
        """
        values = {}
        for param in cast(Tool, self.tool)["inputs"]:
            value = self._command_value(param)
            if value is not _OMIT:
                values[param["name"]] = value
        return values

    def _command_value(self, param: Param) -> Any:
        """One parameter as a command line needs it, or `_OMIT` when it is left out."""
        name = param["name"]
        toggle = self.unset_toggles.get(name)
        if toggle is not None and not toggle.value:
            return _OMIT
        region = self.region_toggles.get(name)
        if (
            region is not None and region.value
        ):  # a selection cannot be written on a command line: the note says so
            return "region.tif"
        source = self.file_sources.get(name)
        if source is not None and _is_set(source.value):
            return str(source.value)
        value = self.gui[name].value
        if param["type"] in ("integer", "float") and not param.get("pixel_size_of"):
            return _numbers.check(
                param, value
            )  # a command line never carries a number that a run would refuse
        if param["type"] in ("image", "labels"):
            path = getattr(getattr(value, "source", None), "path", None)
            return str(path) if path else None
        if value is None or (isinstance(value, Path) and str(value) in ("", ".")):
            return _OMIT
        if param["type"] in ("table", "file", "folder"):
            return str(value)
        return value

    def copy_as_command(self, kind: str = "terminal") -> str | None:
        """Put the terminal line or the Python snippet that repeats this form on the clipboard."""
        from labconstrictor_tools import command

        if self.gui is None or self.tool is None:
            return None
        app = self.app_box.value
        try:
            values = self.current_values()
        except ValueError as error:  # a number that a run would refuse is not copied (SPEC 6.2)
            self.status.setText("⚠ %s" % error)
            return None
        if kind == "python":
            text = command.python_snippet(app, self.tool, values)
        else:
            text = command.command_line(app, self.tool, values, python=self.apps[app].get("python", "python"))
        notes = self._command_notes()
        if (
            notes
        ):  # as comment lines after the placeholder line (if any), before the command: the order every host uses
            lines = text.split("\n")
            head = next((i for i, line in enumerate(lines) if not line.startswith("#")), len(lines))
            text = "\n".join(lines[:head] + notes + lines[head:])
        clipboard = QApplication.clipboard()
        if (
            clipboard is None
        ):  # no clipboard (no QApplication/display): say so instead of reporting a copy that did not happen
            log.error("napari: no clipboard to copy the %s to", kind)
            self.status.setText(_failure_line("there is no clipboard to copy to"))
            return None
        clipboard.setText(text)
        self.status.setText(
            "✔ copied the %s to the clipboard"
            % ("Python snippet" if kind == "python" else "terminal command")
        )
        return text

    def _command_notes(self) -> list[str]:
        """One comment line for everything the command cannot say: a selection (not copied) and a chosen channel (the command
        sends the whole file). Same sentences and order as the other hosts, per parameter in the tool's order.
        """
        notes = []
        for param in cast(Tool, self.tool)["inputs"]:
            name = param["name"]
            toggle = self.region_toggles.get(name)
            if toggle is not None and toggle.value:
                notes.append(
                    "# %s: the selection cannot be copied; save it as a label image and put its path here"
                    % name
                )
                continue
            picked = self._picked_channel(name)
            if picked is not None:
                notes.append(
                    "# %s: napari sent only channel %d; the command sends the whole file" % (name, picked + 1)
                )
        return notes

    def _picked_channel(self, name: str) -> int | None:
        """The index of the channel the person chose for image parameter `name`, or None when there is nothing to choose."""
        box = self.channel_boxes.get(name)
        if box is None or box.native.isHidden() or box.value in ("", None):
            return None
        return list(box.choices).index(box.value)

    def _set_running(self, running: bool) -> None:
        # the run owns the worker: lookups wait until it ends (SPEC_WRONG_SCIENCE 5.5)
        self._lookups.hold(running)
        self.bar.setVisible(running)
        if running:
            self.bar.setRange(0, 0)
            self.status.setText("starting worker…")
        self.cancel_button.setEnabled(running)
        self.app_box.enabled = self.tool_box.enabled = (
            not running
        )  # the form must stay the one that was launched
        self.rescan_button.setEnabled(not running)  # a rescan rebuilds the form under a running task
        self.restart_button.setEnabled(not running)  # and a restart would close the worker that is running it
        if self.gui is not None:
            self.gui.call_button.enabled = not running

    def cancel(self, *_: Any) -> None:
        if not self.task or self.task.done.is_set():
            return
        self.status.setText("cancelling…")
        task, worker = self.task, self.worker
        task.cancel()
        # Escalate to killing the worker if the tool ignores Cancel. Bound to THIS task, so a stale timer
        # from an earlier run can never kill a later run's worker.
        QTimer.singleShot(int(CANCEL_GRACE_S * 1000), lambda: None if task.done.is_set() else worker.kill())

    def _on_progress(self, message: str | None, fraction: float | None) -> None:
        if fraction is None:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 100)
            self.bar.setValue(int(100 * fraction))
        self.status.setText(message or "")

    def _on_done(self, task: Any) -> None:
        if (
            task is not self.task
        ):  # a late signal of a run that is no longer the current one: never touch the current run's files
            return
        if (
            self._closed
        ):  # the widget was closed during this run: closeEvent already ended it (markers, worker, files)
            return
        self.last_task = task
        self.timings["run_wall_s"] = time.perf_counter() - self._started
        self._set_running(False)
        healthy = task.status in (
            "COMPLETE",
            "FAILED",
        )  # a cancelled or crashed worker may be mid-task: never reuse it
        if task.status != "COMPLETE":
            self._record_run(task)
            self._workers.release(self._run_app, self.worker, keep=self.reuse_box.isChecked() and healthy)
            _retention.discard_job_dir(self._job_dir)  # the host's own temporary folder (outside LC_HOME)
            self.status.setText(_unfinished_text(task))
            self._end_markers(tools_runs.done_status(task.status, getattr(task, "cancel_requested", False)))
            return
        summaries, withheld = self._show_results(
            task
        )  # also keeps the files that must outlive the job folder (3.4)
        self._record_run(task)
        self._workers.release(self._run_app, self.worker, keep=self.reuse_box.isChecked() and healthy)
        self._end_markers("ok")
        if summaries is None:
            return
        self._report_success(summaries, withheld)
        self._clear_after_run()
        self._schedule_choices(CHOICES_AFTER_RUN_MS)

    def _show_results(self, task: Any) -> tuple[list[str] | None, list[str]]:
        """Show every result of a finished task: (the summaries, the sentences for results that were not drawn), or (None, [...]) after
        reporting that they could not be shown. Then the temporary job folder goes, after every file that is reported has been moved to
        an owned folder under <LC_HOME>/results (section 3.4): a reported path never points into a folder about to be deleted.
        """
        results: list[Any] = []
        summaries: list[str | None] = []
        withheld: list[tuple[Any, tuple[str, str]]] = []
        try:
            results = list(task.outputs["results"])
            summaries = [None] * len(results)
            for index, result in enumerate(results):
                self._keep_reported_file(
                    result
                )  # a FileOut in the job folder is moved first, so the status shows its final path
                problem = self.presenter.placement_problem(result)
                if (
                    problem is not None
                ):  # its source layer is gone or changed: nothing is drawn (RUN-01, RUN-04)
                    withheld.append((result, problem))
                    summaries[index] = ""
                    continue
                before = result.get("path") if isinstance(result, dict) else None
                summaries[index] = self.presenter.show(result)
                if any(result is kept for kept in self.presenter.file_results):
                    # points / outlines with no image input are a table or a file (SPEC 1.1.5, 1.1.6): the file is kept, the status names it
                    moved = self._keep_reported_file(result, force=True)
                    if moved is not None and before:
                        summaries[index] = (summaries[index] or "").replace(before, str(moved))
            for index, text in enumerate(
                summaries
            ):  # not drawn although it was tried: keep the file, say where it is
                if text and text.startswith(COULD_NOT_DISPLAY):
                    summaries[index] = self._keep_undisplayed(results[index], text)
            return [text or "" for text in summaries], self._unavailable_sentences(withheld)
        except Exception as error:  # noqa: BLE001 - some results may already be shown: do not claim success
            log.error("napari: could not show the results of %s", self._run_tool["id"], exc_info=True)
            for index, result in enumerate(results):  # whatever was not shown stays reachable
                if index >= len(summaries) or summaries[index] is None:
                    self._keep_reported_file(result, force=True)
            self._show_failure(
                "the tool finished but its results could not be shown completely: %s" % error, error
            )
            self._show_problem = self.last_details
            return None, []
        finally:
            self._discard_job_dir()

    def _keep_reported_file(self, result: Any, force: bool = False) -> Path | None:
        """Move the file a result reports into an owned results folder when it lies in the job folder and must outlive it: a `file`
        result always, any other kind only with `force` (it could not be shown). Rewrites `result["path"]`. Files outside the job
        folder are never moved or modified. None when nothing was moved."""
        if not isinstance(result, dict) or not isinstance(result.get("path"), str) or self._results is None:
            return None
        if result.get("type") != "file" and not force:
            return None
        source = Path(result["path"])
        if not source.is_file() or not _retention.inside(source, self._job_dir):
            return None
        moved = self._results.adopt(source)
        if moved is None:  # the move failed: the job folder is kept so that the reported path stays valid
            self._keep_job_dir = True
            return None
        result["path"] = str(moved)
        return moved

    def _keep_undisplayed(self, result: Any, text: str) -> str:
        """A result that could not be shown (too big, unreadable): its file moves to the owned folder and the sentence names that path."""
        before = result.get("path") if isinstance(result, dict) else None
        moved = self._keep_reported_file(result, force=True)
        return text.replace(before, str(moved)) if moved is not None and before else text

    def _unavailable_sentences(self, withheld: list[tuple[Any, tuple[str, str]]]) -> list[str]:
        """One `target_unavailable` sentence per source that is gone; the files of those results are kept (section 4.4)."""
        if not withheld or self.snapshot is None:
            return []
        for result, _ in withheld:
            self._keep_reported_file(result, force=True)
        folder = self._results.folder if self._results is not None else None
        sentences = []
        for source, reason in dict.fromkeys(problem for _, problem in withheld):
            where = folder or next(
                (Path(r["path"]).parent for r, _ in withheld if r.get("path")), self._job_dir
            )
            sentences.append(_snapshot.unavailable_sentence(self.snapshot.run_id, source, reason, where))
            log.warning("napari: %s (%s)", sentences[-1], _snapshot.TARGET_UNAVAILABLE)
        return sentences

    def _discard_job_dir(self) -> None:
        """The temporary job folder goes, unless a file that is reported could not be moved out of it."""
        if getattr(self, "_keep_job_dir", False):
            self._keep_job_dir = False
            log.warning(
                "napari: keeping %s: a result file could not be moved to %s",
                self._job_dir,
                registry.home() / "results",
            )
            return
        _retention.discard_job_dir(self._job_dir)

    def _report_success(self, summaries: list[str], withheld: list[str] | None = None) -> None:
        if self.presenter.messages:
            self.message_label.setText("\n\n".join(self.presenter.messages))
            self.message_label.setVisible(True)
        failed = [s for s in summaries if s and s.startswith(COULD_NOT_DISPLAY)]
        text = "  ".join(s for s in summaries if s)
        if (
            withheld
        ):  # the tool succeeded but results were not drawn: they are in a folder, and the sentence says which run and where
            self.status.setText("⚠ " + "  ".join([*withheld, text] if text else withheld))
        elif failed:  # the tool succeeded but part of its output is not in the viewer: not a plain success
            self.status.setText(
                "⚠ done in %.1fs, but some results could not be shown  %s"
                % (self.timings["run_wall_s"], text)
            )
            self.last_details += "\n\nnot shown:\n" + "\n".join(failed)
        else:
            self.status.setText("✔ done in %.1fs  %s" % (self.timings["run_wall_s"], text))
        if withheld:
            self.last_details += "\n\nnot drawn:\n" + "\n".join(withheld)

    def _clear_after_run(self) -> None:
        """ClearAfterRun parameters go back to their default (or unset) once a run has succeeded."""
        tool = self._run_tool
        if self.gui is None or tool is not self.tool:
            return
        for p in cast(Tool, tool)["inputs"]:
            if not p.get("clear_after_run"):
                continue
            widget = self.gui[p["name"]]
            toggle = self.unset_toggles.get(p["name"])
            if toggle is not None:
                toggle.value = False
            default = p.get("default", "" if p["type"] == "string" else None)
            if default is not None:
                widget.value = default
            box = self._choice_boxes.get(p["name"])
            if box is not None:
                box.value = ""

    def _record_run(self, task: Any) -> None:
        stderr = "".join(self.worker.stderr)
        total = getattr(self.worker.stderr, "total", None)
        if (
            total is not None and self._stderr_mark is not None
        ):  # a kept worker has output of earlier runs: not part of this one
            fresh = total - self._stderr_mark
            stderr = stderr[-fresh:] if fresh > 0 else ""
        snapshot = self.snapshot
        content = _retention.run_record(
            self._run_app,
            self._run_tool["id"],
            self._request,
            task,
            self.timings["run_wall_s"],
            stderr,
            snapshot,
            keep_inputs=(CALIBRATION_KEY,),
        )
        self.last_record = self._finish_record(
            tools_runs.done_status(task.status, getattr(task, "cancel_requested", False)), content
        )
        lines = [
            "status: %s" % task.status,
            "run id: %s" % (snapshot.run_id if snapshot else "-"),
            "run record: %s" % (self.last_record or "(could not be written)"),
        ]
        if task.error:
            lines += ["", "error: %s" % task.error]
        if task.traceback:
            lines += ["", task.traceback]
        if stderr.strip():
            lines += ["", "worker output (tail):", stderr[-STDERR_TAIL_CHARS:]]
        lines += ["", "log file: %s" % log.log_path()]  # not its tail: that would show earlier runs
        if self._show_problem:  # why the results could not be shown (set before the record is written)
            lines += ["", self._show_problem]
        self.last_details = "\n".join(lines)
        self.details_button.setEnabled(True)

    def _finish_record(self, status: str, content: dict[str, Any]) -> Path | None:
        """Write run.json and then the done marker of this run's record. Never raises: a record must not break a run."""
        if self._record is None:
            return None
        try:
            text = tools_runs.record_json(content)
        except (TypeError, ValueError) as error:
            log.warning("napari: could not serialize the run record (%s: %s)", type(error).__name__, error)
            text = json.dumps({"status": content.get("status"), "run_id": content.get("run_id")})
        return self._record.finish(status, text)

    def _end_markers(self, status: str, content: dict[str, Any] | None = None) -> None:
        """The run has ended: the record (when this is a run that never produced one, with `content`) and the results folder get their
        done marker, and only then is `prune` started. Never deletes anything, never raises."""
        if content is not None:
            self.last_record = self._finish_record(
                status,
                {"run_id": self.snapshot.run_id if self.snapshot else None, "app": self._run_app, **content},
            )
        if self._results is not None:
            self._results.finish(status)
        app = self._run_app
        self.last_prune = _retention.start_prune(
            (self.apps.get(app) or {}).get("python"), self.schemas.get(app)
        )

    def _show_details(self, *_: Any) -> None:
        from qtpy.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("LabConstrictor - last run")
        box.setText("Run details (copy this when asking for help)")
        box.setDetailedText(self.last_details)
        box.exec()

    def closeEvent(self, event: Any) -> None:  # Qt API name
        self._reaper.stop()
        self._choice_timer.stop()
        self._shut_down = True  # first: nothing started from now on outlives the widget (5.6)
        self._form_gen = next_form_gen()
        self._lookups.close()  # pending dropped, the one in flight cancelled, its thread joined
        if (
            self.task is not None and not self.task.done.is_set() and not self._closed
        ):  # closed during a run: stop it, do not leave worker or temp files
            self._closed = True
            try:
                self.worker.kill()
            except (
                OSError,
                subprocess.SubprocessError,
            ):  # best effort while closing: already gone / cannot be signalled
                log.error("napari: could not stop the worker while closing the widget", exc_info=True)
            _retention.discard_job_dir(getattr(self, "_job_dir", ""))
            self._end_markers(
                "cancelled",
                {
                    "status": "CANCELED",
                    "error": "the widget was closed while the tool was running",
                    "inputs": self._request,
                },
            )
        self._workers.shutdown()
        thread = self._run_thread
        if (
            thread is not None and thread.is_alive()
        ):  # its worker is gone, so its wait has ended: no thread of the widget stays
            thread.join(2.0)
        self._lookups.hold(False)  # a run that was ended by the close no longer holds the worker
        self._shut_down = False
        self._was_closed = True
        super().closeEvent(event)

    @property
    def tables(self) -> dict[str, list[list[str]]]:
        return self.presenter.tables if self.presenter else {}

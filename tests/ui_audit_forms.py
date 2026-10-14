"""The form step of the Napari UI audit: open the form of a tool and check one widget of the declared kind per parameter
(`form_opens`), then activate every control the form makes for those parameters and read the state back (`form_controls`).
A control of the form that no declared parameter explains is a failure. Not a test."""

import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from qtpy.QtWidgets import QPushButton
from ui_audit_core import MAIN_WINDOW, AppCtx, press_with_modal, pump, real_click, scroll_to, windows_problem

# schema type -> the class names (magicgui, ours) of the widget that may show it
KINDS: dict[str, tuple[str, ...]] = {
    "integer": ("IntegerField", "Slider"),
    "float": ("FloatField", "FloatSlider"),
    "string": ("LineEdit",),
    "boolean": ("CheckBox",),
    "choice": ("ComboBox", "RadioButtons"),
    "image": ("ComboBox",),
    "labels": ("ComboBox",),
    "table": ("FileEdit",),
    "file": ("FileEdit",),
    "folder": ("FileEdit",),
}
CALIBRATION_BUTTON = "use the image's calibration"


def open_form(ctx: AppCtx, tool_id: str) -> Any:
    """Choose the tool through the choosers; the form (a magicgui container)."""
    w = ctx.host.widget
    w.app_box.value = ctx.app
    pump(0.2)
    w.tool_box.value = ctx.labels[tool_id]
    pump(0.5)
    if w.gui is None:
        raise AssertionError("no form after choosing %r: %s" % (ctx.labels[tool_id], w.status.text()))
    return w.gui


def form_opens(ctx: AppCtx, tool: dict[str, Any]) -> str:
    """One widget per declared parameter, of the declared kind; image inputs also have their 'or file' row."""
    w, gui, problems = ctx.host.widget, open_form(ctx, tool["id"]), []
    for param in tool["inputs"]:
        name, kind = param["name"], param["type"]
        try:
            widget = gui[name]
        except KeyError:
            problems.append("%s: no widget" % name)
            continue
        found = type(widget).__name__
        if kind not in KINDS:
            problems.append("%s: the audit has no widget kind for the type %r" % (name, kind))
        elif found not in KINDS[kind]:
            problems.append("%s (%s): widget is %s, expected %s" % (name, kind, found, "/".join(KINDS[kind])))
        if kind in ("image", "labels") and type(w.file_sources.get(name)).__name__ != "FileEdit":
            problems.append("%s: no 'or file' row" % name)
        if param.get("pick_channel") and name not in w.channel_boxes:
            problems.append("%s: no channel chooser" % name)
        if (
            param.get("nullable")
            and kind in ("integer", "float", "string", "choice", "boolean")
            and not param.get("pixel_size_of")
            and name not in w.unset_toggles
        ):
            problems.append("%s: optional but no 'set' box" % name)
        if param.get("region_of") and name not in w.region_toggles:
            problems.append("%s: no 'use the selection' box" % name)
    if tool.get("description", "") != w.description.text():
        problems.append("the description shown is %r" % w.description.text())
    if problems:
        raise AssertionError("; ".join(problems))
    return "%d parameters: %s" % (
        len(tool["inputs"]),
        ", ".join("%s:%s" % (p["name"], p["type"]) for p in tool["inputs"]),
    )


def browse(ctx: AppCtx, button: QPushButton) -> str:
    """Click a '...' button (a real click, scrolled into view first): a file dialog must open on screen (closed again at once)."""
    scroll_to(ctx.host.widget, button)
    return str(
        press_with_modal(lambda: real_click(button), lambda dialog: type(dialog).__name__, ["QFileDialog"])
    )


def _number(ctx: AppCtx, param: dict[str, Any], widget: Any) -> str:
    low = param.get("minimum")
    value = (0 if low is None else low) if param["type"] == "integer" else (0.5 if low is None else low)
    start = widget.value
    widget.value = value
    pump(0.05)
    if widget.value != value:
        raise AssertionError("set %r, read back %r" % (value, widget.value))
    widget.value = start
    return "number %r" % value


def _linked(ctx: AppCtx, param: dict[str, Any], widget: Any) -> str:
    """A pixel size: type a value, then 'use the image's calibration' gives the field back to the image."""
    w = ctx.host.widget
    ctx.host.viewer.layers.clear()
    pump(0.1)
    widget.native.setText("0.5")
    widget.native.textEdited.emit("0.5")
    widget.native.editingFinished.emit()
    if widget.native.text() != "0.5":
        raise AssertionError("typed 0.5, the box shows %r" % widget.native.text())
    button = next(b for b in w.gui if type(b).__name__ == "PushButton" and b.text == CALIBRATION_BUTTON)
    scroll_to(w, button.native)
    real_click(button.native)
    if widget.native.text() != "":
        raise AssertionError(
            "after 'use the image's calibration' (no image) the box shows %r" % widget.native.text()
        )
    return "typed value, then the calibration button cleared it"


def _choice(ctx: AppCtx, param: dict[str, Any], widget: Any) -> str:
    start = widget.value
    for choice in param["choices"]:
        widget.value = choice
        pump(0.05)
        if widget.value != choice:
            raise AssertionError("chose %r, read back %r" % (choice, widget.value))
    widget.value = start
    return "%d choices" % len(param["choices"])


def _layer_input(ctx: AppCtx, param: dict[str, Any], widget: Any) -> str:
    """Layer chooser (a layer shows up and can be chosen), 'or file' row (a file greys the chooser, '...' opens a dialog) and the
    channel chooser (an RGB layer offers its three colours)."""
    w, viewer, name = ctx.host.widget, ctx.host.viewer, param["name"]
    data = np.zeros((8, 8), np.uint8)
    layer = (
        viewer.add_image(data, name="audit")
        if param["type"] == "image"
        else viewer.add_labels(data, name="audit")
    )
    pump(0.2)
    if layer not in widget.choices:
        raise AssertionError("the layer chooser does not list a new %s layer" % param["type"])
    widget.value = layer
    edit = w.file_sources[name]
    with tempfile.NamedTemporaryFile(suffix=".tif") as handle:
        edit.value = Path(handle.name)
        pump(0.1)
        if widget.enabled:
            raise AssertionError("a chosen file does not grey out the layer chooser")
        edit.value = None
        pump(0.1)
        if not widget.enabled:
            raise AssertionError("emptying the file does not give the layer chooser back")
    dialog = browse(ctx, edit.native.findChildren(QPushButton)[0])
    note = "layer chosen, file greys it out, '...' opened %s" % dialog
    if param.get("pick_channel"):
        viewer.layers.clear()
        rgb = viewer.add_image(np.zeros((8, 8, 3), np.uint8), rgb=True, name="audit_rgb")
        pump(0.2)
        widget.value = rgb
        pump(0.2)
        box = w.channel_boxes[name]
        if list(box.choices) != ["Red", "Green", "Blue"] or not box.visible:
            raise AssertionError(
                "an RGB layer gives the channels %s (visible=%s)" % (list(box.choices), box.visible)
            )
        for colour in box.choices:
            box.value = colour
            if box.value != colour:
                raise AssertionError("channel %r not kept" % colour)
        note += "; channels Red/Green/Blue"
    viewer.layers.clear()
    return note


def _path(ctx: AppCtx, param: dict[str, Any], widget: Any) -> str:
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) if param["type"] == "folder" else Path(folder) / "a.csv"
        widget.value = target
        if Path(str(widget.value)) != target:
            raise AssertionError("set %s, read back %s" % (target, widget.value))
        dialog = browse(ctx, widget.native.findChildren(QPushButton)[0])
    return "path kept, '...' opened %s" % dialog


def _toggles(ctx: AppCtx, param: dict[str, Any]) -> list[str]:
    """The 'set' box of an optional value and the 'use the selection' box of a region."""
    w, name, notes = ctx.host.widget, param["name"], []
    if name in w.unset_toggles:
        toggle, field = w.unset_toggles[name], w.gui[name]
        toggle.value = True
        pump(0.05)
        on = field.enabled
        toggle.value = False
        pump(0.05)
        if not on or field.enabled:
            raise AssertionError(
                "the 'set' box does not enable/disable the field (on=%s, off=%s)" % (on, field.enabled)
            )
        notes.append("'set' box")
    if name in w.region_toggles:
        toggle = w.region_toggles[name]
        toggle.value = True
        pump(0.05)
        greyed = w.gui[name].enabled
        toggle.value = False
        pump(0.05)
        if greyed or not w.gui[name].enabled:
            raise AssertionError(
                "'use the selection' does not take over the chooser (on: enabled=%s)" % greyed
            )
        notes.append("'use the selection' box")
    return notes


def _enabled_when(ctx: AppCtx, tool: dict[str, Any], param: dict[str, Any]) -> str:
    rule, w = param["enabled_when"], ctx.host.widget
    control = w.gui[rule["param"]]
    kind = next(p["type"] for p in tool["inputs"] if p["name"] == rule["param"])
    if kind not in ("boolean", "choice"):
        raise AssertionError(
            "enabled_when on a %s parameter: the audit can only drive boolean and choice" % kind
        )
    start = control.value
    if "equals" in rule:
        other = (
            next((c for c in control.choices if c not in rule["equals"]), None) if kind == "choice" else None
        )
        on, off = rule["equals"][0], other
    else:
        on, off = True, False
    control.value = on
    pump(0.1)
    enabled = w.gui[param["name"]].enabled
    note = "%s enabled by %s=%r" % (param["name"], rule["param"], on)
    if off is not None:
        control.value = off
        pump(0.1)
        if w.gui[param["name"]].enabled:
            raise AssertionError("%s stays enabled when %s=%r" % (param["name"], rule["param"], off))
        note += ", disabled by %r" % (off,)
    control.value = start
    if not enabled:
        raise AssertionError("%s is not enabled when %s=%r" % (param["name"], rule["param"], on))
    return note


def _advanced(ctx: AppCtx) -> list[str]:
    """'Show advanced settings' and the collapsible group headings."""
    w, notes = ctx.host.widget, []
    if w.advanced_toggle is not None:
        advanced = [w.gui[p["name"]] for p in w.tool["inputs"] if p.get("advanced")]
        w.advanced_toggle.value = True
        pump(0.05)
        shown = all(a.visible for a in advanced)
        w.advanced_toggle.value = False
        pump(0.05)
        if not shown or any(a.visible for a in advanced):
            raise AssertionError("'Show advanced settings' does not show/hide the advanced parameters")
        notes.append("advanced box")
    for group, button in getattr(w, "_group_heading", {}).items():
        members = w._group_members[group]  # noqa: SLF001
        before = all(m.visible for m in members)
        scroll_to(w, button.native)
        real_click(button.native)
        if all(m.visible for m in members) == before:
            raise AssertionError("the heading of the group %r does not open/close it" % group)
        real_click(button.native)
        notes.append("group %r" % group)
    return notes


def unexplained(ctx: AppCtx, tool: dict[str, Any]) -> list[str]:
    """Interactive widgets of the form that no declared parameter explains (a control without a test)."""
    w = ctx.host.widget
    known = {id(w.gui[p["name"]]) for p in tool["inputs"]}
    known |= {
        id(x)
        for group in (w.file_sources, w.channel_boxes, w.unset_toggles, w.region_toggles, w._choice_boxes)
        for x in group.values()
    }  # noqa: SLF001
    known |= {id(w.gui.call_button), id(w.advanced_toggle)}
    known |= {id(b) for b in getattr(w, "_group_heading", {}).values()}
    inert = ("Label", "Container", "EmptyWidget")
    out = []
    for widget in w.gui:
        if id(widget) in known or type(widget).__name__ in inert:
            continue
        if type(widget).__name__ == "PushButton" and widget.text == CALIBRATION_BUTTON:
            continue
        out.append("%s %r" % (type(widget).__name__, getattr(widget, "text", getattr(widget, "label", ""))))
    return out


def form_controls(ctx: AppCtx, tool: dict[str, Any]) -> str:
    """Activate every control of the form, per declared parameter, and read the state back."""
    w, gui, problems, done = ctx.host.widget, open_form(ctx, tool["id"]), [], []
    status_before = w.status.text()  # the status of an earlier run is not this form's
    windows = windows_problem([MAIN_WINDOW])  # a form opens no window of its own
    ctx.host.viewer.layers.clear()
    for param in tool["inputs"]:
        name, kind = param["name"], param["type"]
        try:
            widget = gui[name]
            if param.get("pixel_size_of"):
                note = _linked(ctx, param, widget)
            elif kind in ("integer", "float"):
                note = _number(ctx, param, widget)
            elif kind == "string":
                start = widget.value
                widget.value = "audit-x"
                note = "text" if widget.value == "audit-x" else "text read back %r" % widget.value
                widget.value = start
                if note != "text":
                    raise AssertionError(note)
            elif kind == "boolean":
                start = widget.value
                widget.value = not start
                if widget.value == start:
                    raise AssertionError("the check box did not change")
                widget.value = start
                note = "check box"
            elif kind == "choice":
                note = _choice(ctx, param, widget)
            elif kind in ("image", "labels"):
                note = _layer_input(ctx, param, widget)
            else:
                note = _path(ctx, param, widget)
            note = "; ".join([note, *_toggles(ctx, param)])
            if param.get("enabled_when"):
                note += "; " + _enabled_when(ctx, tool, param)
            done.append("%s: %s" % (name, note))
        # every parameter is tried; the check fails with all of the problems
        except Exception as error:  # noqa: BLE001
            problems.append("%s (%s): %s: %s" % (name, kind, type(error).__name__, error))
    try:
        notes = _advanced(ctx)
    except AssertionError as error:
        problems.append(str(error))
        notes = []
    if windows:
        problems.append(windows)
    extra = unexplained(ctx, tool)
    if extra:
        problems.append("controls without a declared parameter or a table entry: %s" % extra)
    if w.status.text() != status_before and w.status.text().startswith("\u2716"):
        problems.append("the status reports an error: %s" % w.status.text())
    if problems:
        raise AssertionError("; ".join(problems))
    return "%d parameters activated%s" % (len(done), " (%s)" % ", ".join(notes) if notes else "")

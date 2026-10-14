"""The control table of the LabConstrictor dock widget and the panel checks of the Napari UI audit.

A control is a row of CONTROLS: id, widget kind, where to find it, the expected effect (text) and the function that asserts it. The audit
enumerates the widget tree (everything but the per-parameter form, which `ui_audit_forms` covers) and requires SET EQUALITY with the
table: a control without a row fails, a row whose control is gone fails, and finding fewer than MIN_CONTROLS fails.

Expected effects come from outside the panel: the registry and schema files under LC_HOME, the processes of the workers, the cases
file, the run record and log on disk, the clipboard. They are never read back from the state the control just set. To add a control:
add a row and an effect function (docs/UI_AUDIT.md). Not a test."""

import ast
import json
import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from labconstrictor_tools import testing
from qtpy.QtCore import Qt
from qtpy.QtGui import QAction
from qtpy.QtTest import QTest
from qtpy.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QScrollBar,
    QTextEdit,
    QWidget,
)
from ui_audit_core import (
    MAIN_WINDOW,
    AppCtx,
    Human,
    NotRun,
    press_with_modal,
    pump,
    real_click,
    until,
    windows_problem,
)
from ui_audit_runs import choose_case, execute, prepare, tool_of

INTERACTIVE = (
    QAbstractButton,
    QComboBox,
    QAbstractSpinBox,
    QLineEdit,
    QAbstractSlider,
    QTextEdit,
    QPlainTextEdit,
)
MIN_CONTROLS = 10  # the table has 11 rows: finding far fewer means the walk of the widget tree is broken
COPY_LABELS = ["Terminal command", "Python snippet"]
Effect = Callable[[AppCtx], str]


@dataclass(frozen=True)
class Control:
    id: str  # the panel check is ui_napari_panel_<id>
    kind: str  # the Qt / magicgui widget it is
    find: Callable[[Any], Any]  # widget -> the Qt object
    expected: str  # the effect, in words (docs/UI_AUDIT.md)
    effect: Effect  # asserts it


def _menu_action(widget: Any, index: int) -> QAction:
    return widget.copy_button.menu().actions()[index]


def enumerate_controls(widget: Any) -> list[Any]:
    """Every interactive Qt object of the dock widget outside the per-parameter form (the form's own Run button is kept), plus the
    entries of every menu. Internal parts (a spin box's line edit, scroll bars) are not controls."""
    form = widget.gui.native if widget.gui is not None else None
    stale = [
        c
        for c in widget.children()
        if isinstance(c, QWidget) and c.isHidden() and widget.layout().indexOf(c) < 0
    ]
    found: list[Any] = []
    for obj in widget.findChildren(INTERACTIVE):
        if isinstance(obj, QScrollBar) or isinstance(obj.parent(), (QAbstractSpinBox, QComboBox)):
            continue
        if any(
            old.isAncestorOf(obj) for old in stale
        ):  # a form that was replaced and waits for Qt to delete it (`_remove_form`)
            continue
        if form is not None and form.isAncestorOf(obj) and obj is not widget.gui.call_button.native:
            continue
        found.append(obj)
    for menu in widget.findChildren(QMenu):
        found += [a for a in menu.actions() if not a.isSeparator()]
    return found


def describe(obj: Any) -> str:
    return "%s %r" % (type(obj).__name__, obj.text() if hasattr(obj, "text") else obj.objectName())


def control_ids(widget: Any) -> list[str]:
    return sorted(describe(o) for o in enumerate_controls(widget))


def registry_apps(ctx: AppCtx) -> list[str]:
    """The apps registered under LC_HOME, from the files."""
    return sorted(
        p.name[: -len(".json")]
        for p in (ctx.cfg.home / "apps").glob("*.json")
        if not p.name.endswith(".schema.json")
    )


def chooser_labels(schema: dict[str, Any]) -> list[str]:
    """The tool chooser entries the schema file calls for: the label, or `label (id)` when two tools share a label."""
    labels = [t["label"] for t in schema["tools"]]
    return [
        t["label"] if labels.count(t["label"]) == 1 else "%s (%s)" % (t["label"], t["id"])
        for t in schema["tools"]
    ]


# ---- effects: each presses one control with a real click and asserts what the table says ----------------------------------------
def effect_run(ctx: AppCtx) -> str:
    """The Run button of a form (clicked by every run step): started a task, greyed out while it ran, usable again after."""
    if not ctx.runs:
        raise NotRun("no tool ran, so Run was never pressed")
    obs = ctx.runs[0]
    problems = [
        text for ok, text in (
            (obs.started, "no task started"),
            (obs.disabled_while_running, "Run stayed enabled while the tool ran (a second click is silently ignored)"),
            (obs.enabled_after, "Run stayed disabled after the run"),
        ) if not ok
    ]  # fmt: skip
    if problems:
        raise AssertionError("%s (tool %s)" % ("; ".join(problems), obs.tool))
    return "clicked for %s: started, disabled while running, enabled after (%s)" % (obs.tool, obs.task_status)


def effect_cancel(ctx: AppCtx) -> str:
    """With nothing running Cancel is greyed out, a click on it and a call of it change nothing."""
    w = ctx.host.widget
    if w.task is not None and not w.task.done.is_set():
        raise AssertionError("a run is still going before the check")
    before = w.status.text()
    if w.cancel_button.isEnabled():
        raise AssertionError("Cancel is enabled with nothing running")
    real_click(w.cancel_button, expect_disabled=True)
    w.cancel()
    pump(0.2)
    if w.status.text() != before:
        raise AssertionError(
            "Cancel with nothing running changed the status: %r -> %r" % (before, w.status.text())
        )
    return "greyed out and a no-op when idle (status unchanged)"


def effect_rescan(ctx: AppCtx) -> str:
    """The registry is read again; the chooser then lists apps that are registered on disk, and the choice stays."""
    w = ctx.host.widget
    app, tool = w.app_box.value, w.tool_box.value
    w.timings["discovery_ms"] = -1.0
    real_click(w.rescan_button)
    pump(0.5)
    on_disk, listed = registry_apps(ctx), list(w.app_box.choices)
    problems = []
    if w.timings["discovery_ms"] < 0:
        problems.append("the registry was not read again")
    if not set(listed) <= set(on_disk) or ctx.app not in listed:
        problems.append("the chooser lists %s, the registry files are %s" % (listed, on_disk))
    if (w.app_box.value, w.tool_box.value) != (app, tool):
        problems.append("the choice changed: %r/%r -> %r/%r" % (app, tool, w.app_box.value, w.tool_box.value))
    if list(w.tool_box.choices) != chooser_labels(ctx.schema):
        problems.append(
            "the tools shown are %s, the schema file gives %s"
            % (list(w.tool_box.choices), chooser_labels(ctx.schema))
        )
    if problems:
        raise AssertionError("; ".join(problems))
    return "registry read again; apps %s of the files %s, choice kept" % (listed, on_disk)


def _run_first_case(ctx: AppCtx) -> None:
    tool_id = ctx.runs[0].tool
    case = choose_case(ctx, tool_id)[1]
    prepare(ctx, tool_id, case)
    execute(ctx, tool_id, case, time.time() + ctx.cfg.timeout)


def effect_restart(ctx: AppCtx) -> str:
    """The kept worker PROCESS ends (read from the process, not from the widget's cache)."""
    w = ctx.host.widget
    if not ctx.runs:
        raise NotRun("no tool ran, so there is no worker to restart")
    if not w._workers._workers.get(
        ctx.app
    ):  # noqa: SLF001 - the last run ended cancelled or crashed: one more, to have a kept worker
        _run_first_case(ctx)
    worker = w.worker
    if worker.proc.poll() is not None:
        raise AssertionError("the worker of the last run is not alive before Restart worker")
    pid = worker.proc.pid
    real_click(w.restart_button)
    if not until(lambda: worker.proc.poll() is not None, 15):
        raise AssertionError("worker process %d is still alive 15 s after Restart worker" % pid)
    return "worker process %d ended after Restart worker" % pid


def effect_keep(ctx: AppCtx) -> str:
    """Ticked by default: the worker process of a run stays alive. Unticked (a real click): it ends after the run."""
    w = ctx.host.widget
    if not ctx.runs:
        raise NotRun("no tool ran, so the worker of a run cannot be looked at")
    if not w.reuse_box.isChecked():
        raise AssertionError("the box is not ticked by default")
    _run_first_case(ctx)
    kept = w.worker.proc
    pump(1.0)
    if kept.poll() is not None:
        raise AssertionError("ticked: the worker process %d ended after the run" % kept.pid)
    real_click(w.reuse_box)
    try:
        if w.reuse_box.isChecked():
            raise AssertionError("a click did not untick the box")
        _run_first_case(ctx)
        single = w.worker.proc
        if not until(lambda: single.poll() is not None, 15):
            raise AssertionError("unticked: the worker process %d is still alive after the run" % single.pid)
    finally:
        if not w.reuse_box.isChecked():
            real_click(w.reuse_box)
    if not w.reuse_box.isChecked():
        raise AssertionError("a click did not tick the box again")
    return "ticked (default): worker %d stayed alive; unticked: worker %d ended" % (kept.pid, single.pid)


def effect_details(ctx: AppCtx) -> str:
    """A dialog with the details of the last run: the run record and the log it names exist on disk."""
    w = ctx.host.widget
    if not ctx.runs:
        raise NotRun("no tool ran, so Details has nothing to show")

    def inspect(dialog: Any) -> tuple[str, str]:
        return dialog.windowTitle(), dialog.detailedText()

    title, detail = press_with_modal(lambda: real_click(w.details_button), inspect, ["QMessageBox"])  # type: ignore[misc]
    named = {
        k: v
        for k, _, v in (line.partition(": ") for line in detail.splitlines())
        if k in ("run record", "log file")
    }
    missing = [k for k, v in named.items() if not Path(v).exists()]
    if set(named) != {"run record", "log file"} or missing:
        raise AssertionError("the dialog names %s; not on disk: %s" % (sorted(named), missing))
    if not (Path(named["run record"]) / "run.json").is_file():
        raise AssertionError("the run record %s has no run.json" % named["run record"])
    return "dialog %r opened and closed; the run record and the log it names exist on disk" % title


def _copy_entry(ctx: AppCtx, index: int) -> str:
    """Click Copy as command (real click), check the popup offers exactly the two entries, click entry `index`: the clipboard text."""
    w = ctx.host.widget
    if not ctx.runs:
        raise NotRun("no tool ran, so there is no case to compare the copied command with")
    tool_id = ctx.runs[0].tool
    prepare(ctx, tool_id, choose_case(ctx, tool_id)[1])
    clipboard = QApplication.clipboard()
    clipboard.setText("")

    def inspect(menu: Any) -> list[str]:
        labels = [a.text() for a in menu.actions()]
        if labels != COPY_LABELS:
            raise AssertionError("the Copy as command menu offers %s, expected %s" % (labels, COPY_LABELS))
        QTest.mouseClick(
            menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(menu.actions()[index]).center()
        )
        return labels

    press_with_modal(lambda: real_click(w.copy_button), inspect, ["QMenu"])
    pump(0.2)
    text = clipboard.text()
    if not text:
        raise AssertionError("nothing on the clipboard; status: %s" % w.status.text())
    return text


def _case_values(ctx: AppCtx) -> tuple[str, dict[str, Any]]:
    """The tool of the first run and the values its case gives: the independent source of what the copied command must say."""
    tool_id = ctx.runs[0].tool
    case = choose_case(ctx, tool_id)[1]
    return tool_id, testing._resolve_paths(case, tool_of(ctx, tool_id))  # noqa: SLF001


def _same(text: str, value: Any) -> bool:
    if text == str(value) or text.lower() == str(value).lower():
        return True
    try:
        return float(text) == float(value)
    except (TypeError, ValueError):
        return False


def effect_copy_terminal(ctx: AppCtx) -> str:
    """The terminal line says `run <app> <tool>` and every value of the case as name=value (files as the fixture paths)."""
    text = _copy_entry(ctx, 0)
    tool_id, values = _case_values(ctx)
    line = next((x for x in text.split("\n") if x and not x.startswith("#")), "")
    words = shlex.split(line)
    start = words.index("run") if "run" in words else -1
    if start < 0 or words[start : start + 3] != ["run", ctx.app, tool_id]:
        raise AssertionError("the line has no 'run %s %s': %r" % (ctx.app, tool_id, line[:200]))
    pairs = dict(x.split("=", 1) for x in words[start + 3 :] if "=" in x)
    wrong = [k for k, v in values.items() if k not in pairs or not _same(pairs[k], v)]
    if wrong:
        raise AssertionError("the line misses or changes the values of %s: %r" % (wrong, line[:300]))
    return "terminal line: run %s %s with the %d values of the case: %s" % (
        ctx.app,
        tool_id,
        len(values),
        line[:120],
    )


def effect_copy_python(ctx: AppCtx) -> str:
    text = _copy_entry(ctx, 1)
    tool_id, values = _case_values(ctx)
    ast.parse(text)
    missing = [
        x
        for x in (ctx.app, tool_id, *(str(v) for v in values.values() if isinstance(v, str)))
        if x not in text
    ]
    if missing:
        raise AssertionError("the Python snippet lacks %s" % missing)
    return "Python snippet parses and holds the app, the tool and the case's text values (%d lines)" % len(
        text.splitlines()
    )


def effect_copy_button(ctx: AppCtx) -> str:
    """The popup the button opens has exactly the two entries (also checked inside each copy click)."""
    menu = ctx.host.widget.copy_button.menu()
    labels = [a.text() for a in menu.actions()] if menu is not None else []
    if labels != COPY_LABELS:
        raise AssertionError("the menu has %s" % labels)
    return "menu entries %s" % labels


def effect_app_chooser(ctx: AppCtx) -> str:
    """The chooser lists registered apps only, and each app gives the tools its schema file names."""
    w, apps = ctx.host.widget, list(ctx.host.widget.app_box.choices)
    on_disk = registry_apps(ctx)
    if not set(apps) <= set(on_disk) or ctx.app not in apps:
        raise AssertionError("the chooser lists %s, the registry files are %s" % (apps, on_disk))
    seen = []
    for app in apps:
        schema = json.loads((ctx.cfg.home / "apps" / ("%s.schema.json" % app)).read_text(encoding="utf-8"))
        w.app_box.value = app
        pump(0.3)
        if list(w.tool_box.choices) != chooser_labels(schema):
            raise AssertionError(
                "%s: the tool chooser shows %s, its schema gives %s"
                % (app, list(w.tool_box.choices), chooser_labels(schema))
            )
        seen.append("%s(%d)" % (app, len(schema["tools"])))
    w.app_box.value = ctx.app
    pump(0.3)
    return "apps and their tool counts: %s" % ", ".join(seen)


def effect_tool_chooser(ctx: AppCtx) -> str:
    """Each entry gives that tool's form, with the description of the schema file."""
    w = ctx.host.widget
    w.app_box.value = ctx.app
    pump(0.3)
    for tool in ctx.schema["tools"]:
        w.tool_box.value = ctx.labels[tool["id"]]
        pump(0.4)
        if w.tool is None or w.tool["id"] != tool["id"]:
            raise AssertionError(
                "choosing %r gives the tool %r" % (ctx.labels[tool["id"]], w.tool and w.tool["id"])
            )
        if w.gui is None or w.gui.name != tool["id"]:
            raise AssertionError("no form of %s: %s" % (tool["id"], w.status.text()))
        if w.description.text() != tool.get("description", ""):
            raise AssertionError(
                "%s: description %r, the schema file says %r"
                % (tool["id"], w.description.text(), tool.get("description", ""))
            )
    return "%d tools chosen, each gave its form and the description of the schema" % len(ctx.schema["tools"])


CONTROLS: list[Control] = [
    Control("run", "magicgui PushButton (the form's call button)", lambda w: w.gui.call_button.native,
            "a click starts the task; the button is greyed out while it runs and usable after", effect_run),
    Control("cancel", "QPushButton", lambda w: w.cancel_button, "idle: greyed out; a click or a call changes nothing", effect_cancel),
    Control("rescan_apps", "QPushButton", lambda w: w.rescan_button,
            "the registry is read again; the chooser lists registered apps, the choice stays", effect_rescan),
    Control("restart_worker", "QPushButton", lambda w: w.restart_button, "the kept worker process ends", effect_restart),
    Control("keep_the_worker_running", "QCheckBox", lambda w: w.reuse_box,
            "ticked by default: the worker process outlives the run; unticked: it ends", effect_keep),
    Control("details", "QPushButton", lambda w: w.details_button,
            "a dialog opens; the run record and log it names exist on disk", effect_details),
    Control("copy_as_command", "QPushButton with a QMenu", lambda w: w.copy_button,
            "a popup with exactly Terminal command and Python snippet", effect_copy_button),
    Control("copy_terminal_command", "QMenu action", lambda w: _menu_action(w, 0),
            "the clipboard holds run <app> <tool> and every value of the case", effect_copy_terminal),
    Control("copy_python_snippet", "QMenu action", lambda w: _menu_action(w, 1),
            "the clipboard holds Python that parses and names the app, tool and values", effect_copy_python),
    Control("app_chooser", "magicgui ComboBox (QComboBox)", lambda w: w.app_box.native,
            "registered apps only; each gives the tools of its schema file", effect_app_chooser),
    Control("tool_chooser", "magicgui ComboBox (QComboBox)", lambda w: w.tool_box.native,
            "each tool gives its form and the schema's description", effect_tool_chooser),
]  # fmt: skip


def controls_all_known(ctx: AppCtx) -> str:
    """Set equality of the controls found and the table, at least MIN_CONTROLS found, and only the main window on screen."""
    w = ctx.host.widget
    if w.gui is None:
        raise AssertionError("no form is open, so the Run button cannot be found")
    found = enumerate_controls(w)
    problems = []
    if len(found) < MIN_CONTROLS:
        problems.append("only %d controls found, at least %d expected" % (len(found), MIN_CONTROLS))
    known: dict[int, str] = {}
    for row in CONTROLS:
        obj = row.find(w)
        if not any(obj is f for f in found):
            problems.append("table row %r: its control is not in the widget tree" % row.id)
        known[id(obj)] = row.id
    unknown = [describe(f) for f in found if id(f) not in known]
    if unknown:
        problems.append("controls without a row in the control table: %s" % "; ".join(unknown))
    window = windows_problem([MAIN_WINDOW])
    if window:
        problems.append(window)
    if problems:
        raise AssertionError(" | ".join(problems))
    return "%d controls found = the %d table rows: %s" % (
        len(found),
        len(CONTROLS),
        ", ".join(r.id for r in CONTROLS),
    )


def cancel_running(ctx: AppCtx) -> str:
    """While a tool runs (a case with cancel_after_s): the same controls are on screen, Cancel is enabled, and a real click on it ends
    the run cancelled."""
    case = next(
        (c for c in ctx.cases if "cancel_after_s" in c and not c.get("skip") and "memory" not in c["tool"]),
        None,
    )
    if case is None:
        raise Human("no case of cases.json sets cancel_after_s: a person presses Cancel during a long run")
    before = control_ids(ctx.host.widget)
    prepare(ctx, case["tool"], case)
    seen: dict[str, Any] = {}

    def during(w: Any) -> None:
        seen["controls"] = control_ids(w)
        seen["cancel"] = w.cancel_button.isEnabled()
        seen["windows"] = windows_problem([MAIN_WINDOW])

    _, task = execute(ctx, case["tool"], case, time.time() + ctx.cfg.timeout, during)
    problems = []
    if seen["controls"] != before:
        problems.append(
            "the controls changed while running: %s" % sorted(set(seen["controls"]) ^ set(before))
        )
    if not seen["cancel"]:
        problems.append("Cancel was not enabled while the tool ran")
    if seen["windows"]:
        problems.append(seen["windows"])
    if task.status != "CANCELED" or not ctx.runs[-1].status_text.startswith("cancelled"):
        problems.append("the run ended %s: %s" % (task.status, ctx.runs[-1].status_text))
    if problems:
        raise AssertionError("; ".join(problems))
    return "Cancel (real click) ended %s as CANCELED; the %d controls were the same while it ran" % (
        case["tool"],
        len(before),
    )

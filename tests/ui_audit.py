"""UI audit of the LabConstrictor Napari dock widget against an INSTALLED app (docs/UI_AUDIT.md; contract: TEST_STRATEGY.md section 3 of
LabConstrictor-Tools). Run under xvfb in an environment with napari, labconstrictor-tools and napari-labconstrictor:

    LC_HOME=<registry with the app> LC_APP=<name> LC_APP_TESTS=<app>/lc_tests LC_EXPECT_NAPARI=listed LC_SHOTS=screens \\
        xvfb-run -a python tests/ui_audit.py

Prints `CHECK <id> PASS|FAIL <detail>` and `NOTE <id> not run: <reason>` per assertion, rewrites
`<LC_SHOTS>/matrix_ui_napari_<app>.json` after every one, never stops at the first failure, and exits non-zero if any check failed.
"""

import io
import json
import os
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent))

import napari  # noqa: E402
import ui_audit_controls as controls  # noqa: E402
import ui_audit_core as core  # noqa: E402
import ui_audit_forms as forms  # noqa: E402
import ui_audit_runs as runs  # noqa: E402
from qtpy.QtWidgets import QApplication  # noqa: E402
from ui_audit_core import (  # noqa: E402
    AppCtx,
    AuditConfigError,
    Config,
    Host,
    Human,
    Recorder,
    config_from_env,
    install_excepthook,
    install_sentinel,
    pump,
    sanitise,
)
from ui_audit_watch import supervise  # noqa: E402

PLUGIN, DOCK = "napari-labconstrictor", "LabConstrictor tools"
PANEL_ORDER = ["run", "cancel", "details", "copy_as_command", "copy_terminal_command", "copy_python_snippet", "rescan_apps",
               "restart_worker", "keep_the_worker_running", "app_chooser", "tool_chooser"]  # fmt: skip


SENTINELS: list[Any] = []  # keeps the sentinel timer alive


def open_host() -> Host:
    """The Napari window with the LabConstrictor dock widget, the way a person opens it."""
    print("STEP viewer", file=sys.stderr, flush=True)
    viewer = napari.Viewer(show=True)
    print("STEP viewer made", file=sys.stderr, flush=True)
    window = viewer.window._qt_window  # noqa: SLF001
    # the whole window, frame included, must fit the usable part of the screen (not under a taskbar or menu bar), or a button of the dock
    # is out of reach: a window larger than the screen is cut down by Windows (a 1024x768 CI screen gets a 1024x749 client under its title bar)
    area = QApplication.primaryScreen().availableGeometry()
    frame_w = window.frameGeometry().width() - window.width()
    frame_h = window.frameGeometry().height() - window.height()
    window.resize(min(1500, area.width() - frame_w), min(850, area.height() - frame_h))
    print("STEP sizing %s" % (window.frameGeometry().getRect(),), file=sys.stderr, flush=True)
    window.move(area.topLeft())
    print("STEP dock", file=sys.stderr, flush=True)
    _, widget = viewer.window.add_plugin_dock_widget(PLUGIN, DOCK)
    print("STEP dock made", file=sys.stderr, flush=True)
    pump(1.0)
    print("STEP pumped %s" % (window.frameGeometry().getRect(),), file=sys.stderr, flush=True)
    if not area.contains(window.frameGeometry()):
        raise AssertionError(
            "the Napari window %s does not fit the usable screen %s: run with a larger screen (xvfb -s '-screen 0 1600x1000x24')"
            % (window.frameGeometry().getRect(), area.getRect())
        )
    install_excepthook()  # after napari's own: a slot that raises is recorded against the running check
    SENTINELS.append(
        install_sentinel()
    )  # a dialog nobody asked for is recorded and closed, never left blocking the Qt thread
    return Host(viewer, widget)


def tool_labels(host: Host, app: str) -> dict[str, str]:
    """tool id -> the label of the tool chooser, read by choosing each entry."""
    w, labels = host.widget, {}
    w.app_box.value = app
    pump(0.3)
    for label in list(w.tool_box.choices):
        w.tool_box.value = label
        pump(0.4)
        if w.tool is None:
            raise AssertionError("choosing %r gives no tool: %s" % (label, w.status.text()))
        labels[w.tool["id"]] = label
    return labels


def multi_checks(host: Host, cfg: Config, rec: Recorder) -> None:
    """LC_APPS: the chooser lists every named app with all its tools, and switching shows the right tools."""
    w = host.widget

    def lists(app: str) -> Callable[[], str]:
        def body() -> str:
            if app not in w.app_box.choices:
                raise AssertionError("%s is not in the chooser %s" % (app, list(w.app_box.choices)))
            labels = tool_labels(host, app)
            ids = [t["id"] for t in w.schemas[app]["tools"]]
            if sorted(labels) != sorted(ids) or not ids:
                raise AssertionError(
                    "the chooser offers tools %s, the schema has %s" % (sorted(labels), sorted(ids))
                )
            return "%d tools: %s" % (len(ids), ", ".join(sorted(ids)))

        return body

    def switch(a: str, b: str) -> Callable[[], str]:
        def body() -> str:
            seen = []
            for app in (a, b, a):
                w.app_box.value = app
                pump(0.4)
                shown = sorted(w.tool_box.choices)
                want = sorted(t["id"] for t in w.schemas[app]["tools"])
                if len(shown) != len(want) or (w.tool is not None and w.tool["id"] not in want):
                    raise AssertionError(
                        "after choosing %s the tool chooser shows %s, expected tools %s" % (app, shown, want)
                    )
                if w.gui is None:
                    raise AssertionError("after choosing %s no form is shown" % app)
                seen.append("%s(%d)" % (app, len(want)))
            return "switched " + " -> ".join(seen)

        return body

    for app in cfg.apps:
        rec.check("ui_napari_multi_lists_%s" % sanitise(app), lists(app), control="app_chooser")
    for a, b in zip(cfg.apps, cfg.apps[1:]):
        rec.check(
            "ui_napari_multi_switch_%s_%s" % (sanitise(a), sanitise(b)), switch(a, b), control="app_chooser"
        )


def disk_schema(cfg: Config, app: str) -> dict[str, Any]:
    """The schema of the app as the registry file holds it: the audit's independent source for tools, parameters and results."""
    return json.loads((cfg.home / "apps" / ("%s.schema.json" % app)).read_text(encoding="utf-8"))


def build_ctx(host: Host, cfg: Config, app: str, rec: Recorder) -> AppCtx:
    folder = runs.scratch_copy(cfg.tests[app])
    cases, no_case, problem = runs.load_cases(folder)
    ctx = AppCtx(
        host,
        cfg,
        app,
        rec,
        disk_schema(cfg, app),
        cases,
        no_case,
        tool_labels(host, app),
        folder,
        case_problem=problem,
    )
    return ctx


def expected_ids(ctx: AppCtx) -> list[str]:
    """Every id this audit of the app intends to produce (written before anything runs; one without a row ends as NOT_RUN)."""
    ids = ["ui_napari_app_listed", "ui_napari_controls_all_known", "ui_napari_panel_cancel_running"]
    ids += ["ui_napari_panel_%s" % c for c in PANEL_ORDER]
    for tool in ctx.schema["tools"]:
        key = sanitise(tool["id"])
        ids += ["ui_napari_form_%s_opens" % key, "ui_napari_form_%s_controls" % key]
        ids += ["ui_napari_run_%s" % key, "ui_napari_screens_%s" % key]
    return ids


def audit_tool(ctx: AppCtx, tool: dict[str, Any]) -> None:
    """The form, run and screenshot checks of one tool, each in its own guard, inside one time budget."""
    rec, tid = ctx.rec, tool["id"]
    key, deadline = sanitise(tid), time.time() + ctx.cfg.timeout
    form_png, after_png = runs.shot_paths(ctx, tid)
    rec.check("ui_napari_form_%s_opens" % key, lambda: forms.form_opens(ctx, tool), tid, "form")
    rec.check("ui_napari_form_%s_controls" % key, lambda: forms.form_controls(ctx, tool), tid, "form")
    outcome: dict[str, Any] = {}
    rec.check(
        "ui_napari_run_%s" % key,
        lambda: runs.run_tool(ctx, tid, deadline, outcome),
        tid,
        "run",
        str(form_png),
    )

    def screens() -> str:
        try:
            runs.choose_case(ctx, tid)
        except Human as reason:  # a tool that is not run: its form is still photographed, for a person
            runs.form_only_shot(ctx, tid)
            raise Human("%s; the form screenshot %s was taken" % (reason, form_png.name)) from None
        except AssertionError:
            pass  # no case and no reason: the run check failed, and the missing screenshots fail this one too
        return runs.screens_check(ctx, tid, outcome)

    rec.check("ui_napari_screens_%s" % key, screens, tid, "screens", str(after_png))


def audit_panel(ctx: AppCtx) -> None:
    """The fixed controls of the dock widget: the enumeration against the table, then each control of the table."""
    rec, w = ctx.rec, ctx.host.widget
    w.app_box.value = ctx.app
    pump(0.3)
    if ctx.schema["tools"]:
        w.tool_box.value = ctx.labels[ctx.schema["tools"][0]["id"]]
        pump(0.5)
    rec.check("ui_napari_controls_all_known", lambda: controls.controls_all_known(ctx), control="all")
    by_id = {c.id: c for c in controls.CONTROLS}
    if sorted(PANEL_ORDER) != sorted(by_id):
        raise RuntimeError(
            "the panel order and the control table differ: %s" % sorted(set(PANEL_ORDER) ^ set(by_id))
        )
    for cid in PANEL_ORDER:
        row = by_id[cid]
        rec.check("ui_napari_panel_%s" % cid, lambda row=row: row.effect(ctx), control=cid)
    rec.check("ui_napari_panel_cancel_running", lambda: controls.cancel_running(ctx), control="cancel")


def audit_app(host: Host, cfg: Config, app: str, rec: Recorder) -> None:
    w = host.widget
    if cfg.expect == "not_listed":
        rec.declare(["ui_napari_not_listed"])
        rec.check("ui_napari_not_listed", lambda: _absent(w, app), control="app_chooser")
        print(
            "NOTE ui_napari_not_listed_forms not run: no control, form or run checks, %s is hidden from this host by design"
            % app,
            flush=True,
        )
        return
    rec.declare(["ui_napari_app_listed"])
    if not rec.check("ui_napari_app_listed", lambda: _listed(host, cfg, app), control="app_chooser"):
        return
    ctx = build_ctx(host, cfg, app, rec)
    rec.declare(expected_ids(ctx))
    for tool in runs.tool_order(ctx):
        audit_tool(ctx, tool)
    audit_panel(ctx)


def _absent(w: Any, app: str) -> str:
    choices = list(w.app_box.choices)
    if app in choices:
        raise AssertionError("%s is offered although this host must not list it: %s" % (app, choices))
    return "%s is not in the app chooser %s" % (app, choices)


def _listed(host: Host, cfg: Config, app: str) -> str:
    w = host.widget
    choices = list(w.app_box.choices)
    if app not in choices:
        raise AssertionError("%s is not in the app chooser %s" % (app, choices))
    schema = disk_schema(cfg, app)
    w.app_box.value = app
    pump(0.3)
    if list(w.tool_box.choices) != controls.chooser_labels(schema):
        raise AssertionError(
            "tool chooser %s, the schema file gives %s"
            % (list(w.tool_box.choices), controls.chooser_labels(schema))
        )
    return "%s is offered with all %d tools of its schema file" % (app, len(schema["tools"]))


def audit(cfg: Config, on_widget: Callable[[Any], None] | None = None) -> int:
    """Run the whole audit; the number of failed checks. `on_widget` (the self test) gets the dock widget before the first check."""
    core.HOST_VERSION = core.host_version()
    print("NOTE ui_napari_host_version %s" % core.HOST_VERSION, flush=True)
    host = open_host()
    failed = 0
    rec: Recorder | None = None
    try:
        if on_widget is not None:
            on_widget(host.widget)
        shared: list[dict[str, Any]] = []
        for index, app in enumerate(cfg.apps):
            rec = Recorder(app, cfg.shots, shared)
            try:
                if index == 0 and len(cfg.apps) > 1 and cfg.expect == "listed":
                    pairs = list(zip(cfg.apps, cfg.apps[1:]))
                    rec.declare(["ui_napari_multi_lists_%s" % sanitise(a) for a in cfg.apps])
                    rec.declare(
                        ["ui_napari_multi_switch_%s_%s" % (sanitise(a), sanitise(b)) for a, b in pairs]
                    )
                    multi_checks(host, cfg, rec)
                    shared = list(rec.rows)
                audit_app(host, cfg, app, rec)
            # the host itself broke: the matrix written so far stays valid
            except Exception as error:  # noqa: BLE001
                rec.add(
                    "ui_napari_driver_crashed",
                    "FAIL",
                    "%s: %s | %s" % (type(error).__name__, error, traceback.format_exc()[-300:]),
                )
            rec.finish()
            failed += len(rec.red)
    finally:
        host.viewer.close()
        pump(1.0)
    print("NAPARI UI AUDIT SUMMARY failed=%d" % failed, flush=True)
    return failed


def child_main() -> None:
    """The audit itself (in the child process the watchdog started)."""
    try:
        cfg = config_from_env(os.environ)
    except AuditConfigError as error:
        sys.exit("ui_audit: %s" % error)
    failed = audit(cfg)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(
        1 if failed else 0
    )  # the verdict is printed; exit handlers of PyQt6 + napari can segfault (tests/_paths.py `_leave`)


def main() -> None:
    """Start the audit in a child process under the watchdog (ui_audit_watch.py): a hard crash or a frozen Qt thread still ends with a
    complete, red matrix. `--child` runs the audit in this process (no watchdog)."""
    # the check details quote the widget's own sentences (warning signs, ellipses): a Windows console (cp1252) cannot print them
    cast(io.TextIOWrapper, sys.stdout).reconfigure(encoding="utf-8")
    if "--child" in sys.argv:
        child_main()
        return
    try:
        cfg = config_from_env(os.environ)
    except AuditConfigError as error:
        sys.exit("ui_audit: %s" % error)
    idle = float(os.environ.get("LC_UI_IDLE_S", 3 * cfg.timeout + 180))
    sys.exit(supervise([sys.executable, str(Path(__file__).resolve()), "--child"], cfg.shots, cfg.apps, idle))


if __name__ == "__main__":
    main()

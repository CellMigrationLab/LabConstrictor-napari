"""The Qt backend end to end (issue #41): the plugin is offered under Plugins > LabConstrictor tools in napari's real menu, opens
from that menu entry, and the pieces that depend on the Qt binding work on the one installed (PyQt6, PySide6 or the deprecated
PyQt5): a long form scrolls, the Details dialog really opens (QMessageBox.exec_ through qtpy) and shows the run's record, the
status line and the results table dock render what the tool returned.

The CI job names the backend it installed in LC_EXPECT_QT ("PyQt6", "PySide6"); the test then fails if qtpy picked another one,
so a job can never silently test the wrong stack. Without it the backend is only reported.
"""

import json
import os
import sys
import time

import _paths  # noqa: F401  (must come first)
import napari
import numpy as np
import qtpy
from _paths import EVIDENCE
from qtpy.QtCore import QTimer
from qtpy.QtWidgets import QApplication, QMenu, QMessageBox, QScrollArea

report, failures = {}, []


def expect(name, condition, detail=""):
    report[name] = bool(condition)
    if not condition:
        failures.append("%s %s" % (name, detail))


expected = os.environ.get("LC_EXPECT_QT")
print("Qt backend:", qtpy.API_NAME, qtpy.QT_VERSION, "| napari", napari.__version__)
expect(
    "backend_is_the_expected_one", expected is None or expected == qtpy.API_NAME, (qtpy.API_NAME, expected)
)
if expected in ("PyQt6", "PySide6"):
    expect("never_a_second_binding_loaded", not any(m in sys.modules for m in ("PyQt5", "PySide2")), expected)
    other = {"PyQt6": "PySide6", "PySide6": "PyQt6"}[expected]
    expect("never_both_qt6_bindings_in_one_process", other not in sys.modules, other)

v = napari.Viewer(show=True)
v.window.resize(1500, 950)
qa = QApplication.instance()


def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        qa.processEvents()
        time.sleep(0.02)


def find_actions(menu, text, path=()):
    """Every action whose label starts with `text` in `menu` and its submenus, with the menu path leading to it.
    napari labels a widget entry "<widget> (<plugin display name>)"."""
    found = []
    for action in menu.actions():
        sub = action.menu()
        if isinstance(sub, QMenu):
            found += find_actions(sub, text, (*path, action.text().replace("&", "")))
        elif action.text().replace("&", "").startswith(text):
            found.append((path, action))
    return found


# 1. the entry in napari's Plugins menu, opened from there (not through add_plugin_dock_widget)
plugins_menu = v.window.plugins_menu
hits = find_actions(plugins_menu, "LabConstrictor tools")
expect("menu_entry_exists_under_plugins", len(hits) == 1, [h[0] for h in hits])
expect(
    "menu_entry_names_the_plugin",
    bool(hits) and "(LabConstrictor)" in hits[0][1].text(),
    [h[1].text() for h in hits],
)
if hits:
    hits[0][1].trigger()
    pump(1.0)
docks = {n: x for n, x in v.window.dock_widgets.items() if "LabConstrictor tools" in n}
expect("menu_entry_opens_the_dock", len(docks) == 1, list(v.window.dock_widgets))
if not docks:
    print("FAILURES:", failures)
    sys.exit(1)
w = next(iter(docks.values()))
expect("dock_holds_the_labconstrictor_widget", hasattr(w, "details_button"), type(w))


def wait(timeout=120):
    end = time.time() + timeout
    while (w.last_task is None or w.task is not w.last_task) and time.time() < end:
        qa.processEvents()
        time.sleep(0.05)
    pump(0.8)
    return w.last_task


def run():
    w.last_task = None
    w.gui()
    return wait()


def pick(app, label):
    w.app_box.value = app
    pump(0.1)
    w.tool_box.value = label
    pump(0.3)


expect("app_dropdown_lists_the_app", "synthetic" in list(w.app_box.choices), list(w.app_box.choices))

# 2. a long form sits in a scroll area that really scrolls (Kitchen sink is taller than a small dock)
pick("synthetic", "Kitchen sink")
v.window.resize(900, 420)
pump(0.6)
areas = [
    a for a in w.findChildren(QScrollArea) if a.widget() is not None and a.verticalScrollBar().maximum() > 0
]
expect(
    "long_form_has_a_working_scrollbar",
    len(areas) >= 1,
    [a.verticalScrollBar().maximum() for a in w.findChildren(QScrollArea)],
)
if areas:
    bar = areas[0].verticalScrollBar()
    bar.setValue(bar.maximum())
    pump(0.2)
    expect("long_form_scrolls_to_the_end", bar.value() == bar.maximum() and bar.value() > 0, bar.value())
v.window.resize(1500, 950)
pump(0.4)

# 3. a run: status text and the results table dock
layer = v.add_image(np.random.default_rng(1).random((64, 64)).astype("float32") * 1000, name="query")
pump()
w.gui.required_string.value = "hello"
w.gui.image.value = layer
pump()
task = run()
expect("run_completes", task.status == "COMPLETE", (task.status, w.status.text()))
expect(
    "status_line_renders_the_result", w.status.isVisible() and w.status.text().strip() != "", w.status.text()
)
table_docks = [n for n in v.window.dock_widgets if "rows" in n]
expect(
    "results_table_dock_exists",
    "rows" in w.tables and len(table_docks) >= 1,
    (list(w.tables), list(v.window.dock_widgets)),
)
if table_docks:
    expect("results_table_dock_is_shown", v.window.dock_widgets[table_docks[0]].isVisible())

# 4. a failure, then the Details dialog opened for real; a timer inspects it while exec_() is blocking, then closes it
pick("synthetic", "Explode")
task = run()
expect(
    "failure_shows_in_status", task.status == "FAILED" and "always fails" in w.status.text(), w.status.text()
)
seen = {}


def inspect_dialog():
    box = qa.activeModalWidget()
    seen["is_message_box"] = isinstance(box, QMessageBox)
    if isinstance(box, QMessageBox):
        seen["title"] = box.windowTitle()
        seen["detailed"] = box.detailedText()
        box.accept()
    else:  # never leave exec_() blocking the run
        for top in qa.topLevelWidgets():
            if isinstance(top, QMessageBox):
                top.accept()


QTimer.singleShot(1500, inspect_dialog)
w.details_button.click()  # blocks in exec_() until inspect_dialog closes the box
expect("details_dialog_opened", seen.get("is_message_box") is True, seen)
expect(
    "details_dialog_shows_the_run_record",
    "always fails" in seen.get("detailed", "") and "log file:" in seen.get("detailed", ""),
    seen.get("detailed", "")[:200],
)
expect("details_dialog_title", "LabConstrictor" in seen.get("title", ""), seen)

(EVIDENCE / "qt_backend_report.json").write_text(json.dumps({"backend": qtpy.API_NAME, **report}, indent=2))
print(json.dumps(report, indent=2))
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)

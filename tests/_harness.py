"""Shared set-up of the parity tests (import after `_paths`): a napari viewer with the LabConstrictor dock, and the
helpers the scripted GUI tests use. The older tests carry their own copy of this and are left as they are."""

import json
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import napari
from qtpy.QtWidgets import QApplication

if TYPE_CHECKING:
    from collections.abc import Callable

report: dict[str, bool] = {}
failures: list[str] = []


def register(name: str, module: str) -> None:
    """Register one more example app of labconstrictor-tools in the private test registry."""
    subprocess.run(
        [sys.executable, "-m", "labconstrictor_tools", "register", "--name", name, "--prefix", sys.prefix,
         "--module", module, "--version", "0.0"],
        check=True, capture_output=True,
    )  # fmt: skip
    widget.rescan()


viewer = napari.Viewer(show=True)
viewer.window._qt_window.resize(1500, 850)
_qa = QApplication.instance()
_, widget = viewer.window.add_plugin_dock_widget("napari-labconstrictor", "LabConstrictor tools")


def pump(sec: float = 0.3) -> None:
    end = time.time() + sec
    while time.time() < end:
        _qa.processEvents()
        time.sleep(0.02)


def until(condition: "Callable[[], object]", timeout: float = 120) -> None:
    end = time.time() + timeout
    while not condition() and time.time() < end:
        _qa.processEvents()
        time.sleep(0.05)
    pump(0.4)


def run() -> None:
    """Press Run and wait until the run has finished and its results are shown."""
    widget.last_task = None
    widget.gui()
    until(lambda: widget.last_task is not None and widget.task is widget.last_task)
    pump(0.6)


def choose(app: str, tool: str) -> None:
    widget.app_box.value = app
    pump(0.3)
    widget.tool_box.value = tool
    pump(1.0)


def expect(name: str, condition: object, detail: object = "") -> None:
    report[name] = bool(condition)
    if not condition:
        failures.append("%s %s" % (name, detail))


def finish() -> None:
    print(json.dumps(report, indent=2))
    print("FAILURES:", failures or "none")
    sys.exit(1 if failures else 0)

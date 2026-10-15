"""Shared parts of the Napari UI audit (tests/ui_audit.py, docs/UI_AUDIT.md): the configuration read from the environment, the
matrix file that is rewritten after every check, the guarded check (one failure never stops the run), waits and screenshots.
Not a test (CI runs only test_*.py)."""

import json
import os
import re
import sys
import time
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qtpy.QtCore import QRect, Qt, QTimer
from qtpy.QtTest import QTest
from qtpy.QtWidgets import QApplication, QWidget

HOST = "napari"
FAMILY = "ui"
HOST_VERSION = (
    ""  # set once by host_version() when the audit starts (the watchdog parent never imports napari)
)
DEFAULT_TOOL_TIMEOUT_S = 300.0
DETAIL_MAX = 500


class NotRun(Exception):
    """Something expected that could not be executed here: status NOT_RUN, printed as `NOTE <id> not run: <reason>`, counted as red."""


class Human(Exception):
    """Something that cannot be automated (a tool without a case, a stress tool): status HUMAN, listed for a person, never green."""


class AuditConfigError(Exception):
    """The environment does not describe a run (a missing variable): the driver refuses instead of guessing."""


def sanitise(text: str) -> str:
    """`[a-z0-9_]` only, as the check ids need (a tool id may hold dots or dashes)."""
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")


def host_version() -> str:
    """The Napari host under audit: the installed distribution's version (a tag install), plus the git commit when it is an editable
    checkout, so a matrix says which host it describes."""
    import subprocess
    from importlib import metadata

    version = metadata.version("napari-labconstrictor")
    import importlib.util

    spec = importlib.util.find_spec("napari_labconstrictor")
    root = (
        Path(spec.origin).resolve().parent.parent
        if spec is not None and spec.origin
        else Path("/nonexistent")
    )
    if (root / ".git").exists():  # the package is imported from a git checkout, not from site-packages
        sha = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if sha.returncode == 0:
            return "%s+git.%s (editable checkout)" % (version, sha.stdout.strip())
    return version


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Config:
    home: Path  # LC_HOME: the registry that holds the installed app(s)
    apps: list[str]  # LC_APP, or the names of LC_APPS
    tests: dict[str, Path]  # app -> its lc_tests folder (LC_APP_TESTS, a comma list aligned with LC_APPS)
    shots: Path  # LC_SHOTS
    expect: str  # LC_EXPECT_NAPARI: "listed" | "not_listed"
    timeout: float  # LC_UI_TOOL_TIMEOUT: seconds one tool (form and run) may take
    input_mode: str = (
        "layer"  # LC_UI_INPUT: "layer" (a 2D TIFF fixture is opened as a layer) | "file" (always the 'or file' row)
    )


def config_from_env(env: Mapping[str, str]) -> Config:
    expect = env.get("LC_EXPECT_NAPARI", "")
    if expect not in ("listed", "not_listed"):
        raise AuditConfigError("LC_EXPECT_NAPARI must be 'listed' or 'not_listed', got %r" % expect)
    if not env.get("LC_HOME"):
        raise AuditConfigError("LC_HOME (the scratch registry with the installed app) is required")
    apps = [a.strip() for a in env.get("LC_APPS", "").split(",") if a.strip()] or [env.get("LC_APP", "")]
    if not apps[0]:
        raise AuditConfigError("LC_APP (or LC_APPS, a comma list) is required")
    folders = [t.strip() for t in env.get("LC_APP_TESTS", "").split(",") if t.strip()]
    if expect == "listed" and len(folders) != len(apps):
        raise AuditConfigError(
            "LC_APP_TESTS needs one lc_tests folder per app (%d apps, %d folders)" % (len(apps), len(folders))
        )
    mode = env.get("LC_UI_INPUT", "layer")
    if mode not in ("layer", "file"):
        raise AuditConfigError("LC_UI_INPUT must be 'layer' or 'file', got %r" % mode)
    return Config(
        home=Path(env["LC_HOME"]),
        apps=apps,
        tests=dict(zip(apps, map(Path, folders))),
        shots=Path(env.get("LC_SHOTS", "./screens")),
        expect=expect,
        timeout=float(env.get("LC_UI_TOOL_TIMEOUT", DEFAULT_TOOL_TIMEOUT_S)),
        input_mode=mode,
    )


SLOT_ERRORS: list[str] = (
    []
)  # exceptions that reached the Qt event loop (a slot raised): a check that sees a new one fails


def install_excepthook() -> None:
    """Record an exception of a Qt slot instead of letting PyQt6 abort the process (and attribute it to the running check)."""

    def hook(kind: type[BaseException], error: BaseException, tb: Any) -> None:
        SLOT_ERRORS.append("%s: %s" % (kind.__name__, error))
        traceback.print_exception(kind, error, tb, file=sys.stderr)

    sys.excepthook = hook


class Recorder:
    """The checks of one app: prints `CHECK` / `NOTE` lines and rewrites the matrix file (atomically) after every single one.

    Statuses: PASS, FAIL, NOT_RUN (expected, not executed: red) and HUMAN (cannot be automated, listed for a person, never green).
    A row's `id` is the printed id (the contract's); the app is a field of the row and of the file, one matrix file per app.
    """

    def __init__(self, app: str, shots: Path, shared: list[dict[str, Any]] | None = None) -> None:
        self.app, self.path = app, shots / ("matrix_ui_%s_%s.json" % (HOST, app))
        self.expected_path = shots / ("expected_%s_%s.json" % (HOST, app))
        self.started, self.finished = now(), None
        self.rows: list[dict[str, Any]] = list(shared or [])
        self.red: list[str] = []  # ids that failed or were never run
        self.expected: list[str] = []  # every id this audit intends to produce
        shots.mkdir(parents=True, exist_ok=True)
        self._write()

    def declare(self, ids: list[str]) -> None:
        """Write the list of every id this audit intends to produce: one without a row at the end is NOT_RUN (red)."""
        self.expected += [i for i in ids if i not in self.expected]
        tmp = self.expected_path.with_name(self.expected_path.name + ".tmp")
        tmp.write_text(json.dumps(self.expected, indent=1), encoding="utf-8")
        os.replace(tmp, self.expected_path)
        self._write()

    def _write(self) -> None:
        doc = {
            "host": HOST,
            "app": self.app,
            "family": FAMILY,
            "host_version": HOST_VERSION,
            "started": self.started,
            "finished": self.finished,
            "expected": len(self.expected),
            "rows": self.rows,
        }
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(
        self, cid: str, status: str, detail: object, tool: str = "", control: str = "", seconds: float = 0.0,
        screenshot: str | None = None,
    ) -> None:  # fmt: skip
        text = str(detail).replace("\n", " | ")[:DETAIL_MAX]
        if status in ("PASS", "FAIL"):
            print("CHECK %s %s %s" % (cid, status, text), flush=True)
        else:
            print("NOTE %s not run: %s%s" % (cid, "[human] " if status == "HUMAN" else "", text), flush=True)
        if status in ("FAIL", "NOT_RUN"):
            self.red.append(cid)
        self.rows.append(
            {
                "id": cid, "family": FAMILY, "host": HOST, "app": self.app, "tool": tool, "control": control,
                "status": status, "detail": text, "seconds": round(seconds, 2), "screenshot": screenshot, "ts": now(),
            }
        )  # fmt: skip
        self._write()

    def check(
        self, cid: str, body: Callable[[], str], tool: str = "", control: str = "", screenshot: str | None = None
    ) -> bool:  # fmt: skip
        """Run one assertion in its own guard: its detail is a PASS; NotRun / Human their statuses; any exception (a failed assertion,
        a timeout, a slot error or an unexpected dialog of Qt) a FAIL that names the exception. The audit goes on with the next check.
        """
        started, seen = time.time(), len(SLOT_ERRORS)
        status = "PASS"
        try:
            detail = body()
        except (NotRun, Human) as reason:
            status, detail = ("HUMAN" if isinstance(reason, Human) else "NOT_RUN"), str(reason)
        # the point of the guard: one broken control must not hide the others
        except Exception as error:  # noqa: BLE001
            detail, status = "%s: %s" % (type(error).__name__, error), "FAIL"
            if not isinstance(error, AssertionError):  # a bug of the audit or of the host: say where
                frame = traceback.extract_tb(error.__traceback__)[-1]
                detail += " (at %s:%d)" % (Path(frame.filename).name, frame.lineno or 0)
        if status == "PASS" and len(SLOT_ERRORS) > seen:
            detail, status = (
                "a slot raised or a dialog interrupted: %s | %s" % (SLOT_ERRORS[seen], detail),
                "FAIL",
            )
        self.add(cid, status, detail, tool, control, time.time() - started, screenshot)
        return status == "PASS"

    def finish(self) -> None:
        """Every declared id that has no row is NOT_RUN: it was expected and never executed."""
        done = {r["id"] for r in self.rows}
        for cid in self.expected:
            if cid not in done:
                self.add(cid, "NOT_RUN", "declared in the expected file, never executed")
        self.finished = now()
        self._write()


@dataclass
class RunObs:
    """What the Run button did in one run (read by the panel checks of Run, Keep the worker and Details)."""

    tool: str
    started: bool = False
    disabled_while_running: bool = False
    ended_before_looked: bool = (
        False  # the task was over when the button was looked at (an instant tool): nothing to observe
    )
    enabled_after: bool = False
    status_text: str = ""
    task_status: str = ""
    progress_events: int = 0
    worker_kept: bool = False
    worker_pid: int = 0
    file_problems: list[str] = field(
        default_factory=list
    )  # contract and expect.results problems, read before the job folder goes
    case_index: int = -1


@dataclass
class Host:
    """The Napari window of the audit and the LabConstrictor dock widget in it."""

    viewer: Any
    widget: Any


@dataclass
class AppCtx:
    """Everything one app's audit needs: the host, the recorder, the app's schema, cases and the run observations."""

    host: Host
    cfg: Config
    app: str
    rec: Recorder
    schema: dict[str, Any]
    cases: list[dict[str, Any]]
    no_case: dict[str, str]
    labels: dict[str, str]  # tool id -> the label of the tool chooser
    scratch: Path  # the scratch copy of lc_tests the cases run in (files a tool writes are found there)
    runs: list[RunObs] = field(default_factory=list)
    replayed: set[int] = field(
        default_factory=set
    )  # indexes of the cases of cases.json that have run (prerequisites are replayed once)
    case_problem: str = ""  # why cases.json could not be read (every run check then fails with it)


def pump(sec: float = 0.3) -> None:
    app = QApplication.instance()
    end = time.time() + sec
    while time.time() < end:
        if app is not None:
            app.processEvents()
        time.sleep(0.02)


def until(condition: Callable[[], object], timeout: float, step: float = 0.05) -> bool:
    """Process events until `condition()` is true; False when `timeout` seconds passed first."""
    app = QApplication.instance()
    end = time.time() + timeout
    while not condition():
        if time.time() > end:
            return False
        if app is not None:
            app.processEvents()
        time.sleep(step)
    return True


def choose(widget: Any, app: str, label: str | None = None) -> None:
    """Pick an application (and a tool) the way a person does: through the choosers."""
    widget.app_box.value = app
    pump(0.2)
    if label is not None:
        widget.tool_box.value = label
        pump(0.5)


def shoot(host: Host, path: Path) -> None:
    """The whole Napari window (canvas, docks, panel) as a PNG: evidence for a person, not a check of the picture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pump(0.3)
    host.viewer.screenshot(path=str(path), canvas_only=False, flash=False)


MIN_PNG_BYTES = 2000


def fresh_problem(path: Path, since: float) -> str | None:
    """None when the file exists, was written after `since` (this run, not an earlier one) and has a plausible size. That is all it says:
    whether the picture is right is for a person to look at."""
    if not path.is_file():
        return "%s does not exist" % path.name
    if path.stat().st_mtime < since:
        return "%s is older than this run" % path.name
    if path.stat().st_size < MIN_PNG_BYTES:
        return "%s has only %d bytes" % (path.name, path.stat().st_size)
    return None


# ---- real input events -----------------------------------------------------------------------------------------------------------
def screen_rect() -> QRect:
    screen = QApplication.primaryScreen()
    if screen is None:
        raise AssertionError("there is no screen")
    return screen.geometry()


def reach_problem(widget: QWidget) -> str | None:
    """Why a person could not click this widget at its centre: not shown, greyed out, outside the screen, clipped or covered."""
    if not widget.isVisible():
        return "not visible"
    if not widget.isEnabled():
        return "not enabled"
    screen, rect = screen_rect(), widget.rect()
    for point in (rect.center(), rect.topLeft(), rect.bottomRight()):
        if not screen.contains(widget.mapToGlobal(point)):
            return "outside the screen %dx%d" % (screen.width(), screen.height())
    top = QApplication.widgetAt(widget.mapToGlobal(rect.center()))
    if top is None or not (top is widget or widget.isAncestorOf(top)):
        return "covered or clipped by %s" % (type(top).__name__ if top is not None else "nothing")
    return None


def real_click(widget: QWidget, expect_disabled: bool = False, settle: bool = True) -> None:
    """A left click at the centre of the widget through Qt's event queue (QTest). A widget a person could not click fails; a greyed-out
    one is clicked only with `expect_disabled` (the click must then do nothing)."""
    problem = reach_problem(widget)
    if problem == "not enabled" and expect_disabled:
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=widget.rect().center())
        pump(0.1)
        return
    if problem:
        name = widget.text() if hasattr(widget, "text") else type(widget).__name__
        raise AssertionError("%s %r cannot be clicked: %s" % (type(widget).__name__, name, problem))
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=widget.rect().center())
    if settle:
        pump(0.1)


def class_names(widgets: list[QWidget]) -> list[str]:
    return sorted(type(w).__name__ for w in widgets)


def visible_windows() -> list[QWidget]:
    return [w for w in QApplication.topLevelWidgets() if w.isVisible()]


def windows_problem(expected: list[str]) -> str | None:
    """The visible top-level windows (main window, dialogs, popups) must be exactly `expected` (class names) and lie inside the screen."""
    shown = visible_windows()
    if class_names(shown) != sorted(expected):
        return "top-level windows are %s, expected %s" % (class_names(shown), sorted(expected))
    screen = screen_rect()
    out = [type(w).__name__ for w in shown if not screen.contains(w.frameGeometry())]
    return "windows outside the screen %dx%d: %s" % (screen.width(), screen.height(), out) if out else None


MAIN_WINDOW = "_QtMainWindow"
EXPECT_DIALOG = [False]  # True while the audit itself opens a dialog: the sentinel then leaves it alone


def install_sentinel() -> QTimer:
    """A timer that keeps running inside any nested event loop: a modal dialog the audit did not ask for (an error box of the widget)
    is recorded as a slot error against the running check and closed, so a modal dialog can never block the Qt thread for good.
    """
    timer = QTimer()

    def look() -> None:
        dialog = QApplication.activeModalWidget()
        if dialog is None or EXPECT_DIALOG[0]:
            return
        text = dialog.text() if hasattr(dialog, "text") else ""
        SLOT_ERRORS.append(
            "unexpected modal dialog %s %r: %s"
            % (type(dialog).__name__, dialog.windowTitle(), str(text)[:200])
        )
        dialog.close()

    timer.timeout.connect(look)
    timer.start(100)
    return timer


def press_with_modal(
    press: Callable[[], object], inspect: Callable[[Any], object], expected_windows: list[str], timeout: float = 10.0
) -> object:  # fmt: skip
    """Run `press()` (it opens a modal dialog or a popup menu and blocks in `exec()`): a timer finds it, checks the windows on screen are
    exactly the main window and `expected_windows` and inside the screen, hands the dialog to `inspect`, and closes it. Returns what
    `inspect` returned; raises when nothing opened (it cannot block then: `press` has returned)."""
    box: dict[str, object] = {}
    timer = QTimer()
    end = time.time() + timeout

    def look() -> None:
        dialog = QApplication.activeModalWidget() or QApplication.activePopupWidget()
        if dialog is None:
            if time.time() > end:
                box["error"] = "no dialog or popup appeared within %.0f s" % timeout
                timer.stop()
            return
        timer.stop()
        try:
            problem = windows_problem([MAIN_WINDOW, *expected_windows])
            if problem:
                raise AssertionError(problem)
            box["value"] = inspect(dialog)
        # the dialog must be closed whatever went wrong, or exec() never returns
        except Exception as error:  # noqa: BLE001
            box["error"] = "%s: %s" % (type(error).__name__, error)
        dialog.close()

    timer.timeout.connect(look)
    timer.start(50)
    EXPECT_DIALOG[0] = True
    try:
        press()
    finally:
        EXPECT_DIALOG[0] = False
        timer.stop()
    if "error" in box:
        raise AssertionError(box["error"])
    if "value" not in box:
        raise AssertionError("the control opened no dialog or popup")
    return box["value"]


def scroll_to(widget: Any, native: QWidget) -> None:
    """Scroll the form so that a control is in view, as a person does before clicking it."""
    widget.form_scroll.ensureWidgetVisible(native)
    pump(0.1)

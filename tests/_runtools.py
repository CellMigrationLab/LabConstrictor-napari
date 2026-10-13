"""Shared helpers of the retention and run-identity tests (import after `_paths` and `_harness`): the test app, a prune recorder,
barrier files, marker readers. Not a test (CI runs only test_*.py)."""

import json
import os
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import _paths
from _harness import expect, pump, widget
from qtpy.QtWidgets import QApplication

from napari_labconstrictor import _retention

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from threading import Thread
    from typing import Any

HOME = _paths.HOME
WORK = Path(tempfile.mkdtemp(prefix="lcrun_work_"))
APP = "runapp"
CREATED = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")

_qa = QApplication.instance()


def register_app() -> None:
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "labconstrictor_tools", "register", "--name", APP, "--prefix", sys.prefix,
         "--module", "lctest_runapp", "--pythonpath", str(Path(__file__).resolve().parent), "--version", "0.0"],
        check=True, capture_output=True,
    )  # fmt: skip
    widget.rescan()


register_app()


def pick(tool_label: str, app: str = APP) -> None:
    widget.app_box.value = app
    pump(0.1)
    widget.tool_box.value = tool_label
    pump(0.4)


def wait_done(timeout: float = 120) -> "Any":
    """Wait until the run that was started has ended and its results are handled (the done slot runs inside processEvents)."""
    end = time.time() + timeout
    while (widget.last_task is None or widget.task is not widget.last_task) and time.time() < end:
        _qa.processEvents()
        time.sleep(0.02)
    pump(0.05)
    return widget.last_task


def start() -> None:
    widget.last_task = None
    widget.gui()


def quick_run(timeout: float = 120) -> "Any":
    start()
    return wait_done(timeout)


def wait_until(condition: "Callable[[], object]", timeout: float = 60) -> object:
    end = time.time() + timeout
    while not condition() and time.time() < end:
        _qa.processEvents()
        time.sleep(0.02)
    return condition()


def new_gate() -> Path:
    return WORK / ("gate_%d_%d" % (os.getpid(), time.time_ns()))


def release(gate: str | Path) -> None:
    Path(gate).write_text("go", encoding="utf-8")


def folders(root: str) -> list[Path]:
    base = HOME / root
    return sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []


def text_of(path: str | Path) -> str | None:
    """The text of a file, or None when it is gone (a failed check, not a crash)."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


def read_json(path: str | Path) -> "Any":
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ the prune recorder (the subprocess is replaced, never the host code)
RECORDER = WORK / "prune_recorder.py"
RECORDER.write_text(
    "import json, os, sys, time\n"
    "from pathlib import Path\n"
    "home = Path(os.environ['LC_HOME'])\n"
    "state = {}\n"
    "for root in ('runs', 'results'):\n"
    "    base = home / root\n"
    "    for p in (sorted(base.iterdir()) if base.is_dir() else []):\n"
    "        if p.is_dir():\n"
    "            done = p / '.lc-done.json'\n"
    "            state[root + '/' + p.name] = {'owner': (p / '.lc-owner.json').is_file(),\n"
    "                'done': json.loads(done.read_text())['status'] if done.is_file() else None}\n"
    "time.sleep(float(os.environ.get('LC_TEST_PRUNE_SLEEP', '0')))\n"
    "with open(sys.argv[1], 'a') as f:\n"
    "    f.write(json.dumps({'argv': sys.argv[2:], 'state': state}) + '\\n')\n",
    encoding="utf-8",
)
RECORD = WORK / "prune_calls.jsonl"
_real_argv = _retention.prune_argv


def use_recorder() -> None:
    """Replace the `prune` command by the recorder; it logs its arguments and which folders had owner / done markers when it started."""
    _retention.prune_argv = lambda python: [sys.executable, str(RECORDER), str(RECORD), *_real_argv(python)]


def use_command(argv: "Sequence[str]") -> None:
    _retention.prune_argv = lambda python: list(argv)


def use_real() -> None:
    _retention.prune_argv = _real_argv


def calls() -> "list[Any]":
    return [json.loads(line) for line in RECORD.read_text().splitlines()] if RECORD.exists() else []


def join_prune(timeout: float = 120) -> "Thread":
    thread = widget.last_prune
    if thread is not None:
        thread.join(timeout)
    return thread


# ------------------------------------------------------------------ markers
def valid_owner(folder: str | Path, kind: str, markers: "dict[str, Any]") -> list[str]:
    """The owner marker of `folder` against the field list of conformance.json; returns (problems)."""
    problems = []
    path = Path(folder) / markers["owner_file"]
    if not path.is_file():
        return ["no %s" % markers["owner_file"]]
    data = read_json(path)
    if sorted(data) != sorted(markers["owner_fields"]):
        problems.append("fields %s" % sorted(data))
    if type(data.get("lc_marker")) is not int or data.get("lc_marker") != 1:
        problems.append("lc_marker %r" % data.get("lc_marker"))
    if data.get("kind") != kind:
        problems.append("kind %r" % data.get("kind"))
    if data.get("name") != Path(folder).name:
        problems.append("name %r" % data.get("name"))
    if data.get("host") != "napari" or data.get("host") not in markers["hosts"]:
        problems.append("host %r" % data.get("host"))
    if data.get("pid") != os.getpid():
        problems.append("pid %r" % data.get("pid"))
    if not isinstance(data.get("created"), str) or not CREATED.match(data["created"]):
        problems.append("created %r" % data.get("created"))
    if not isinstance(data.get("token"), str) or not re.match(r"^[A-Za-z0-9_-]{8,64}$", data["token"]):
        problems.append("token %r" % data.get("token"))
    return problems


def done_status(folder: str | Path, markers: "dict[str, Any]") -> str | None:
    """The status in `.lc-done.json` of `folder`; None when there is no done file; 'INVALID' when its fields are wrong."""
    path = Path(folder) / markers["done_file"]
    if not path.is_file():
        return None
    data = read_json(path)
    if sorted(data) != sorted(markers["done_fields"]) or data.get("status") not in markers["done_statuses"]:
        return "INVALID"
    if not CREATED.match(str(data.get("finished"))):
        return "INVALID"
    return data["status"]


def make_owned(
    root: str | Path, kind: str, count: int, prefix: str, done: bool = True, base_year: int = 2020
) -> None:
    import json

    for i in range(count):
        name = "%s%04d_old_x" % (prefix, i)
        folder = HOME / root / name
        folder.mkdir(parents=True)
        (folder / "sentinel.txt").write_text("keep-" + name, encoding="utf-8")
        owner = {"lc_marker": 1, "kind": kind, "name": name, "host": "napari", "pid": 1,
                 "created": "%d-01-01T00:%02d:%02d.000Z" % (base_year, i // 60, i % 60), "token": "t" + uuid.uuid4().hex[:20]}  # fmt: skip
        (folder / ".lc-owner.json").write_text(json.dumps(owner))
        if done:
            (folder / ".lc-done.json").write_text(
                json.dumps({"finished": "2020-01-02T00:00:00.000Z", "status": "ok"})
            )


__all__ = ["expect"]

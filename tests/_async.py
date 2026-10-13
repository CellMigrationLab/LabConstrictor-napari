"""Shared helpers of the async-lookup tests (import after `_paths`; the GUI tests also after `_harness`). Not a test.

The expectations come from the ASY fixtures of conformance.json (SPEC_WRONG_SCIENCE 5.7): `case(id, sequence)` returns the fixture
and fails if its sequence is no longer the one the test was written for, so a spec change is noticed instead of silently ignored.
"""

import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import _paths  # noqa: F401  (must come first)
from labconstrictor_tools import conformance

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from napari_labconstrictor._lookups import Lookup, Reply

HERE = Path(__file__).resolve().parent
WORK = Path(tempfile.mkdtemp(prefix="lcasy_work_"))
CASES = {f["id"]: f for f in conformance.load()["wrong_science"]["async_lookups"]["fixtures"]}


def case(case_id: str, sequence_starts: str) -> "dict[str, Any]":
    fixture = CASES[case_id]
    if not fixture["sequence"].startswith(sequence_starts):
        raise SystemExit("fixture %s changed: %r" % (case_id, fixture["sequence"]))
    return fixture


def register(name: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "labconstrictor_tools", "register", "--name", name, "--prefix", sys.prefix,
         "--module", "lctest_async", "--pythonpath", str(HERE), "--version", "0.0"],
        check=True, capture_output=True,
    )  # fmt: skip


def folder(label: str) -> Path:
    path = Path(tempfile.mkdtemp(prefix="lcasy_%s_" % label, dir=WORK))
    return path


def started(path: str | Path, name: str) -> bool:
    return (Path(path) / ("started_" + name)).exists()


def release(path: str | Path) -> None:
    (Path(path) / "release").write_text("go", encoding="utf-8")


def alive(pid: int) -> bool:
    """Is the process running? Never signals it (on Windows `os.kill(pid, 0)` would terminate it); a zombie counts as gone."""
    import psutil  # a dependency of napari

    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def live_threads(*names: str) -> list[str]:
    return [t.name for t in threading.enumerate() if t.name in names and t.is_alive()]


class Gate:
    """A stand-in for `_lookups.execute` whose answer the test gives: each call blocks until the test releases it (deterministic
    barriers, no clock): `calls[i]` has the lookup (`job`), `started` (set when it began) and `release` (the test sets it).
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def __call__(self, job: "Lookup", workers: "Any", **_: object) -> "Reply":
        entry: dict[str, Any] = {
            "job": job,
            "started": threading.Event(),
            "release": threading.Event(),
            "reply": None,
        }
        with self._lock:
            self.calls.append(entry)
        entry["started"].set()
        entry["release"].wait(60)
        return entry["reply"]

    def count(self) -> int:
        with self._lock:
            return len(self.calls)

    def answer(self, index: int, reply: "Reply") -> None:
        self.calls[index]["reply"] = reply
        self.calls[index]["release"].set()


def wait_for(
    condition: "Callable[[], object]", pump: "Callable[[float], object]", timeout: float = 60
) -> object:
    end = time.time() + timeout
    while not condition() and time.time() < end:
        pump(0.02)
    return condition()


def counting(client_module: "Any") -> "tuple[list[tuple[str, int, float]], type[Any]]":
    """Replace `WorkerProcess` by a subclass that remembers every process started: returns the list [(app, pid, time)] and a hook
    (`Counting.before_start`, an Event-like with `.wait()`) that a test can use to hold a worker while it starts.
    """
    started: list[tuple[str, int, float]] = []

    class Counting(client_module.WorkerProcess):
        entered = threading.Event()
        gate: threading.Event | None = None  # an Event: the constructor waits for it

        def __init__(self, app: str, *a: object, **k: object) -> None:
            Counting.entered.set()
            if Counting.gate is not None:
                Counting.gate.wait(60)
            super().__init__(app, *a, **k)
            started.append((app, self.proc.pid, time.time()))

    client_module.WorkerProcess = Counting
    return started, Counting

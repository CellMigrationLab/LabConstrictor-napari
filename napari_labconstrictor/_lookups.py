"""Background ChoicesFrom lookups (SPEC_WRONG_SCIENCE 5): identity, one bounded queue, one thread, and the job that talks to a worker.

Nothing here touches a Qt object. A job carries plain data in, and a `Reply` (plain data) goes out; the widget decides on the
main thread whether the reply still applies and is the only code that sets a control, a tooltip or the status line.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from labconstrictor_tools import log
from labconstrictor_tools.protocol import JOB_DIR_KEY

from . import _retention

LOOKUP_TIMEOUT_S = 60.0  # a lookup running longer is cancelled and its worker discarded (5.4)
MAX_PENDING = 8  # lookups waiting in all; beyond it the oldest is dropped (5.4)
CANCEL_GRACE_S = 3.0  # a tool gets this long to honour a cancel before its worker is killed
POLL_S = 0.05  # how often a running lookup looks at its cancel flag
THREAD_NAME = "lc-lookups"

_gen_lock = threading.Lock()
_gen = 0


def next_form_gen() -> int:
    """A process-wide, never reset, increasing number: a form is built or destroyed, and every older reply is void (5.1)."""
    global _gen
    with _gen_lock:
        _gen += 1
        return _gen


def snapshot_deps(values: dict[str, Any] | None) -> str | None:
    """The serialised values a lookup depends on (None while a needed value is missing)."""
    return None if values is None else json.dumps(values, sort_keys=True, default=str)


@dataclass(eq=False)
class Lookup:
    """One question to a source tool, with everything that identifies it (5.1)."""

    form_gen: int
    app: str
    tool: str  # the tool whose form asked
    param: str
    deps: str | None
    request_id: int
    source: str  # the source tool that answers
    output: str  # the output value of the source tool that holds the list
    inputs: dict[str, Any]
    cancelled: threading.Event = field(default_factory=threading.Event)
    reason: str = ""  # why it was cancelled: "timeout", "superseded" or "closed"
    worker: Any = None  # the worker running it, so that a stuck shutdown can kill it

    def cancel(self, reason: str = "superseded") -> None:
        if not self.cancelled.is_set():
            self.reason = reason
            self.cancelled.set()


@dataclass
class Reply:
    lookup: Lookup
    options: list[str] | None
    problem: str = (
        ""  # why there are no options (the text field stays); empty when the answer was an ordinary "none"
    )


class LookupQueue:
    """One thread, one lookup in flight, one pending slot per parameter, at most `max_pending` slots (5.4, 5.6)."""

    def __init__(self, run: Callable[[Lookup], None], max_pending: int = MAX_PENDING) -> None:
        self._run = run
        self._max_pending = max_pending
        self._cond = threading.Condition()
        self._pending: dict[str, Lookup] = {}
        self._current: Lookup | None = None
        self._thread: threading.Thread | None = None
        self._closed = False
        self._held = False
        self.dropped = 0  # lookups dropped because more than `max_pending` were waiting
        self.peak_in_flight = 0  # the most lookups in flight at once, and waiting at once, since the queue was made (a diagnostic)
        self.peak_pending = 0

    # -- state (any thread) --
    @property
    def busy(self) -> bool:
        with self._cond:
            return bool(self._pending) or self._current is not None

    def counts(self) -> tuple[int, int]:
        """(in flight, pending)"""
        with self._cond:
            return (1 if self._current is not None else 0, len(self._pending))

    def thread_alive(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    # -- control --
    def submit(self, job: Lookup) -> list[Lookup]:
        """Queue `job`; it replaces the pending one of its parameter. Returns the lookups dropped for lack of room (none when closed)."""
        overflow: list[Lookup] = []
        with self._cond:
            if self._closed:
                return overflow
            superseded = self._pending.pop(job.param, None)
            if superseded is not None:
                superseded.cancel("superseded")
            self._pending[job.param] = job
            while len(self._pending) > self._max_pending:
                oldest = next(iter(self._pending))
                dropped = self._pending.pop(oldest)
                dropped.cancel("superseded")
                overflow.append(dropped)
                self.dropped += 1
                log.warning("napari: too many choice lookups waiting; dropped the oldest (%s)", oldest)
            self.peak_pending = max(self.peak_pending, len(self._pending))
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name=THREAD_NAME, daemon=True)
                self._thread.start()
            self._cond.notify_all()
        return overflow

    def drop(self, param: str) -> None:
        """Forget the pending lookup of `param` and cancel it if it is the one in flight."""
        with self._cond:
            job = self._pending.pop(param, None)
            if job is not None:
                job.cancel("superseded")
            if self._current is not None and self._current.param == param:
                self._current.cancel("superseded")

    def drop_all(self, reason: str = "superseded") -> None:
        with self._cond:
            for job in self._pending.values():
                job.cancel(reason)
            self._pending.clear()
            if self._current is not None:
                self._current.cancel(reason)

    def hold(self, held: bool) -> None:
        """While a run owns the worker, no pending lookup starts (5.5)."""
        with self._cond:
            self._held = held
            self._cond.notify_all()

    def close(self, timeout: float = 10.0, final: bool = False) -> None:
        """Shutdown (5.6): no new work, pending dropped, the one in flight cancelled, the thread joined (its worker killed if it hangs).
        Without `final` the queue accepts work again once this returns (a closed widget can still be used)."""
        with self._cond:
            self._closed = True
            for job in self._pending.values():
                job.cancel("closed")
            self._pending.clear()
            current, thread = self._current, self._thread
            if current is not None:
                current.cancel("closed")
            self._cond.notify_all()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
            if thread.is_alive() and current is not None and current.worker is not None:
                log.warning("napari: a choice lookup did not stop in %s s; killing its worker", timeout)
                try:
                    current.worker.kill()
                except Exception:  # noqa: BLE001 - best effort while closing
                    log.error("napari: could not kill the worker of a choice lookup", exc_info=True)
                thread.join(2.0)
        with self._cond:
            self._closed = final

    def reopen(self) -> None:
        with self._cond:
            self._closed = False

    # -- the thread --
    def _loop(self) -> None:
        while True:
            with self._cond:
                while not self._closed and (not self._pending or self._held):
                    self._cond.wait()
                if self._closed:
                    return
                param = next(iter(self._pending))
                job = self._pending.pop(param)
                self._current = job
                self.peak_in_flight = max(self.peak_in_flight, 1)
            try:
                self._run(job)
            except Exception:  # noqa: BLE001 - the thread must outlive one bad lookup
                log.error("napari: a choice lookup failed unexpectedly", exc_info=True)
            finally:
                with self._cond:
                    self._current = None
                    self._cond.notify_all()


def execute(
    job: Lookup,
    workers: Any,
    timeout_s: float = LOOKUP_TIMEOUT_S,
    grace_s: float = CANCEL_GRACE_S,
) -> Reply:
    """Ask the source tool and wait for the answer, or for a cancel (superseded, shutdown) or the time limit. Never raises."""
    options: list[str] | None = None
    problem = ""
    worker = None
    job_dir = tempfile.mkdtemp(prefix="lcchoices_")
    healthy = False
    try:
        if job.cancelled.is_set():
            return Reply(job, None, _cancelled_text(job, timeout_s))
        worker = workers.acquire(job.app, reuse=True)
        job.worker = worker
        task = worker.task(job.source, {**job.inputs, JOB_DIR_KEY: job_dir})
        started = time.monotonic()
        cancel_sent_at: float | None = None
        killed = False
        while not task.done.wait(POLL_S):
            now = time.monotonic()
            if job.reason != "timeout" and now - started > timeout_s and not job.cancelled.is_set():
                job.cancel("timeout")
            if job.cancelled.is_set():
                if cancel_sent_at is None:
                    cancel_sent_at = now
                    task.cancel(grace=None)  # the escalation is below: this thread is the only one that waits
                elif not killed and now - cancel_sent_at > grace_s:
                    killed = True
                    worker.kill()
        # a worker whose tool answered or acknowledged a cancel is idle again and is kept; one that timed out, was killed or crashed is not
        healthy = task.status in ("COMPLETE", "FAILED") or (
            task.status == "CANCELED" and job.reason != "timeout"
        )
        if task.status == "COMPLETE" and not job.cancelled.is_set():
            for result in task.outputs["results"]:
                values = result.get("values", {}) if isinstance(result, dict) else {}
                if isinstance(values.get(job.output), list):
                    options = [str(v) for v in values[job.output]]
                    break
        if options is None:  # intended fallback (the text field stays), but never a silent one
            if job.cancelled.is_set() or task.status == "CANCELED":
                problem = _cancelled_text(job, timeout_s)
            else:
                log.warning(
                    "napari: %s gave no list for %r (status %s); using a text field",
                    job.source,
                    job.output,
                    task.status,
                )
                problem = "%s gave no choices for %s" % (job.source, job.param)
    # BLE001: isolation boundary - any worker failure must leave the text field usable
    except Exception:  # noqa: BLE001
        log.error("napari: could not ask %s for choices", job.source, exc_info=True)
        problem = (
            _cancelled_text(job, timeout_s)
            if job.cancelled.is_set()
            else ("could not get the choices for %s (see the log)" % job.param)
        )
    finally:
        job.worker = None
        if worker is not None:
            try:
                workers.release(job.app, worker, keep=healthy and worker.alive)
            except Exception:  # noqa: BLE001
                log.error("napari: could not hand the worker back", exc_info=True)
        _retention.discard_job_dir(job_dir)
    return Reply(job, options, problem)


def _cancelled_text(job: Lookup, timeout_s: float) -> str:
    if job.reason == "timeout":
        return "the choices for %s took more than %d s and were cancelled" % (job.param, timeout_s)
    return "the choices for %s were cancelled" % job.param

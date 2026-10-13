"""Keep one worker per app alive between runs (a repeat run of a heavy tool is typically seconds instead of tens of seconds), and never leak them.

One lock guards the cache (SPEC_WRONG_SCIENCE 5.5): the main thread (reaper, run end, restart), the lookup thread and the close path
all go through it. Slow work (starting or closing a process) happens outside the lock, on a worker that no other thread can reach.
"""

from __future__ import annotations

import atexit
import threading
import time

from labconstrictor_tools import client

IDLE_SECONDS = 600  # an unused worker (and the memory its imports hold) is closed after this long
CLOSE_TIMEOUT_S = 10  # how long a worker gets to exit politely when closed, before it is killed (PROTOCOL.md: the worker exits within 10 s)


class CacheClosed(RuntimeError):
    """`acquire` met a `shutdown`: the widget was closed (while the worker started, or for good), no worker may outlive it."""


class WorkerCache:
    """Workers kept per app between runs; `acquire`/`release` hand one out and take it back, `close_all` runs at exit.

    Every worker is owned by exactly one party: the idle cache (`_workers`), the job that acquired it (`_active`), or nobody (closed).
    """

    def __init__(self, idle_seconds: float = IDLE_SECONDS) -> None:
        self.idle_seconds = idle_seconds
        self._lock = threading.RLock()
        self._workers: dict[str, list] = (
            {}
        )  # app name -> [WorkerProcess, last_used]  (idle, ready for the next run)
        self._active: set = set()  # workers handed out by acquire() and not released yet
        self._claimed: set = (
            set()
        )  # active workers that close_all closed: their job's later release() must not close them again
        self._epoch = 0  # advanced by every shutdown(): a worker started before it, and finished after, is closed by its maker
        self._closed = False  # set by shutdown(final=True): from then on acquire() refuses
        atexit.register(self.close_all)

    def acquire(self, app: str, reuse: bool = True) -> client.WorkerProcess:
        """A running worker for `app`: the cached one if allowed and still alive, otherwise a new one."""
        with self._lock:
            if self._closed:
                raise CacheClosed("the widget is closed")
            epoch = self._epoch
            cached = self._workers.pop(app, None)
            if cached and cached[0].alive and reuse:
                self._active.add(cached[0])
                return cached[0]
        if cached:
            cached[0].close(timeout=CLOSE_TIMEOUT_S)
        worker = client.WorkerProcess(app)  # slow: outside the lock
        with self._lock:
            if not self._closed and epoch == self._epoch:
                self._active.add(worker)
                return worker
        worker.close(
            timeout=CLOSE_TIMEOUT_S
        )  # shutdown happened while it started: the thread that made it closes it (5.6)
        raise CacheClosed("the widget was closed while a worker was starting")

    def release(self, app: str, worker: client.WorkerProcess, keep: bool) -> None:
        """Hand the worker back after a run. Only healthy workers are kept."""
        displaced = None
        with self._lock:
            self._active.discard(worker)
            if worker in self._claimed:  # close_all already closed it: not cached, not closed twice
                self._claimed.discard(worker)
                return
            if keep and worker.alive and not self._closed:
                cached = self._workers.get(
                    app
                )  # a second worker for the same app was kept meanwhile: do not leak it
                if cached and cached[0] is not worker:
                    displaced = cached[0]
                self._workers[app] = [worker, time.monotonic()]
                worker = None
        if displaced is not None:
            displaced.close(timeout=CLOSE_TIMEOUT_S)
        if worker is not None and worker.alive:
            worker.close(timeout=CLOSE_TIMEOUT_S)

    def discard(self, app: str) -> None:
        """Close and forget the idle worker of `app`, if any."""
        with self._lock:
            cached = self._workers.pop(app, None)
        if cached:
            cached[0].close(timeout=CLOSE_TIMEOUT_S)

    def reap_idle(self) -> None:
        """Close the workers that have been idle longer than `idle_seconds`."""
        now = time.monotonic()
        with self._lock:
            stale = [a for a, (_, used) in self._workers.items() if now - used > self.idle_seconds]
        for app in stale:
            self.discard(app)

    def close_all(self) -> None:
        with self._lock:
            idle = [entry[0] for entry in self._workers.values()]
            self._workers.clear()
            running = list(self._active)  # also the ones that are running a task right now
            self._active.clear()
            self._claimed.update(running)
        for worker in idle + running:
            worker.close(timeout=CLOSE_TIMEOUT_S)

    def shutdown(self, final: bool = False) -> None:
        """The widget is closed: close everything, and close any worker that is just being started (5.6). With `final` (the widget is
        deleted) no worker is handed out again until `reopen`; otherwise the cache is usable at once (a closed widget can still be used).
        """
        with self._lock:
            self._epoch += 1
            self._closed = final
        self.close_all()

    def reopen(self) -> None:
        with self._lock:
            self._closed = False

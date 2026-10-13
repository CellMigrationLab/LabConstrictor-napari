"""ASY-08 and the shutdown / bounded-work rules of SPEC_WRONG_SCIENCE 5.4-5.6, without a GUI: the worker cache and the lookup queue
with fake workers, driven by barriers (events the test sets), so that the interleavings are forced and not hoped for.
"""

import json
import sys
import threading
import time
from typing import ClassVar

import _async
import _paths  # noqa: F401  (must come first)

from napari_labconstrictor import _lookups, _workers
from napari_labconstrictor._lookups import Lookup, LookupQueue

report, failures = {}, []


def expect(name, condition, detail=""):
    report[name] = bool(condition)
    if not condition:
        failures.append("%s %s" % (name, detail))


class FakeWorker:
    """Counts its closes; `close` can be held on an event (a close that takes a while)."""

    made: ClassVar[list] = []
    hold_close = None  # an Event: close() waits for it
    closing = None  # an Event set when a close has begun
    build_gate = None  # an Event: the constructor waits for it
    building = None  # an Event set when a constructor has begun

    def __init__(self, app):
        if FakeWorker.building is not None:
            FakeWorker.building.set()
        if FakeWorker.build_gate is not None:
            FakeWorker.build_gate.wait(30)
        self.app, self.alive, self.closes, self.killed = app, True, 0, False
        self.state = threading.Lock()
        FakeWorker.made.append(self)

    def close(self, timeout=None):
        with self.state:
            self.closes += 1
        if FakeWorker.closing is not None:
            FakeWorker.closing.set()
        if FakeWorker.hold_close is not None:
            FakeWorker.hold_close.wait(30)
        self.alive = False

    def kill(self):
        self.killed = True
        self.alive = False


def reset():
    FakeWorker.made, FakeWorker.hold_close, FakeWorker.closing = [], None, None
    FakeWorker.build_gate = FakeWorker.building = None


_workers.client.WorkerProcess = FakeWorker
_workers.atexit.register = lambda *_a, **_k: None  # the caches of this script are closed by the script


def in_thread(function, *args):
    box = {}

    def target():
        try:
            box["value"] = function(*args)
        except BaseException as error:  # noqa: BLE001 - reported by the test
            box["error"] = error

    thread = threading.Thread(target=target)
    thread.start()
    return thread, box


# ---- ASY-08 ------------------------------------------------------------------------------------------------------------------
_async.case("ASY-08", "interleave acquire/release/reap/close from three threads")

# (1) a worker is being closed by close_all while its job hands it back: the job must not close it a second time, nor cache it
reset()
cache = _workers.WorkerCache()
worker = cache.acquire("a")
FakeWorker.hold_close, FakeWorker.closing = threading.Event(), threading.Event()
closer, _ = in_thread(cache.close_all)
FakeWorker.closing.wait(30)  # close_all is inside worker.close() now
releaser, _ = in_thread(cache.release, "a", worker, False)
releaser.join(10)
FakeWorker.hold_close.set()
closer.join(10)
expect("ASY-08 release during close_all: closed once", worker.closes == 1, worker.closes)
expect(
    "ASY-08 release during close_all: not cached",
    not cache._workers and not cache._active,
    (cache._workers, cache._active),
)

# (2) the same with keep=True, after the close finished: not cached either
reset()
cache = _workers.WorkerCache()
worker = cache.acquire("a")
cache.close_all()
cache.release("a", worker, True)
expect(
    "ASY-08 a closed worker is not cached on release",
    not cache._workers and worker.closes == 1,
    (cache._workers, worker.closes),
)

# (3) two threads ask for the one cached worker at the same time: it is owned once
reset()
cache = _workers.WorkerCache()
first = cache.acquire("a")
cache.release("a", first, True)
FakeWorker.build_gate, FakeWorker.building = threading.Event(), threading.Event()
t1, b1 = in_thread(cache.acquire, "a")
t2, b2 = in_thread(cache.acquire, "a")
FakeWorker.building.wait(30)  # the loser is creating its own worker
FakeWorker.build_gate.set()
t1.join(10)
t2.join(10)
got = [b1.get("value"), b2.get("value")]
expect(
    "ASY-08 a cached worker is handed out once",
    len({id(x) for x in got}) == 2 and first in got and len(cache._active) == 2,
    got,
)
cache.close_all()

# (4) three threads against one cache, released together by a barrier, many rounds: nothing is closed twice, nothing handed out is
# closed under its job, and after the last close every worker that was made is closed exactly once
reset()
cache = _workers.WorkerCache(idle_seconds=0)
rounds = 150
barrier = threading.Barrier(3)
held, problems = set(), []
held_lock = threading.Lock()


def job():
    for _ in range(rounds):
        barrier.wait(30)
        try:
            w = cache.acquire("a")
        except _workers.CacheClosed:
            continue
        with held_lock:
            if w in held:
                problems.append("handed out twice")
            held.add(w)
        if w.closes:
            problems.append("handed out after a close")
        with held_lock:
            held.discard(w)
        cache.release("a", w, True)


def reaper():
    for _ in range(rounds):
        barrier.wait(30)
        cache.reap_idle()


def closer_thread():
    for i in range(rounds):
        barrier.wait(30)
        if i % 3 == 0:
            cache.close_all()
        elif i % 3 == 1:
            cache.discard("a")


threads = [threading.Thread(target=f) for f in (job, reaper, closer_thread)]
[t.start() for t in threads]
[t.join(120) for t in threads]
cache.close_all()
twice = [w for w in FakeWorker.made if w.closes > 1]
leaked = [w for w in FakeWorker.made if w.closes == 0]
expect("ASY-08 three threads: no double close", not twice, len(twice))
expect(
    "ASY-08 three threads: every worker ends closed, none leaked",
    not leaked and not cache._workers and not cache._active,
    len(leaked),
)
expect("ASY-08 three threads: no worker handed out twice or after its close", not problems, problems[:3])

# ---- 5.6: a worker that is being created when the widget closes is closed by the thread that created it -------------------------
reset()
cache = _workers.WorkerCache()
FakeWorker.build_gate, FakeWorker.building = threading.Event(), threading.Event()
t, box = in_thread(cache.acquire, "a")
FakeWorker.building.wait(30)
cache.shutdown()
FakeWorker.build_gate.set()
t.join(10)
made = FakeWorker.made[0]
expect(
    "ASY-07 a worker created after close does not survive",
    isinstance(box.get("error"), _workers.CacheClosed)
    and made.closes == 1
    and not made.alive
    and not cache._active,
    (box, made.closes),
)
expect("ASY-07 after a close the cache is usable again", cache.acquire("a").alive)
cache.shutdown(final=True)
try:
    cache.acquire("a")
    refused = False
except _workers.CacheClosed:
    refused = True
expect("ASY-07 a deleted widget's cache hands out no worker", refused)
cache.reopen()
expect("ASY-07 a reopened cache works again", cache.acquire("a").alive)
cache.close_all()


# ---- 5.4: bounded work ------------------------------------------------------------------------------------------------------------
def make_job(param, request_id=1):
    return Lookup(1, "app", "tool", param, None, request_id, "src", "choices", {})


_async.case("ASY-04", "change a dependency 50 times in 1 s")
ran, enter, leave = [], threading.Event(), threading.Event()


def slow_run(job):
    ran.append(job.request_id)
    enter.set()
    leave.wait(30)


queue = LookupQueue(slow_run)
queue.submit(make_job("mode", 0))
enter.wait(30)
for i in range(1, 51):
    queue.submit(make_job("mode", i))
expect(
    "ASY-04 50 requests: one in flight, one pending for the parameter",
    queue.counts() == (1, 1),
    queue.counts(),
)
expect(
    "ASY-04 50 requests: one thread",
    len(_async.live_threads(_lookups.THREAD_NAME)) == 1,
    _async.live_threads(_lookups.THREAD_NAME),
)
leave.set()
queue.close()
expect(
    "ASY-04 peaks stay at one in flight and one pending",
    queue.peak_in_flight == 1 and queue.peak_pending == 1,
    (queue.peak_in_flight, queue.peak_pending),
)

ran, enter, leave = [], threading.Event(), threading.Event()
queue = LookupQueue(slow_run)
queue.submit(make_job("mode", 0))
enter.wait(30)
for i in range(1, 51):
    queue.submit(make_job("mode", i))
enter.clear()
leave.set()
_async.wait_for(lambda: not queue.busy, lambda s: enter.wait(s))
expect("ASY-04 the newest request replaced the older ones", ran == [0, 50], ran)
queue.close()

ran, enter, leave = [], threading.Event(), threading.Event()
queue = LookupQueue(slow_run)
queue.submit(make_job("p0"))
enter.wait(30)
overflow = []
for i in range(1, 13):
    overflow += queue.submit(make_job("p%d" % i))
expect(
    "ASY-04 at most 8 pending, the oldest told",
    queue.counts() == (1, 8)
    and [j.param for j in overflow] == ["p1", "p2", "p3", "p4"]
    and queue.dropped == 4,
    (queue.counts(), [j.param for j in overflow]),
)
leave.set()
queue.close()

# a run holds the worker: nothing starts until it ends (5.5)
ran, enter, leave = [], threading.Event(), threading.Event()
leave.set()
queue = LookupQueue(slow_run)
queue.hold(True)
queue.submit(make_job("mode", 1))
expect(
    "ASY-06 a lookup waits while a run holds the worker",
    not enter.wait(0.5) and ran == [] and queue.counts() == (0, 1),
    (ran, queue.counts()),
)
queue.hold(False)
expect("ASY-06 and runs when the run ends", enter.wait(30) and ran == [1], ran)
queue.close()

# 5.6: close with a lookup in flight: pending dropped, the one in flight cancelled, the thread gone
enter, flight = threading.Event(), []


def cancellable(job):
    flight.append(job)
    enter.set()
    job.cancelled.wait(30)


queue = LookupQueue(cancellable)
queue.submit(make_job("a", 1))
enter.wait(30)
queue.submit(make_job("b", 2))
queue.close()
expect(
    "ASY-07 close cancels the one in flight, drops the pending, joins the thread",
    flight[0].cancelled.is_set()
    and flight[0].reason == "closed"
    and not queue.thread_alive()
    and queue.counts() == (0, 0)
    and len(flight) == 1,
    (flight, queue.counts()),
)
expect(
    "ASY-07 a queue is usable again after close",
    queue.submit(make_job("c", 3)) == [] and _async.wait_for(lambda: len(flight) == 2, time.sleep),
)
queue.close(final=True)
expect(
    "ASY-07 nothing is accepted after the final close",
    queue.submit(make_job("d", 4)) == [] and queue.counts() == (0, 0) and not queue.thread_alive(),
)

print(json.dumps(report, indent=2))
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)

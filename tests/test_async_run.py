"""ASY-06 (SPEC_WRONG_SCIENCE 5.5): a run keeps its worker to the end; a lookup asked meanwhile, in another app, waits and then runs
in that app's own worker. Real worker processes; the run and the lookup are held by barrier files the test releases.
"""

import _async
import _paths  # noqa: F401  (must come first)
from _harness import expect, finish, pump
from _harness import widget as w

from napari_labconstrictor import _workers

_async.register("asyapp")
_async.register("asyapp2")
w.rescan()
started, Counting = _async.counting(_workers.client)
_async.case("ASY-06", "start a run, switch app, request a lookup")

w.app_box.value = "asyapp"
pump(0.3)
w.tool_box.value = "Slow run"
pump(0.3)
run_dir = _async.folder("run")
w.gui.gate.value = str(run_dir)
w.last_task = None
w.gui()  # Run
_async.wait_for(lambda: (run_dir / "run_started").exists(), pump)
run_worker, run_pid = w.worker, w.worker.proc.pid
expect(
    "ASY-06 the run started in its worker",
    (run_dir / "run_started").exists() and [s[0] for s in started] == ["asyapp"],
    started,
)

w.app_box.value = "asyapp2"  # switch app during the run
pump(0.3)
w.tool_box.value = "Pick one"
pump(0.3)
look = _async.folder("look")
_async.release(look)  # the lookup would end at once if it ran
w.gui.folder.value = str(look)
w._choice_timer.stop()
w._resolve_choices()  # the debounce fires: the run is active
pump(0.8)
expect(
    "ASY-06 the lookup waits while the run is active",
    not _async.started(look, "mode")
    and [s[0] for s in started] == ["asyapp"]
    and "mode" in w._choice_pending
    and w._choice_timer.isActive(),
    (started, w._choice_pending, w._choice_timer.isActive()),
)
expect(
    "ASY-06 the run's worker is untouched",
    w.worker is run_worker and _async.alive(run_pid) and w._workers._active == {run_worker},
    w._workers._active,
)
(run_dir / "run_release").write_text("go", encoding="utf-8")
_async.wait_for(lambda: w.last_task is not None and w.task is w.last_task, pump, 90)
expect(
    "ASY-06 the run used its worker to the end",
    w.last_task is not None and w.last_task.status == "COMPLETE" and w.last_task.worker is run_worker,
    w.last_task and w.last_task.status,
)
w._schedule_choices(0)  # the retry (1500 ms) would do the same; no need to wait for it
ok = _async.wait_for(w.choices_settled, pump, 90)
box = w._choice_boxes["mode"]
expect(
    "ASY-06 the lookup then ran, in the new app's worker",
    ok
    and _async.started(look, "mode")
    and [s[0] for s in started] == ["asyapp", "asyapp2"]
    and list(box.choices) == ["", "m1", "m2"],
    (started, list(box.choices)),
)
finish()

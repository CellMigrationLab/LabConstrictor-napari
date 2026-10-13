"""ASY-01, ASY-02, ASY-03 (SPEC_WRONG_SCIENCE 5.1-5.3): a late answer never reaches a form it was not asked for.

The source lookup is a gate the test releases (no clock): tool A and tool B both have a ChoicesFrom parameter called `mode`,
the checks read what the dropdown, the text field, the tooltips and the status line actually show.
"""

import dataclasses
from typing import TYPE_CHECKING

import _async
import _paths  # noqa: F401  (must come first)
from _harness import expect, finish, pump
from _harness import widget as w

from napari_labconstrictor import _lookups
from napari_labconstrictor._lookups import Reply

if TYPE_CHECKING:
    from magicgui.widgets import Widget

_async.register("asyapp")
w.rescan()
gate = _async.Gate()
_lookups.execute = gate
w.app_box.value = "asyapp"
pump(0.3)


def wait_call(n: int) -> object:
    return _async.wait_for(lambda: gate.count() >= n and gate.calls[n - 1]["started"].is_set(), pump)


def settled() -> object:
    return _async.wait_for(w.choices_settled, pump)


def shown(x: "Widget") -> bool:
    return not x.native.isHidden()


def tooltips() -> list[str]:
    return [x.native.toolTip() for x in w.gui]


# ---- ASY-01: a slow lookup of tool A, switch to tool B (also `mode`), release A -------------------------------------------------
_async.case("ASY-01", "tool A and B both have ChoicesFrom param mode")
w.tool_box.value = "Pick one"
pump(0.3)
dir_a, dir_b = _async.folder("a"), _async.folder("b")
w.gui.folder.value = str(dir_a)
a_started = wait_call(1)
job_a = gate.calls[0]["job"] if gate.count() else None
w.tool_box.value = "Pick other"  # B: its form is new, its first request would have the same number as A's
pump(0.3)
w.gui.folder.value = str(dir_b)
expect(
    "ASY-01 leaving the form cancels the lookup in flight",
    job_a.cancelled.is_set() and job_a.reason == "superseded",
)
gate.answer(0, Reply(job_a, ["a1", "a2"]))  # A's late answer, with A's options
b_started = wait_call(2)  # the queue ran A to its end first, so B's question starts after A's answer was sent
pump(0.3)
job_b = gate.calls[1]["job"] if gate.count() > 1 else None
box = w._choice_boxes["mode"]
expect(
    "ASY-01 a late answer of A does not show in B",
    a_started and b_started and not shown(box) and "a1" not in box.choices,
    list(box.choices),
)
expect("ASY-01 B is pending, its text field shows", "mode" in w._choice_pending and shown(w.gui.mode))
expect(
    "ASY-01 A and B are told apart",
    job_a
    and job_b
    and (job_a.form_gen, job_a.tool) != (job_b.form_gen, job_b.tool)
    and job_a.form_gen < job_b.form_gen,
    (job_a, job_b),
)
gate.answer(1, Reply(job_b, ["b1", "b2"]))
settled()
expect(
    "ASY-01 B shows only B's choices",
    shown(box)
    and not shown(w.gui.mode)
    and list(box.choices) == ["", "b1", "b2"]
    and box.value == ""
    and w.gui.mode.value == "",
    (list(box.choices), box.value, w.gui.mode.value),
)

# ---- ASY-02: the dependency changes, the old answer arrives before the debounce fires ---------------------------------------
_async.case("ASY-02", "change the dependency of mode")
dir_b1, dir_b2 = _async.folder("b1"), _async.folder("b2")
w.gui.folder.value = str(dir_b1)
wait_call(3)
job_old = gate.calls[2]["job"] if gate.count() > 2 else None
w.gui.folder.value = str(dir_b2)  # the old value is void NOW
w._choice_timer.stop()  # the debounce has not fired (a test must not depend on how fast this machine is)
expect(
    "ASY-02 pending at once, no old choices shown",
    "mode" in w._choice_pending and not shown(box) and shown(w.gui.mode),
)
gate.answer(2, Reply(job_old, ["old1"]))
_async.wait_for(lambda: not w._lookups.busy, pump)
pump(0.3)
expect(
    "ASY-02 old answer dropped, mode stays pending",
    "mode" in w._choice_pending and not shown(box) and "old1" not in box.choices,
    (list(box.choices), w._choice_pending),
)
w._schedule_choices(0)  # the debounce fires now
wait_call(4)
job_new = gate.calls[3]["job"] if gate.count() > 3 else None
expect(
    "ASY-02 the new question asks for the new value",
    job_new
    and job_old
    and job_new.request_id > job_old.request_id
    and job_new.inputs == {"folder": str(dir_b2)},
    job_new,
)
gate.answer(3, Reply(job_new, ["new1"]))
settled()
expect(
    "ASY-02 the new answer is shown",
    shown(box) and "new1" in box.choices and "old1" not in box.choices,
    list(box.choices),
)
same_id_old_deps = dataclasses.replace(
    job_new, deps='{"folder": "somewhere else"}'
)  # same request, other values than now
expect(
    "ASY-02 dependencies are recomputed at reply time",
    w._reply_applies(job_new) and not w._reply_applies(same_id_old_deps),
)

# the same values asked twice: the older request is still void (5.2: the newest request for the parameter)
w.gui.folder.value = str(_async.folder("b4"))
w._choice_timer.stop()
n = gate.count()
w._resolve_choices()
wait_call(n + 1)
first_job = gate.calls[n]["job"]
w._resolve_choices()  # nothing changed, but a newer question is asked
gate.answer(n, Reply(first_job, ["first"]))
wait_call(n + 2)
second_job = gate.calls[n + 1]["job"]
pump(0.3)
expect(
    "ASY-02 the older of two requests for the same values is dropped",
    first_job.deps == second_job.deps
    and first_job.request_id < second_job.request_id
    and "first" not in box.choices
    and not shown(box),
    list(box.choices),
)
gate.answer(n + 1, Reply(second_job, ["second"]))
settled()
expect(
    "ASY-02 the newest request is shown",
    shown(box) and "second" in box.choices and "first" not in box.choices,
    list(box.choices),
)
# each part of the identity of a lookup (5.1, 5.2) decides on its own
expect(
    "ASY-02 form, app, tool and request each void a reply on their own",
    w._reply_applies(second_job)
    and not w._reply_applies(dataclasses.replace(second_job, form_gen=second_job.form_gen - 1))
    and not w._reply_applies(dataclasses.replace(second_job, app="elsewhere"))
    and not w._reply_applies(dataclasses.replace(second_job, tool="another tool"))
    and not w._reply_applies(dataclasses.replace(second_job, request_id=second_job.request_id - 1)),
)

# ---- ASY-03: A's lookup fails after the switch to B ---------------------------------------------------------------------------
_async.case("ASY-03", "A's lookup fails after switch to B")
w.tool_box.value = "Pick one"  # A again
pump(0.3)
w.gui.folder.value = str(_async.folder("a2"))
n = gate.count()
wait_call(n + 1)
job_a2 = gate.calls[n]["job"]
w.tool_box.value = "Pick other"
pump(0.3)
w.gui.folder.value = str(_async.folder("b3"))
w.status.setText("")
gate.answer(n, Reply(job_a2, None, "opts_mode gave no choices for mode"))  # A fails, late
wait_call(n + 2)
pump(0.3)
expect(
    "ASY-03 no tooltip or error on any B field",
    all("type the value" not in t and "opts_mode" not in t for t in tooltips())
    and "opts_mode" not in w.status.text()
    and w.status.text() == "",
    (tooltips(), w.status.text()),
)
job_b3 = gate.calls[n + 1]["job"]
gate.answer(
    n + 1, Reply(job_b3, None, "opts_other gave no choices for mode")
)  # B's own failure is said (tooltip and status line)
settled()
expect(
    "ASY-03 a failure of the current lookup is said in the tooltip and the status line",
    "opts_other gave no choices for mode: type the value" in w.gui.mode.native.toolTip()
    and "opts_other gave no choices for mode" in w.status.text()
    and shown(w.gui.mode)
    and not shown(w._choice_boxes["mode"]),
    (w.gui.mode.native.toolTip(), w.status.text()),
)
# the form goes away for one without any lookup: the question in flight is cancelled (5.6), and its answer shows nowhere
w.tool_box.value = "Pick one"
pump(0.3)
n = gate.count()
w.gui.folder.value = str(_async.folder("a3"))
wait_call(n + 1)
job_gone = gate.calls[n]["job"]
w.tool_box.value = "Slow run"
pump(0.3)
expect(
    "ASY-01 a lookup in flight is cancelled when its form goes away",
    job_gone.cancelled.is_set() and job_gone.reason == "superseded" and w.choices_settled() is False,
)
gate.answer(n, Reply(job_gone, ["late"]))
settled()
expect(
    "ASY-01 its late answer shows nowhere",
    not w._choice_boxes and "late" not in str(tooltips()) and "late" not in w.status.text(),
)
# the root of a race a test could lose (a script that waited for the first dropdown read the tooltip of the next field too early):
# "settled" means every question of the form is answered AND applied, and the questions are asked one after the other in form order
w.status.setText("")
w.tool_box.value = "Pick two"
pump(0.3)
n = gate.count()
w.gui.folder.value = str(_async.folder("two"))
wait_call(n + 1)
first = gate.calls[n]["job"]
gate.answer(n, Reply(first, ["m1"]))
wait_call(n + 2)
second = gate.calls[n + 1]["job"]
pump(0.3)
expect(
    "ASY-05 one question after the other, in form order; not settled while one is open",
    (first.param, second.param) == ("mode", "kind")
    and gate.calls[n + 1]["reply"] is None
    and not w.choices_settled()
    and shown(w._choice_boxes["mode"]),
    (first.param, second.param, w.choices_settled()),
)
gate.answer(n + 1, Reply(second, None, "opts_kind gave no choices for kind"))
_async.wait_for(w.choices_settled, pump)
expect(
    "ASY-05 settled means applied: the tooltip and the status line are there at once",
    "opts_kind gave no choices for kind: type the value" in w.gui.kind.native.toolTip()
    and "opts_kind" in w.status.text()
    and w.gui.mode.native.toolTip() == ""
    and shown(w.gui.kind),
    (w.gui.kind.native.toolTip(), w.status.text()),
)
finish()

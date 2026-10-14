"""The run step of the Napari UI audit: press the real Run button with the inputs of a case of the app's lc_tests/cases.json, wait, and
assert the status, the declared results and where they land, the files on disk; the screenshots of the form and after the run. Not a test.

How a case becomes host input: a parameter of type image/labels given as a file name is put into the 'or file' row of its chooser (the
case names fixture files; no layer is made from them), so the calibration source is the TIFF's own tags (ui_audit_place.py); table, file
and folder parameters go into their file pickers; numbers, text, choices and booleans into their widgets (an optional one behind its
'set' box). Cases run on a scratch COPY of lc_tests (a tool that writes into the fixtures cannot dirty the app's folder).

Which case: the first of the tool that expects COMPLETE (no failure, crash or cancel case, no tool named stress_*). Apps whose cases
are an ordered game (GuessTheCondition: prepare_game before play_round) have their earlier COMPLETE cases replayed first, in file order
and once, through the same Run button."""

import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from labconstrictor_tools import testing
from ui_audit_core import (
    MAIN_WINDOW,
    AppCtx,
    Human,
    RunObs,
    fresh_problem,
    pump,
    real_click,
    sanitise,
    scroll_to,
    shoot,
    until,
    windows_problem,
)
from ui_audit_place import Frame, calibration_problems, fixture_scale, open_fixture_layer, placement_problems

CANCEL_WAIT_S = 15.0  # how long a polite tool gets to stop after Cancel, and a killed worker to be reported
NEVER_RUN = (
    "stress_",
    "memory",
    "crash",
    "hang",
)  # tools the app's own extras exercise (never stress_real_memory from here)


def scratch_copy(folder: Path) -> Path:
    """A private copy of the app's lc_tests folder (the cases run there)."""
    target = Path(tempfile.mkdtemp(prefix="lc_ui_audit_tests_")) / folder.name
    shutil.copytree(folder, target)
    return target


def load_cases(folder: Path) -> tuple[list[dict[str, Any]], dict[str, str], str]:
    """(cases, no_case reasons, problem): the problem is the sentence that makes every run check fail (unreadable files)."""
    cases: list[dict[str, Any]] = []
    no_case: dict[str, str] = {}
    problems = []
    try:
        cases = testing.load_cases(folder / "cases.json")
    except (
        OSError,
        ValueError,
    ) as error:  # ValueError covers invalid JSON and the validator's own list of problems
        problems.append("lc_tests/cases.json: %s" % error)
    path = folder / "no_case.json"
    if path.is_file():
        try:
            no_case = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            problems.append("lc_tests/no_case.json: %s" % error)
    return cases, no_case, " | ".join(problems)


def never_run(tool_id: str) -> bool:
    return tool_id.startswith(NEVER_RUN[0]) or any(word in tool_id for word in NEVER_RUN[1:])


def completes(case: dict[str, Any]) -> bool:
    return (
        case.get("expect", {}).get("status", "COMPLETE") == "COMPLETE"
        and "cancel_after_s" not in case
        and not case.get("skip")
    )


def choose_case(ctx: AppCtx, tool_id: str) -> tuple[int, dict[str, Any]]:
    """(index, case): the first COMPLETE case of the tool. Human for a tool that has none by design; an assertion for one with neither."""
    if ctx.case_problem:
        raise AssertionError(ctx.case_problem)
    if never_run(tool_id):
        raise Human("%s is a stress tool: the app's own extras run it, the UI audit never does" % tool_id)
    own = [(i, c) for i, c in enumerate(ctx.cases) if c["tool"] == tool_id]
    if not own:
        if tool_id in ctx.no_case:
            raise Human("declared in no_case.json, form checks only: %s" % ctx.no_case[tool_id])
        raise AssertionError("no case in cases.json and no reason in no_case.json for the tool %r" % tool_id)
    found = next(((i, c) for i, c in own if completes(c)), None)
    if found is None:
        raise Human(
            "the cases of %s expect failure, cancel or a skip: none completes, so nothing is shown to check"
            % tool_id
        )
    return found


def tool_of(ctx: AppCtx, tool_id: str) -> dict[str, Any]:
    return next(t for t in ctx.schema["tools"] if t["id"] == tool_id)


def tool_order(ctx: AppCtx) -> list[dict[str, Any]]:
    """The tools in the order of their chosen case in cases.json (the order a stateful app needs); tools without one last."""

    def key(tool: dict[str, Any]) -> tuple[int, int]:
        try:
            return 0, choose_case(ctx, tool["id"])[0]
        except (Human, AssertionError):
            return 1, 0

    return sorted(ctx.schema["tools"], key=key)


def fill_inputs(
    ctx: AppCtx, tool: dict[str, Any], case: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Frame]]:
    """Set the form the way a person does (see the module doc); the resolved inputs and, per image parameter, the Frame it was given as."""
    w = ctx.host.widget
    inputs = testing._resolve_paths(
        case, tool
    )  # noqa: SLF001 - the one resolver of relative fixture names, shared with `labconstrictor-tools test`
    params = {p["name"]: p for p in tool["inputs"]}
    unknown = sorted(set(inputs) - set(params))
    if unknown:
        raise AssertionError("the case sets %s, which the tool does not declare" % unknown)
    frames: dict[str, Frame] = {}
    for name, value in inputs.items():
        kind = params[name]["type"]
        if kind in ("image", "labels"):
            path = Path(str(value))
            layer = open_fixture_layer(ctx, name, path, kind) if ctx.cfg.input_mode == "layer" else None
            if layer is not None:
                w.file_sources[name].value = None
                w.gui[name].value = layer
                frames[name] = Frame(path, fixture_scale(path), "layer")
            else:
                w.file_sources[name].value = path
                frames[name] = Frame(
                    path, (1.0, 1.0), "file"
                )  # SPEC_WRONG_SCIENCE 1.3: the pixel frame of the file
        elif kind in ("table", "file", "folder"):
            w.gui[name].value = Path(str(value))
        else:
            if name in w.unset_toggles:
                w.unset_toggles[name].value = True
            if params[name].get("pixel_size_of"):  # typed text, as a person gives it
                field = w.gui[name].native
                field.setText(str(value))
                field.textEdited.emit(str(value))
                field.editingFinished.emit()
            else:
                w.gui[name].value = value
        pump(0.05)
    until(w.choices_settled, 20)
    return inputs, frames


def reset_unset_inputs(ctx: AppCtx, tool: dict[str, Any], case: dict[str, Any]) -> None:
    """Every parameter the case does not give goes back to what a freshly opened form shows (the form is not rebuilt: the form of the
    last run keeps its values): an optional value unset, a value with a default at its default, an image's file row empty.
    """
    w, given = ctx.host.widget, case.get("inputs", {})
    for param in tool["inputs"]:
        name = param["name"]
        if name in given:
            continue
        if name in w.unset_toggles:
            w.unset_toggles[name].value = False
        elif param["type"] in ("image", "labels"):
            w.file_sources[name].value = None
        elif "default" in param and not param.get("pixel_size_of"):
            w.gui[name].value = param["default"]


def prepare(ctx: AppCtx, tool_id: str, case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Frame]]:
    """Choose the tool, empty the viewer of earlier results, reset what the case leaves out and fill the form with the case."""
    w = ctx.host.widget
    w.app_box.value = ctx.app
    pump(0.2)
    w.tool_box.value = ctx.labels[tool_id]
    pump(0.5)
    ctx.host.viewer.layers.clear()
    pump(0.2)
    reset_unset_inputs(ctx, tool_of(ctx, tool_id), case)
    return fill_inputs(ctx, tool_of(ctx, tool_id), case)


def abort(ctx: AppCtx) -> None:
    """After a timeout: Cancel, kill the worker when the tool ignores it, then the host's own Restart worker."""
    w = ctx.host.widget
    task = w.task
    if task is not None and not task.done.is_set():
        w.cancel_button.click()
        if not until(task.done.is_set, CANCEL_WAIT_S):
            w.worker.kill()
            until(task.done.is_set, CANCEL_WAIT_S)
    pump(0.5)
    if not w.restart_button.isEnabled():
        raise RuntimeError("the run is still not over after Cancel and a kill: Restart worker is disabled")
    w.restart_button.click()
    pump(0.3)


def execute(
    ctx: AppCtx, tool_id: str, case: dict[str, Any], deadline: float, during: Any = None
) -> tuple[RunObs, Any]:  # fmt: skip
    """Click Run (a real mouse click on the real button) and wait for the end; what the button did and the finished task.
    `during(widget)` is called while the task runs (the panel checks look at the window then)."""
    w = ctx.host.widget
    obs = RunObs(tool_id)
    ticks: list[object] = []

    def count(*args: object) -> None:
        ticks.append(args)

    w._signals.progress.connect(
        count
    )  # noqa: SLF001 - one more listener beside the widget's own: counts the progress updates
    tool, expect = tool_of(ctx, tool_id), case.get("expect", {})
    discard = w._discard_job_dir  # noqa: SLF001

    def read_files_then_discard() -> None:
        """The widget deletes the job folder right after it showed the results: the files the contract and `expect.results` read must be
        looked at before that (the same checks as `labconstrictor-tools test`)."""
        task = w.task
        if task is not None and task.status == "COMPLETE" and "cancel_after_s" not in case:
            results = list(task.outputs["results"])
            obs.file_problems = testing.contract_problems(tool, results)
            obs.file_problems += testing.expectation_problems(
                expect, results, w.timings["run_wall_s"], len(ticks)
            )
        discard()

    w._discard_job_dir = read_files_then_discard  # noqa: SLF001
    try:
        before = w.task
        button = w.gui.call_button
        scroll_to(w, button.native)
        real_click(button.native, settle=False)
        obs.started = w.task is not None and w.task is not before
        obs.disabled_while_running = not button.enabled
        task = w.task
        if not obs.started:
            raise AssertionError("Run did not start a task; status: %s" % w.status.text())
        obs.worker_pid = w.worker.proc.pid
        if during is not None:
            during(w)
        if "cancel_after_s" in case:
            until(lambda: task.done.is_set(), float(case["cancel_after_s"]))
            real_click(w.cancel_button)  # the real Cancel
        if not until(lambda: w.last_task is task, max(1.0, deadline - time.time())):
            abort(ctx)
            raise TimeoutError(
                "the run did not finish within the tool timeout; cancelled and the worker restarted"
            )
        pump(0.8)
    finally:
        w._signals.progress.disconnect(count)  # noqa: SLF001
        w._discard_job_dir = discard  # noqa: SLF001
    obs.progress_events = len(ticks)
    obs.enabled_after = bool(button.enabled)
    obs.status_text, obs.task_status = w.status.text(), task.status
    obs.worker_kept = bool(w._workers._workers.get(ctx.app))  # noqa: SLF001
    ctx.runs.append(obs)
    return obs, task


def shown_problems(ctx: AppCtx, tool: dict[str, Any], results: list[dict[str, Any]]) -> list[str]:
    """Every declared output must be shown the way the Results table of the README says."""
    w, problems = ctx.host.widget, []
    layers = {layer.name for layer in ctx.host.viewer.layers}
    by_name = {r["name"]: r for r in results}
    status = w.status.text()
    for out in tool["outputs"]:
        name, kind = out["name"], out["type"]
        result = by_name.get(name)
        layer = "%s:%s" % (ctx.app, name)
        if result is None:
            problems.append("no result named %r" % name)
        elif kind in ("image", "labels") and layer not in layers:
            problems.append("%s %r: no layer %r" % (kind, name, layer))
        elif (
            kind in ("points", "shapes")
            and layer not in layers
            and name not in w.tables
            and "file:" not in status
        ):
            problems.append("%s %r: no layer, table or file in the status" % (kind, name))
        elif kind == "table" and name not in w.tables:
            problems.append("table %r: no table dock (%s)" % (name, sorted(w.tables)))
        elif kind == "values":
            problems += [
                "values %r: %r not in the status" % (name, k)
                for k in result["values"]
                if "%s=" % k not in status
            ]
        elif kind == "message" and (
            result["text"] not in w.message_label.text() or w.message_label.isHidden()
        ):
            problems.append("message %r is not shown under the status" % name)
        elif kind == "file" and ("file: " not in status or not Path(result["path"]).parent.exists()):
            problems.append("file %r: its path is not in the status" % name)
    return problems


def record_problems(ctx: AppCtx, tool_id: str) -> list[str]:
    """The run record and the log, read from disk (LC_HOME), not from the panel."""
    w, problems = ctx.host.widget, []
    folder = Path(w.last_record) if w.last_record else None
    run_json = folder / "run.json" if folder is not None else None
    if run_json is None or not run_json.is_file():
        problems.append("no run.json at %s" % (folder,))
    else:
        try:
            text = run_json.read_text(encoding="utf-8")
            if tool_id not in text or not isinstance(json.loads(text), dict):
                problems.append("run.json does not describe the run of %s" % tool_id)
        except (OSError, ValueError) as error:
            problems.append("run.json is unreadable: %s" % error)
        if folder is not None and ctx.cfg.home not in folder.parents:
            problems.append("the run record %s is not under LC_HOME" % folder)
    log = ctx.cfg.home / "logs" / "labconstrictor.log"
    if not log.is_file() or log.stat().st_size == 0:
        problems.append("no log file under LC_HOME/logs")
    return problems


def verify(
    ctx: AppCtx, tool: dict[str, Any], case: dict[str, Any], obs: RunObs, task: Any, frames: dict[str, Frame]
) -> str:
    """The assertions of one run; the detail of a pass."""
    w, expect = ctx.host.widget, case.get("expect", {})
    wanted = expect.get("status", "COMPLETE")
    if "cancel_after_s" in case:
        wanted = expect.get("status", "CANCELED")
    problems: list[str] = []
    if task.status != wanted:
        problems.append("status %s, expected %s (%s)" % (task.status, wanted, task.error or obs.status_text))
    if wanted == "FAILED":
        if "code" in expect and task.code != expect["code"]:
            problems.append("error code %r, expected %r" % (task.code, expect["code"]))
        if "message_contains" in expect and expect["message_contains"] not in "%s %s" % (
            task.error,
            obs.status_text,
        ):
            problems.append("the message lacks %r: %s" % (expect["message_contains"], task.error))
        if not obs.status_text.startswith("✖"):
            problems.append("the status does not report the failure: %s" % obs.status_text)
    elif wanted == "CANCELED" and not obs.status_text.startswith("cancelled"):
        problems.append("the status does not say cancelled: %s" % obs.status_text)
    elif wanted == "COMPLETE" and task.status == "COMPLETE":
        results = list(task.outputs["results"])
        problems += obs.file_problems
        problems += shown_problems(ctx, tool, results)
        problems += placement_problems(ctx, tool, frames)
        if obs.status_text.startswith("⚠"):
            problems.append("the run ended with a warning: %s" % obs.status_text)
    if not obs.enabled_after:
        problems.append("Run is still disabled after the run")
    problems += record_problems(ctx, tool["id"])
    windows = windows_problem([MAIN_WINDOW])  # a finished run leaves no dialog behind
    problems += [windows] if windows else []
    if problems:
        raise AssertionError("; ".join(problems))
    return "%s in %.1fs, %d progress updates, outputs: %s" % (
        task.status, w.timings["run_wall_s"], obs.progress_events,
        ", ".join("%s(%s)" % (o["name"], o["type"]) for o in tool["outputs"]) or "none",
    )  # fmt: skip


def shot_paths(ctx: AppCtx, tool_id: str) -> tuple[Path, Path]:
    base = ctx.cfg.shots / "napari" / ctx.app
    return base / ("%s_form.png" % sanitise(tool_id)), base / ("%s_after_run.png" % sanitise(tool_id))


def replay_prerequisites(ctx: AppCtx, index: int, deadline: float) -> list[str]:
    """Replay the earlier cases that have not run yet, in file order, through the same form and Run button (a stateful app's game: the
    state is in the results folder, and a case that expects FAILED can still change it, as the app's own `labconstrictor-tools test` run
    sees). Each must end as its own `expect` says (status, and error code); stress, cancel and skipped cases are not replayed.
    """
    done = []
    for j, case in enumerate(ctx.cases[:index]):
        if j in ctx.replayed or never_run(case["tool"]) or "cancel_after_s" in case or case.get("skip"):
            continue
        ctx.replayed.add(j)
        prepare(ctx, case["tool"], case)
        obs, task = execute(ctx, case["tool"], case, deadline)
        expect = case.get("expect", {})
        wanted = expect.get("status", "COMPLETE")
        if task.status != wanted or ("code" in expect and task.code != expect["code"]):
            raise AssertionError(
                "prerequisite case %d (%s) ended %s %s, its expect says %s %s | %s"
                % (j, case["tool"], task.status, task.code, wanted, expect.get("code", ""), obs.status_text)
            )
        done.append(case["tool"] + ("" if wanted == "COMPLETE" else "(%s)" % wanted))
    return done


def run_tool(ctx: AppCtx, tool_id: str, deadline: float, outcome: dict[str, Any]) -> str:
    """ui_napari_run_<tool> and its screenshots. Screenshot problems go to `outcome` (checked by `screens_check`)."""
    form_png, after_png = shot_paths(ctx, tool_id)
    tool = tool_of(ctx, tool_id)
    index, case = choose_case(ctx, tool_id)
    replayed = replay_prerequisites(ctx, index, deadline)
    ctx.replayed.add(index)
    inputs, frames = prepare(ctx, tool_id, case)
    calibration = calibration_problems(ctx, tool, inputs, frames)
    for path in (form_png, after_png):
        path.unlink(missing_ok=True)
    outcome["since"] = time.time()
    shoot(ctx.host, form_png)
    try:
        obs, task = execute(ctx, tool_id, case, deadline)
    finally:
        try:
            shoot(ctx.host, after_png)
        # reported by the screens check; the run's own verdict must still be given
        except Exception as error:  # noqa: BLE001
            outcome["after"] = "%s: %s" % (type(error).__name__, error)
    obs.case_index = index
    detail = verify(ctx, tool, case, obs, task, frames)
    if calibration:
        raise AssertionError("; ".join(calibration) + " | " + detail)
    return detail + (" (prerequisites replayed: %s)" % ", ".join(replayed) if replayed else "")


def form_only_shot(ctx: AppCtx, tool_id: str) -> Path:
    """A tool without a run still gets the screenshot of its form."""
    form_png, _ = shot_paths(ctx, tool_id)
    ctx.host.widget.app_box.value = ctx.app
    pump(0.2)
    ctx.host.widget.tool_box.value = ctx.labels[tool_id]
    pump(0.5)
    shoot(ctx.host, form_png)
    return form_png


def screens_check(ctx: AppCtx, tool_id: str, outcome: dict[str, Any]) -> str:
    """Both screenshots exist, are fresh (written after the run started) and have a plausible size. Evidence for a person to look at:
    this does not say the picture is right."""
    form_png, after_png = shot_paths(ctx, tool_id)
    since = outcome.get("since", time.time())
    problems = [p for p in (fresh_problem(form_png, since), fresh_problem(after_png, since)) if p]
    if outcome.get("after"):
        problems.append("the screenshot after the run failed: %s" % outcome["after"])
    if problems:
        raise AssertionError("; ".join(problems))
    return "%s and %s written for a person to look at (%d and %d bytes)" % (
        form_png.name, after_png.name, form_png.stat().st_size, after_png.stat().st_size,
    )  # fmt: skip

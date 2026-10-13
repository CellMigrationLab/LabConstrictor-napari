"""Retention, the host side (SPEC_WRONG_SCIENCE section 3; conformance.json fixtures HRET-01..04, RET-10, RET-11, RET-14).

The napari plugin never prunes: it writes `.lc-owner.json` when it creates a run record or a results folder, `.lc-done.json` when the run
has ended, and then starts `labconstrictor-tools prune` in a subprocess. Here the subprocess is replaced by a recorder (the real `prune`
against a private LC_HOME is test_retention_prune_real.py), and the real napari widget, worker and files are used.
"""

import ast
import logging
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import _paths  # noqa: F401  (must come first)
import _runtools as R
import numpy as np
import tifffile
from _harness import expect, finish, pump, viewer, widget
from labconstrictor_tools import conformance, log

from napari_labconstrictor import _results, _retention

if TYPE_CHECKING:
    from typing import Any

w = widget
C = conformance.load()["wrong_science"]["retention"]
M = C["markers"]
ids = {f["id"] for f in C["fixtures_hosts"]}
for needed in ("HRET-01", "HRET-02", "HRET-03", "HRET-04", "RET-10", "RET-11", "RET-14"):
    expect("fixture_%s_is_in_conformance_json" % needed, needed in ids)

records = []


class _Catch(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        records.append((record.levelno, record.getMessage()))


log.logger().addHandler(_Catch())
log.logger().setLevel(logging.DEBUG)


def logged(text: str) -> list[str]:
    return [message for _, message in records if text in message]


A = viewer.add_image(np.ones((8, 8), np.uint8), name="A", scale=(2.0, 2.0))
R.use_recorder()
runs_before = len(R.folders("runs"))

# ---- HRET-03: owner first (visible while the run is still going), done last, right content --------------------------------------
R.pick("Gated points")
w.gui.image.value = A
gate = R.new_gate()
w.gui.gate.value = str(gate)
R.start()
expect("run_is_going", R.wait_until(lambda: w.task is not None and not w.task.done.is_set()))
pump(0.5)
runs = R.folders("runs")
expect("a_run_record_exists_while_running", len(runs) == runs_before + 1, runs)
folder = runs[-1]
expect(
    "HRET-03_owner_marker_is_valid_during_the_run",
    R.valid_owner(folder, "run", M) == [],
    R.valid_owner(folder, "run", M),
)
expect("HRET-03_no_done_marker_while_running", R.done_status(folder, M) is None)
expect("no_run_json_while_running", not (folder / "run.json").exists())
expect("no_prune_started_while_running", R.calls() == [], R.calls())
R.release(gate)
R.wait_done()
R.join_prune()
expect("HRET-03_done_marker_is_ok", R.done_status(folder, M) == "ok", R.done_status(folder, M))
expect("run_json_written", (folder / "run.json").is_file())
record = R.read_json(folder / "run.json")
expect("run_record_has_the_run_id", record.get("run_id") == w.snapshot.run_id, record.get("run_id"))
expect("last_record_is_the_folder", w.last_record == folder, w.last_record)
expect("no_results_folder_when_nothing_must_be_kept", R.folders("results") == [], R.folders("results"))

# ---- HRET-04: `prune` started after the done marker existed, as `<app python> -m labconstrictor_tools prune` --------------
calls = R.calls()
expect("HRET-04_prune_started_once", len(calls) == 1, calls)
expect(
    "HRET-04_command_is_the_apps_python_m_labconstrictor_tools_prune",
    calls and calls[0]["argv"] == [w.apps[R.APP]["python"], "-m", "labconstrictor_tools", "prune"],
    calls,
)
expect(
    "HRET-04_started_after_the_done_marker",
    calls and calls[0]["state"].get("runs/" + folder.name, {}).get("done") == "ok",
    calls and calls[0]["state"],
)
expect(
    "the_real_command_line",
    R._real_argv("py") == ["py", "-m", "labconstrictor_tools", "prune"],
    R._real_argv("py"),
)

# ---- RET-10: a FileOut in the job folder is moved to an owned results folder before the job folder goes -----------------------
R.pick("Report file")
n_calls = len(R.calls())
R.quick_run()
R.join_prune()
reported = Path(w.last_task.outputs["results"][0]["path"])
results = R.folders("results")
expect("RET-10_one_results_folder", len(results) == 1, results)
rfolder = results[0]
expect("RET-10_reported_path_is_under_results", reported.parent == rfolder, reported)
expect("RET-10_contents_are_data", reported.is_file() and reported.read_text() == "data")
expect("RET-10_job_folder_is_gone", not w._job_dir.exists(), w._job_dir)
expect("RET-10_status_names_the_kept_path", str(reported) in w.status.text(), w.status.text())
expect(
    "RET-10_results_folder_name",
    __import__("re").match(r"^\d{8}T\d{6}_[0-9a-f]{6}_runapp_report_file$", rfolder.name),
    rfolder.name,
)
expect(
    "RET-10_results_owner_valid",
    R.valid_owner(rfolder, "result", M) == [],
    R.valid_owner(rfolder, "result", M),
)
expect("RET-10_results_done_ok", R.done_status(rfolder, M) == "ok")
last_run = R.folders("runs")[-1]
expect(
    "RET-10_run_record_keeps_the_reported_path",
    R.read_json(last_run / "run.json")["results"][0]["path"] == str(reported),
    R.read_json(last_run / "run.json")["results"],
)
expect(
    "RET-10_prune_after_both_done_markers",
    len(R.calls()) == n_calls + 1
    and R.calls()[-1]["state"].get("results/" + rfolder.name, {}).get("done") == "ok"
    and R.calls()[-1]["state"].get("runs/" + last_run.name, {}).get("done") == "ok",
    R.calls()[-1:],
)

# a file the tool made elsewhere is never moved or modified
outside = R.WORK / "elsewhere.txt"
outside.write_text("mine", encoding="utf-8")
stamp = outside.stat().st_mtime_ns
R.pick("Outside file")
w.gui.path.value = str(outside)
R.quick_run()
R.join_prune()
expect(
    "outside_file_not_moved_or_modified",
    outside.read_text() == "mine" and outside.stat().st_mtime_ns == stamp,
)
expect("outside_file_makes_no_results_folder", len(R.folders("results")) == 1, R.folders("results"))
expect("outside_file_is_reported_where_it_is", str(outside) in w.status.text(), w.status.text())

# ---- RET-14: an image over the display limit stays at a stable owned path and the path is shown --------------------------------
real_limit = _results.MAX_DISPLAY_BYTES
_results.MAX_DISPLAY_BYTES = 8  # the 4 x 4 uint8 picture is 16 bytes
R.pick("Big picture")
R.quick_run()
R.join_prune()
_results.MAX_DISPLAY_BYTES = real_limit
results = R.folders("results")
expect("RET-14_a_second_results_folder", len(results) == 2, results)
picture = results[-1] / "picture.tif"
expect("RET-14_file_is_in_the_owned_folder", picture.is_file(), list(results[-1].iterdir()))
expect("RET-14_file_is_readable", picture.is_file() and tifffile.imread(picture).shape == (4, 4))
expect("RET-14_not_shown_in_the_viewer", "runapp:picture" not in viewer.layers)
expect("RET-14_path_is_shown", str(picture) in w.status.text(), w.status.text())
expect(
    "RET-14_no_path_into_the_deleted_job_folder",
    str(w._job_dir) not in w.status.text() and not w._job_dir.exists(),
)
expect(
    "RET-14_owner_and_done",
    R.valid_owner(results[-1], "result", M) == [] and R.done_status(results[-1], M) == "ok",
)

# ---- RET-11: failed, cancelled and crashed runs: temporary folder removed, markers say what happened ----------------------------
results_before = R.folders("results")


def ended_run(label: str, expected_status: str) -> Path:
    R.join_prune()
    folder = R.folders("runs")[-1]
    expect(
        "RET-11_%s_record_status" % label,
        R.done_status(folder, M) == expected_status,
        R.done_status(folder, M),
    )
    expect("RET-11_%s_job_folder_removed" % label, not w._job_dir.exists(), w._job_dir)
    expect(
        "RET-11_%s_no_results_folder" % label, R.folders("results") == results_before, R.folders("results")
    )
    seen = R.calls()[-1]["state"].get("runs/" + folder.name, {}).get("done")
    expect("RET-11_%s_prune_after_done" % label, seen == expected_status, seen)
    return folder


R.pick("Explode", app="synthetic")
R.quick_run()
ended_run("failed", "failed")

R.pick("Slow with progress", app="synthetic")
w.gui.seconds.value = 30
w.gui.steps.value = 100  # checks for Cancel every 0.3 s: the worker stops by itself
R.start()
R.wait_until(lambda: w.task is not None and not w.task.done.is_set())
pump(1.0)
w.cancel()
R.wait_done(60)
expect("cooperative_cancel_is_canceled", w.last_task.status == "CANCELED", w.last_task.status)
ended_run("cancelled", "cancelled")

R.pick("Stubborn (ignores cancel)", app="synthetic")
w.gui.seconds.value = 30
R.start()
R.wait_until(lambda: w.task is not None and not w.task.done.is_set())
pump(1.0)
w.cancel()
R.wait_done(60)
expect(
    "forced_kill_after_cancel",
    w.last_task.status == "CRASHED" and w.status.text() == "cancelled (worker stopped)",
    (w.last_task.status, w.status.text()),
)
ended_run("cancelled_after_kill", "cancelled")

R.pick("Slow with progress", app="synthetic")

w.gui.seconds.value = 30
R.start()
R.wait_until(lambda: w.task is not None and not w.task.done.is_set())
pump(1.0)
w.worker.proc.kill()
R.wait_done(60)
expect("worker_crash_is_a_crash", w.last_task.status == "CRASHED", w.last_task.status)
ended_run("crashed", "failed")

# ---- a worker that cannot even start: the record still gets its done marker -----------------------------------------------------
R.pick("Echo")
real_acquire = w._workers.acquire


def gone(*_args: object, **_kw: object) -> None:
    raise OSError("the app's python is gone")


w._workers.acquire = gone
n_calls = len(R.calls())
w.last_task = None
w.gui()
pump(0.5)
w._workers.acquire = real_acquire
R.join_prune()
folder = R.folders("runs")[-1]
expect("start_failure_record_is_failed", R.done_status(folder, M) == "failed", R.done_status(folder, M))
expect(
    "start_failure_run_json_has_the_error",
    "python is gone" in R.read_json(folder / "run.json").get("error", ""),
)
expect("start_failure_job_folder_removed", not w._job_dir.exists())
expect("start_failure_prune_started", len(R.calls()) == n_calls + 1, len(R.calls()) - n_calls)
expect("start_failure_form_usable", w.gui.call_button.enabled and w.app_box.enabled)

# ---- prune is never a reason for a run to fail, and never blocks the GUI --------------------------------------------------------
n_before = len(R.folders("runs"))
for label, command, expected_log in (
    ("exit_code_3", [sys.executable, "-c", "import sys; sys.exit(3)"], "exit code 3"),
    (
        "missing_executable",
        [str(R.WORK / "no-such-python"), "-m", "labconstrictor_tools", "prune"],
        "could not run",
    ),
):
    records.clear()
    R.use_command(command)
    R.quick_run()
    R.join_prune()
    expect(
        "HRET-04_failing_prune_%s_run_is_fine" % label, w.status.text().startswith("✔ done"), w.status.text()
    )
    expect(
        "HRET-04_failing_prune_%s_record_ok" % label,
        R.done_status(R.folders("runs")[-1], M) == "ok",
    )
    expect(
        "HRET-04_failing_prune_%s_is_logged" % label,
        any(expected_log in m for m in logged("the cleanup")),
        records[-5:],
    )
    expect("HRET-04_failing_prune_%s_form_usable" % label, w.gui.call_button.enabled and w.app_box.enabled)
expect("failing_prune_deleted_nothing", len(R.folders("runs")) == n_before + 2)

R.use_recorder()
os.environ["LC_TEST_PRUNE_SLEEP"] = "15"
started = time.time()
R.quick_run()
took = time.time() - started
alive = w.last_prune is not None and w.last_prune.is_alive()
expect("prune_does_not_block_the_run", alive and took < 12, (alive, took))
os.environ["LC_TEST_PRUNE_SLEEP"] = "0"
R.join_prune()

# ---- compat rule 6: no `retention_prune` feature, no subprocess, one log line, nothing deleted -------------------------------
schema = w.schemas[R.APP]
real_features = schema.get("features")
n_calls, n_runs = len(R.calls()), len(R.folders("runs"))
for label, features in (
    ("feature_missing", [f for f in real_features if f != "retention_prune"]),
    ("no_features_list", None),
):
    if features is None:
        schema.pop("features", None)
    else:
        schema["features"] = features
    records.clear()
    R.quick_run()
    pump(0.5)
    expect(
        "compat6_%s_no_subprocess" % label,
        len(R.calls()) == n_calls and w.last_prune is None,
        R.calls()[n_calls:],
    )
    expect("compat6_%s_one_log_line" % label, len(logged("retention_prune")) == 1, logged("retention_prune"))
    expect("compat6_%s_run_is_fine" % label, w.status.text().startswith("✔ done"), w.status.text())
    expect("compat6_%s_record_is_marked" % label, R.done_status(R.folders("runs")[-1], M) == "ok")
schema["features"] = real_features
expect("compat6_nothing_deleted", len(R.folders("runs")) == n_runs + 2)
R.quick_run()
R.join_prune()
expect("compat6_feature_back_prune_started", len(R.calls()) == n_calls + 1)


# ---- HRET-01 / HRET-02: the host does many runs and deletes nothing, even with the recorder as the only cleanup ----------------
for root, name in (("results", "20261008T120000_reanalysis_backup"), ("runs", "0000_keep_this_analysis")):
    (R.HOME / root / name).mkdir(parents=True, exist_ok=True)
    (R.HOME / root / name / "x.txt").write_text("keep")
R.make_owned("results", "result", 60, "20200101T000000_")
R.make_owned("runs", "run", 120, "2020")


def snapshot_of_files() -> "dict[str, Any]":
    return {
        str(p.relative_to(R.HOME)): p.read_bytes()
        for root in ("results", "runs")
        for p in (R.HOME / root).rglob("*")
        if p.is_file()
    }


before = snapshot_of_files()
counts = {root: len(R.folders(root)) for root in ("results", "runs")}
R.pick("Echo")
for _ in range(5):
    R.quick_run()
after = snapshot_of_files()
lost = [k for k, v in before.items() if after.get(k) != v]
expect("HRET-02_none_of_the_old_files_is_gone_after_5_runs", not lost, lost[:5])
expect(
    "HRET-02_counts_only_grow", len(R.folders("runs")) == counts["runs"] + 5, (counts, len(R.folders("runs")))
)
for _ in range(55):
    R.quick_run()
R.join_prune()
after = snapshot_of_files()
lost = [k for k, v in before.items() if after.get(k) != v]
expect(
    "HRET-01_foreign_folders_and_x_txt_intact",
    all(
        R.text_of(R.HOME / root / name / "x.txt") == "keep"
        for root, name in (
            ("results", "20261008T120000_reanalysis_backup"),
            ("runs", "0000_keep_this_analysis"),
        )
    ),
)
expect("HRET-01_nothing_lost_after_60_runs", not lost, lost[:5])
expect(
    "HRET-01_run_records_only_grew",
    len(R.folders("runs")) == counts["runs"] + 60,
    (counts["runs"], len(R.folders("runs"))),
)
expect("HRET-01_prune_started_for_every_run", len(R.calls()) >= 60, len(R.calls()))

# ---- no deletion code in the plugin except the host's own temporary folders; the guard refuses LC_HOME/results|runs ------------
package = Path(_retention.__file__).parent
FORBIDDEN = ("rmtree", "rmdir", "unlink", "remove", "removedirs")


class Finder(ast.NodeVisitor):
    def __init__(self, filename: str) -> None:
        self.filename, self.stack, self.found = filename, [], []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        name = getattr(node.func, "attr", getattr(node.func, "id", ""))
        allowed = self.filename == "_retention.py" and self.stack[:1] == ["discard_job_dir"]
        layer_list = (
            getattr(getattr(node.func, "value", None), "attr", "") == "layers"
        )  # viewer.layers.remove(layer)
        if name in FORBIDDEN and not allowed and not layer_list:
            self.found.append("%s:%s %s" % (self.filename, node.lineno, name))
        self.generic_visit(node)


bad = []
for source in sorted(package.glob("*.py")):
    finder = Finder(source.name)
    finder.visit(ast.parse(source.read_text(encoding="utf-8")))
    bad += finder.found
expect("no_deletion_code_outside_discard_job_dir", not bad, bad)

keep = R.HOME / "results" / "20200101T000000_0000_old_x"
for target, label in (
    (keep, "an_owned_results_folder"),
    (R.HOME / "runs", "the_runs_root"),
    (R.HOME, "lc_home_itself"),
):
    removed = _retention.discard_job_dir(target)
    expect("guard_refuses_%s" % label, removed is False and target.exists(), removed)
expect("guard_left_the_sentinel", R.text_of(keep / "sentinel.txt") == "keep-" + keep.name)
scratch = R.WORK / "lcin_scratch"
scratch.mkdir()
expect(
    "guard_allows_a_temporary_folder_outside_lc_home",
    _retention.discard_job_dir(scratch) and not scratch.exists(),
)
expect("guard_ignores_an_empty_path", _retention.discard_job_dir("") is False)

# ---- closing the widget during a run: the record is finished as cancelled, nothing is left, the file kept by RET-10 survives -----
R.pick("Gated points")
w.gui.image.value = A
gate = R.new_gate()
w.gui.gate.value = str(gate)
R.start()
R.wait_until(lambda: w.task is not None and not w.task.done.is_set())
pump(0.5)
job, n_runs, n_calls = w._job_dir, len(R.folders("runs")), len(R.calls())
w.close()
R.join_prune()
pump(0.5)
folder = R.folders("runs")[-1]
expect("close_during_run_one_new_record", len(R.folders("runs")) == n_runs, (n_runs, len(R.folders("runs"))))
expect("RET-11_closed_record_is_cancelled", R.done_status(folder, M) == "cancelled", R.done_status(folder, M))
expect("RET-11_closed_run_json_says_why", "closed" in R.read_json(folder / "run.json").get("error", ""))
expect("RET-11_closed_job_folder_removed", not job.exists())
expect(
    "RET-11_closed_prune_started_after_done",
    len(R.calls()) == n_calls + 1
    and R.calls()[-1]["state"].get("runs/" + folder.name, {}).get("done") == "cancelled",
)
R.release(gate)
pump(1.5)
expect(
    "close_then_late_done_changes_nothing",
    len(R.folders("runs")) == n_runs and R.done_status(folder, M) == "cancelled",
)
expect(
    "RET-10_file_survives_closing_the_widget", reported.is_file() and reported.read_text() == "data", reported
)

finish()

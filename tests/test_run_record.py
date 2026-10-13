"""The run record is Tools' (`labconstrictor_tools.runs`), not a copy kept here (docs/PROTOCOL.md "A Python host that writes its own run
record"). No Qt call is made: the content, its text, the done status and the version check are plain functions.

* The bytes of `run.json` are the ones the plugin wrote before it called Tools (OLD_CONTENT below is that code, frozen), for every way a
  run can end, with `_calibration` under `inputs` (SPEC_WRONG_SCIENCE 2.3.4) whether or not the installed Tools copies it.
* The `.lc-done.json` status of every task status is the one SPEC_WRONG_SCIENCE 3.2 decides (a crash after Cancel is cancelled).
* A Tools below the minimum version (v0.2.0-rc.1 and rc.2 both report 0.2.0rc1) or without the three helpers is refused at import with
  a sentence that says what to install; each check alone is enough to refuse.
"""

import json
import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from typing import ClassVar
from unittest import mock

import _paths  # noqa: F401  (must come first)
from labconstrictor_tools import registry
from labconstrictor_tools import runs as tools_runs

from napari_labconstrictor import _retention

ROOT = _paths.ROOT
CAL = {
    "x": {"value": 0.25, "unit": "um", "source": "user"},
    "y": {"value": 0.25, "unit": "um", "source": "user"},
}
REQUEST = {"image": "/data/a.tif", "pixel_size": 0.25, "note": None, "_calibration": {"pixel_size": CAL}}
SNAPSHOT = SimpleNamespace(
    run_id="0b1c2d3e-0000-4000-8000-000000000001", started="2026-10-13T08:00:00.123456Z"
)
APP, TOOL = "synthetic", "blur"
OLD_STDERR_TAIL = (
    3000  # what the plugin cut the stderr of run.json to before (Tools cuts to runs.STDERR_TAIL_CHARS)
)


def task(status, error=None, code=None, traceback=None, results=(), cancel_requested=False):
    outputs = {"results": list(results), "timings": {"total_s": 1.5}, "diagnostics": {"python": "3.11.0"}}
    return SimpleNamespace(
        status=status,
        error=error,
        code=code,
        traceback=traceback,
        outputs=outputs,
        cancel_requested=cancel_requested,
    )


RUNS = {
    "complete": task("COMPLETE", results=[{"type": "image", "name": "out", "path": "/r/out.tif", "matrix_yx": [[1, 0, 0]]}]),
    "failed": task("FAILED", error="bad input", code="invalid_parameter", traceback="Traceback (most recent call last):\n  x"),
    "canceled": task("CANCELED"),
    "crashed": task("CRASHED", error="worker died", cancel_requested=True),
}  # fmt: skip


def old_content(task, stderr, snapshot, apps):
    """What `_widget._record_run` built before this change (main at 6f9317f), copied here so the bytes are compared with it."""
    return {
        "run_id": snapshot.run_id if snapshot else None,
        "app": APP,
        "app_version": (apps.get(APP) or {}).get("version"),
        "tool": TOOL,
        "started_utc": snapshot.started if snapshot else None,
        "finished_utc": "FIXED",
        "seconds": round(2.3456, 2),
        "status": task.status,
        "error": task.error,
        "code": task.code,
        "traceback": task.traceback,
        "inputs": {k: v for k, v in REQUEST.items() if k != "_job_dir"},
        "results": [{k: v for k, v in r.items() if k != "matrix_yx"} for r in task.outputs.get("results", [])],
        "timings": task.outputs.get("timings"),
        "interpreter": task.outputs.get("diagnostics"),
        "stderr_tail": stderr[-OLD_STDERR_TAIL:],
    }  # fmt: skip


def new_content(task, stderr, **kw):
    content = _retention.run_record(APP, TOOL, REQUEST, task, 2.3456, stderr, SNAPSHOT, **kw)
    content["finished_utc"] = "FIXED"  # the only field that is the time of writing
    return content


class RunJson(unittest.TestCase):
    def setUp(self):
        self.apps = {APP: {"version": "1.4.2"}}
        patcher = mock.patch.object(registry, "load_all", return_value=self.apps)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_text_is_what_the_plugin_wrote_before_for_every_way_a_run_ends(self):
        for label, t in RUNS.items():
            for stderr in ("", "short worker output\n", "x" * 2999):
                with self.subTest(run=label, stderr=len(stderr)):
                    old = json.dumps(old_content(t, stderr, SNAPSHOT, self.apps), indent=2, default=str)
                    new = tools_runs.record_json(new_content(t, stderr, keep_inputs=("_calibration",)))
                    self.assertEqual(new, old)

    def test_the_file_is_the_same_bytes(self):
        t, stderr = RUNS["failed"], "boom\n"
        old = json.dumps(old_content(t, stderr, SNAPSHOT, self.apps), indent=2, default=str)
        record = _retention.RunRecord.start(APP, TOOL, SNAPSHOT.run_id)
        self.assertIsNotNone(record.folder)
        record.finish("failed", tools_runs.record_json(new_content(t, stderr, keep_inputs=("_calibration",))))
        expected = old.replace(
            "\n", os.linesep
        )  # write_text translates newlines the way the platform does, now and before
        self.assertEqual((record.folder / "run.json").read_bytes(), expected.encode("utf-8"))

    def test_keys_come_in_the_old_order_and_the_job_folder_and_matrix_are_left_out(self):
        content = new_content(RUNS["complete"], "")
        self.assertEqual(list(content), list(old_content(RUNS["complete"], "", SNAPSHOT, self.apps)))
        self.assertEqual(content["run_id"], SNAPSHOT.run_id)
        self.assertEqual(content["started_utc"], SNAPSHOT.started)
        self.assertNotIn("matrix_yx", content["results"][0])
        request = dict(REQUEST, _job_dir="job")
        got = _retention.run_record(APP, TOOL, request, RUNS["complete"], 1, "", SNAPSHOT)
        self.assertNotIn("_job_dir", got["inputs"])

    def test_calibration_is_under_inputs(self):
        self.assertEqual(new_content(RUNS["complete"], "")["inputs"]["_calibration"], {"pixel_size": CAL})

    def test_calibration_is_kept_even_when_the_installed_tools_does_not_copy_it(self):
        real = tools_runs.build_record

        def without_calibration(*args, **kwargs):
            content = real(*args, **kwargs)
            content["inputs"].pop("_calibration", None)  # a Tools that drops reserved inputs
            return content

        with mock.patch.object(tools_runs, "build_record", without_calibration):
            kept = new_content(RUNS["complete"], "", keep_inputs=("_calibration",))
            dropped = new_content(RUNS["complete"], "")
        self.assertEqual(kept["inputs"]["_calibration"], {"pixel_size": CAL})
        self.assertNotIn("_calibration", dropped["inputs"])  # the guard is what keeps it, not luck

    def test_a_calibration_entry_tools_copied_is_not_replaced(self):
        real = tools_runs.build_record

        def own_copy(*args, **kwargs):
            content = real(*args, **kwargs)
            content["inputs"]["_calibration"] = {"from": "tools"}
            return content

        with mock.patch.object(tools_runs, "build_record", own_copy):
            self.assertEqual(
                new_content(RUNS["complete"], "", keep_inputs=("_calibration",))["inputs"]["_calibration"],
                {"from": "tools"},
            )

    def test_the_stderr_tail_is_the_one_tools_writes_for_its_own_records(self):
        long = "".join(chr(65 + i % 26) for i in range(6000))
        tail = new_content(RUNS["failed"], long)["stderr_tail"]
        self.assertEqual(
            tail, long[-tools_runs.STDERR_TAIL_CHARS :]
        )  # 4000 (was 3000 here: the one change in run.json)
        self.assertGreater(len(tail), OLD_STDERR_TAIL)


class DoneStatus(unittest.TestCase):
    TABLE: ClassVar[list[tuple[str, bool, str]]] = [  # (task status, cancel requested, status of .lc-done.json): SPEC_WRONG_SCIENCE 3.2
        ("COMPLETE", False, "ok"), ("CANCELED", False, "cancelled"), ("FAILED", False, "failed"),
        ("CRASHED", True, "cancelled"), ("CRASHED", False, "failed"),
        ("FAILED", True, "failed"), ("COMPLETE", True, "ok"), ("RUNNING", False, "failed"),
    ]  # fmt: skip

    def test_every_way_a_task_ends(self):
        for status, cancel, expected in self.TABLE:
            with self.subTest(status=status, cancel_requested=cancel):
                self.assertEqual(tools_runs.done_status(status, cancel), expected)

    def test_the_plugin_keeps_no_copy_of_the_mapping(self):
        self.assertFalse(hasattr(_retention, "done_status"))
        self.assertFalse(hasattr(_retention, "_DONE_STATUS"))
        source = (ROOT / "napari_labconstrictor" / "_widget.py").read_text(encoding="utf-8")
        self.assertIn('tools_runs.done_status(task.status, getattr(task, "cancel_requested", False))', source)


class ToolsVersionCheck(unittest.TestCase):
    def test_this_tools_has_the_helpers(self):
        self.assertIsNone(_retention.tools_problem())

    def test_a_tools_without_a_helper_gets_a_sentence_that_says_what_to_do(self):
        old = SimpleNamespace(done_status=lambda *a: "ok")  # what v0.2.0-rc.1 has of the three: none of them
        problem = _retention.tools_problem(
            old, installed=_retention.TOOLS_MINIMUM
        )  # the version alone would pass
        self.assertIsNotNone(problem)
        for text in ("runs.build_record", "runs.record_json", "v0.3.0-alpha.1", "0.3.0a1", "update Tools"):
            self.assertIn(text, problem)
        self.assertNotIn("runs.done_status", problem)  # it has that one
        with self.assertRaises(ImportError) as caught:
            _retention.require_run_helpers(old)
        self.assertIn("update Tools to v0.3.0-alpha.1 or newer (version 0.3.0a1)", str(caught.exception))

    def test_rc1_and_rc2_are_refused_by_their_version_even_with_the_helpers(self):
        for installed in (
            "0.2.0rc1",
            "0.2.0",
            "0.1.0",
        ):  # rc.2 has the helpers and reports 0.2.0rc1
            with self.subTest(installed=installed):
                problem = _retention.tools_problem(tools_runs, installed=installed)
                self.assertIsNotNone(problem)
                self.assertIn("update Tools to v0.3.0-alpha.1 or newer (version 0.3.0a1)", problem)
                self.assertIn(installed, problem)
                self.assertNotIn("has no runs.", problem)  # the helpers are there: only the version refuses
        for installed in ("0.3.0a1", "0.3.0a2", "0.3.0b1", "0.3.0", "0.4.1"):
            with self.subTest(installed=installed):
                self.assertIsNone(_retention.tools_problem(tools_runs, installed=installed))

    def test_a_helper_that_is_not_callable_counts_as_missing(self):
        broken = SimpleNamespace(build_record=None, record_json=str, done_status=str)
        self.assertIn("runs.build_record", _retention.tools_problem(broken))

    def _import_with(self, patch):
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "import labconstrictor_tools.runs as r, labconstrictor_tools._version as v\n"
            "%s\n"
            "import napari_labconstrictor._retention\n" % (str(ROOT), patch)
        )
        return subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ)
        )

    def test_the_plugin_refuses_to_load_with_a_tools_without_a_helper(self):
        run = self._import_with("del r.build_record")  # the module of rc.1 as the plugin sees it
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("ImportError", run.stderr)
        self.assertIn("runs.build_record", run.stderr)
        self.assertIn("v0.3.0-alpha.1", run.stderr)

    def test_the_plugin_refuses_to_load_with_the_version_of_rc2(self):
        run = self._import_with(
            "v.__version__ = '0.2.0rc1'"
        )  # rc.2: the helpers exist, the version is 0.2.0rc1
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("ImportError", run.stderr)
        self.assertIn("update Tools to v0.3.0-alpha.1 or newer (version 0.3.0a1)", run.stderr)

    def test_the_minimum_in_pyproject_is_the_one_in_the_message(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"labconstrictor-tools>=%s"' % _retention.TOOLS_MINIMUM, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

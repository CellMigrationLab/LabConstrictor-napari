"""Regression test of the UI audit driver (tests/ui_audit.py) for the driver bugs found in the alpha.2 to alpha.4 audits of real apps: each
was a FAIL of the driver, not of the Napari widget. The app is `ui_audit_probe_app.py` (an optional field behind an `enabled_when` rule, a
bounded pixel size, an image tool audited after the tool whose cases refuse input). Layer mode (the default of the driver) is used.
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

import _paths  # noqa: F401  (must come first)
import numpy as np
import tifffile
from _paths import HOME
from ui_audit import audit
from ui_audit_core import Config

cast(io.TextIOWrapper, sys.stdout).reconfigure(
    encoding="utf-8"
)  # the check details hold the widget's own sentences ("⚠ ...")
report: dict[str, bool] = {}
failures: list[str] = []


def expect(name: str, condition: object, detail: object = "") -> None:
    report[name] = bool(condition)
    if not condition:
        failures.append("%s %s" % (name, detail))


here = Path(__file__).resolve().parent
subprocess.run(
    [sys.executable, "-m", "labconstrictor_tools", "register", "--name", "probe", "--prefix", sys.prefix,
     "--module", "ui_audit_probe_app", "--pythonpath", str(here), "--version", "0.0"],  # the worker imports the probe app from here
    check=True, capture_output=True,
)  # fmt: skip

work = Path(tempfile.mkdtemp(prefix="lc_ui_audit_regress_"))
tests = work / "lc_tests"
(tests / "fixtures").mkdir(parents=True)
tifffile.imwrite(tests / "fixtures" / "plane.tif", np.arange(64, dtype=np.uint16).reshape(8, 8))
plane = "fixtures/plane.tif"
cases: list[dict[str, Any]] = [
    {"tool": "segment", "inputs": {"image": plane, "pixel_size_um": 0.5}, "expect": {"results": {"values": {"mean": 31.5}}}},
    # the form refuses a negative pixel size: no task starts. A prerequisite of `count` below, never a failure of the `count` row
    {"tool": "segment", "inputs": {"image": plane, "pixel_size_um": -1.0}, "expect": {"status": "FAILED", "code": "invalid_parameter"}},
    # a typed 0 is read as 'use the image's calibration' (no calibration in the file): the run cannot reach the tool's own refusal
    {"tool": "segment", "inputs": {"image": plane, "pixel_size_um": 0.0}, "expect": {"status": "FAILED", "code": "invalid_parameter"}},
    {"tool": "count", "inputs": {"image": plane}, "expect": {"results": {"values": {"pixels": 64}}}},
    {"tool": "devices", "expect": {"results": {"values": {}}}},
]  # fmt: skip
(tests / "cases.json").write_text(json.dumps(cases), encoding="utf-8")

out = io.StringIO()
with contextlib.redirect_stdout(out):
    red = audit(Config(HOME, ["probe"], {"probe": tests}, work / "shots", "listed", 120.0))
lines = [x for x in out.getvalue().splitlines() if x.startswith(("CHECK ", "NOTE "))]
print("\n".join(x[:260] for x in lines))
matrix = json.loads((work / "shots" / "matrix_ui_napari_probe.json").read_text(encoding="utf-8"))
rows = {r["id"]: r for r in matrix["rows"]}


def status(cid: str) -> str:
    return rows[cid]["status"] if cid in rows else "MISSING"


def detail(cid: str) -> str:
    return rows[cid]["detail"] if cid in rows else "(no row)"


expect(
    "enabled_when_field_with_set_box_passes",
    status("ui_napari_form_segment_controls") == "PASS",
    detail("ui_napari_form_segment_controls"),
)
expect("refused_prerequisite_is_human_with_its_reason", status("ui_napari_prerequisite_segment_case1") == "HUMAN" and "refused" in detail("ui_napari_prerequisite_segment_case1"), detail("ui_napari_prerequisite_segment_case1"))  # fmt: skip
expect("typed_zero_prerequisite_is_human", status("ui_napari_prerequisite_segment_case2") == "HUMAN" and "calibration" in detail("ui_napari_prerequisite_segment_case2"), detail("ui_napari_prerequisite_segment_case2"))  # fmt: skip
expect("next_tool_row_is_not_blamed", status("ui_napari_run_count") == "PASS" and "prerequisites replayed" in detail("ui_napari_run_count"), detail("ui_napari_run_count"))  # fmt: skip
expect("zero_parameter_tool_passes", status("ui_napari_run_devices") == "PASS" and status("ui_napari_form_devices_controls") == "PASS", detail("ui_napari_run_devices"))  # fmt: skip
expect("layer_mode_copy_rows_accept_the_placeholder", status("ui_napari_panel_copy_terminal_command") == "PASS" and status("ui_napari_panel_copy_python_snippet") == "PASS", detail("ui_napari_panel_copy_terminal_command") + " | " + detail("ui_napari_panel_copy_python_snippet"))  # fmt: skip
expect("only_the_known_widget_bug_is_red_if_any", all(r["id"] in ("ui_napari_panel_run",) for r in matrix["rows"] if r["status"] in ("FAIL", "NOT_RUN")), [r["id"] for r in matrix["rows"] if r["status"] in ("FAIL", "NOT_RUN")])  # fmt: skip

print(json.dumps(report, indent=2))
print("red rows of the audit: %d" % red)
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)

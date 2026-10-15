"""Self test of the UI audit driver (tests/ui_audit.py) against the example apps of labconstrictor-tools: the known checks pass, a control
that is not in the control table fails, and a broken control makes its check fail while the audit goes on (docs/UI_AUDIT.md).
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import _paths  # noqa: F401  (must come first)
import numpy as np
import tifffile
import ui_audit_runs
from _paths import HOME
from qtpy.QtCore import QTimer
from qtpy.QtWidgets import QMessageBox, QPushButton, QWidget
from ui_audit import audit
from ui_audit_core import Config
from ui_audit_watch import supervise

report: dict[str, bool] = {}
failures: list[str] = []


def expect(name: str, condition: object, detail: object = "") -> None:
    report[name] = bool(condition)
    if not condition:
        failures.append("%s %s" % (name, detail))


def make_synthetic_tests(folder: Path) -> Path:
    """An lc_tests folder for the synthetic app: a first case per tool (a cancel case for `slow`, a declared failure for `explode`)."""
    fixtures = folder / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "tracks.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    tifffile.imwrite(fixtures / "plane.tif", np.arange(64, dtype=np.uint16).reshape(8, 8))
    (fixtures / "note.txt").write_text("hello", encoding="utf-8")
    cases = [
        {"tool": "scalar_echo", "inputs": {"a": 2.0, "b": 3.5}, "expect": {"results": {"values": {"sum": 5.5}}}},
        {"tool": "slow", "inputs": {"seconds": 0.6, "steps": 3}, "expect": {"progress_events_min": 3}},
        {"tool": "slow", "inputs": {"seconds": 20, "steps": 40}, "cancel_after_s": 1.0},
        {"tool": "explode", "expect": {"status": "FAILED", "code": "expected_failure", "message_contains": "always fails"}},
        {"tool": "table_sum", "inputs": {"tab": "fixtures/tracks.csv"}, "expect": {"results": {"values": {"total": 10.0}}}},
        {"tool": "image_stats", "inputs": {"image": "fixtures/plane.tif"}, "expect": {"results": {"values": {"dtype": "uint16"}}}},
        {"tool": "plane_mean", "inputs": {"image": "fixtures/plane.tif"}, "expect": {"results": {"values": {"mean": 31.5}}}},
        {"tool": "unicode_echo"},
        {"tool": "path_info", "inputs": {"some_file": "fixtures/note.txt"}, "expect": {"results": {"values": {"size": 5}}}},
        {"tool": "kitchen_sink", "inputs": {"required_string": "x", "image": "fixtures/plane.tif", "count": 2, "scale": 0.5},
         "expect": {"results": {"rows": {"rows": 2}}}},
    ]  # fmt: skip
    (folder / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    (folder / "no_case.json").write_text(
        json.dumps({"stubborn": "blocks on purpose; its cancel is the host's kill test"}), encoding="utf-8"
    )
    return folder


def make_interactions_tests(folder: Path) -> Path:
    """The same for the `interactions` app: points, labels, outlines, messages, a table, a channel chooser, a ChoicesFrom dropdown.
    blobs.tif is calibrated (ImageJ unit um, 2 pixels per um: 0.5 um per pixel), so the placement of results is asserted from its tags.
    """
    fixtures = folder / "fixtures"
    fixtures.mkdir(parents=True)
    tifffile.imwrite(
        fixtures / "blobs.tif", BLOBS, imagej=True, resolution=(2.0, 2.0), metadata={"unit": "um"}
    )
    stack = np.stack([BLOBS, BLOBS // 2, BLOBS // 4]).astype(np.uint8)
    tifffile.imwrite(fixtures / "three_channels.tif", stack, imagej=True, metadata={"axes": "CYX"})
    cases = [
        {"tool": "list_shapes", "expect": {"results": {"values": {"choices": ["square", "bar", "dot"]}}}},
        {"tool": "show_shape"},
        {"tool": "find_bright_spots", "inputs": {"image": "fixtures/blobs.tif"}, "expect": {"results": {"summary": {"contains": "Found **61**"}}}},
        {"tool": "outline_blobs", "inputs": {"image": "fixtures/blobs.tif"}, "expect": {"results": {"summary": {"contains": "Outlined **2**"}}}},
        {"tool": "channel_mean", "inputs": {"image": "fixtures/three_channels.tif"}},
        {"tool": "check_installation"},
    ]  # fmt: skip
    (folder / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    return folder


def make_quick_tests(folder: Path, cases: list[dict[str, Any]], others: list[str]) -> Path:
    """An lc_tests folder with the given cases; `others` declared in no_case.json (a short audit for the seeded failures)."""
    folder.mkdir(parents=True)
    tifffile.imwrite(folder / "plane.tif", np.arange(64, dtype=np.uint16).reshape(8, 8))
    (folder / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    (folder / "no_case.json").write_text(
        json.dumps({t: "not run in this short audit" for t in others}), encoding="utf-8"
    )
    return folder


BLOBS = np.zeros((32, 32), np.uint16)
BLOBS[4:9, 4:9] = 1000
BLOBS[20:26, 18:24] = 900
SYNTHETIC = [
    "kitchen_sink",
    "slow",
    "stubborn",
    "explode",
    "scalar_echo",
    "table_sum",
    "image_stats",
    "unicode_echo",
    "path_info",
    "plane_mean",
]
SCALAR = {
    "tool": "scalar_echo",
    "inputs": {"a": 2.0, "b": 3.5},
    "expect": {"results": {"values": {"sum": 5.5}}},
}
PANEL = ["run", "cancel", "details", "copy_as_command", "copy_terminal_command", "copy_python_snippet", "rescan_apps", "restart_worker",
         "keep_the_worker_running", "app_chooser", "tool_chooser"]  # fmt: skip


def run_audit(cfg: Config, hook: Any = None) -> tuple[int, dict[str, str], dict[str, Any]]:
    """Run the driver; (red count, printed id -> status (CHECK PASS/FAIL, NOTE), the matrix of the first app). Prints the lines."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        red = audit(cfg, hook)
    lines = [x for x in out.getvalue().splitlines() if x.startswith(("CHECK ", "NOTE "))]
    print("\n".join(x[:230] for x in lines))
    status = {x.split()[1]: (x.split()[2] if x.startswith("CHECK") else "NOTE") for x in lines}
    matrix = json.loads((cfg.shots / ("matrix_ui_napari_%s.json" % cfg.apps[0])).read_text(encoding="utf-8"))
    return red, status, matrix


def detail_of(matrix: dict[str, Any], cid: str) -> str:
    return next((r["detail"] for r in matrix["rows"] if r["id"] == cid), "(no row)")


def row_status(matrix: dict[str, Any], cid: str) -> str:
    return next((r["status"] for r in matrix["rows"] if r["id"] == cid), "MISSING")


work = Path(tempfile.mkdtemp(prefix="lc_ui_audit_"))
synthetic, interactions = make_synthetic_tests(work / "s_tests"), make_interactions_tests(work / "i_tests")
subprocess.run(
    [sys.executable, "-m", "labconstrictor_tools", "register", "--name", "interactions", "--prefix", sys.prefix,
     "--module", "labconstrictor_tools.examples.interactions", "--version", "0.0"],
    check=True, capture_output=True,
)  # fmt: skip

# ---- 1. two apps, everything, against the real example apps -----------------------------------------------------------------------
placed: dict[str, dict[str, Any]] = {}


def watch(widget: Any) -> None:
    """Read the result layers the moment each run is shown: the independent record the placement assertions below use."""

    def snap(task: Any) -> None:
        placed[task.tool_id] = {
            layer.name: (tuple(layer.scale), tuple(layer.translate), np.asarray(layer.data).copy())
            for layer in widget.viewer.layers
        }

    widget._signals.done.connect(snap)


cfg = Config(
    HOME,
    ["synthetic", "interactions"],
    {"synthetic": synthetic, "interactions": interactions},
    work / "shots",
    "listed",
    120.0,
)
red, st, matrix = run_audit(cfg, watch)
itools = [
    "list_shapes",
    "show_shape",
    "find_bright_spots",
    "outline_blobs",
    "channel_mean",
    "check_installation",
]
expect("multi_lists_and_switch", all(st.get(c) == "PASS" for c in ("ui_napari_multi_lists_synthetic", "ui_napari_multi_lists_interactions", "ui_napari_multi_switch_synthetic_interactions")), st)  # fmt: skip
expect(
    "controls_all_known_passes",
    st.get("ui_napari_controls_all_known") == "PASS",
    detail_of(matrix, "ui_napari_controls_all_known"),
)
expect("panel_controls_pass", all(st.get("ui_napari_panel_" + c) == "PASS" for c in PANEL), [x for x in st if "_panel_" in x and st[x] != "PASS"])  # fmt: skip
forms_ok = all(
    st.get("ui_napari_form_%s_%s" % (t, k)) == "PASS"
    for t in SYNTHETIC + itools
    for k in ("opens", "controls")
)
expect(
    "forms_of_every_tool_pass",
    forms_ok,
    [x for x in st if "_form_" in x and st[x] != "PASS"],
)
runs_ok = all(
    st.get("ui_napari_run_" + t) == "PASS" for t in SYNTHETIC + itools if t not in ("stubborn", "explode")
)
expect("runs_pass", runs_ok, [(x, st[x]) for x in st if "_run_" in x and st[x] != "PASS"])
expect("declared_and_failure_only_tools_are_human", row_status(matrix, "ui_napari_run_stubborn") == "HUMAN" and row_status(matrix, "ui_napari_run_explode") == "HUMAN", detail_of(matrix, "ui_napari_run_explode"))  # fmt: skip
expect("screens_pass", all(st.get("ui_napari_screens_" + t) == "PASS" for t in SYNTHETIC + itools if t not in ("stubborn", "explode")), [x for x in st if "_screens_" in x and st[x] != "PASS"])  # fmt: skip
expect("nothing_is_red", sorted(r["id"] for r in matrix["rows"] if r["status"] in ("FAIL", "NOT_RUN")) == [], [r["id"] for r in matrix["rows"] if r["status"] in ("FAIL", "NOT_RUN")])  # fmt: skip
ROW_FIELDS = {
    "id",
    "family",
    "host",
    "app",
    "tool",
    "control",
    "status",
    "detail",
    "seconds",
    "screenshot",
    "ts",
}
expect("matrix_schema", all(set(r) >= ROW_FIELDS and r["family"] == "ui" and r["host"] == "napari" for r in matrix["rows"]) and {"host", "app", "family", "host_version", "started", "finished", "expected", "rows"} == set(matrix) and matrix["expected"] == len(json.loads((cfg.shots / "expected_napari_synthetic.json").read_text())), sorted(matrix))  # fmt: skip
expect(
    "matrix_finished_and_small",
    matrix["finished"] is not None
    and (cfg.shots / "matrix_ui_napari_synthetic.json").stat().st_size < 400_000,
)
expect(
    "expected_file_written",
    set(json.loads((cfg.shots / "expected_napari_synthetic.json").read_text()))
    <= {r["id"] for r in matrix["rows"]},
)
expect("one_matrix_per_app", (cfg.shots / "matrix_ui_napari_interactions.json").is_file())
expect("screenshots_on_disk", (cfg.shots / "napari/synthetic/scalar_echo_after_run.png").is_file() and (cfg.shots / "napari/interactions/find_bright_spots_form.png").is_file())  # fmt: skip
# placement, from the layer data the run produced and the fixture's own tags (0.5 um per pixel), not from any panel state
spots = placed.get("find_bright_spots", {}).get("interactions:spots")
blob_pixels = BLOBS > 0
expect("points_are_calibrated_and_on_the_blobs", spots is not None and np.allclose(spots[0][-2:], 0.5) and np.allclose(spots[1][-2:], 0) and len(spots[2]) > 0 and all(blob_pixels[round(y), round(x)] for y, x in spots[2][:, -2:]), spots and spots[:2])  # fmt: skip
mask = placed.get("outline_blobs", {}).get("interactions:blobs")
expect("labels_are_calibrated_cover_the_blobs_only", mask is not None and np.allclose(mask[0][-2:], 0.5) and mask[2].shape == BLOBS.shape and int(mask[2].max()) == 2 and bool(((mask[2] > 0) == blob_pixels).all()), mask and mask[:2])  # fmt: skip

# ---- 2. negative controls: every seeded failure goes red, the audit goes on ---------------------------------------------------------
quick = make_quick_tests(work / "q1", [SCALAR], [t for t in SYNTHETIC if t != "scalar_echo"])


def seeded_controls(widget: Any) -> None:
    widget.stray = QPushButton("Stray button", widget)  # an extra control
    widget.layout().addWidget(widget.stray)
    widget.layout().removeWidget(widget.restart_button)  # a removed control
    widget.restart_button.setParent(None)
    cover = QWidget(
        widget
    )  # a covered button: a red panel that follows the Rescan button wherever the layout puts it
    cover.setStyleSheet("background: red")
    button = widget.rescan_button

    def follow() -> None:
        cover.setGeometry(button.rect().translated(button.mapTo(widget, button.rect().topLeft())))
        cover.show()
        cover.raise_()

    follower = QTimer(widget)
    follower.timeout.connect(follow)
    follower.start(100)
    widget.cover, widget.follower = cover, follower


red1, st1, m1 = run_audit(
    Config(HOME, ["synthetic"], {"synthetic": quick}, work / "seed1", "listed", 120.0), seeded_controls
)
d = detail_of(m1, "ui_napari_controls_all_known")
expect(
    "seed_extra_control_goes_red",
    st1.get("ui_napari_controls_all_known") == "FAIL" and "Stray button" in d,
    d,
)
expect("seed_removed_control_goes_red", "restart_worker" in d and "not in the widget tree" in d, d)
expect("seed_covered_button_goes_red", st1.get("ui_napari_panel_rescan_apps") == "FAIL" and "cannot be clicked" in detail_of(m1, "ui_napari_panel_rescan_apps"), detail_of(m1, "ui_napari_panel_rescan_apps"))  # fmt: skip
expect(
    "seed_audit_went_on",
    st1.get("ui_napari_run_scalar_echo") == "PASS" and st1.get("ui_napari_panel_tool_chooser") == "PASS",
    st1,
)

bad = [SCALAR | {"expect": {"results": {"values": {"sum": 99.0}}}}, {"tool": "explode", "expect": {"results": {}}},
       {"tool": "kitchen_sink", "inputs": {"required_string": "x", "image": "plane.tif", "scale": 0.5}, "expect": {"results": {"doubled": {"mean": 999}}}}]  # fmt: skip
bad_tests = make_quick_tests(
    work / "q2", bad, [t for t in SYNTHETIC if t not in ("scalar_echo", "explode", "kitchen_sink")]
)


def seeded_dialog(widget: Any) -> None:
    widget.rescan_button.clicked.connect(
        lambda *_: QMessageBox(widget).exec()
    )  # an error box nobody asked for


red2, st2, m2 = run_audit(
    Config(HOME, ["synthetic"], {"synthetic": bad_tests}, work / "seed2", "listed", 120.0), seeded_dialog
)
expect(
    "seed_wrong_value_goes_red",
    st2.get("ui_napari_run_scalar_echo") == "FAIL",
    detail_of(m2, "ui_napari_run_scalar_echo"),
)
expect("seed_failing_run_goes_red", st2.get("ui_napari_run_explode") == "FAIL" and "FAILED" in detail_of(m2, "ui_napari_run_explode"), detail_of(m2, "ui_napari_run_explode"))  # fmt: skip
expect(
    "seed_wrong_image_result_goes_red",
    st2.get("ui_napari_run_kitchen_sink") == "FAIL",
    detail_of(m2, "ui_napari_run_kitchen_sink"),
)
expect("seed_unexpected_dialog_goes_red", st2.get("ui_napari_panel_rescan_apps") == "FAIL" and "unexpected modal dialog" in detail_of(m2, "ui_napari_panel_rescan_apps"), detail_of(m2, "ui_napari_panel_rescan_apps"))  # fmt: skip

undeclared = make_quick_tests(
    work / "q3", [SCALAR], [t for t in SYNTHETIC if t not in ("scalar_echo", "slow")]
)  # slow: no case, no reason
red3, st3, m3 = run_audit(
    Config(HOME, ["synthetic"], {"synthetic": undeclared}, work / "seed3", "listed", 120.0)
)
expect("seed_tool_without_case_or_reason_goes_red", st3.get("ui_napari_run_slow") == "FAIL" and "no_case.json" in detail_of(m3, "ui_napari_run_slow"), detail_of(m3, "ui_napari_run_slow"))  # fmt: skip

# a step that never ran is NOT_RUN (red), found through the expected file
original_order = ui_audit_runs.tool_order
ui_audit_runs.tool_order = lambda ctx: original_order(ctx)[:1]
red4, st4, m4 = run_audit(Config(HOME, ["synthetic"], {"synthetic": quick}, work / "seed4", "listed", 120.0))
ui_audit_runs.tool_order = original_order
missing = [
    r
    for r in m4["rows"]
    if r["status"] == "NOT_RUN" and r["detail"].startswith("declared in the expected file")
]
expect(
    "seed_missing_steps_are_not_run_and_red",
    len(missing) >= 9 * 4 and red4 >= len(missing),
    (len(missing), red4),
)

# a hung tool: the run check times out (FAIL) and the audit goes on to the other checks
hang = make_quick_tests(work / "q7", [{"tool": "stubborn"}], [t for t in SYNTHETIC if t != "stubborn"])
red7, st7, m7 = run_audit(Config(HOME, ["synthetic"], {"synthetic": hang}, work / "seed7", "listed", 8.0))
expect("seed_hung_tool_times_out_and_goes_red", st7.get("ui_napari_run_stubborn") == "FAIL" and "did not finish" in detail_of(m7, "ui_napari_run_stubborn"), detail_of(m7, "ui_napari_run_stubborn"))  # fmt: skip
expect("seed_hung_tool_audit_went_on", st7.get("ui_napari_panel_tool_chooser") == "PASS" and st7.get("ui_napari_panel_cancel") == "PASS" and m7["finished"] is not None, st7)  # fmt: skip


def make_blob_tests(folder: Path, cases: list[dict[str, Any]]) -> Path:
    """An lc_tests folder for the `interactions` app with the calibrated blobs fixture; the tools without a case are declared."""
    folder.mkdir(parents=True)
    tifffile.imwrite(folder / "blobs.tif", BLOBS, imagej=True, resolution=(2.0, 2.0), metadata={"unit": "um"})
    cases_file = [c | {"inputs": {"image": "blobs.tif"}} for c in cases]
    (folder / "cases.json").write_text(json.dumps(cases_file), encoding="utf-8")
    (folder / "no_case.json").write_text(json.dumps({t: "not run in this short audit" for t in ITOOLS if t not in {c["tool"] for c in cases}}), encoding="utf-8")  # fmt: skip
    return folder


ITOOLS = [
    "list_shapes",
    "show_shape",
    "find_bright_spots",
    "outline_blobs",
    "channel_mean",
    "check_installation",
]
blob_tests = make_blob_tests(
    work / "q8",
    [{"tool": "find_bright_spots", "expect": {"results": {"summary": {"contains": "Found **61**"}}}}],
)


def vanishing(widget: Any) -> None:
    """The result is shown and then removed: a blank result."""
    widget._signals.done.connect(lambda task: widget.viewer.layers.clear())


def misplaced(widget: Any) -> None:
    """The result is shown on the wrong frame: its calibration is dropped."""

    def drop(task: Any) -> None:
        for layer in widget.viewer.layers:
            layer.scale = (1, 1)

    widget._signals.done.connect(drop)


cfg_blob = Config(HOME, ["interactions"], {"interactions": blob_tests}, work / "seed8", "listed", 120.0)
red8, st8, m8 = run_audit(cfg_blob)
expect("blob_run_passes_in_layer_mode", st8.get("ui_napari_run_find_bright_spots") == "PASS", detail_of(m8, "ui_napari_run_find_bright_spots"))  # fmt: skip
red9, st9, m9 = run_audit(
    Config(HOME, ["interactions"], {"interactions": blob_tests}, work / "seed9", "listed", 120.0, "file")
)
expect("blob_run_passes_in_file_mode_with_identity_frame", st9.get("ui_napari_run_find_bright_spots") == "PASS", detail_of(m9, "ui_napari_run_find_bright_spots"))  # fmt: skip
red10, st10, m10 = run_audit(
    Config(HOME, ["interactions"], {"interactions": blob_tests}, work / "seed10", "listed", 120.0), vanishing
)
expect("seed_blank_result_goes_red", st10.get("ui_napari_run_find_bright_spots") == "FAIL" and "spots" in detail_of(m10, "ui_napari_run_find_bright_spots"), detail_of(m10, "ui_napari_run_find_bright_spots"))  # fmt: skip
red11, st11, m11 = run_audit(
    Config(HOME, ["interactions"], {"interactions": blob_tests}, work / "seed11", "listed", 120.0), misplaced
)
expect("seed_wrong_placement_goes_red", st11.get("ui_napari_run_find_bright_spots") == "FAIL" and "layer scale" in detail_of(m11, "ui_napari_run_find_bright_spots"), detail_of(m11, "ui_napari_run_find_bright_spots"))  # fmt: skip

# the outer watchdog: a frozen Qt thread and a dead process each end with the crash row, NOT_RUN rows for the rest, and a finished matrix
CHILD = work / "child.py"
CHILD.write_text(
    "import os, sys, time\n"
    "sys.path.insert(0, %r)\n"
    "import ui_audit\n"
    "from ui_audit_core import config_from_env\n"
    "cfg = config_from_env(os.environ)\n"
    "mode = os.environ['CHILD_MODE']\n"
    "def hook(widget):\n"
    "    if mode == 'freeze':\n"
    "        widget.rescan_button.clicked.connect(lambda *_: time.sleep(10000))\n"
    "    else:\n"
    "        widget.rescan_button.clicked.connect(lambda *_: os._exit(139))\n"
    "ui_audit.audit(cfg, hook)\n" % str(Path(__file__).resolve().parent),
    encoding="utf-8",
)
for mode in ("freeze", "die"):
    shots = work / ("watch_" + mode)
    env = dict(os.environ, LC_APP="synthetic", LC_APP_TESTS=str(quick), LC_EXPECT_NAPARI="listed", LC_SHOTS=str(shots), LC_UI_TOOL_TIMEOUT="60", CHILD_MODE=mode)  # fmt: skip
    for attempt in range(
        3
    ):  # a Qt abort at start-up (seen under CPU load, exit -6) never reached the seeded freeze or death: try again
        code = supervise([sys.executable, str(CHILD)], shots, ["synthetic"], 45.0, env)
        if (shots / "expected_napari_synthetic.json").is_file():
            break
        print("watchdog %s: the child died before it started (attempt %d), run again" % (mode, attempt + 1))
    doc = json.loads((shots / "matrix_ui_napari_synthetic.json").read_text(encoding="utf-8"))
    ids = {r["id"]: r for r in doc["rows"]}
    expected = json.loads((shots / "expected_napari_synthetic.json").read_text(encoding="utf-8"))
    expect("watchdog_%s_exit_code_2" % mode, code == 2, code)
    expect(
        "watchdog_%s_crash_row" % mode,
        ids.get("ui_napari_driver_crashed", {}).get("status") == "FAIL",
        sorted(ids)[:5],
    )
    expect("watchdog_%s_every_expected_id_has_a_row" % mode, all(i in ids for i in expected) and doc["finished"] is not None, [i for i in expected if i not in ids])  # fmt: skip
    expect("watchdog_%s_rows_before_the_crash_kept" % mode, ids.get("ui_napari_app_listed", {}).get("status") == "PASS" and ids.get("ui_napari_run_scalar_echo", {}).get("status") == "PASS", sorted(ids)[:5])  # fmt: skip
    print(
        "watchdog %s: exit %s, %d rows, %s"
        % (mode, code, len(doc["rows"]), ids["ui_napari_driver_crashed"]["detail"][:120])
    )

# not_listed: an absent app passes with one check and a NOTE line; a listed one fails
red5, st5, _ = run_audit(Config(HOME, ["nothere"], {}, work / "shots5", "not_listed", 120.0))
expect(
    "not_listed_one_check_and_a_note",
    red5 == 0 and st5.get("ui_napari_not_listed") == "PASS" and len(st5) == 3,
    st5,
)
red6, st6, _ = run_audit(Config(HOME, ["synthetic"], {}, work / "shots6", "not_listed", 120.0))
expect("not_listed_fails_for_a_listed_app", red6 == 1 and st6.get("ui_napari_not_listed") == "FAIL", st6)

print(json.dumps(report, indent=2))
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)

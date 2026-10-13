"""The plugin's cleanup against the REAL Tools `prune` and a private LC_HOME: after real napari runs the subprocess removes only what the
policy allows (owned, finished, beyond the newest 50 run records / 20 results) and leaves every foreign, legacy, unfinished, renamed or
linked folder alone (SPEC_WRONG_SCIENCE 3.3; the host itself deletes nothing: test_retention_markers.py)."""

import os

import _paths  # noqa: F401  (must come first)
import _runtools as R
import numpy as np
from _harness import expect, finish, viewer, widget
from labconstrictor_tools import conformance

w = widget
M = conformance.load()["wrong_science"]["retention"]["markers"]
R.use_real()
A = viewer.add_image(np.ones((8, 8), np.uint8), name="A")

home = R.HOME
LOCK, OWNER, DONE = M["lock_file"], M["owner_file"], M["done_file"]

# ---- what is already there ------------------------------------------------------------------------------------------------------
for root, foreign in (("results", "20261008T120000_reanalysis_backup"), ("runs", "0000_keep_this_analysis")):
    (home / root / foreign).mkdir(parents=True, exist_ok=True)
    (home / root / foreign / "x.txt").write_text("keep")
legacy = {}
for root, count in (("results", 30), ("runs", 60)):
    for i in range(count):
        name = "20250101T0000%02d_%06d_old_tool" % (i % 60, i)
        folder = home / root / name
        folder.mkdir()
        (folder / "sentinel.txt").write_text("legacy-" + name)
        legacy[(root, name)] = "legacy-" + name
R.make_owned("results", "result", 25, "20200101T000000_")
R.make_owned("runs", "run", 60, "2020")
R.make_owned("results", "result", 1, "19990101T000000_crashed", done=False, base_year=1999)
R.make_owned("runs", "run", 1, "1999_crashed", done=False, base_year=1999)
crashed = {("results", "19990101T000000_crashed0000_old_x"), ("runs", "1999_crashed0000_old_x")}

# a renamed copy of an owned folder (its marker names another folder) and a symlink to a folder that has markers (RET-05, RET-06)
import shutil  # noqa: E402

copy = home / "results" / "20260101T000000_000000_app_copy"
shutil.copytree(home / "results" / "20200101T000000_0000_old_x", copy)
outside = R.WORK / "outside_target"
shutil.copytree(home / "results" / "20200101T000000_0001_old_x", outside)
(outside / OWNER).write_text(
    (outside / OWNER).read_text().replace("20200101T000000_0001_old_x", "linked_folder")
)
link = home / "results" / "linked_folder"
try:
    os.symlink(outside, link, target_is_directory=True)
    linked = True
except (OSError, NotImplementedError):
    linked = False  # no right to make a symlink here: reported as unsupported below, never as passed

before_runs = {p.name for p in R.folders("runs")}
before_results = {p.name for p in R.folders("results")}


def owned_done(root):
    """Names of the owned, finished folders of a root, oldest first by their marker."""
    found = []
    for p in R.folders(root):
        if p.is_symlink() or not (p / OWNER).is_file() or not (p / DONE).is_file():
            continue
        owner = R.read_json(p / OWNER)
        if owner.get("name") == p.name:
            found.append((owner["created"], p.name))
    return [name for _, name in sorted(found)]


owned_runs_before, owned_results_before = owned_done("runs"), owned_done("results")
expect("setup_run_records", len(owned_runs_before) == 60, len(owned_runs_before))
expect("setup_results", len(owned_results_before) == 25, len(owned_results_before))

# ---- real runs: three that make only a run record, two that also keep a file ----------------------------------------------------
R.pick("Echo")
for _ in range(3):
    R.quick_run()
    R.join_prune()
R.pick("Report file")
for _ in range(2):
    R.quick_run()
    R.join_prune()
new_runs = sorted(set(p.name for p in R.folders("runs")) - before_runs)
new_results = sorted(set(p.name for p in R.folders("results")) - before_results)
expect("five_new_run_records_made", len(new_runs) == 5, new_runs)
expect("two_new_results_folders_made", len(new_results) == 2, new_results)

# ---- what the real prune did -----------------------------------------------------------------------------------------------------
runs_now, results_now = owned_done("runs"), owned_done("results")
expect("runs_pruned_to_50", len(runs_now) == 50, len(runs_now))
expect("runs_the_five_new_ones_are_kept", all(n in runs_now for n in new_runs), (new_runs, runs_now[-6:]))
expect(
    "runs_the_oldest_by_created_went",
    [n for n in owned_runs_before if n not in runs_now] == owned_runs_before[:15],
    [n for n in owned_runs_before if n not in runs_now][:3],
)
expect("results_pruned_to_20", len(results_now) == 20, len(results_now))
expect("results_the_two_new_ones_are_kept", all(n in results_now for n in new_results), new_results)
expect(
    "results_the_oldest_by_created_went",
    [n for n in owned_results_before if n not in results_now] == owned_results_before[:7],
    [n for n in owned_results_before if n not in results_now][:3],
)
expect(
    "HRET-01_foreign_folders_intact",
    all(
        (home / root / name / "x.txt").read_text() == "keep"
        for root, name in (
            ("results", "20261008T120000_reanalysis_backup"),
            ("runs", "0000_keep_this_analysis"),
        )
    ),
)
expect(
    "RET-07_legacy_folders_without_markers_intact",
    all((home / root / name / "sentinel.txt").read_text() == text for (root, name), text in legacy.items()),
)
expect(
    "RET-12_unfinished_owned_folders_intact",
    all((home / root / name / "sentinel.txt").is_file() for root, name in crashed),
)
expect("RET-06_renamed_copy_intact", (copy / "sentinel.txt").is_file())
if linked:
    expect(
        "RET-05_symlink_and_its_target_intact",
        link.is_symlink() and (outside / "sentinel.txt").is_file() and (outside / OWNER).is_file(),
    )
else:
    print("RET-05 symlink: unsupported here (cannot create a symlink)")
expect("prune_took_the_lock_file", (home / LOCK).exists())
expect(
    "no_half_deleted_leftovers",
    not [
        p
        for root in ("results", "runs")
        for p in (home / root).iterdir()
        if p.name.startswith(M["deleting_prefix"])
    ],
)
expect("the_runs_still_work_after_prune", w.status.text().startswith("✔ done"), w.status.text())
expect(
    "the_kept_report_files_exist",
    all((home / "results" / n / "report.txt").read_text() == "data" for n in new_results),
)
finish()

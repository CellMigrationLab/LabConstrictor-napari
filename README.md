# napari-labconstrictor

One generic napari dock widget for **every installed LabConstrictor app**. Pick an app and a tool; the form is generated from the
tool's declared schema (see [LabConstrictor-Tools](https://github.com/CellMigrationLab/LabConstrictor-Tools)). The tool runs in the
app's own Python environment in a separate process, so napari never imports the app's packages and apps with conflicting
dependencies coexist.

![widget](docs/screenshot.png)

## Install
In the napari environment (**Python >= 3.11**: napari 0.8 and later need it; this plugin is tested with napari 0.9 on Python 3.11):

    pip install https://github.com/CellMigrationLab/LabConstrictor-Tools/archive/refs/heads/main.zip      # the runtime (not on PyPI yet)
    pip install https://github.com/CellMigrationLab/napari-labconstrictor/archive/refs/heads/main.zip

(Source archives: no `git` program is needed. With git you can use `git+https://github.com/CellMigrationLab/<repository>` instead.)

The plugin installs no Qt backend (it uses `qtpy`, so it runs on the one your napari has). If you install napari yourself, choose a
**Qt6** backend: `pip install "napari[pyqt6]"` or `pip install "napari[pyside6]"` (both tested here on Linux). **PyQt5 is deprecated**
by napari since 0.8.0 (14 July 2026), which plans to drop Qt5 support; it still works for now, but do not start new environments with it.

Then **Plugins > LabConstrictor tools**. The widget lists the apps registered on this machine (the LabConstrictor installer
registers each app; for a manual registration see the Tools repository: `labconstrictor-tools register ...`).
`labconstrictor-tools doctor` shows what is registered and why an app might be skipped.

## What it does
* **Forms from schemas**: numbers with ranges and units, choices, checkboxes, file and folder pickers. A value that is optional and has no default (a seed, a time limit) has a **"set" checkbox**: unticked, it is greyed out and the tool receives `None`.
* **Longer forms made readable**: parameters of a `group` sit under a bold heading, `advanced` ones behind a **"Show advanced settings"** box (closed by default), and settings that do not apply to the current choice (`enabled_when`) are greyed out.
* **Image inputs from an open layer *or* a file**: each image parameter has a layer chooser and an "or file" row; a chosen file wins.
  TIFF/OME-TIFF always, other formats if the app has `imageio`. Tables are chosen as CSV files.
* **Calibration**: a pixel-size field linked to an image follows the layer (units converted to micrometres) or the TIFF header.
* **Typed results**: images/labels become layers, tables a table dock, alignments an affine-placed layer, values the status line.
* **"No match" is a notice, not an error**: a tool that fails with the code `no_match` / `no_result` is shown as a warning line, not a red cross.
* **Progress and Cancel**; a tool that ignores Cancel has its worker killed after 3 s. Optional worker reuse for fast repeat runs.
* **When something fails**: the status line says what, **Details...** shows the error, traceback, worker output and log tail, and
  everything is in `~/.labconstrictor/logs/labconstrictor.log` (`labconstrictor-tools support-bundle` zips it for a bug report).
  Every run also leaves `~/.labconstrictor/runs/<time>_<app>_<tool>/run.json`.

## Development and tests
    pip install -e ".[test-pyqt6]"                 # also install labconstrictor-tools (see above). ONE Qt backend per environment:
    pip install -e ".[test-pyside6]"               #   test-pyqt6 or test-pyside6 (recommended), never both in one environment
    pip install -e ".[test-pyqt5]"                 #   DEPRECATED legacy (Windows/macOS CI until their Qt6 jobs exist); to be retired
    cd tests
    python test_units.py
    QT_QPA_PLATFORM=offscreen python test_results_and_workers.py   # per-axis calibration, result display limits, worker cache
    xvfb-run -a python test_widget.py              # on Linux without a display; elsewhere run directly
    xvfb-run -a python test_file_sources.py
    xvfb-run -a python test_run_state.py
    xvfb-run -a python test_presentation.py        # groups, advanced toggle, enabled_when
    xvfb-run -a python test_interactions.py        # ChoicesFrom dropdown, ClearAfterRun, Collapsed accordion, Replace
    xvfb-run -a python test_widgets.py             # Widget("slider") and Widget("radio")
    xvfb-run -a python test_copy_command.py        # Copy as command: terminal line and Python snippet, run for real
    xvfb-run -a python test_shapes.py              # ShapesOut: GeoJSON outlines as a shapes layer
    xvfb-run -a python test_region.py              # RegionOf: use the selection as the region (labels 1..N), refusals
    xvfb-run -a python test_scroll.py              # a form taller than the dock scrolls; Run/status stay in view
    xvfb-run -a python test_messages_points.py     # message and points outputs with the example app of labconstrictor-tools
    xvfb-run -a python test_channels.py            # PickChannel: channel chooser for RGB layers and multi-channel TIFF files
    xvfb-run -a python test_widget_hardening.py    # failed starts, unshowable results, full disk, duplicate labels, optional yes/no
    xvfb-run -a python test_parity_dimensions.py   # parity with the other hosts: a stack into a 2D tool is refused with the worker's sentence
    xvfb-run -a python test_parity_worker_close.py # a worker gets 10 s to exit when closed
    xvfb-run -a python test_parity_copy_notes.py   # Copy as command: channel and selection notes, in the order of the other hosts
    xvfb-run -a python test_parity_messages.py     # missing_parameter / file_not_found / channel sentences before a run
    xvfb-run -a python test_parity_results.py      # outline cap counts features; the sentence for a result type this version does not know
    xvfb-run -a python test_parity_region.py       # RegionOf: refused for an image given as a file; at most 65 535 shapes, 16 bit
    xvfb-run -a python test_parity_points_frame.py # points/outlines without apply_to go on the first image input
    xvfb-run -a python test_qt_backend.py          # Plugins menu entry opens the dock; scrolling, results table dock, status, Details dialog on this Qt binding
    scripts/check_qt_backend.sh pyqt6|pyside6      # the same in a brand-new virtualenv with only that backend (Linux, needs xvfb-run)
    python test_harness_exit.py                    # a test script's exit code still carries its verdict (os._exit in tests/_paths.py)

CI runs every `tests/test_*.py` (a loop, not a list): on Linux in two separate environments, PyQt6 and PySide6 (`LC_EXPECT_QT`
makes `test_qt_backend.py` fail if the wrong binding was loaded). Windows and macOS still run the deprecated PyQt5 until a later pull
request adds Qt6 jobs there (issue #41 stays open for them).

Under a PyQt binding each script leaves through `os._exit` (`tests/_paths.py`): PyQt's own exit handler crashes the interpreter with a
napari window open, after the verdict is printed. Measured on Linux (napari 0.9.2): PyQt5 about 1 run in 10, **PyQt6 6.11 still
crashes (37 of 60 runs of `test_parity_region.py`)**, PySide6 6.12 did not (0 of 60), so PySide6 exits normally. This is a test-harness
measure only (the exit code still carries the verdict, see `tests/test_harness_exit.py`). To re-check after a PyQt6 update, remove
the `sys.exit = _leave` line and loop one script ~60 times.

The tests register the example app shipped with `labconstrictor-tools` (`labconstrictor_tools.examples.synthetic`) in a private
registry, so no real LabConstrictor app is needed. Real apps are tested in their own repositories.

Layout: `napari_labconstrictor/` = `_widget.py` (the dock widget), `_schema.py` (schema -> magicgui signature), `_results.py`,
`_units.py`, `_workers.py` (worker cache), `napari.yaml` (npe2 manifest).

Status: **testing phase**. Tested on Linux (PyQt6 and PySide6, napari 0.9) under Xvfb; Windows and macOS only with the deprecated PyQt5 so far, and those runs are new: to help, follow the
[human test protocol](https://github.com/CellMigrationLab/LabConstrictor-Tools/blob/main/docs/HUMAN_TEST_PROTOCOL.md). License: MIT.

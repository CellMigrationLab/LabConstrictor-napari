# LabConstrictor for napari

**Run registered Python analysis tools from napari.**

The repository is **LabConstrictor-napari**; the Python package it contains is **napari-labconstrictor** (`pip` name, import `napari_labconstrictor`, plugin name in napari).

Choose an image layer, select an analysis tool and run it. Results come back as napari layers, tables or messages. The analysis itself runs in the application's own Python environment, in a separate process, so you do not need to install its scientific dependencies into napari and applications with conflicting dependencies can coexist.

The plugin provides **one dock widget for all registered LabConstrictor applications**. It builds the controls from each tool's declared schema (see [LabConstrictor-Tools](https://github.com/CellMigrationLab/LabConstrictor-Tools)).

![LabConstrictor tools dock widget](docs/screenshot.png)

## First run: Playground

Install [LabConstrictor Playground](https://github.com/CellMigrationLab/LabConstrictor-Playground) to try the widget without scientific data. Open the LabConstrictor widget and select **Feature tour**.

You can leave its image input unset: the tool then makes a small demonstration image with round blobs, rings and blobs in two parts. It returns a label image, outlines, points, a measurements table and a summary message. Change the threshold and run again: these outputs are marked for replacement, so the second run updates the earlier layers instead of adding new ones.

Playground is a test application, not a validated scientific analysis. Once an application such as NucleiSky or CellTracksColab is installed and registered, its declared tools appear in the same widget.

## Use it with your own data

1. Open an image in napari, or prepare a TIFF/OME-TIFF file.
2. Choose **Plugins > LabConstrictor tools**.
3. Select the registered application and the tool.
4. Choose a layer or a file for each image input. If both are set, **the file wins**.
5. Set the parameters and run. Watch the progress and inspect the results in napari.

### What the form can do

- **Forms from schemas:** numbers with ranges and units, choices, checkboxes, file and folder pickers. Tables are chosen as CSV files.
- **Optional parameters without a default** (for example a seed or a time limit) have a **"set" checkbox**. Unticked, the field is greyed out and the tool receives `None`.
- **Longer forms stay readable:** parameters of a `group` sit under a bold heading, `advanced` ones are behind a **"Show advanced settings"** box (closed by default), and settings that do not apply to the current choice (`enabled_when`) are greyed out. A form taller than the dock scrolls.
- **Images from a layer or a file:** each image input has a layer chooser and an "or file" row. TIFF/OME-TIFF files always work; other formats work if the application's environment has `imageio`.

### Selections, channels and calibration

- **Use a selection:** a tool with a `RegionOf(...)` input gets a **"use the selection" checkbox** (off by default). When ticked, the shapes of the selected Shapes layer are sent as the region (several shapes become labels 1, 2, 3 ...). This is tool-specific; it does not crop every analysis automatically. It needs an open image layer: with an image given as a file the run is refused (see [docs/HOST_FEATURES.md](docs/HOST_FEATURES.md)).
- **Pick a channel:** a tool with `PickChannel()` gets a channel chooser for the colours of an RGB layer or the channels of a TIFF given as a file. The chooser is hidden when there is only one channel.
- **Pixel size:** a pixel-size field linked to an image follows the layer's scale (units converted to micrometres) or the TIFF header. Both axes are read: if the Y and X pixel sizes differ, the status line warns and the tool, which takes one value, receives the X one. A layer whose unit is napari's default `pixel` (or another unit that is not a length) is taken to be in micrometres, and the status line says so. Check the calibration before relying on measurements.

## Results

| Tool result | In napari |
|---|---|
| Image or labels | Image or Labels layer |
| Points or outlines | Points or Shapes layer |
| Table | Table dock |
| Alignment (affine) | Layer placed with the affine transform |
| Message | Text shown below the status line |
| Values or file | Summary in the status line |

A tool can ask for repeated runs to replace earlier results rather than create more layers. Very large results are not shown in full: a result image over 4 GiB is not loaded, a table dock shows at most 100 000 rows and at most 50 000 outlines are drawn (the rest is reported; the tool's own files hold everything).

Long-running tools report progress and respond to **Cancel**; a tool that ignores Cancel has its worker killed after 3 seconds. The option **Keep the worker running between runs (faster repeat runs)** is ticked by default; untick it to start a fresh worker for every run. An idle kept worker is closed after 10 minutes.

If a tool reports that nothing matched (the code `no_match` or `no_result`), the widget shows a notice rather than a red error.

## Install

In the Python environment used by napari (**Python 3.11 or newer**; napari 0.8 and later need it):

```bash
python -m pip install https://github.com/CellMigrationLab/LabConstrictor-Tools/archive/refs/heads/main.zip
python -m pip install https://github.com/CellMigrationLab/LabConstrictor-napari/archive/refs/heads/main.zip
```

Neither is on PyPI yet. These are source archives, so no `git` program is needed (with git you can use `git+https://github.com/CellMigrationLab/<repository>` instead).

The plugin installs no Qt backend: it uses `qtpy` and runs on the one your napari has. If you install napari yourself, we recommend a **Qt6** backend: `python -m pip install "napari[pyqt6]"` or `python -m pip install "napari[pyside6]"`. PyQt5 is not tested here; napari deprecated it in 0.8.0 and plans to drop Qt5 support.

Then start napari and choose **Plugins > LabConstrictor tools**.

You must also install the LabConstrictor application whose tools you want to run. Its installer normally registers it. If nothing appears, inspect the registry:

```bash
labconstrictor-tools list
labconstrictor-tools doctor
```

The widget reads the cached tool descriptions of registered applications, then runs each tool in a worker process in that application's own interpreter.

## Reproduce a run and diagnose failures

The widget can copy the last run as a terminal command or a Python snippet (**Copy as command**). When an input came from an unsaved layer, save the data before expecting that command to reproduce the run from disk.

Failures appear in the status line; **Details...** shows the error, traceback, worker output and the log tail. The shared log is `~/.labconstrictor/logs/labconstrictor.log` by default. `labconstrictor-tools support-bundle` zips diagnostics for a bug report.

### Run records and cleanup

Every run leaves a record, `<LC_HOME>/runs/<time>_<app>_<tool>/run.json` (`LC_HOME` is `~/.labconstrictor` unless the environment variable says otherwise). It holds the app, tool, status, error, inputs, results, timings and the tail of the worker's output.

What the plugin does today about cleanup:

- The plugin writes its run records with the LabConstrictor-Tools library. With the Tools installed from the main archive above (a Tools without the retention feature does not have this), that call marks each record with the owner and done marker files and prunes old run records itself: the newest 50 finished records are kept. Only folders that carry both marker files are ever removed; folders you made yourself, older folders without markers, and folders of a run that has not finished are never touched.
- The plugin does **not** start `labconstrictor-tools prune` itself yet, and it does not write results under `<LC_HOME>/results`: it uses temporary folders for inputs and outputs and removes them after the run (results stay in the viewer). The newest-20 rule for result folders therefore applies to results written by the Tools command line, not to napari runs.
- You can run the cleanup yourself: `labconstrictor-tools prune --dry-run` lists what it would remove and changes nothing; `labconstrictor-tools prune` removes it. The full rules are in section 3 of [SPEC_WRONG_SCIENCE](https://github.com/CellMigrationLab/LabConstrictor-Tools/blob/main/docs/SPEC_WRONG_SCIENCE.md).

## Current status

**Testing phase.** CI runs the full test suite with PySide6 and PyQt6, each in its own environment, on Linux (under a virtual display), Windows and macOS. Tests on real machines by people are still open: the [human test protocol](https://github.com/CellMigrationLab/LabConstrictor-Tools/blob/main/docs/HUMAN_TEST_PROTOCOL.md) explains how to help. Not every host supports every LabConstrictor presentation hint in the same way; this README describes the napari implementation, not a guarantee about Fiji or QuPath.

For more detail, see [napari inputs and results](docs/USING_NAPARI.md).

## Applications

The widget reads registered LabConstrictor tool manifests. You do not need a new napari plugin for every scientific application; its declared tools appear in the same widget.

Try [Playground](https://github.com/CellMigrationLab/LabConstrictor-Playground) for a test image, [Guess the Condition](https://github.com/CellMigrationLab/GuessTheCondition) for blinded image classification or [VLab4Mic](https://github.com/CellMigrationLab/LabConstrictor-VLab4Mic) for microscopy simulations. Other applications include [NucleiSky](https://github.com/CellMigrationLab/NucleiSky) and [CellTracksColab](https://github.com/CellMigrationLab/CellTracksColab_LabConstrictor). See the [Tools repository](https://github.com/CellMigrationLab/LabConstrictor-Tools) for installation links.

These are examples, not a list of applications permitted to connect. Choose tools according to whether they make sense in a layer-based workflow and whether napari provides a useful presentation of their outputs.

## Development

The widget lives in `napari_labconstrictor/_widget.py`, with schema conversion in `_schema.py`, result presentation in `_results.py`, units and calibration in `_units.py`, layer/file export in `_export.py`, the worker cache in `_workers.py` and the npe2 manifest in `napari.yaml`.

Install one Qt backend per environment, through its test extra (never both in one environment), and LabConstrictor-Tools:

```bash
python -m pip install https://github.com/CellMigrationLab/LabConstrictor-Tools/archive/refs/heads/main.zip
python -m pip install -e ".[test-pyqt6]"      # or ".[test-pyside6]"
cd tests
python test_units.py
xvfb-run -a python test_widget.py             # on Linux without a display; elsewhere run directly
xvfb-run -a python test_interactions.py
xvfb-run -a python test_region.py
xvfb-run -a python test_messages_points.py
```

Every `tests/test_*.py` is a standalone script; CI runs them all in a loop (a new test is picked up without editing the workflow). `scripts/check_qt_backend.sh pyqt6|pyside6` repeats the Qt backend check in a brand-new virtualenv (Linux, needs `xvfb-run`). The tests use the synthetic example application of LabConstrictor-Tools in a private registry, so no real scientific application is needed.

CI runs PySide6 and PyQt6 on Linux, Windows and macOS (`LC_EXPECT_QT` makes `test_qt_backend.py` fail if the wrong binding was loaded), plus lint (black, ruff) and a mypy type check.

Under a PyQt binding each test script leaves through `os._exit` (`_leave` in `tests/_paths.py`): PyQt's own exit handler crashed the interpreter with a napari window open after the verdict was printed (measured on Linux with PyQt6 6.11 and napari 0.9.2: 37 of 60 runs of one script; PySide6 6.12: 0 of 60). This is a test-harness workaround only; the exit code still carries the verdict.

Related projects: [Tools](https://github.com/CellMigrationLab/LabConstrictor-Tools) · [Fiji](https://github.com/CellMigrationLab/LabConstrictor-Fiji) · [QuPath](https://github.com/CellMigrationLab/LabConstrictor-QuPath) · [Playground](https://github.com/CellMigrationLab/LabConstrictor-Playground).

License: MIT.

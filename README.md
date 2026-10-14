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
- **Numbers are text, and checked as typed:** an integer or float field is a line of text (no spin box, which would drop a digit, round to its decimals or lose an exponent). A field with no `Min`/`Max` takes integers up to +-9007199254740991 (2^53 - 1) and floats up to +-1e15; a value beyond a limit, declared or the form's own, is refused when Run is pressed with the worker's sentence (`'L' must be <= 9007199254740991`), never clamped, and nothing is sent. So are text that is not a number, `nan` / `inf`, an exponent beyond the double range, and an empty field (`'L' is required: type a number`). Grammar: an integer is a sign and digits; a float is a sign, digits with an optional fraction (or only a fraction) and an optional exponent. A required number with no default starts at the allowed value nearest 0. The number in a `Widget('slider')` readout cannot be typed into.
- **Optional parameters without a default** (for example a seed or a time limit) have a **"set" checkbox**. Unticked, the field is greyed out and the tool receives `None`.
- **Longer forms stay readable:** parameters of a `group` sit under a bold heading, `advanced` ones are behind a **"Show advanced settings"** box (closed by default), and settings that do not apply to the current choice (`enabled_when`) are greyed out. A form taller than the dock scrolls.
- **Images from a layer or a file:** each image input has a layer chooser and an "or file" row. TIFF/OME-TIFF files always work; other formats work if the application's environment has `imageio`.

### Selections, channels and calibration

- **Use a selection:** a tool with a `RegionOf(...)` input gets a **"use the selection" checkbox** (off by default). When ticked, the shapes of the selected Shapes layer are sent as the region (several shapes become labels 1, 2, 3 ...). The shapes are converted into the pixel grid of the image that is sent, through napari's world coordinates and the full transform (scale, translate, rotate, shear, affine) of **both** layers, so the mask covers the pixels you see under the outline even when the Shapes layer and the image have different origins, scales or rotations; the mask has exactly the size of the sent image. This is tool-specific; it does not crop every analysis automatically. It needs an open 2D image layer: with an image given as a file the run is refused, and so is an image whose transform cannot be inverted (see [docs/HOST_FEATURES.md](docs/HOST_FEATURES.md)).
- **Pick a channel:** a tool with `PickChannel()` gets a channel chooser for the colours of an RGB layer, the channels (`C` axis) of a TIFF given as a file, or the colours (`S` axis) of an RGB TIFF file. The chooser is hidden when there is only one channel. A file with `C` and `S` together, or with an `S` axis that is not exactly three colours (an alpha channel, two samples), is refused with a sentence, never treated as one channel. One channel is read from the file page by page (or through a memory map), never by decoding the whole series; a file that cannot be read that way is refused before reading when it would not fit the 4 GB budget the layer export uses.
- **Pixel size:** a pixel-size field linked to an image follows the file chosen for it, else the chosen layer (its scale and units, read through the unit catalog of `labconstrictor-tools`' conformance data: `um`, `micron`, `nm`, `mm`, `cm`, `m`, Angstrom, each with its names), until you type a value. A source that cannot state a length per pixel (napari's default `pixel` unit, no unit, a unit that is not a length, pixels that are not square by more than 0.1 %, or a TIFF whose only resolution is the 72 or 96 dpi default) is *not calibrated*: the field is cleared, nothing is assumed, and a run that needs the value is refused with `'<parameter>' needs a value: '<image>' has no pixel size. Enter it in um.` (an optional pixel-size parameter is sent as null). The field is a line of text like every number field: an automatic value shows its exact digits (nothing is rounded), a value you type is kept as typed when the image changes and is checked when Run is pressed (beyond a limit, or text that is not a number, it is refused with a sentence; it is never rounded or clamped), and the field shows "(not set)" while it is empty. Clear it (empty the box or type 0) or press "use the image's calibration" to follow the source again. The request also carries a reserved `_calibration` input (per axis, with its source: image, file or user), which tools never see and `run.json` records.

## Results

| Tool result | In napari |
|---|---|
| Image or labels | Image or Labels layer (with the source image's transform when the tool says which image it belongs to) |
| Points or outlines | Points or Shapes layer placed on their image (a table or a file when there is no image input) |
| Table | Table dock |
| Alignment (affine) | Layer placed with the affine transform |
| Message | Text shown below the status line |
| Values or file | Summary in the status line |

**Where results are placed.** A tool works on the pixels of the image that was sent and never sees napari's world coordinates; the plugin puts the result back (docs/SPEC_WRONG_SCIENCE.md of LabConstrictor-Tools, section 1):

- Points, outlines, image and labels results that belong to an image (the image named by `ApplyTo`, or for points and outlines the first image input) get that layer's **complete transform**: scale, translate, rotate, shear, affine and units. Pixel centres sit at integer data coordinates, so a point at pixel `(y, x)` is drawn on the centre of that pixel (`result.data_to_world(p) == source.data_to_world(p)`). The transform is read from the layer when the results arrive, so a result follows a layer that was moved while the tool ran. A 2D result of a stack is placed only when the stack's other axes do not move the plane (identity scale and translate, no coupling); otherwise the result is not drawn, the status says why and the files are kept.
- A transform that cannot be inverted is refused (nothing is drawn, the files are kept); nothing is ever approximated or resampled.
- **No image input, no frame:** points and outlines of a tool that has no image input are **not** drawn at the pixel origin. Points are shown as a table and outlines are listed as a file; the files are kept under `<LC_HOME>/results/...` and the status names their path.
- **An image given as a file** is its own pixel frame: the results are drawn in the pixels of the file (identity transform, no units), never on a layer that happens to be open or was shown last.
- An image or labels result with no `ApplyTo` keeps the pixel origin (identity, no units). One with `ApplyTo` whose size differs from the sent image is shown at the pixel origin and the status says `'name' is W x H but 'source' was exported as W2 x H2; shown at the pixel origin, not aligned`.
- A repeated run that replaces a layer sets its transform again from the new result.
- Not covered yet: stacks and time axes (selections on a stack, `t`/`z` columns of points) and results at a reduced resolution; the Affine overlay still uses only the target's scale.

A tool can ask for repeated runs to replace earlier results rather than create more layers. Very large results are not shown in full: a result image over 4 GiB is not loaded, a table dock shows at most 100 000 rows and at most 50 000 outlines are drawn (the rest is reported; the tool's own files hold everything).

Long-running tools report progress and respond to **Cancel**; a tool that ignores Cancel has its worker killed after 3 seconds. The option **Keep the worker running between runs (faster repeat runs)** is ticked by default; untick it to start a fresh worker for every run. An idle kept worker is closed after 10 minutes.

If a tool reports that nothing matched (the code `no_match` or `no_result`), the widget shows a notice rather than a red error.

## Install

In the Python environment used by napari (**Python 3.11 or newer**; napari 0.8 and later need it):

```bash
python -m pip install https://github.com/CellMigrationLab/LabConstrictor-Tools/archive/refs/heads/main.zip
python -m pip install https://github.com/CellMigrationLab/LabConstrictor-napari/archive/refs/heads/main.zip
```

**Which Tools:** the plugin needs LabConstrictor-Tools **v0.3.0-alpha.1 or newer** (version `0.3.0a1`; the `main` archive above is). It uses `runs.build_record`, `runs.record_json` and `runs.done_status` to write `run.json` and the done marker exactly as Tools does. Those came in v0.2.0-rc.2, which reports the same version as rc.1 (`0.2.0rc1`), so `pip` requires `labconstrictor-tools>=0.3.0a1`, and the plugin also checks the version and the three functions when it loads: with an older Tools it refuses to load with a message that says to update Tools.

**Which apps are listed:** napari lists an app only if the app declares napari in its `hosts` (registry entry field, feature `app_hosts_v1`, rule `labconstrictor_tools.app_hosts.listed_for`). An app that leaves napari out, or whose declaration is not valid, is not offered; the widget says so in its "skipped" line and the sentence is written to the Tools log. An app with no declaration is still listed, and the log says `declares no hosts` each time the list is read. This needs Tools 0.3.0a1 with the feature `app_hosts_v1`; the plugin refuses to load without it.

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

Every run leaves a record, `<LC_HOME>/runs/<time>_<app>_<tool>/run.json` (`LC_HOME` is `~/.labconstrictor` unless the environment variable says otherwise). It holds the app, tool, status, error, inputs, results, timings and the tail of the worker's output (the last 4000 characters). The content and the status of the done marker come from `labconstrictor_tools.runs` (`build_record`, `done_status`), the same code Tools uses for its own records; the plugin adds only the run's `run_id` and start time, and keeps the reserved `_calibration` input under `inputs`.

What the plugin does about cleanup (rules: section 3 of [SPEC_WRONG_SCIENCE](https://github.com/CellMigrationLab/LabConstrictor-Tools/blob/main/docs/SPEC_WRONG_SCIENCE.md)):

- **The plugin never deletes anything under `<LC_HOME>/runs` or `<LC_HOME>/results`.** It only creates folders there and marks them. When a run starts it makes the run record folder and writes `.lc-owner.json` first; when the run has ended (finished, failed or cancelled; closing the widget during a run counts as cancelled) it writes `run.json` and then `.lc-done.json` last, with the status `ok`, `failed` or `cancelled`. A run that is still going, or whose napari crashed, has no done file and is never cleaned up.
- **Result files.** Results stay in the viewer, and the temporary folders for inputs and outputs (`lcin_*`, outside `<LC_HOME>`) are removed after the run. Before they are removed, every file a tool reports (`FileOut`) that lies in that temporary folder, and every image or labels result that could not be shown (for example one above the display limit), is moved to a results folder `<LC_HOME>/results/<YYYYMMDDTHHMMSS>_<6 hex>_<app>_<tool>` (marked the same way), and the status shows that path. A folder is only made when there is a file to keep; files outside the temporary folder are never moved or modified. If a file cannot be moved, the temporary folder is kept so that the reported path stays valid.
- **Cleanup is done by LabConstrictor-Tools, started by the plugin.** After the done marker is written, the plugin starts `<the app's Python> -m labconstrictor_tools prune` as a separate process, in the background: the widget does not wait for it, ignores its exit code, and writes a failure to the shared log. The one thing it does wait for is the start: closing the widget (or ending the process) returns only once the `prune` subprocess exists, never while a thread is still inside the operating system call that makes it (on Windows, ending the process then is an access violation); `prune` itself keeps running on its own. `prune` keeps the newest 20 finished results folders and the newest 50 finished run records and removes older ones, but only folders that carry both marker files. Folders you made yourself, older folders without markers, folders of a run that has not finished, links and anything outside the two folders are never touched.
- If the app's `labconstrictor-tools` is too old to have the `prune` command (its schema does not list the feature `retention_prune`), the plugin starts nothing, writes one line to the shared log and deletes nothing; the folders then pile up until you update the app's Tools. The plugin never falls back to deleting them itself.
- You can run the cleanup yourself: `labconstrictor-tools prune --dry-run` lists what it would remove and changes nothing; `labconstrictor-tools prune` removes it. The full rules are in section 3 of [SPEC_WRONG_SCIENCE](https://github.com/CellMigrationLab/LabConstrictor-Tools/blob/main/docs/SPEC_WRONG_SCIENCE.md).

## Current status

**Testing phase.** CI runs the full test suite with PySide6 and PyQt6, each in its own environment, on Linux (under a virtual display), Windows and macOS. Tests on real machines by people are still open: the [human test protocol](https://github.com/CellMigrationLab/LabConstrictor-Tools/blob/main/docs/HUMAN_TEST_PROTOCOL.md) explains how to help. Not every host supports every LabConstrictor presentation hint in the same way; this README describes the napari implementation, not a guarantee about Fiji or QuPath.

For more detail, see [napari inputs and results](docs/USING_NAPARI.md).

## Applications

The widget reads registered LabConstrictor tool manifests. You do not need a new napari plugin for every scientific application; its declared tools appear in the same widget.

Try [Playground](https://github.com/CellMigrationLab/LabConstrictor-Playground) for a test image, [Guess the Condition](https://github.com/CellMigrationLab/GuessTheCondition) for blinded image classification or [VLab4Mic](https://github.com/CellMigrationLab/LabConstrictor-VLab4Mic) for microscopy simulations. Other applications include [NucleiSky](https://github.com/CellMigrationLab/NucleiSky) and [CellTracksColab](https://github.com/CellMigrationLab/CellTracksColab_LabConstrictor). See the [Tools repository](https://github.com/CellMigrationLab/LabConstrictor-Tools) for installation links.

These are examples, not a list of applications permitted to connect. Choose tools according to whether they make sense in a layer-based workflow and whether napari provides a useful presentation of their outputs.

## Development

The widget lives in `napari_labconstrictor/_widget.py`, with schema conversion in `_schema.py`, result presentation in `_results.py`, units and calibration in `_units.py`, layer/file export in `_export.py`, the frozen run (run identity) in `_snapshot.py`, run records, result folders, markers and the `prune` subprocess in `_retention.py`, the worker cache (one lock, one owner per worker) in `_workers.py`, the ChoicesFrom lookups (identity, one bounded queue, one thread) in `_lookups.py` and the npe2 manifest in `napari.yaml`.

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
xvfb-run -a python test_retention_markers.py     # run records, markers, the prune subprocess (a recorder), nothing deleted by the plugin
xvfb-run -a python test_retention_prune_real.py  # the real `labconstrictor-tools prune` against a private LC_HOME
xvfb-run -a python test_run_identity.py          # RUN-01..06: the run is frozen at the click (RUN-05 for translate, rotate, shear, affine)
xvfb-run -a python test_coordinate_frame.py      # CF-01..CF-14: placement and masks with real layers and real affines (conformance.json)
xvfb-run -a python test_coordinate_frame_run.py  # the same through the widget and a real worker: the mask and image the worker received
xvfb-run -a python test_number_limits.py         # NUM-01..05 typed into the form: the request, or the refusal sentence, never a clamp
xvfb-run -a python test_number_text.py           # number grammar, precision, empty, optional, sliders, copy as command
xvfb-run -a python test_number_run.py            # NUM cases with a real worker: the exact integer / float the tool received
xvfb-run -a python test_channels_rgb.py          # PickChannel on RGB TIFF files (S axis), C and S together, alpha (issue #39)
xvfb-run -a python test_channel_memory.py        # one channel of a large TIFF is read, not the series (issue #40)
```

Every `tests/test_*.py` is a standalone script; CI runs them all in a loop (a new test is picked up without editing the workflow). `scripts/check_qt_backend.sh pyqt6|pyside6` repeats the Qt backend check in a brand-new virtualenv (Linux, needs `xvfb-run`). The tests use the synthetic example application of LabConstrictor-Tools in a private registry, so no real scientific application is needed.

CI runs PySide6 and PyQt6 on Linux, Windows and macOS (`LC_EXPECT_QT` makes `test_qt_backend.py` fail if the wrong binding was loaded), plus lint (black, ruff, the annotation check) and a mypy type check of the package, the tests and the scripts.

**Annotations (a rule, not a style).** Every function in `napari_labconstrictor/`, `tests/` and `scripts/` is annotated: every parameter (`self` / `cls` excepted, `*args` and `**kwargs` included) and the return (`-> None` included). A lambda has no syntax for annotations and is not counted. `python scripts/check_annotations.py` (standard library only, it reads the files and never imports them) lists every function that lacks one and exits 1; the lint job runs it, `--summary` prints the count per file. The one allowed exception is a function that is unannotated on purpose (for example a test that checks what happens to a tool declared without annotations): `# lc-annotations: skip - <reason>` on its `def` line, and a marker without a reason does not count. No function carries it today.

`mypy` (no arguments; the `[tool.mypy]` section of `pyproject.toml` lists the paths) runs `disallow_untyped_defs` and `disallow_incomplete_defs` on all three, in the typecheck job, with napari, magicgui and Qt installed so the calls are checked against their signatures. The test scripts are checked for everything except the error codes listed in the single `[[tool.mypy.overrides]]` block of `pyproject.toml`, which says why each code is off; a new `tests/*.py` is added to the module list there (a file left out is checked with every code). Rules for annotation edits in tests: no new runtime import (a name needed only for a type goes under `if TYPE_CHECKING:` and the annotation is a string), no `from __future__ import annotations` in a file that lacks it (it would turn the annotations of functions that magicgui or the tools introspect into strings), no blanket `Any` where a real type exists, and a `# type: ignore[code]` only with the reason on the same line. `python scripts/verify_annotation_only.py [--base origin/main]` is the proof that such a change touched annotations and nothing else: it removes annotations and the `TYPE_CHECKING` scaffolding from the old and the new version of every changed `.py` file and compares the two with `ast.dump`.

Under a PyQt binding each test script leaves through `os._exit` (`_leave` in `tests/_paths.py`): PyQt's own exit handler crashed the interpreter with a napari window open after the verdict was printed (measured on Linux with PyQt6 6.11 and napari 0.9.2: 37 of 60 runs of one script; PySide6 6.12: 0 of 60). This is a test-harness workaround only; the exit code still carries the verdict, and `_leave` makes that true by waiting for the `prune` watcher threads of the widget before `os._exit` (a process that ends while a thread is inside `CreateProcess` dies with an access violation on Windows after printing `FAILURES: none`; `tests/test_harness_exit.py` and `tests/test_retention_exit.py` check it). The same `os._exit` is used under PySide6 on Python below 3.12, for a different reason: PySide6 6.12.0 loses one reference to `None` on every void Qt call (`sys.getrefcount(None)` falls by one per `setText`, `setVisible`, `processEvents`, `QTableWidget.setItem`, ...), so a test with enough Qt calls aborts in interpreter finalisation (`none_dealloc`, exit 134) after printing its verdict; it showed up as three failing PySide6 scripts on Linux in the CI of the coordinate-frame PR. Python 3.12 made `None` immortal and is not affected. A table of about 100 000 cells filled cell by cell (`MAX_TABLE_ROWS`) can hit the same limit while it is being made on PySide6 + Python 3.11; that is not changed here.

Related projects: [Tools](https://github.com/CellMigrationLab/LabConstrictor-Tools) · [Fiji](https://github.com/CellMigrationLab/LabConstrictor-Fiji) · [QuPath](https://github.com/CellMigrationLab/LabConstrictor-QuPath) · [Playground](https://github.com/CellMigrationLab/LabConstrictor-Playground).

License: MIT.

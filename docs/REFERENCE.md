# napari plugin reference

How the napari plugin builds a tool's form, runs it, places the results and what it writes to disk, and how to work on its code. To install and use the plugin, read the [napari guide](https://cellmigrationlab.github.io/LabConstrictor-Site/guides/napari/).

The plugin is one dock widget for every installed app. It reads the cached tool descriptions of the registered apps and runs each tool in a worker process in that app's own Python, so napari's environment never needs the app's packages. The rules it shares with Fiji and QuPath are in [SPEC_WRONG_SCIENCE](https://github.com/CellMigrationLab/LabConstrictor-Tools/blob/main/docs/SPEC_WRONG_SCIENCE.md) and [PROTOCOL](https://github.com/CellMigrationLab/LabConstrictor-Tools/blob/main/docs/PROTOCOL.md) of LabConstrictor-Tools.

## Requirements

The install command and the current versions are in the [napari guide](https://cellmigrationlab.github.io/LabConstrictor-Site/guides/napari/#install). What the plugin depends on:

- **Python 3.11 or newer** and a **Qt6 backend** (`napari[pyqt6]` or `napari[pyside6]`). The plugin installs no Qt backend of its own: it uses `qtpy` and runs on the one napari has. PyQt5 is not tested.
- **labconstrictor-tools 0.3.0a1 or newer** in napari's environment. The plugin refuses to load with an older one. Host requirements (below) are checked only with 0.3.0a2 or newer.
- **Release tags, not `main`.** The plugin is not on PyPI; it is installed from a release's source archive, which needs no `git`.

## Which apps are listed

- An app is listed when it declares napari in its `hosts`, or declares no hosts at all. An app that leaves napari out, or whose declaration is not valid, is not offered: the panel says so in its "skipped" line and the sentence is written to the Tools log. For an app with no declaration the log says `declares no hosts` each time the list is read.
- An app can declare the oldest napari plugin it needs (`host_requirements`). When this plugin is older, the app stays listed and a warning is shown with its tools and written to the Tools log. When the requirement says `required: true`, Run is refused for that app until a newer plugin is installed.
- An app's installer normally registers it. If an app is missing, `labconstrictor-tools list` shows the registry and `labconstrictor-tools doctor` says why an app is skipped.

## How the form is built

The form is generated from the tool's schema: numbers with ranges and units, choices, checkboxes, file and folder pickers. Tables are chosen as CSV files.

- **Help.** An input with a description has an **ⓘ** after its label. Hover over it to read the description, click it to keep it open (it closes at the next click or key), or move into the input with Tab.
- **Optional parameters without a default** (a seed, a time limit) have a **"set" checkbox**. Unticked, the field is greyed out and the tool receives `None`.
- **Groups and advanced settings.** Parameters of a `group` sit under a bold heading. `advanced` ones are behind **Show advanced settings**, closed by default. Settings that do not apply to the current choice (`enabled_when`) are greyed out.
- **Layout.** A form taller than the dock scrolls. **Run**, **Cancel** and the status line sit under the form and stay in view.

### Numbers

An integer or float field is a line of text, not a spin box, so no digit, decimal or exponent is lost. What you type is checked when **Run** is pressed, never rounded or clamped; a refused value sends nothing and shows the worker's sentence:

- A field with no `Min`/`Max` takes integers up to ±9007199254740991 (2^53 - 1) and floats up to ±1e15. A value beyond a limit is refused with `'L' must be <= 9007199254740991` (or the declared limit).
- Text that is not a number, `nan`, `inf` and an exponent beyond the double range are refused. An empty required field is refused with `'L' is required: type a number`.
- An integer is a sign and digits; a float is a sign, digits with an optional fraction (or only a fraction) and an optional exponent.
- A required number with no default starts at the allowed value nearest 0. The readout of a `Widget('slider')` cannot be typed into.

### Image inputs

- **Layer or file.** Each image input has a layer chooser and an "or file" row. If both are set, the file is used. TIFF and OME-TIFF always work; other formats work if the app's environment has `imageio`.
- **2D only.** A stack or multi-channel image given to a 2D tool (`Axes("YX")`) is refused, never flattened: the worker answers `[wrong_dimensions] 'L' must be a 2D image (YX) but got 3D with shape (...)` and the status line shows it. The plugin does not pick a Z or T plane for you.
- **Channels.** A tool with `PickChannel()` gets a channel chooser for the colours of an RGB layer, the channels (`C` axis) of a TIFF file, or the colours (`S` axis) of an RGB TIFF file. It is hidden when there is only one channel. A file with both `C` and `S`, or an `S` axis that is not exactly three colours (an alpha channel, two samples), is refused with a sentence. One channel is read page by page or through a memory map, never by decoding the whole series; a file that cannot be read that way is refused when it would not fit the 4 GiB export limit. A channel picked from a file that also has a Z axis is still a stack and is refused as above.

### Pixel size

A pixel-size field linked to an image follows the file chosen for it, else the layer (its scale and units, converted to micrometres), until you type a value. Recognised units are `um`, `micron`, `nm`, `mm`, `cm`, `m` and Angstrom, each with its usual names; explicit units count even at scale 1 (`1 micrometer` is 1 µm per pixel).

A source that cannot state a length per pixel is *not calibrated*: napari's default `pixel` unit, no unit, a unit that is not a length, pixels that are not square by more than 0.1 %, or a TIFF whose only resolution is the 72 or 96 dpi default. The field is then cleared and shows "(not set)", nothing is assumed, and a run that needs the value is refused with:

`'<parameter>' needs a value: '<image>' has no pixel size. Enter it in um.`

An optional pixel-size parameter is sent as null instead. An automatic value shows its exact digits. A typed value is kept when the image changes and is checked like any number. To follow the image again, empty the box, type 0 or press "use the image's calibration".

The request also carries a reserved `_calibration` input (per axis, with its source: image, file or user). Tools never see it; `run.json` records it.

### Selections

A tool with a `RegionOf(...)` input gets a **"use the selection" checkbox**, off by default. When ticked, the shapes of the selected Shapes layer are sent as the region mask; several shapes become labels 1, 2, 3 and so on. Only the input the tool declares gets the mask: a selection does not crop other inputs.

- Each vertex goes through the Shapes layer's transform to napari's world coordinates and back through the image layer's transform (scale, translate, rotate, shear and affine of both layers; level 0 of a multiscale image). The mask has the size of the sent image and covers the pixels under the outline you see. A pixel is in the mask when its centre is inside the shape. Ellipses stay ellipses under rotation and shear.
- At most 65 535 shapes are supported; the label image is 16-bit.
- A selection is refused, with a sentence and nothing started, when the image is given as a file (`'L': the selection belongs to an open image, but a file was chosen for 'L2': open the image, or untick the selection`), when the image's transform cannot be inverted, when the shapes lie completely outside the image, or when the image is a stack.

## Running a tool

- **The run is fixed at the click.** The layers, the selection's shapes, the app and the tool are taken when you press **Run**; changing them during the run changes nothing.
- **Progress and Cancel.** Tools can report progress. A tool that ignores **Cancel** has its worker killed after 3 seconds.
- **Kept workers.** **Keep the worker running between runs (faster repeat runs)** is ticked by default, so a repeat run skips the start-up. Untick it for a fresh worker each run. An idle kept worker is closed after 10 minutes, and all workers are closed when napari exits. A closed worker gets 10 seconds to exit before it is killed.
- **Choices from a tool (`ChoicesFrom`)** are looked up in the background. A lookup that fails, answers without a list, or takes more than 60 seconds (it is then cancelled and its worker discarded) leaves the parameter as a text field; the status line and the field's tooltip say why. A reply for a form or values that are no longer current is dropped.

## Where results go

| Tool result | In napari |
|---|---|
| Image or labels | Image or Labels layer, with the source image's transform when the tool says which image it belongs to |
| Points or outlines | Points or Shapes layer on their image; a table or a file when the tool has no image input |
| Table | Table dock |
| Alignment (affine) | Layer placed with the affine transform |
| Message | Text below the status line (Markdown) |
| Values or file | Summary in the status line |

A tool that fails with the code `no_match` or `no_result` is shown as a notice, not as an error. A tool can mark an output with `Replace()` so that repeated runs update a layer or table instead of adding one; if that table dock was closed, a new one is added.

### Placement

A tool works in the pixels of the image that was sent and never sees napari's world coordinates; the plugin puts the result back.

- **On its image.** A result that belongs to an image (the image named by `ApplyTo`; for points and outlines without one, the first image input) gets that layer's whole transform: scale, translate, rotate, shear, affine and units. Pixel centres are at integer coordinates, so a point at pixel `(y, x)` is drawn on the centre of that pixel. The transform is read when the results arrive, so a result follows a layer that was moved during the run. A repeated run that replaces a layer sets its transform again.
- **Transform that cannot be inverted.** Nothing is drawn, the files are kept and the status says why. Nothing is approximated or resampled.
- **No image input.** Points and outlines are not drawn at the pixel origin: points are shown as a table and outlines are listed as a file, kept under `<LC_HOME>/results/...`, and the status names the path.
- **Image given as a file.** The file's pixels are the frame: identity transform, no units. No open layer is used.
- **Image or labels with no `ApplyTo`.** Pixel origin, identity transform, no units. With `ApplyTo` but a different size from the sent image, it is shown at the pixel origin and the status says `'name' is W x H but 'source' was exported as W2 x H2; shown at the pixel origin, not aligned`.
- **Stacks.** A 2D result of a stack is placed only when the stack's other axes have identity scale and translate and do not couple to Y and X; otherwise it is not drawn, the status says why and the files are kept. Not supported yet: selections on stacks, `t`/`z` columns of points, results at a reduced resolution. The affine overlay uses only the target's scale.
- **Image closed during the run.** If the layer a result belongs to is closed, replaced (even by a layer with the same name) or changes size while the tool runs, the result is not drawn. Its files are kept and the status says `run <id> on '<layer>': '<layer>' is no longer open; results are in <folder>`.

Every layer a run draws carries `layer.metadata["labconstrictor"]` with the run's `run_id`, `app` and `tool`; `run.json` has the same `run_id`.

### Size limits

A result image over 4 GiB is not loaded, a table dock shows at most 100 000 rows and at most 50 000 outlines are drawn. The rest is reported in a message; the tool's own files hold everything.

## What is written to disk

`LC_HOME` is `~/.labconstrictor` unless the environment variable `LC_HOME` says otherwise.

- **Run records.** Every run leaves `<LC_HOME>/runs/<time>_<app>_<tool>/run.json` with the app, tool, status, error, inputs (including `_calibration`), results, timings and the last 4000 characters of the worker's output. It is written with `labconstrictor_tools.runs` (`build_record`, `done_status`), the same code Tools uses for its own records; the plugin adds the `run_id` and start time.
- **Result folders.** The temporary folders for inputs and outputs (`lcin_*`, outside `LC_HOME`) are removed after the run. Before that, every file a tool reports (`FileOut`) inside the temporary folder, and every image or labels result that could not be shown, is moved to `<LC_HOME>/results/<YYYYMMDDTHHMMSS>_<6 hex>_<app>_<tool>`, and the status shows that path. A folder is made only when there is a file to keep. Files outside the temporary folder are never moved or changed. If a file cannot be moved, the temporary folder is kept so the reported path stays valid.
- **Markers.** When the plugin makes a run record or results folder it writes `.lc-owner.json` first. When the run has ended (finished, failed or cancelled; closing the widget during a run counts as cancelled) it writes `run.json` and then `.lc-done.json` last, with the status `ok`, `failed` or `cancelled`. A run that is still going, or whose napari crashed, has no done marker.
- **Cleanup.** The plugin never deletes anything under `<LC_HOME>/runs` or `<LC_HOME>/results`. After writing the done marker it starts `<the app's Python> -m labconstrictor_tools prune` in the background; it does not wait for it, ignores its exit code and logs a failure. Closing the widget waits only until that process has started. `prune` keeps the newest 20 finished results folders and the newest 50 finished run records and removes older ones that carry both markers. Folders without markers, unfinished runs, links and anything outside the two folders are never touched.
- If the app's Tools has no `prune` command (its schema does not list the feature `retention_prune`), the plugin starts nothing, writes one line to the log and deletes nothing.
- To clean up by hand: `labconstrictor-tools prune --dry-run` lists what would be removed; `labconstrictor-tools prune` removes it.

## Reproduce a run and diagnose failures

- **Copy as command** copies the last run as a terminal command or a Python snippet. When an input came from an unsaved layer, save it before expecting the command to reproduce the run.
- Failures appear in the status line. **Details…** shows the error, traceback, worker output and the log tail.
- The shared log is `~/.labconstrictor/logs/labconstrictor.log`. `labconstrictor-tools support-bundle` zips diagnostics for a bug report.
- When something cannot be read, the plugin carries on and says so in the status line, and logs it: a TIFF whose header cannot be read gives no calibration ("could not read the pixel size from <file> (...): type it"), and an image file whose channels cannot be read gives no channel list ("could not read the channels of <file>: ...").

## Working on the code

| Module | What it does |
|---|---|
| `_widget.py` | The dock widget |
| `_schema.py` | Schema to form (an `inspect.Signature` that magicgui turns into widgets) |
| `_numbers.py`, `_number_field.py` | Number fields: grammar, limits, the text field |
| `_help.py` | The ⓘ help marker |
| `_hosts.py` | Which apps are listed, host requirements |
| `_units.py`, `_calibration.py` | Pixel size from layers and files, the linked field's state |
| `_export.py` | Layers, files, channels and selections written for the worker |
| `_frame.py` | Coordinate frames: where results are placed |
| `_snapshot.py` | The run fixed at the click |
| `_results.py` | Results shown in napari |
| `_workers.py` | The worker cache |
| `_lookups.py` | `ChoicesFrom` lookups |
| `_retention.py` | Run records, result folders, markers, the `prune` process |
| `napari.yaml` | The npe2 manifest |

### Tests

Install one Qt backend per environment, through its test extra (never both in one environment), and LabConstrictor-Tools:

```bash
python -m pip install git+https://github.com/CellMigrationLab/LabConstrictor-Tools   # the Tools source CI uses (needs git)
python -m pip install -e ".[test-pyqt6]"      # or ".[test-pyside6]"
cd tests
for t in test_*.py; do python "$t" || echo "FAILED: $t"; done   # on Linux without a display: xvfb-run -a python "$t"
```

Every `tests/test_*.py` is a standalone script. The tests use the example app of LabConstrictor-Tools in a private registry, so no scientific app is needed. `scripts/check_qt_backend.sh pyqt6|pyside6` repeats the Qt backend check in a new virtualenv (Linux, needs `xvfb-run`). More on the test helpers and the UI audit: [tests/README.md](../tests/README.md).

CI runs every test script with PySide6 and PyQt6 on Linux (under a virtual display), Windows and macOS; `LC_EXPECT_QT` makes `test_qt_backend.py` fail if the wrong binding was loaded. A new test script is picked up without editing the workflow.

### Lint and type checks

- `black --check .` and `ruff check .`.
- `python scripts/check_annotations.py`: every function in `napari_labconstrictor/`, `tests/` and `scripts/` must annotate every parameter (`self`/`cls` excepted) and its return. It lists the ones that do not and exits 1; `--summary` counts per file. A function left unannotated on purpose carries `# lc-annotations: skip - <reason>` on its `def` line.
- `mypy` (no arguments; paths and settings are in `[tool.mypy]` of `pyproject.toml`), with napari, magicgui and Qt installed. A new `tests/*.py` is added to the module list of the `[[tool.mypy.overrides]]` block. Rules for annotation-only changes in tests are in [tests/README.md](../tests/README.md).

### Releasing

The package version names the release, so `pip show napari-labconstrictor` tells which one is installed. Between releases, `version` in `pyproject.toml` is the next release's version with `.dev0` (for example `0.2.0b1.dev0`). To release, set it to the tag's version (`v0.2.0-beta.1` is `0.2.0b1`), merge, then tag. `python scripts/check_version.py <tag>` compares the two; the `version` workflow runs it on every pushed tag. After a release, update the versions in the [napari guide](user-guide.md).

Related projects: [Tools](https://github.com/CellMigrationLab/LabConstrictor-Tools) · [Fiji](https://github.com/CellMigrationLab/LabConstrictor-Fiji) · [QuPath](https://github.com/CellMigrationLab/LabConstrictor-QuPath) · [Playground](https://github.com/CellMigrationLab/LabConstrictor-Playground).

License: MIT.

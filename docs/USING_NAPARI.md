# Using LabConstrictor in napari

The LabConstrictor widget lists tools registered by installed applications. Tools run in the application's Python environment, in a separate process, and return results to napari. (The repository is LabConstrictor-napari; the Python package is napari-labconstrictor.)

## Scientific applications

napari can discover the declared tools of registered LabConstrictor applications without a plugin for each one. Applications differ in how useful their tools are for layer-based workflows; see the [Tools repository](https://github.com/CellMigrationLab/LabConstrictor-Tools) for examples.

## First run

Install [LabConstrictor Playground](https://github.com/CellMigrationLab/LabConstrictor-Playground) and open **Plugins > LabConstrictor tools**. Select **Feature tour**. Its optional image input can be left unset to generate a demonstration image.

Check that the result includes labels, points, outlines, a table and a message. This tests data exchange with the widget; it does not validate a scientific segmentation method.

## Forms

Tool annotations supply ranges, units, choices, checkboxes, file and folder pickers (tables are chosen as CSV files) and optional fields.

- An optional parameter without a default has a **"set" checkbox**. Unticked, the field is greyed out and the tool receives `None`.
- Parameters of a `group` sit under a bold heading. `advanced` parameters are behind **Show advanced settings** (closed by default).
- Settings that do not apply to the current choice (`enabled_when`) are greyed out.
- A form taller than the dock scrolls; the Run button and the status stay in view.

## Image inputs

### Layer or file

Image inputs can come from a napari layer or an image file. If both are supplied, the file takes precedence. TIFF and OME-TIFF always work; other formats work if the application's environment has `imageio`.

### Channels

`PickChannel()` gives a channel chooser for the colours of an RGB layer or the channels of a TIFF given as a file. It is hidden when there is only one channel, and the tool receives only the chosen channel.

### Physical calibration

When the tool declares a pixel-size parameter linked to an image, the widget fills it from the layer's scale (converted to micrometres) or from the TIFF header. Both the Y and the X pixel size are read; the tool takes one value and receives the X one, and the status line warns when Y and X differ. A layer unit that is not a length (napari's default `pixel`) is taken to be micrometres, and the status line says so. Check units before quantitative analysis.

## Selections

A `RegionOf(...)` input has a **"use the selection" checkbox** (off by default). When ticked, the shapes of the selected Shapes layer are sent as the region mask (several shapes become labels 1, 2, 3 ...). The tool must explicitly declare that input; a selected shape does not automatically crop other image inputs. The selection belongs to an open image layer: with an image given as a file the run is refused.

## Running, progress and cancelling

Tools can report progress and respond to **Cancel**; a tool that ignores Cancel has its worker killed after 3 seconds.

**Keep the worker running between runs (faster repeat runs)** is ticked by default, so a repeat run of a heavy tool skips the start-up. Untick it to use a fresh worker for every run. An idle kept worker is closed after 10 minutes and all workers are closed when napari exits.

## Results

| Return type | napari |
|---|---|
| Image / labels | Image or Labels layer |
| Points / outlines | Points or Shapes layer |
| Table | Table dock |
| Affine | Layer placed with the affine transform |
| Message | Text below the status line |
| Values / file | Summary in the status line |

Some outputs carry replacement metadata so repeated runs update an existing layer or table. Check which layer is selected before starting another run.

A tool that fails with the code `no_match` or `no_result` is shown as a notice, not as an error. Very large results are limited in the viewer: a result image over 4 GiB is not loaded, a table dock shows at most 100 000 rows, and at most 50 000 outlines are drawn.

## Reproduce a run

Use **Copy as command** (a terminal line or a Python snippet) to repeat the last run outside napari. Save inputs that currently exist only as in-memory layers before expecting a command-line run to reproduce them.

## Run records

Every run leaves `<LC_HOME>/runs/<time>_<app>_<tool>/run.json` (default `LC_HOME` is `~/.labconstrictor`). It records the app, tool, status, error, inputs, results, timings and the tail of the worker output. **Details...** in the widget shows the same information for the last run.

Old run records are pruned by LabConstrictor-Tools, not by the widget: with the Tools installed from the main archive, writing a record keeps the newest 50 finished ones, and only folders that carry the owner and done marker files are removed. The plugin does not start `labconstrictor-tools prune` itself yet and keeps no results under `<LC_HOME>/results` (it uses temporary folders it removes after the run); the newest-20 rule for result folders applies to results written by the Tools command line. Run `labconstrictor-tools prune --dry-run` to see what a cleanup would remove. The rules are in section 3 of [SPEC_WRONG_SCIENCE](https://github.com/CellMigrationLab/LabConstrictor-Tools/blob/main/docs/SPEC_WRONG_SCIENCE.md).

## Troubleshooting and tests

If the application or tool is missing, run `labconstrictor-tools list` and `labconstrictor-tools doctor`. Check the widget's **Details...** and the shared log (`~/.labconstrictor/logs/labconstrictor.log`) for worker failures; `labconstrictor-tools support-bundle` collects them for a bug report.

The widget and conversion tests live under `tests/` and run in CI with PySide6 and PyQt6 on Linux, Windows and macOS. Maintainers should test image/file precedence, channel selection, Shapes masks, pixel size, each output type, cancellation and repeated runs when those code paths change.

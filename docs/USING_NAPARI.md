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

`PickChannel()` gives a channel chooser for the colours of an RGB layer, the channels (`C` axis) of a TIFF given as a file, or the colours (`S` axis) of an RGB TIFF file. It is hidden when there is only one channel, and the tool receives only the chosen channel (one 2D image from an RGB file). A file with both `C` and `S`, or an `S` axis that is not exactly three colours, is refused with a sentence. The channel is read without decoding the whole file.

### Physical calibration

When the tool declares a pixel-size parameter linked to an image, the widget fills it from the file chosen for that image, else from the layer's scale and units (converted to micrometres), until you type a value. It never assumes micrometres: a layer with napari's default `pixel` unit, an unknown or non-length unit, pixels that are not square (Y and X differ by more than 0.1 %) or a TIFF with only a 72 or 96 dpi resolution is not calibrated, the field is cleared (it shows "(not set)"), and the tool does not run until you enter the value (an optional pixel-size parameter is sent as null). Explicit units win even at scale 1 (`1 micrometer` is 1 um per pixel). A value you typed stays when you switch image; type 0 or press "use the image's calibration" to follow the image again. Check units before quantitative analysis.

## Selections

A `RegionOf(...)` input has a **"use the selection" checkbox** (off by default). When ticked, the shapes of the selected Shapes layer are sent as the region mask (several shapes become labels 1, 2, 3 ...). The tool must explicitly declare that input; a selected shape does not automatically crop other image inputs. The selection belongs to an open 2D image layer: with an image given as a file the run is refused.

The shapes are not painted in their own raw coordinates. Each vertex goes through the Shapes layer's transform to napari's world coordinates and back through the image layer's transform into the pixel grid of the image that is sent (scale, translate, rotate, shear and affine of both layers; level 0 of a multi-scale image). The mask therefore has exactly the size of the sent image and covers the pixels under the outline you see, also when the two layers have the same scale but different origins, or one is rotated. A pixel is in the mask when its centre lies inside the shape. Rectangles and ellipses are converted as shapes (an ellipse stays an ellipse under rotation and shear). A selection is refused, with a sentence and nothing started, when the image's transform cannot be inverted, when it lies completely outside the image, or when the image is a stack (selections on stacks are not supported yet). If you move or edit the Shapes layer or the image after pressing Run, the mask is still the one of the click.

## Running, progress and cancelling

Tools can report progress and respond to **Cancel**; a tool that ignores Cancel has its worker killed after 3 seconds.

**Keep the worker running between runs (faster repeat runs)** is ticked by default, so a repeat run of a heavy tool skips the start-up. Untick it to use a fresh worker for every run. An idle kept worker is closed after 10 minutes and all workers are closed when napari exits.

## Results

| Return type | napari |
|---|---|
| Image / labels | Image or Labels layer, with the source image's transform when the tool says which image it belongs to |
| Points / outlines | Points or Shapes layer on their image; a table or a file when the tool has no image input |
| Table | Table dock |
| Affine | Layer placed with the affine transform |
| Message | Text below the status line |
| Values / file | Summary in the status line |

Some outputs carry replacement metadata so repeated runs update an existing layer or table. Check which layer is selected before starting another run.

### Where a result is drawn

A tool reports coordinates in the pixels of the image that was sent (the centre of a pixel is an integer). The plugin draws the result on the layer the tool says it belongs to (`ApplyTo`; for points and outlines without one, the first image input) with that layer's **whole** transform: scale, translate, rotate, shear and affine, and its units. A point at pixel `(y, x)` is on the centre of that pixel, so it overlays the image for a translated, rotated or sheared layer and not only for a scaled one. The transform is read when the results arrive: a result follows its layer if you moved the layer while the tool ran. A layer with a transform that cannot be inverted is refused: nothing is drawn, the files are kept and the status says why.

- **No image input:** points and outlines of a tool that has no image input are not drawn at the pixel origin. Points appear as a table dock and outlines are listed as a file; the files are copied to `<LC_HOME>/results/...` and the status shows the path.
- **Image given as a file:** its pixels are the frame; the result is drawn with an identity transform and no units. No open layer is used, however recently it was shown.
- **Image or labels with no `ApplyTo`:** pixel origin, identity transform, no units. With `ApplyTo` but another size than the sent image: pixel origin again, and the status says `'name' is W x H but 'source' was exported as W2 x H2; shown at the pixel origin, not aligned`.
- **Repeated runs (`Replace`)** set the transform again from the new result; they never keep the previous one.
- **Stacks:** only 2D images are covered. A 2D result of a stack is placed when the stack's other axes have identity scale and translate and do not couple to Y/X; otherwise it is not drawn. Time and z columns, selections on stacks and results at reduced resolution are later work.

A tool that fails with the code `no_match` or `no_result` is shown as a notice, not as an error. Very large results are limited in the viewer: a result image over 4 GiB is not loaded, a table dock shows at most 100 000 rows, and at most 50 000 outlines are drawn.

## Reproduce a run

Use **Copy as command** (a terminal line or a Python snippet) to repeat the last run outside napari. Save inputs that currently exist only as in-memory layers before expecting a command-line run to reproduce them.

## Run records

Every run leaves `<LC_HOME>/runs/<time>_<app>_<tool>/run.json` (default `LC_HOME` is `~/.labconstrictor`). It records the app, tool, status, error, inputs, results, timings and the tail of the worker output. **Details...** in the widget shows the same information for the last run.

The widget never deletes run records or result folders. It writes an owner marker when it makes the record, a done marker when the run has ended, keeps in `<LC_HOME>/results` the files a tool reported (`FileOut`) and the results it could not show, and then starts `labconstrictor-tools prune` in the background (an app whose Tools lacks the `retention_prune` feature gets no cleanup and a line in the log). Only `prune` removes anything: owned, finished folders beyond the newest 50 run records and 20 result folders. Run `labconstrictor-tools prune --dry-run` to see what a cleanup would remove. The rules are in section 3 of [SPEC_WRONG_SCIENCE](https://github.com/CellMigrationLab/LabConstrictor-Tools/blob/main/docs/SPEC_WRONG_SCIENCE.md).

Every layer a run draws carries `layer.metadata["labconstrictor"]` with the run's `run_id`, `app` and `tool`, and `run.json` has the same `run_id`. The run is fixed when you press Run (which layers, the selection's shapes, the app and tool): changing the layer, the selection or the tool during the run changes nothing. If the layer a result belongs to is closed (or replaced by another layer, even one with the same name, or changes size) while the tool runs, the result is not drawn: its files are kept in a results folder and the status says `run <id> on '<layer>': '<layer>' is no longer open; results are in <folder>`.

## Troubleshooting and tests

If the application or tool is missing, run `labconstrictor-tools list` and `labconstrictor-tools doctor`. Check the widget's **Details...** and the shared log (`~/.labconstrictor/logs/labconstrictor.log`) for worker failures; `labconstrictor-tools support-bundle` collects them for a bug report.

The widget and conversion tests live under `tests/` and run in CI with PySide6 and PyQt6 on Linux, Windows and macOS. Maintainers should test image/file precedence, channel selection, Shapes masks and result placement (`test_coordinate_frame.py` runs every coordinate case of the shared conformance data with real affines), pixel size, each output type, cancellation and repeated runs when those code paths change.

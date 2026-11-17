# LabConstrictor for napari

Run the analysis tools of your LabConstrictor apps from inside [napari](https://napari.org). Open the **LabConstrictor tools** panel, pick an app and a tool, choose an image layer and press **Run**. The results come back as napari layers and tables. The analysis runs in the app's own Python environment, so you do not install the app's packages into napari.

![napari with the LabConstrictor tools panel: nuclei segmented by the StarDist2D app, shown as labels, outlines and a table](docs/img/napari-stardist.png)

*The StarDist2D app's "Segment nuclei" tool, run from napari on an open image layer.*

It has been tested on Linux, Windows and macOS. Please [tell us](https://github.com/CellMigrationLab/LabConstrictor-napari/issues) what you find.

## Install

Install it with pip in the Python environment you start napari from, and install at least one LabConstrictor app: see the [napari guide](https://cellmigrationlab.github.io/LabConstrictor-Site/guides/napari/). The guide also shows how to open the panel, check that it works and fix common problems.

## Apps that work in napari

| App | What it does |
|---|---|
| [StarDist2D](https://cellmigrationlab.github.io/LabConstrictor-Site/apps/stardist2d/) | Segment nuclei and cells in 2D images with StarDist |
| [NucleiSky](https://cellmigrationlab.github.io/LabConstrictor-Site/apps/nucleisky/) | Align microscopy images by matching the pattern of their nuclei |
| [Guess the Condition](https://cellmigrationlab.github.io/LabConstrictor-Site/apps/guessthecondition/) | A blinded test of whether conditions can be told apart by eye |
| [VLab4Mic](https://cellmigrationlab.github.io/LabConstrictor-Site/apps/labconstrictor-vlab4mic/) | Simulate fluorescence microscopy images of virtual samples |
| [Playground](https://cellmigrationlab.github.io/LabConstrictor-Site/apps/labconstrictor-playground/) | Check your computer and try every feature of the plugin |

Any LabConstrictor app that declares napari as one of its hosts appears in the panel; no extra plugin is needed per app. The [App Centre](https://cellmigrationlab.github.io/LabConstrictor-Site/apps/?host=napari) has the current list.

## Getting help

- **Something failed?** The line under the Run button says what went wrong, and **Details...** shows the full report.
- **Install and first use:** the [napari guide](https://cellmigrationlab.github.io/LabConstrictor-Site/guides/napari/), with a section for when something does not work.
- **More guides:** the [LabConstrictor website guides](https://cellmigrationlab.github.io/LabConstrictor-Site/guides/).
- **Bugs and questions:** the [issue tracker](https://github.com/CellMigrationLab/LabConstrictor-napari/issues).

## More detail

- [Using LabConstrictor in napari](docs/USING_NAPARI.md): image inputs, channels, pixel size, selections, where results are drawn, run records.
- [Technical reference](docs/REFERENCE.md): the rules behind the form and the results, and notes for developers.
- The same apps also run in [Fiji](https://github.com/CellMigrationLab/LabConstrictor-Fiji) and [QuPath](https://github.com/CellMigrationLab/LabConstrictor-QuPath). To make your own app, start at the [LabConstrictor website](https://cellmigrationlab.github.io/LabConstrictor-Site/).

## For developers

The repository is `LabConstrictor-napari`; the Python package is `napari-labconstrictor`. To run the tests:

```bash
pip install git+https://github.com/CellMigrationLab/LabConstrictor-Tools   # the Tools source CI uses (needs git)
pip install -e ".[test-pyqt6]"            # or ".[test-pyside6]"; one Qt backend per environment
cd tests
for t in test_*.py; do python "$t" || echo "FAILED: $t"; done   # on Linux without a display: xvfb-run -a python "$t"
```

Each `tests/test_*.py` is a standalone script, and they use a small example app, so no scientific app needs to be installed. Linting, type checks and releasing are described in the [technical reference](docs/REFERENCE.md#development) and in [tests/README.md](tests/README.md).

License: [MIT](LICENSE).

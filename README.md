# LabConstrictor for napari

Run the analysis tools of your LabConstrictor apps from inside [napari](https://napari.org). Open the **LabConstrictor tools** panel, pick an app and a tool, choose an image layer and press **Run**. The results come back as napari layers and tables. The analysis runs in the app's own Python environment, so you do not install the app's packages into napari.

![napari with the LabConstrictor tools panel: nuclei segmented by the StarDist2D app, shown as labels, outlines and a table](docs/img/napari-stardist.png)

*The StarDist2D app's "Segment nuclei" tool, run from napari on an open image layer.*

It runs on Linux, Windows and macOS.

## Install

In the Python environment you start napari from, install napari, LabConstrictor-Tools and this plugin with one `pip install` line, then install at least one LabConstrictor app. The [napari guide](https://cellmigrationlab.github.io/LabConstrictor-Site/guides/napari/) has the command for the current release, and shows how to open the panel, check that it works and fix common problems.

## Apps that work in napari

| App | What it does |
|---|---|
| [StarDist2D](https://cellmigrationlab.github.io/LabConstrictor-Site/apps/stardist2d/) | Segment nuclei and cells in 2D images with StarDist |
| [NucleiSky](https://cellmigrationlab.github.io/LabConstrictor-Site/apps/nucleisky/) | Align microscopy images by matching the pattern of their nuclei |
| [Guess the Condition](https://cellmigrationlab.github.io/LabConstrictor-Site/apps/guessthecondition/) | A blinded test of whether conditions can be told apart by eye |
| [VLab4Mic](https://cellmigrationlab.github.io/LabConstrictor-Site/apps/labconstrictor-vlab4mic/) | Simulate fluorescence microscopy images of virtual samples |
| [Playground](https://cellmigrationlab.github.io/LabConstrictor-Site/apps/labconstrictor-playground/) | Check your computer and try every feature of the plugin |

Any LabConstrictor app that declares napari as one of its hosts appears in the panel; no extra plugin is needed per app. The [App Centre](https://cellmigrationlab.github.io/LabConstrictor-Site/apps/?host=napari) has the current list.

## More

- **Install, first use and problems:** the [napari guide](https://cellmigrationlab.github.io/LabConstrictor-Site/guides/napari/).
- **How it works, and working on the code:** the [napari plugin reference](docs/REFERENCE.md).
- **Bugs and questions:** the [issue tracker](https://github.com/CellMigrationLab/LabConstrictor-napari/issues).
- The same apps also run in [Fiji](https://github.com/CellMigrationLab/LabConstrictor-Fiji) and [QuPath](https://github.com/CellMigrationLab/LabConstrictor-QuPath). To make your own app, start at the [LabConstrictor website](https://cellmigrationlab.github.io/LabConstrictor-Site/).

## For developers

The repository is `LabConstrictor-napari`; the Python package is `napari-labconstrictor`. Running the tests, linting and releasing are in the [reference](docs/REFERENCE.md#working-on-the-code).

License: [MIT](LICENSE).

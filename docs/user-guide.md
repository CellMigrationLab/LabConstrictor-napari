# Install the napari plugin

One dock widget shows every installed LabConstrictor app. You pick an app and a tool, and the form is generated from the tool's declaration.

> [!WARNING]
> **Under heavy construction.** The automated tests pass in CI, but people have not yet tested this plugin on real machines, so it is unlikely to be stable. Expect bugs, missing features and changes without notice. Do not rely on it for work you cannot redo.
>
> The plugin is installed from GitHub; it is not on PyPI yet.

## What you need

- [napari](https://napari.org), in a Python environment with **Python 3.11 or newer**.
- napari version: the project's automated type check runs against napari 0.9.2 and magicgui 0.10.2 (a type check only: napari is not run there). The automated tests (PySide6 and PyQt6 on Linux, Windows and macOS) install whichever napari version pip picks. We recommend a Qt6 backend: `pip install "napari[pyqt6]"` or `"napari[pyside6]"`.
- At least one LabConstrictor app installed on your computer (the [apps that work in napari](https://labconstrictor.cellmig.org/apps/?host=napari) are listed in the App Centre). Installing the app and installing this plugin are two separate steps: the app's installer registers it on your computer, which is how the plugin finds it.

## Install

Run these commands in the same environment you start napari from. If you start napari from a terminal after `conda activate <name>` (or after activating a virtual environment), activate that environment first. If you installed napari with its desktop installer, follow [napari](https://napari.org)'s instructions for adding packages to that installation. Then install the tools runtime and the plugin:

    pip install https://github.com/CellMigrationLab/LabConstrictor-Tools/archive/refs/heads/main.zip
    pip install https://github.com/CellMigrationLab/LabConstrictor-napari/archive/refs/heads/main.zip

These are source archives, so you do not need `git`. The plugin needs LabConstrictor-Tools v0.3.0-alpha.1 or newer (version 0.3.0a1; the archive above is); with an older one it refuses to load and says to update Tools. Restart napari.

## Open it

Choose **Plugins > LabConstrictor tools**. The widget lists the apps registered on your computer. Pick an app, pick a tool, set the parameters, and press Run.

A first run needs an installed LabConstrictor app that declares tools. If none is registered, the app list shows "(none registered)" and there is nothing to run.

- Image inputs take an open layer or a file (a chosen file wins). TIFF and OME-TIFF always work; other formats work if the app has `imageio`.
- Results appear as layers, a table, or in the status line. A tool that finds nothing shows a notice, not an error.
- A progress bar and a Cancel button are there while a tool runs.

## If something does not work

- The status line says what failed; **Details...** shows the error, the worker's output and the end of the log.
- `labconstrictor-tools doctor` shows which apps are registered and why one might be skipped.
- `labconstrictor-tools support-bundle` zips the log for a bug report. The log is `~/.labconstrictor/logs/labconstrictor.log`.

Source and issues: [LabConstrictor-napari](https://github.com/CellMigrationLab/LabConstrictor-napari) (the Python package is `napari-labconstrictor`).

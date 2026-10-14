# Install the napari plugin

One dock widget shows every installed LabConstrictor app. You pick an app and a tool, and the form is generated from the tool's declaration.

> [!WARNING]
> **Under heavy construction.** The automated tests pass in CI, but people have not yet tested this plugin on real machines, so it is unlikely to be stable. Expect bugs, missing features and changes without notice. Do not rely on it for work you cannot redo.
>
> The plugin is installed from GitHub; it is not on PyPI yet.

## What you need

- [napari](https://napari.org), in a Python environment with **Python 3.11 or newer**.
- napari version: the project's automated type check runs against napari 0.9.2 and magicgui 0.10.2 (a type check only: napari is not run there). The automated tests (PySide6 and PyQt6 on Linux, Windows and macOS) install whichever napari version pip picks. Use a Qt6 backend: `pip install "napari[pyqt6]"` or `"napari[pyside6]"` (not PyQt5).
- At least one LabConstrictor app installed on your computer (the [apps that work in napari](https://labconstrictor.cellmig.org/apps/?host=napari) are listed in the App Centre: apps declare which hosts list them in `hosts:` of their `labconstrictor-app.yaml`; the rule that makes napari follow it is being added in Tools 0.3.0a1). Installing the app and installing this plugin are two separate steps: the app's installer registers it on your computer, which is how the plugin finds it.

## Install

Run these commands in the same environment you start napari from. If you start napari from a terminal after `conda activate <name>` (or after activating a virtual environment), activate that environment first. If you installed napari with its desktop installer, follow [napari](https://napari.org)'s instructions for adding packages to that installation. Then install the tools runtime and the plugin:

    pip install "napari[pyqt6]" \
      https://github.com/CellMigrationLab/LabConstrictor-Tools/archive/refs/tags/v0.3.0-alpha.1.zip \
      https://github.com/CellMigrationLab/LabConstrictor-napari/archive/refs/tags/<NAPARI_TAG>.zip

`<NAPARI_TAG>` is a placeholder: use the **latest release tag** of this repository. This repository has no tag and no release yet (checked 14 Oct 2026), and its only workflow is `ci.yml`; the Tools tag `v0.3.0-alpha.1` had not been created on 14 Oct 2026, so until both exist these addresses do not resolve. Never install from `main.zip`. These are source archives, so you do not need `git`. Use a **Qt6** backend (`napari[pyqt6]` or `napari[pyside6]`); PyQt5 is not tested. The plugin needs LabConstrictor-Tools 0.3.0a1 or newer (it depends on `labconstrictor-tools>=0.3.0a1` and refuses to load with an older one), and so do the apps you run in Fiji and QuPath. The full install page for apps and hosts is [Tools `docs/INSTALL.md`](https://github.com/CellMigrationLab/LabConstrictor-Tools/blob/main/docs/INSTALL.md), and the testing form is the [record sheet](https://github.com/CellMigrationLab/LabConstrictor-Tools/blob/main/docs/HUMAN_TEST_PROTOCOL.md#0-record-sheet-the-test-set-fill-in-before-you-start) (both in Tools PR #132; the links work once it is merged). Restart napari.

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

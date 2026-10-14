# UI audit of the Napari dock widget

`tests/ui_audit.py` presses every control of the LabConstrictor dock widget, opens the form of every tool of an **installed** app, runs
each tool with the inputs of the app's own `lc_tests/cases.json`, and photographs the Napari window. It implements section 3 of
`docs/TEST_STRATEGY.md` of LabConstrictor-Tools (the contract), host `napari`. The release sandbox calls it; you can call it by hand.

## Run it

In an environment with `napari`, `labconstrictor-tools` (the pinned tag) and `napari-labconstrictor`, with a registry that holds the
installed app (a scratch `LC_HOME`), under a display (`xvfb-run -a` on Linux):

    LC_HOME=/path/to/registry LC_APP=guessthecondition LC_APP_TESTS=/path/to/app/lc_tests \
    LC_EXPECT_NAPARI=listed LC_SHOTS=./screens \
        xvfb-run -a python tests/ui_audit.py

| Variable | Meaning |
|---|---|
| `LC_HOME` | the scratch registry with the installed app (required) |
| `LC_APP` | registry name of the app (one app per run) |
| `LC_APPS` | instead of `LC_APP`: comma list of registry names. First the multi-app checks, then each app is audited in turn, one matrix each |
| `LC_APP_TESTS` | the app's `lc_tests` folder (`cases.json`, `fixtures/`, optional `no_case.json`); with `LC_APPS` a comma list, one folder per app, same order |
| `LC_EXPECT_NAPARI` | `listed` or `not_listed` (required, never defaulted). `not_listed`: assert the app is absent from the app chooser, print that one check and a NOTE, nothing else |
| `LC_SHOTS` | output folder (default `./screens`): screenshots and the matrix |
| `LC_UI_INPUT` | `layer` (default): a 2D TIFF fixture named by a case is opened as an image/labels layer whose scale is computed from the file's own tags; `file`: always the chooser's 'or file' row (results are then in the pixel frame of the file, identity, SPEC_WRONG_SCIENCE 1.3). Stacks and non-TIFF files always use the file row |
| `LC_UI_IDLE_S` | watchdog: seconds the audit may go without writing a row before its process is killed and the matrix closed with `ui_napari_driver_crashed` (default `3 x LC_UI_TOOL_TIMEOUT + 180`) |
| `LC_UI_TOOL_TIMEOUT` | seconds one tool (its form checks and its run) may take, default 300. On a timeout the check fails, the run is cancelled, the worker is killed if it ignores Cancel and restarted with the widget's own **Restart worker**, and the audit goes on |

Output: one line per assertion, `CHECK <id> PASS|FAIL <detail>` (detail on one line, at most 500 characters), and
`NOTE <id> not run: <reason>` for what was not executed. Exit code 1 if any check is red (FAIL or NOT_RUN), 0 otherwise. The audit
**never stops at the first failure**: each assertion runs in its own guard, an exception (also one raised inside a Qt slot, and any modal
dialog nobody asked for, which a timer inside the Qt loop records and closes) becomes `FAIL <ExceptionType: message>`. A modal dialog can
therefore never block the run for good. The audit itself runs in a CHILD process under a watchdog (`ui_audit_watch.py`): if the Qt thread
freezes (no row written for `LC_UI_IDLE_S` seconds) or the process dies (a segfault), the parent kills it, writes
`CHECK ui_napari_driver_crashed FAIL <reason>`, turns every expected id without a row into `NOT_RUN` and closes the matrix (exit code 2).
`python tests/ui_audit.py --child` runs the audit in the current process without the watchdog.

Use a screen big enough for the window (the audit resizes Napari to fit the screen and fails a button that is outside it):
`xvfb-run -a -s "-screen 0 1600x1000x24" python tests/ui_audit.py`.

### Statuses

| Status | Meaning | Red? |
|---|---|---|
| `PASS` | the assertion held | no |
| `FAIL` | it did not, or raised, or timed out | yes |
| `NOT_RUN` | expected and not executed (a precondition was missing, or the step never ran: found through the expected file) | yes |
| `HUMAN` | cannot be automated: a tool declared in `no_case.json`, a tool whose cases expect failure/cancel, a `stress_*` tool, Cancel during a run when no case sets `cancel_after_s`. Printed as `NOTE ... not run: [human] ...` and listed for a person | never green; not counted in the exit code |

### The matrix and the expected file

Before anything runs, `<LC_SHOTS>/expected_napari_<app>.json` (a JSON list) holds every id the audit intends to produce (every table
control, every tool x opens, controls, run, screens, and with `LC_APPS` the multi ids). `<LC_SHOTS>/matrix_ui_napari_<app>.json` is
rewritten atomically (temp file, then `os.replace`) after every single row (the schema of `tests/oneoff_2026-10/matrix.py` of the Tools repo):

    {"host": "napari", "app": "...", "family": "ui", "host_version": "0.1.0a1" | "0.1.0a1+git.<sha> (editable checkout)", "started": "...Z", "finished": null | "...Z", "expected": <count of ids>,
     "rows": [{"id", "family", "host", "app", "tool", "control", "status": "PASS|FAIL|NOT_RUN|HUMAN", "detail", "seconds",
               "screenshot": path | null, "ts"}]}

`host_version` says which Napari host the matrix describes (a tag install gives the plain version; an editable checkout adds the commit); it is also printed as `NOTE ui_napari_host_version`. Results on a real app are to be taken against the released tag installed non-editable. `id` is the printed check id. At the end every expected id without a row gets a `NOT_RUN` row. `finished` is `null` until the audit ends,
so a killed run is recognisable. The matrix holds text only; screenshots stay on disk. With `LC_APPS` the multi-app rows are in every
matrix after the first app's.

### What is clicked, and where the expectations come from

* Buttons, the check box and the copy menu are operated with real mouse events (`QTest.mouseClick` at the centre), after checking the
  widget is visible, enabled, inside the screen, and not covered or clipped (`widgetAt` at the click point). A covered or clipped
  control FAILS. The visible top-level windows (main window, dialogs, popups) are asserted at each checkpoint: exactly the expected
  set, inside the screen.
* Expected effects come from outside the panel: the registry and schema files in `LC_HOME` (apps, tools, descriptions, parameter kinds,
  result kinds), the worker processes (alive / ended), the run record and log read from disk, the clipboard text compared with the values
  of the case, and the layer data and the TIFF fixture's own tags for where a result lands (scale from the file's calibration, translate
  0, same pixel grid, points and outlines inside the image).
* Cases: the first case of the tool that expects COMPLETE (no failure, crash, cancel or skip case, no tool named `stress_*`, never
  `stress_real_memory`). Earlier COMPLETE cases of the file are replayed first, once, in file order (a game such as GuessTheCondition:
  `prepare_game` before `play_round`); tools are audited in the order of their cases. How a case's file becomes a host input
  (`LC_UI_INPUT`): `layer` (default): a 2D TIFF given for an `image`/`labels` parameter is opened as a layer whose scale the audit computes
  from the TIFF's own tags (ImageJ unit + XResolution, or ResolutionUnit; 72/96 dpi defaults are not a calibration), so the calibration
  source is that layer, and every result that belongs to the image must come back with that scale, translate 0 and the image's pixel grid;
  a pixel-size field the case leaves empty must show the file's micrometres per pixel. `file`: the file goes into the chooser's "or file"
  row; results must be in the pixel frame of the file (identity). Folders, files and tables go into their pickers; stacks and non-TIFF
  files use the file row in both modes. Cases run on a scratch COPY of `lc_tests`; a stateful app needs FRESH fixtures in that copy
  (GuessTheCondition: run `make_fixtures.py` into it; leftovers of an earlier game make `create_demo_experiment` fail with
  `already_exists`, which is reported, not worked around).

### Screenshots

`<LC_SHOTS>/napari/<app>/<tool_id>_form.png` (the form filled with the case, before Run) and `<tool_id>_after_run.png`: the whole Napari
window (`viewer.screenshot(canvas_only=False)`). They are **evidence for a person**. `ui_napari_screens_<tool>` only asserts that both
files exist, were written after the run started and have a plausible size; it does not say the picture is right (the structural
assertions on the result layers are in the run check). A tool that is not run gets the form screenshot and a `HUMAN` row.

## Check ids

`<tool>` is the tool id of the schema, lower-cased, anything outside `[a-z0-9_]` turned into `_`.

| Id | Passes when |
|---|---|
| `ui_napari_app_listed` | the app is in the app chooser (an extra id: without it nothing else can run) |
| `ui_napari_controls_all_known` | every control found in the widget tree has a row in the control table and every row finds its control |
| `ui_napari_panel_<control>` | pressing the control did what its row says (ids below) |
| `ui_napari_panel_cancel_running` | Cancel during a run of a case with `cancel_after_s` ends it cancelled (NOTE when no case has one) |
| `ui_napari_form_<tool>_opens` | one widget of the declared kind per parameter, 'or file' rows, channel choosers, 'set' boxes, description |
| `ui_napari_form_<tool>_controls` | every control of the form was activated and read back, and no control of the form is left unexplained |
| `ui_napari_run_<tool>` | the first case of the tool ran as `cases.json` says (status, code, message, `expect.results`, contract checks) and every declared result is shown; the run record and log exist |
| `ui_napari_screens_<tool>` | both screenshots exist, are fresh and have a plausible size (evidence for a person, not a verdict on the picture) |
| `ui_napari_multi_lists_<app>`, `ui_napari_multi_switch_<appA>_<appB>` | `LC_APPS`: the chooser lists the app with all its tools; switching shows the right tools |
| `ui_napari_not_listed` | `not_listed`: the app is absent from the chooser |
| `ui_napari_driver_crashed` | only on failure: the host broke under the audit |

A tool with no case and no reason in `no_case.json` fails its run check. `progress_events_min` is checked (the audit counts the widget's
progress signals).

## The control table

`tests/ui_audit_controls.py`, `CONTROLS`: id, widget kind, where to find it, and the effect function that asserts it.

| Id | Kind | Expected effect (source) |
|---|---|---|
| `run` | the form's call button | a click starts the task, the button is greyed out while it runs and usable after (the task, the button) |
| `cancel` | `QPushButton` | idle: greyed out; a click or a call changes nothing |
| `rescan_apps` | `QPushButton` | the registry is read again; the chooser lists apps registered in the files of `LC_HOME`; the choice stays |
| `restart_worker` | `QPushButton` | the kept worker process ends (the process) |
| `keep_the_worker_running` | `QCheckBox` | ticked by default: the worker process outlives the run; unticked: it ends (the process) |
| `details` | `QPushButton` | a dialog opens; the run record and log it names exist on disk (files) |
| `copy_as_command` | `QPushButton` with a `QMenu` | a popup with exactly Terminal command and Python snippet |
| `copy_terminal_command` | menu action | the clipboard holds `run <app> <tool>` and every value of the case (cases.json) |
| `copy_python_snippet` | menu action | the clipboard holds Python that parses and names the app, tool and text values |
| `app_chooser` | `ComboBox` | registered apps only; each gives the tools of its schema file |
| `tool_chooser` | `ComboBox` | each tool gives its form and the description of the schema file |

`ui_napari_controls_all_known` asserts SET EQUALITY of the controls found and these rows (a control without a row fails, a row whose
control is gone fails), at least 10 controls found, and only the main window on screen. `ui_napari_panel_cancel_running` also compares the
controls on screen while the tool runs with those found when idle.

Controls the form makes per parameter (number and text fields, check boxes, choices, layer choosers with their 'or file' row and
'...' browse button, pick-channel, 'use the image's calibration', 'set' and 'use the selection' boxes, enabled-when, advanced and group
headings) are not in this table: `ui_napari_form_<tool>_controls` activates them per declared parameter kind.

**Enumeration.** `enumerate_controls` walks the dock widget (`QAbstractButton`, `QComboBox`, `QAbstractSpinBox`, `QLineEdit`,
`QAbstractSlider`, `QTextEdit`, `QPlainTextEdit`, and the actions of every `QMenu`), leaving out the per-parameter form, the parts of a
spin box or combo box, scroll bars and a replaced form that Qt has not deleted yet.

**Add a control.** Add the widget to the dock widget, then add a `Control(id, kind, find, effect)` row in `CONTROLS`, write its
`effect_<id>(ctx)` (press it, assert, return a one-line detail, raise `AssertionError` to fail, `NotRun` to say why it cannot run), and
add the id to `order` in `audit_panel` in `tests/ui_audit.py`. Until then `ui_napari_controls_all_known` fails and names the control.

## Self test

`tests/test_ui_audit.py` runs the driver against the example apps of `labconstrictor-tools` (`synthetic`, `interactions`), with an
`lc_tests` folder it writes itself. It asserts that the known checks pass, that an injected `QPushButton` fails
`ui_napari_controls_all_known` while the rest of the audit goes on, that a sabotaged Rescan fails only its own check, that two apps are
listed and switched, and the `not_listed` cases. CI runs it with every `tests/test_*.py` of the Linux job (xvfb, PyQt6 and PySide6).

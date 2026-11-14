"""The widget with an app whose host_requirements this napari plugin does not meet (Tools #155), in-process.

Three apps are registered with --app-manifest: one that needs a napari plugin 99.0 (a warning), one that needs it with
required: true (a refusal), and one this plugin satisfies. All three stay listed. Choosing a tool of the first shows the warning
in the status line; Run on the second is refused with its sentence and starts nothing; the third says nothing."""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import _paths  # noqa: F401  (must come first)
import napari
from qtpy.QtWidgets import QApplication

from napari_labconstrictor import _hosts

MODULE = "labconstrictor_tools.examples.synthetic"
WARN, REFUSE, FINE = "NeedsNewerNapari", "RefusesOldNapari", "FineWithNapari"
report: dict[str, bool] = {}
failures: list[str] = []
FOLDER = Path(tempfile.mkdtemp(prefix="lc_hostreq_"))


def register(name: str, block: str) -> None:
    manifest = FOLDER / (name + ".yaml")
    manifest.write_text(
        "hosts: [notebook, napari]\nhost_requirements:\n  napari:\n" + block, encoding="utf-8"
    )
    subprocess.run(
        [sys.executable, "-m", "labconstrictor_tools", "register", "--name", name, "--prefix", sys.prefix,
         "--module", MODULE, "--app-manifest", str(manifest)],
        check=True, capture_output=True,
    )  # fmt: skip


def expect(name: str, condition: object, detail: object = "") -> None:
    report[name] = bool(condition)
    if not condition:
        failures.append("%s %s" % (name, detail))


def pump(sec: float = 0.3) -> None:
    end = time.time() + sec
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.02)


register(WARN, "    min_version: '99.0'\n    why: a test of the warning\n")
register(REFUSE, "    min_version: '99.0'\n    required: true\n")
register(FINE, "    min_version: 0.0.1\n    features: [host_requirements_v1]\n")
SAYS = "%s needs LabConstrictor-napari 99.0 or newer (a test of the warning); this is %s." % (
    WARN,
    _hosts.plugin_version(),
)

v = napari.Viewer(show=True)
_, w = v.window.add_plugin_dock_widget("napari-labconstrictor", "LabConstrictor tools")
pump(0.5)
w.rescan()
choices = list(w.app_box.choices)
expect("every_app_stays_listed", {WARN, REFUSE, FINE} <= set(choices), choices)

w.app_box.value = WARN
pump()
expect("the_warning_shows_with_the_apps_tools", w.status.text().startswith("⚠ " + SAYS), w.status.text())

w.app_box.value = FINE
pump()
expect(
    "a_met_requirement_says_nothing", "needs LabConstrictor-napari" not in w.status.text(), w.status.text()
)

w.app_box.value = REFUSE
pump()
expect(
    "the_refusal_shows_with_the_apps_tools",
    w.status.text().startswith("✖ %s needs" % REFUSE),
    w.status.text(),
)
started = []
real_gui = w.gui
w.gui = lambda *a, **k: started.append(1)
w._run_clicked()
w.gui = real_gui
expect(
    "run_is_refused_and_starts_nothing",
    not started and w.status.text().startswith("✖ "),
    (started, w.status.text()),
)

print(json.dumps(report, indent=1))
v.close()
pump(0.5)
if failures:
    sys.exit("FAILURES: " + "; ".join(failures))
print("FAILURES: none")
sys.exit(0)

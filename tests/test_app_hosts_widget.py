"""The widget lists an app only when the hosts rule says so (napari_check.py of Tools, `listed` / `not_listed` / logs why, in-process).

Four apps are registered into the private registry: one for napari, one for notebook only, one with no declaration, and one whose
entry is edited by hand into an invalid declaration. The widget must offer the first and the third, say the other two in its
"skipped" line (where it also says apps it could not read), and write every sentence to the Tools log."""

import json
import subprocess
import sys
import time

import _paths  # noqa: F401  (must come first)
import napari
from labconstrictor_tools import log, registry
from qtpy.QtWidgets import QApplication

MODULE = "labconstrictor_tools.examples.synthetic"
NAPARI, NOTEBOOK, ABSENT, INVALID = "HostNapari", "HostNotebook", "HostAbsent", "HostInvalid"
report: dict[str, bool] = {}
failures: list[str] = []


def register(name: str, hosts: str | None) -> None:
    extra = [] if hosts is None else ["--hosts", hosts]
    subprocess.run(
        [sys.executable, "-m", "labconstrictor_tools", "register", "--name", name, "--prefix", sys.prefix,
         "--module", MODULE, *extra],
        check=True, capture_output=True,
    )  # fmt: skip


def write_invalid_declaration(name: str) -> None:
    path = registry.apps_dir() / (name + ".json")
    entry = json.loads(path.read_text(encoding="utf-8"))
    entry["hosts"] = []
    path.write_text(json.dumps(entry), encoding="utf-8")


def log_text() -> str:
    path = log.log_path()
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def expect(name: str, condition: object, detail: object = "") -> None:
    report[name] = bool(condition)
    if not condition:
        failures.append("%s %s" % (name, detail))


def pump(sec: float = 0.3) -> None:
    end = time.time() + sec
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.02)


register(NAPARI, "notebook,napari")
register(NOTEBOOK, "notebook")
register(ABSENT, None)
register(INVALID, "notebook,napari")
write_invalid_declaration(INVALID)

SKIP_NOTEBOOK = "'%s' is not listed in napari: the app declares hosts: notebook" % NOTEBOOK
SKIP_INVALID = (
    "'%s' is not listed in napari: its hosts declaration is not valid (hosts is empty; write at least notebook); "
    "register the app again with a valid one" % INVALID
)
SAYS_ABSENT = (
    "'%s' declares no hosts, so it is listed in every host; register it with --app-manifest (or --hosts) to choose"
    % ABSENT
)

v = napari.Viewer(show=True)
_, w = v.window.add_plugin_dock_widget("napari-labconstrictor", "LabConstrictor tools")
pump(0.5)
before = log_text().count(SAYS_ABSENT)
w.rescan()
choices = list(w.app_box.choices)
status = w.status.text()
text = log_text()
expect("napari_lists_the_app_that_declares_it", NAPARI in choices, choices)
expect("napari_lists_an_app_with_no_declaration", ABSENT in choices, choices)
expect("napari_does_not_list_a_notebook_only_app", NOTEBOOK not in choices, choices)
expect("napari_does_not_list_an_invalid_declaration", INVALID not in choices, choices)
expect(
    "napari_says_the_skip_where_it_reports_left_out_apps",
    SKIP_NOTEBOOK in status and SKIP_INVALID in status,
    status,
)
expect("napari_logs_why_it_skipped_the_apps", SKIP_NOTEBOOK in text and SKIP_INVALID in text)
expect(
    "napari_logs_the_absent_sentence_every_time",
    text.count(SAYS_ABSENT) == before + 1,
    text.count(SAYS_ABSENT) - before,
)
w.rescan()
expect("napari_logs_the_absent_sentence_again_on_the_next_scan", log_text().count(SAYS_ABSENT) == before + 2)
expect("napari_does_not_say_the_absent_app_is_skipped", ABSENT not in w.status.text(), w.status.text())

print(json.dumps(report, indent=1))
v.close()
pump(0.5)
if failures:
    sys.exit("FAILURES: " + "; ".join(failures))
print("FAILURES: none")
sys.exit(0)

"""Probe: start the real `prune` watcher, wait until its thread is inside the operating system call that makes the process, and
leave the process through os._exit in one of three ways. argv: mode, qt (none | pyside6 | pyqt6)."""
import importlib.util
import os
import sys
import tempfile
import threading

mode, qt = sys.argv[1], sys.argv[2]
os.environ.setdefault("LC_HOME", tempfile.mkdtemp(prefix="lc_probe_"))
if qt == "pyside6":
    from PySide6.QtWidgets import QApplication, QWidget
elif qt == "pyqt6":
    from PyQt6.QtWidgets import QApplication, QWidget
if qt != "none":
    app = QApplication([])
    window = QWidget()
    window.show()
    app.processEvents()

inside = threading.Event()
if sys.platform == "win32":
    import _winapi

    real = _winapi.CreateProcess

    def create_process(*args):
        inside.set()
        return real(*args)

    _winapi.CreateProcess = create_process
else:
    import _posixsubprocess

    real_fork_exec = _posixsubprocess.fork_exec

    def fork_exec(*args):
        inside.set()
        return real_fork_exec(*args)

    _posixsubprocess.fork_exec = fork_exec

spec = importlib.util.spec_from_file_location("lc_retention", os.path.join("napari_labconstrictor", "_retention.py"))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
thread = r.start_prune(sys.executable, {"features": [r.PRUNE_FEATURE]})
assert thread is not None
if mode == "racy":  # what _leave did: leave while the watcher is starting the subprocess
    assert inside.wait(60)
elif mode == "spawned":  # what closeEvent guarantees: the subprocess exists
    assert r.wait_spawned(60)
elif mode == "idle":  # what _leave does now: the watcher has ended
    assert r.wait_idle(120)
sys.stdout.flush()
os._exit(0)

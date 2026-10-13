"""Probe: start the real `prune` watcher and leave the process at once through os._exit, in one of three ways."""
import importlib.util
import os
import sys
import tempfile

mode = sys.argv[1]
os.environ.setdefault("LC_HOME", tempfile.mkdtemp(prefix="lc_probe_"))
spec = importlib.util.spec_from_file_location("lc_retention", os.path.join("napari_labconstrictor", "_retention.py"))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
thread = r.start_prune(sys.executable, {"features": [r.PRUNE_FEATURE]})
assert thread is not None
if mode == "racy":  # what _leave did: leave at once
    pass
elif mode == "spawned":  # what closeEvent guarantees: the subprocess exists
    assert r.wait_spawned(60)
elif mode == "idle":  # what _leave does now: the watcher has ended
    assert r.wait_idle(120)
sys.stdout.flush()
os._exit(0)

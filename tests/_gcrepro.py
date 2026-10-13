"""Does the cyclic GC of ANOTHER thread free a removed form (Qt widgets) off the GUI thread? Run from tests/."""
import gc, sys, threading, time
import _paths  # noqa
from _numhelpers import choose, pump, w, until
import faulthandler; faulthandler.enable()
mode = sys.argv[1]
stop = threading.Event()
freed = []
def collector():
    while not stop.is_set():
        gc.collect()
        time.sleep(0.001)
if mode == "gc":
    gc.disable()  # only the other thread collects
    t = threading.Thread(target=collector, daemon=True); t.start()
tools = list(w.tool_box.choices)
print("tools", tools[:4], flush=True)
import os
os.environ.setdefault("X","1")
for i in range(60):
    choose(tools[i % 2 + 0] if False else "Free integer")
    choose("Free float")
stop.set()
print("done", flush=True)
sys.exit(0)

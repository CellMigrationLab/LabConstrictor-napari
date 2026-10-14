"""Throwaway experiment runner: runs one test script with the exit variant EXP_VARIANT (V0..V9).

V0 control (current main: os._exit via _paths._leave)   V1 stop status checker + viewer.close, then os._exit
V2 normal interpreter shutdown (py3.11)                  V3 V1 + V2     V4 ASV=true (napari never starts the status checker), os._exit
V5 = V2 on Python 3.12                                   V6 reap Tools workers + reader threads (PR #62), os._exit
V7 stop status checker only (no viewer.close), os._exit  V8 V6 + V7     V9 viewer.close() only, then os._exit
"""

import gc
import os
import runpy
import sys
import threading
import time

VARIANT = os.environ.get("EXP_VARIANT", "V0")
if VARIANT == "V4":
    os.environ["ASV"] = "true"  # napari: StatusChecker.start becomes a no-op (no status thread at all)
_real_exit = sys.exit
import _paths  # noqa: E402

_paths_exit = sys.exit  # _paths._leave (os._exit) on Python < 3.12, else the real one


def native_threads() -> int:
    if os.name != "nt":
        return -1
    import ctypes
    from ctypes import wintypes as wt

    class TE(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ThreadID", wt.DWORD),
            ("th32OwnerProcessID", wt.DWORD), ("tpBasePri", wt.LONG), ("tpDeltaPri", wt.LONG), ("dwFlags", wt.DWORD),
        ]  # fmt: skip

    k = ctypes.windll.kernel32
    k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    k.Thread32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(TE)]
    k.Thread32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(TE)]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    snap = k.CreateToolhelp32Snapshot(4, 0)
    te = TE()
    te.dwSize = ctypes.sizeof(TE)
    n, pid = 0, os.getpid()
    ok = k.Thread32First(snap, ctypes.byref(te))
    while ok:
        n += te.th32OwnerProcessID == pid
        ok = k.Thread32Next(snap, ctypes.byref(te))
    k.CloseHandle(snap)
    return n


def report(tag: str) -> None:
    qt = []
    try:
        from qtpy.QtCore import QThread

        qt = [
            (o.objectName() or type(o).__name__) for o in gc.get_objects() if isinstance(o, QThread) and o.isRunning()
        ]
    except Exception as e:  # noqa: BLE001
        qt = ["err:%r" % e]
    print(
        "EXITREPORT[%s] py_threads=%s qthreads_running=%s native_threads=%s"
        % (tag, [t.name for t in threading.enumerate()], qt, native_threads()),
        flush=True,
    )


def stop_status() -> None:
    import _harness

    st = _harness.viewer.window._qt_window.status_thread
    st.close_terminate()
    st.wait(5000)


def reap_workers(timeout: float = 10.0) -> None:  # copy of PR #62's _paths._reap_workers
    deadline = time.monotonic() + timeout
    workers_module = sys.modules.get("napari_labconstrictor._workers")
    client_module = sys.modules.get("labconstrictor_tools.client")
    if client_module is None:
        return
    objects = gc.get_objects()
    if workers_module is not None:
        for cache in [o for o in objects if isinstance(o, workers_module.WorkerCache)]:
            cache.shutdown(final=True)
    for worker in [o for o in objects if isinstance(o, client_module.WorkerProcess)]:
        proc = getattr(worker, "proc", None)
        if proc is not None and proc.poll() is None:
            worker.close(timeout=max(1.0, deadline - time.monotonic()))
    del objects
    for thread in threading.enumerate():
        if thread.name.endswith(("(_read_responses)", "(_read_stderr)")):
            thread.join(max(0.1, deadline - time.monotonic()))
            if thread.is_alive():
                print("worker reader thread did not end: %s" % thread.name, flush=True)


def stop_napari() -> None:
    import _harness
    from qtpy.QtWidgets import QApplication

    try:
        stop_status()
    except Exception as e:  # noqa: BLE001
        print("status stop failed", e, flush=True)
    _harness.viewer.close()
    app = QApplication.instance()
    for _ in range(5):
        app.processEvents()


def close_viewer_only() -> None:
    import _harness

    _harness.viewer.close()


def normal(code: int | str | None) -> None:
    from qtpy.QtWidgets import QApplication

    app = QApplication.instance()
    app.processEvents()
    app.quit()
    report("normal")
    _paths._prunes_have_ended()
    _real_exit(code)


def leave(code: int | str | None, tag: str) -> None:
    report(tag)
    _paths_exit(code)


def make_exit():
    if VARIANT in ("V0", "V4"):
        return lambda code=None: leave(code, "pre")
    if VARIANT == "V1":
        return lambda code=None: (stop_napari(), leave(code, "V1"))
    if VARIANT in ("V2", "V5"):
        return normal
    if VARIANT == "V3":
        return lambda code=None: (stop_napari(), normal(code))
    if VARIANT == "V6":
        return lambda code=None: (reap_workers(), leave(code, "V6"))
    if VARIANT == "V9":
        return lambda code=None: (close_viewer_only(), leave(code, "V9"))
    if VARIANT == "V7":
        return lambda code=None: (stop_status(), leave(code, "V7"))
    if VARIANT == "V8":
        return lambda code=None: (reap_workers(), stop_status(), leave(code, "V8"))
    raise SystemExit("unknown variant " + VARIANT)


sys.exit = make_exit()
test = sys.argv[1]
sys.argv = [test]
runpy.run_path(test, run_name="__main__")

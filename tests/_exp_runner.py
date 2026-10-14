"""Throwaway experiment runner: runs one test script with the exit variant EXP_VARIANT (V0..V5)."""

import os
import runpy
import sys
import threading

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
        import gc

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


def stop_napari() -> None:
    import _harness
    from qtpy.QtWidgets import QApplication

    v = _harness.viewer
    qw = v.window._qt_window
    try:
        qw.status_thread.close_terminate()
        qw.status_thread.wait(5000)
    except Exception as e:  # noqa: BLE001
        print("status stop failed", e, flush=True)
    v.close()
    app = QApplication.instance()
    for _ in range(5):
        app.processEvents()


def normal(code: int | str | None) -> None:
    from qtpy.QtWidgets import QApplication

    app = QApplication.instance()
    app.processEvents()
    app.quit()
    report("normal")
    _paths._prunes_have_ended()
    _real_exit(code)


def make_exit():
    if VARIANT in ("V0", "V4"):
        return lambda code=None: (report("pre"), _paths_exit(code))
    if VARIANT == "V1":
        return lambda code=None: (stop_napari(), report("V1"), _paths_exit(code))
    if VARIANT in ("V2", "V5"):
        return normal
    if VARIANT == "V3":
        return lambda code=None: (stop_napari(), normal(code))
    raise SystemExit("unknown variant " + VARIANT)


sys.exit = make_exit()
test = sys.argv[1]
sys.argv = [test]
runpy.run_path(test, run_name="__main__")

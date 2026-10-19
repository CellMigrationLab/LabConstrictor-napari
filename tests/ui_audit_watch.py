"""The outer watchdog of the Napari UI audit: the audit runs in a CHILD process; this parent kills it when it stops writing rows (the Qt
thread is blocked for good, which no timer inside that thread can recover from) or when it dies (a segfault), and then writes the
`ui_napari_driver_crashed` FAIL row and turns every expected id without a row into NOT_RUN, so the matrix is always complete and red.
Not a test."""

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

POLL_S = 2.0


def newest_write(shots: Path) -> float:
    """The latest modification time of any matrix file of this run (a row was written then)."""
    times = [p.stat().st_mtime for p in shots.glob("matrix_ui_napari_*.json")]
    return max(times, default=0.0)


def close_after_crash(shots: Path, reason: str, apps: list[str]) -> int:
    """For each app: add the crash row and a NOT_RUN row per expected id without a row; the number of red rows added."""
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    added = 0
    for app in apps:
        path = shots / ("matrix_ui_napari_%s.json" % app)
        expected_path = shots / ("expected_napari_%s.json" % app)
        doc: dict[str, Any] = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.is_file()
            else {"host": "napari", "app": app, "family": "ui", "started": stamp, "rows": []}
        )
        expected = json.loads(expected_path.read_text(encoding="utf-8")) if expected_path.is_file() else []
        done = {r["id"] for r in doc["rows"]}
        missing = ["ui_napari_driver_crashed"] + [i for i in expected if i not in done]
        for cid in missing:
            status, detail = (
                ("FAIL", reason)
                if cid == "ui_napari_driver_crashed"
                else ("NOT_RUN", "the driver crashed before this id ran")
            )
            line = (
                "CHECK %s FAIL %s" % (cid, detail)
                if status == "FAIL"
                else "NOTE %s not run: %s" % (cid, detail)
            )
            print(line[:300], flush=True)
            doc["rows"].append(
                {"id": cid, "family": "ui", "host": "napari", "app": app, "tool": "", "control": "", "status": status,
                 "detail": detail[:500], "seconds": 0.0, "screenshot": None, "ts": stamp}
            )  # fmt: skip
            added += 1
        doc["finished"], doc["expected"] = stamp, len(expected)
        doc.setdefault("host_version", "unknown (the audit crashed before it reported it)")
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    return added


def supervise(
    command: list[str], shots: Path, apps: list[str], idle_s: float, env: dict[str, str] | None = None
) -> int:
    """Run `command` (the audit); its exit code (0 / 1) when it ended by itself with a finished matrix, else 2 after writing the crash rows.
    `idle_s`: how long it may go without writing a row."""
    shots.mkdir(parents=True, exist_ok=True)
    started = time.time()
    child = subprocess.Popen(command, env=env)
    reason = ""
    while child.poll() is None:
        time.sleep(POLL_S)
        idle = time.time() - max(newest_write(shots), started)
        if idle > idle_s:
            child.kill()
            child.wait()
            reason = (
                "the audit wrote no row for %.0f s (the Qt thread is blocked): process killed by the watchdog"
                % idle
            )
    code = child.returncode
    finished = [
        (shots / ("matrix_ui_napari_%s.json" % app)).is_file()
        and json.loads((shots / ("matrix_ui_napari_%s.json" % app)).read_text(encoding="utf-8")).get(
            "finished"
        )
        for app in apps
    ]
    if not reason and code in (0, 1) and all(finished):
        return int(code)
    reason = reason or "the audit process ended with code %s before it finished its matrix" % code
    close_after_crash(shots, reason, apps)
    return 2


if __name__ == "__main__":
    sys.exit("ui_audit_watch is used by ui_audit.py")

"""Throwaway: run the script N times under the variant, count crashes (python driver: independent of bash)."""

import os
import subprocess
import sys
import time

n = int(sys.argv[1])
script = sys.argv[2]
variant = os.environ["EXP_VARIANT"]
nonzero = fatal_runs = noverdict = 0
codes = {}
for i in range(1, n + 1):
    t = time.time()
    try:
        p = subprocess.run(
            [sys.executable, "_exp_runner.py", script], capture_output=True, text=True, timeout=900, errors="replace"
        )
        rc, out = p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        rc, out = -999, "TIMEOUT " + str(e.stdout)[-2000:]
    fatal = out.count("Windows fatal exception")
    verdict = "FAILURES: none" in out
    rep = " | ".join(ln for ln in out.splitlines() if ln.startswith("EXITREPORT"))
    key = hex(rc & 0xFFFFFFFF)
    codes[key] = codes.get(key, 0) + 1
    nonzero += rc != 0
    fatal_runs += fatal > 0
    noverdict += not verdict
    print("run %d rc=%s fatal=%d verdict_none=%s %.0fs %s" % (i, key, fatal, verdict, time.time() - t, rep), flush=True)
    if rc != 0 or fatal:
        tail = out.splitlines()[-45:]
        print("::group::log tail run %d" % i)
        print("\n".join(ln for ln in tail if not ln.startswith('  "')))
        print("::endgroup::", flush=True)
msg = "SUMMARY variant=%s runs=%d nonzero_exit=%d fatal_exception_runs=%d no_verdict=%d rc_histogram=%s" % (
    variant, n, nonzero, fatal_runs, noverdict, codes,
)  # fmt: skip
print(msg)
with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
    f.write(msg + "\n")

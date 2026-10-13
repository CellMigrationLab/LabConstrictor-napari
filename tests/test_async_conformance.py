"""Every ASY fixture of conformance.json (SPEC_WRONG_SCIENCE 5.7) has a test here, and no test claims a fixture the file lacks.
A new or renamed fixture in the file fails this script until a test is written for it."""

import json
import re
import sys
from pathlib import Path

import _async

HERE = Path(__file__).resolve().parent
COVERED_BY = {
    "ASY-01": "test_async_stale.py",
    "ASY-02": "test_async_stale.py",
    "ASY-03": "test_async_stale.py",
    "ASY-04": "test_async_bounded.py",
    "ASY-05": "test_async_bounded.py",
    "ASY-06": "test_async_run.py",
    "ASY-07": "test_async_close.py",
    "ASY-08": "test_async_cache.py",
}
report, failures = {}, []


def expect(name, condition, detail=""):
    report[name] = bool(condition)
    if not condition:
        failures.append("%s %s" % (name, detail))


expect(
    "the file has exactly the fixtures the tests cover",
    sorted(_async.CASES) == sorted(COVERED_BY),
    sorted(_async.CASES),
)
for case_id, name in COVERED_BY.items():
    text = (HERE / name).read_text(encoding="utf-8")
    checks = re.findall(r'expect\(\s*"%s ' % case_id, text)
    expect(
        "%s is checked in %s" % (case_id, name),
        len(checks) >= 1 and ('_async.case("%s"' % case_id) in text,
        len(checks),
    )
    expect("%s has the expectation of the file in view" % case_id, bool(_async.CASES[case_id]["expect"]))
print(json.dumps(report, indent=2))
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)

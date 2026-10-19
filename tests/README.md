# tests/

Every `test_*.py` is a standalone script (run from this folder, under `xvfb-run -a` on Linux); CI runs them all
(`.github/workflows/ci.yml`). The other modules are helpers imported by name.

## The UI audit driver (`ui_audit*.py`)

`ui_audit.py` is not a test: it audits an INSTALLED app through the real Napari dock widget (every control, every tool's form, a real run
of each tool's first case from the app's own `lc_tests/cases.json`, screenshots) and writes a matrix of PASS / FAIL / NOT_RUN / HUMAN rows.
Modules: `ui_audit_core` (host, recorder, clicks), `ui_audit_controls` (the panel's control table), `ui_audit_forms` (per-parameter
form checks), `ui_audit_runs` (cases and runs), `ui_audit_place` (where results land), `ui_audit_watch` (the watchdog process).
`ui_synthetic_napari.py` runs a generated synthetic `cases.json` through the same form for the Tools repo's ground-truth checker.

    LC_HOME=<registry with the installed app> LC_APP=<registry name> LC_APP_TESTS=<the app's lc_tests> \
    LC_EXPECT_NAPARI=listed LC_SHOTS=./screens \
        xvfb-run -a -s "-screen 0 1600x1000x24" python tests/ui_audit.py

The variables, the statuses, the matrix format and every check id are in [`docs/UI_AUDIT.md`](../docs/UI_AUDIT.md). The driver is checked by
`test_ui_audit.py` (the example apps of labconstrictor-tools, with seeded failures) and `test_ui_audit_regressions.py` (the driver bugs found
on real apps).

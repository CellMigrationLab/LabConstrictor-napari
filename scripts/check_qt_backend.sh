#!/usr/bin/env bash
# Clean-environment check for one Qt backend (issue #41): a fresh virtualenv with the plugin and exactly one Qt6 binding,
# napari opened under a virtual display, the plugin found under Plugins > LabConstrictor tools and opened from that menu entry,
# plus the backend-dependent pieces (scrolling, results table dock, Details dialog). See tests/test_qt_backend.py.
#
# usage: scripts/check_qt_backend.sh pyqt6|pyside6 [venv-dir]      (Linux; needs xvfb-run; Python >= 3.11)
set -euo pipefail
backend="${1:?usage: $0 pyqt6|pyside6 [venv-dir]}"
case "$backend" in
  pyqt6) extra=test-pyqt6; expect=PyQt6 ;;
  pyside6) extra=test-pyside6; expect=PySide6 ;;
  *) echo "unknown backend: $backend (pyqt6 or pyside6)" >&2; exit 2 ;;
esac
root="$(cd "$(dirname "$0")/.." && pwd)"
venv="${2:-$(mktemp -d)/venv}"
# --copies: the tools registry refuses an interpreter in a world-writable folder, and a symlink would point into one
python3 -m venv --copies "$venv"
"$venv/bin/pip" install -q "git+https://github.com/CellMigrationLab/LabConstrictor-Tools" "$root[$extra]"
echo "installed in $venv:"; "$venv/bin/pip" list 2>/dev/null | grep -i -E "^(napari|PyQt|PySide|QtPy) "
cd "$root/tests"
LC_EXPECT_QT="$expect" PATH="$venv/bin:$PATH" xvfb-run -a python test_qt_backend.py

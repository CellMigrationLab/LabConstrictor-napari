"""The status line belongs to the tool that wrote it (H-N5): picking another tool, or another app, drops the previous tool's warning
(a calibration note, a refusal, a lookup problem) instead of leaving it under the new form. Real widget, real tool changes.
"""

import _paths  # noqa: F401  (must come first)
from _harness import choose, expect, finish, pump, register
from _harness import widget as w

register("roundtrip", "labconstrictor_tools.examples.roundtrip")
register("interactions", "labconstrictor_tools.examples.interactions")

choose("roundtrip", "Echo radio")
w.status.setText("⚠ pixel size: the image has no calibration")
w._lookup_note = w.status.text()
w.tool_box.value = next(name for name in w.tool_box.choices if name != "Echo radio")
pump(1.0)
expect("another_tool_clears_the_previous_warning", w.status.text() == "", w.status.text())
expect("another_tool_forgets_the_lookup_note", w._lookup_note == "", w._lookup_note)

w.status.setText("✖ refused: something about the previous app")
w.app_box.value = "interactions"
pump(1.0)
expect("another_app_clears_the_previous_refusal", w.status.text() == "", w.status.text())
finish()

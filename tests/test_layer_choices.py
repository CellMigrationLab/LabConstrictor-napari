"""Inserting and removing layers refreshes the layer choosers and nothing else (N-1): a form with a radio choice used to leave parentless
QRadioButton windows behind (magicgui's radio group rebuilds its buttons on `reset_choices`). Real layer events, real widgets.
"""

import _paths  # noqa: F401  (must come first)
import numpy as np
from _harness import choose, expect, finish, pump, register, viewer
from _harness import widget as w
from qtpy.QtWidgets import QApplication, QRadioButton


def stray_radios() -> list[QRadioButton]:
    return [t for t in QApplication.topLevelWidgets() if t.isVisible() and isinstance(t, QRadioButton)]


def cycle(count: int) -> None:
    for index in range(count):
        viewer.add_image(np.zeros((16, 16), np.uint8), name="p%d" % index)
        pump(0.15)
    viewer.layers.clear()
    pump(0.3)


register("roundtrip", "labconstrictor_tools.examples.roundtrip")
register("interactions", "labconstrictor_tools.examples.interactions")

choose("roundtrip", "Echo radio")
expect(
    "the_form_has_a_radio_group",
    any(type(widget).__name__ == "RadioButtons" for widget in w.gui),
    [type(x).__name__ for x in w.gui],
)
before = len(stray_radios())
for count in (1, 3, 3, 6):
    cycle(count)
expect(
    "layer_events_leave_no_stray_radio_windows", len(stray_radios()) == before, (before, len(stray_radios()))
)
expect("the_radio_value_is_kept", w.gui.value.value == "two", w.gui.value.value)

# the layer chooser still follows the layers
choose("interactions", "Mean of a channel")
viewer.add_image(np.zeros((8, 8), np.uint8), name="chooser")
pump(0.3)
expect(
    "layer_chooser_lists_the_new_layer",
    "chooser" in [str(c) for c in w.gui.image.choices],
    list(w.gui.image.choices),
)
viewer.layers.clear()
pump(0.3)
expect(
    "layer_chooser_forgets_the_removed_layer",
    "chooser" not in [str(c) for c in w.gui.image.choices],
    list(w.gui.image.choices),
)
finish()

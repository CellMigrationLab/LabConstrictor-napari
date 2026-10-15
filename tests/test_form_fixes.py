"""Three form fixes of the alpha.2 audit, with real widgets: a control of a replaced form no longer refreshes the new form (H-N4), the
Channel chooser keeps the colours of an RGB layer when the form's choices are reset, and the collapsible group headings are forgotten with
their form."""

import _paths  # noqa: F401  (must come first)
import numpy as np
from _harness import choose, expect, finish, pump, register, viewer
from _harness import widget as w

register("interactions", "labconstrictor_tools.examples.interactions")

# H-N4: the controls of the form that was replaced
choose("interactions", "Show a shape")
old_controls = [  # the controls whose slot refreshes what is greyed out (a group heading folds its group: not one of them)
    widget for widget in w.gui if hasattr(widget, "changed") and widget.native.property("lc_group") is None
]
expect("old_form_has_controls", len(old_controls) > 2, len(old_controls))
expect("group_heading_kept_while_the_form_is_shown", bool(w._group_heading), w._group_heading)

choose("interactions", "Mean of a channel")
expect("group_heading_forgotten_with_its_form", w._group_heading == {}, w._group_heading)

calls = []
real = w._refresh_enabled
w._refresh_enabled = lambda: calls.append(1)
for widget in old_controls:
    widget.changed.emit(None)
pump(0.2)
expect("old_form_controls_refresh_nothing", calls == [], len(calls))
w.file_sources["image"].changed.emit(None)  # a control of the form now shown
expect("current_form_controls_still_refresh", calls == [1], calls)
w._refresh_enabled = real

# the Channel chooser of an RGB layer survives a reset of the form's choices
layer = viewer.add_image(
    np.random.default_rng(1).integers(0, 255, (8, 8, 3), dtype=np.uint8), rgb=True, name="colour"
)
w.gui.image.value = layer
pump(0.5)
box = w.channel_boxes["image"]
colours = ["Red", "Green", "Blue"]
expect("rgb_chooser_lists_the_colours", list(box.choices) == colours and box.visible, list(box.choices))
w.gui.reset_choices()
pump(0.3)
expect("rgb_chooser_keeps_the_colours_after_reset_choices", list(box.choices) == colours, list(box.choices))

finish()

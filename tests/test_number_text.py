"""Empty and required numbers, optional numbers, defaults, the copied command and sliders, through the real form (docs/SPEC_WRONG_SCIENCE.md section 6,
HOST_PARITY B01, B04, B07). The grammar and the precision are in test_number_grammar.py.

The REQUEST a click would send (`_prepare_inputs`) is what is checked; an empty required field is refused (`'L' is required: type a number`),
an optional one that is set and empty too, and a copied command never carries a number that a run would refuse.
"""

import _paths  # noqa: F401  (must come first)
from _numhelpers import INT_MAX, above, choose, expect, finish, refuses, request, type_text, w

# ---- empty and required ------------------------------------------------------------------------------------------------------
refuses("required_emptied", "Free integer", "n", "", "'N' is required: type a number")
refuses("required_blanks", "Free float", "x", "   ", "'X' is required: type a number")
refuses("optional_with_default_emptied", "Defaults", "n", "", "'N' is empty: type a number")
choose("Defaults")
inputs, refused = request()
expect("defaults_are_sent_as_shown", inputs is not None and inputs == {"n": 3, "x": 0.125}, (inputs, refused))
expect(
    "defaults_shown_as_text",
    (w.gui["n"].native.text(), w.gui["x"].native.text()) == ("3", "0.125"),
    w.gui["x"].native.text(),
)

# a required number with no default starts at the allowed value nearest to 0 (B07), shown, and sent as shown
for tag, tool, expected in [
    ("start_free_integer", "Free integer", "0"),
    ("start_free_float", "Free float", "0.0"),
    ("start_bounded", "Bounded integer", "0"),
    ("start_bounded_float", "Bounded float", "0.5"),
    ("start_min_5", "Required positive", "5"),
]:
    choose(tool)
    field = w.tool["inputs"][0]["name"]
    expect(tag, w.gui[field].native.text() == expected, w.gui[field].native.text())
    inputs, refused = request()
    expect(tag + "_request", inputs is not None and str(inputs[field]) == expected, (inputs, refused))

# ---- optional numbers: unset is left out; set and empty is refused; set and typed is sent -----------------------------------------
choose("Optional numbers")
inputs, refused = request()
expect("optional_unset_is_omitted", inputs == {}, (inputs, refused))
w.unset_toggles["n"].value = True
inputs, refused = request()
expect(
    "optional_set_but_empty_is_refused",
    inputs is None and refused == "⚠ 'N' is empty: type a number",
    (inputs, refused),
)
type_text("n", str(INT_MAX))
inputs, refused = request()
expect("optional_set_and_typed", inputs == {"n": INT_MAX} and type(inputs["n"]) is int, (inputs, refused))
type_text("n", str(INT_MAX + 1))
inputs, refused = request()
expect("optional_beyond_limit_refused", inputs is None and refused == above("N", INT_MAX), (inputs, refused))
w.unset_toggles["n"].value = False  # not sent at all: what is in the box does not matter
inputs, refused = request()
expect("optional_unticked_ignores_its_text", inputs == {}, (inputs, refused))

# ---- the command line a copy would make never carries a number that a run refuses --------------------------------------------------
choose("Free integer")
type_text("n", "9007199254740991")
line = w.copy_as_command("terminal")
expect("copy_carries_the_exact_number", line is not None and "9007199254740991" in line, line)
type_text("n", "9007199254740992")
w.status.setText("")
line = w.copy_as_command("terminal")
expect(
    "copy_refuses_a_number_a_run_refuses",
    line is None and w.status.text() == above("N", INT_MAX),
    (line, w.status.text()),
)
type_text("n", "abc")
line = w.copy_as_command("python")
expect(
    "copy_python_refuses_text",
    line is None and "must be an integer, got 'abc'" in w.status.text(),
    (line, w.status.text()),
)

# ---- sliders: the readout takes no typing (a spin box would clamp or round it); a range a slider cannot hold is a text field -----
choose("Slider")
readout = w.gui["level"]._widget._readout_widget.lineEdit()
expect("slider_readout_is_read_only", readout.isReadOnly())
inputs, refused = request()
expect("slider_sends_its_position", inputs == {"level": 0.25}, (inputs, refused))
choose("Wide slider")
expect(
    "range_beyond_32_bits_is_a_text_field",
    type(w.gui["n"]).__name__ == "IntegerField",
    type(w.gui["n"]).__name__,
)
type_text("n", str(2**40))
inputs, refused = request()
expect("wide_range_sent_exactly", inputs == {"n": 2**40}, (inputs, refused))

finish()

"""The linked pixel-size field as text: what the person enters, how it is read, and what an automatic value shows
(docs/SPEC_WRONG_SCIENCE.md 2.2, 2.3 and 6.2; CAL-T3, CAL-T4, CAL-T9 on the text-backed field).

Entries are made as a person makes them (pasted or typed into the line, then Enter) and the check is on the REQUEST. Typed values are never
rounded (the old spin box kept 10 decimals) and never clamped; an automatic value shows its exact digits; text that is not a number is a
`user` value that Run refuses with a sentence; 0 or an empty box is the person asking for the image's calibration again.
"""

import _paths  # noqa: F401  (must come first)
from _linkedhelpers import (
    FIELD,
    LABEL,
    NOCAL,
    UM,
    UM2,
    above,
    enter,
    expect,
    finish,
    link,
    refuses,
    request,
    sends,
    shown,
    start,
    start_with_file,
    w,
)
from qtpy.QtCore import Qt
from qtpy.QtTest import QTest

from napari_labconstrictor import _numbers

# ---- no rounding, no clamping of what was typed -----------------------------------------------------------------------------------
start("Linked free")
sends("more_than_10_decimals", "0.12345678901234567", 0.12345678901234567)
sends("tiny_is_not_rounded_to_zero", "0.00000000012345", 1.2345e-10)
sends("exponent", "2.5e-3", 0.0025)
sends("trailing_zero_is_kept_as_typed", "0.250", 0.25)
sends("the_shortest_float_above_one_third", "0.30000000000000004", 0.30000000000000004)
sends("a_value_beyond_the_old_box_step", "123456789.123456789", 123456789.123456789)
expect(
    "user_tooltip_has_the_exact_value",
    "123456789.12345679 um per pixel" in w.gui[FIELD].tooltip,
    w.gui[FIELD].tooltip,
)

# ---- text that is not a number is a value, refused at Run with a sentence -------------------------------------------------------------
for tag, text, got in [
    ("letters", "abc", "'abc'"),
    ("decimal_comma", "1,5", "'1,5'"),
    ("hexadecimal", "0x10", "'0x10'"),
    ("trailing_point", "5.", "'5.'"),
]:
    refuses(tag, text, "⚠ '%s' must be a number, got %s" % (LABEL, got))
refuses("nan", "nan", "⚠ '%s' must be a finite number, got 'nan'" % LABEL)
refuses("too_close_to_zero", "1e-400", "⚠ '%s' is too close to zero to be held exactly, got '1e-400'" % LABEL)
expect("tooltip_says_it_is_not_a_number", "not a number" in w.gui[FIELD].tooltip, w.gui[FIELD].tooltip)
button = next(b for b in w.gui if getattr(b, "text", "") == "use the image's calibration")
button.native.click()
expect("the_button_forgets_the_bad_text", shown() == "" and link().state == "unset", (shown(), link().state))

# ---- 0 or an empty box is the person asking for the image's calibration (CAL-T4), whatever the spelling ----------------------------
start("Linked free", UM)
expect("T4_auto_shows_the_exact_value", shown() == "0.25" and link().state == "auto", (shown(), link().state))
for spelling in ("0", "0.0", "0e5", "-0", ""):
    sends("T4_user_before_" + (spelling or "empty"), "0.3", 0.3)
    enter(spelling)
    inputs, refused = request()
    expect(
        "T4_clears_with_" + (spelling or "empty"),
        link().state == "auto" and shown() == "0.25" and inputs is not None and inputs[FIELD] == 0.25,
        (spelling, link().state, shown(), refused),
    )
# a negative number is a value, not a clear: it is refused, never turned into "not set" (what the spin box's lowest position did)
refuses(
    "negative_is_not_a_clear",
    "-1",
    "⚠ [invalid_parameter] '%s' must be greater than 0 (um per pixel)" % LABEL,
)

# ---- the entry counts when it is typed, not only when Enter is pressed (a click on Run takes the focus away or not) ------------------
start("Linked free", UM)
enter("0.4", confirm=False)
inputs, refused = request()
expect("unconfirmed_entry_is_sent", inputs is not None and inputs[FIELD] == 0.4, (inputs, refused))
expect("unconfirmed_entry_is_user", link().state == "user" and shown() == "0.4", (link().state, shown()))
enter("0", confirm=False)
inputs, refused = request()
expect(
    "unconfirmed_zero_clears",
    inputs is not None and inputs[FIELD] == 0.25 and link().state == "auto",
    (inputs, refused),
)

# an entry the host replaces before it is confirmed (the source changed) is gone: Enter afterwards is not an edit of the new text
start("Linked free", UM)
enter("0.4", confirm=False)
w.gui.image.value = UM2
QTest.keyClick(w.gui[FIELD].native, Qt.Key.Key_Return)
expect("replaced_entry_is_not_an_edit", link().state == "auto" and shown() == "0.5", (link().state, shown()))

# ---- CAL-T3 / T9: a typed value stays, as typed, across source changes; the flag decides, not a comparison -----------------------------
start("Linked free", UM)
sends("T9_same_value_other_spelling", "0.250", 0.25)
w.gui.image.value = NOCAL
inputs, refused = request()
expect(
    "T9_stays_user",
    inputs is not None and inputs[FIELD] == 0.25 and shown() == "0.250",
    (inputs, refused, shown()),
)
w.gui.image.value = UM
expect(
    "T3_the_text_is_never_rewritten", shown() == "0.250" and link().state == "user", (shown(), link().state)
)
expect(
    "T3_tooltip_names_the_entry",
    "0.25" in w.gui[FIELD].tooltip and "overrides" in w.gui[FIELD].tooltip,
    w.gui[FIELD].tooltip,
)

# ---- an automatic value shows its exact digits and is sent as it is (no rounding to 10 decimals) --------------------------------------
for tag, scale in [
    ("ten_decimals_would_round", 1.2345e-10),
    ("long_fraction", 0.1234567890123456),
    ("repeating", 1 / 3),
]:
    start_with_file("Linked free", scale, tag)
    value = link().value
    inputs, refused = request()
    expect(
        tag + "_shows_the_exact_value",
        shown() == _numbers.as_text(value)
        and float(shown()) == value
        and abs(value - scale) <= 1e-15 * scale,
        (shown(), value),
    )
    expect(tag + "_sent_exactly", inputs is not None and inputs[FIELD] == value, (inputs, refused))
    expect(tag + "_state", link().state == "auto", link().state)
    expect(
        tag + "_tooltip_has_the_exact_value",
        _numbers.as_text(value) in w.gui[FIELD].tooltip,
        w.gui[FIELD].tooltip,
    )
start_with_file("Linked free", 2e15, "huge")
inputs, refused = request()
expect(
    "auto_beyond_the_limit_is_refused", inputs is None and refused == above(LABEL, 1e15), (inputs, refused)
)
expect("auto_beyond_the_limit_is_not_clamped", shown() == "2000000000000000.0", shown())

# ---- an Optional linked field: unset is null, a typed value is checked like any other ---------------------------------------------
start("Linked optional")
inputs, refused = request()
expect("optional_unset_is_null", inputs is not None and inputs[FIELD] is None, (inputs, refused))
refuses("optional_not_a_number", "abc", "⚠ '%s' must be a number, got 'abc'" % LABEL)
sends("optional_typed_value", "0.4", 0.4)
finish()

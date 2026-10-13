"""Number limits through the real form (docs/SPEC_WRONG_SCIENCE.md section 6; CONFORMANCE.md NUM-01..05).

The cases come from conformance.json (`wrong_science.number_limits`); each is typed into the box key by key, and the check is on the REQUEST
a click would send (`_prepare_inputs`) or on the sentence it shows instead, never on the box alone: a value beyond a limit is refused,
never clamped (never `9007199254740991` or `2147483647` in its place), no request is made, and the text stays as the person typed it.
The grammar, precision and the other kinds of wrong entry are in test_number_text.py.
"""

import _paths  # noqa: F401  (must come first)
from _numhelpers import (
    FLOAT_MAX,
    INT_MAX,
    NUM,
    C,
    above,
    below,
    choose,
    expect,
    finish,
    paste_text,
    request,
    type_text,
    w,
)


def entry(
    tag: str,
    tool: str,
    name: str,
    text: str,
    accepted: bool,
    sentence: str | None = None,
    value: float | None = None,
) -> None:
    """Type `text` into field `name` of `tool`; the click either sends `value` (exactly, same type) or refuses with `sentence`."""
    choose(tool)
    type_text(name, text)
    inputs, refused = request()
    shown = w.gui[name].native.text()
    if accepted:
        got = None if inputs is None else inputs.get(name)
        expect(
            tag + "_sent", inputs is not None and got == value and type(got) is type(value), (inputs, refused)
        )
    else:
        expect(tag + "_refused_with_the_sentence", refused == sentence, (refused, sentence))
        expect(tag + "_no_request", inputs is None, inputs)
        expect(tag + "_text_kept_as_typed", shown == text, shown)  # not clamped, not shortened
        stand_in = w.gui[name].value
        expect(
            tag + "_never_a_stand_in", stand_in not in (INT_MAX, -INT_MAX, 2147483647, -2147483647), stand_in
        )


# the limits themselves are the conformance file's
expect("limit_integer", C["limits"]["form_integer_max"]["value"] == 9007199254740991 == INT_MAX)
expect("limit_float", C["limits"]["unbounded_float"]["value"] == 1e15 == FLOAT_MAX)

# NUM-01 .. NUM-03: an integer field with no Min/Max
n = NUM["NUM-01"]
entry("NUM-01", "Free integer", "n", n["typed"], True, value=int(n["typed"]))
n = NUM["NUM-02"]
entry("NUM-02", "Free integer", "n", n["typed"], False, above("N", INT_MAX))
expect("NUM-02_expectation_names_the_limit", "<= %d" % INT_MAX in n["expect"], n["expect"])
n = NUM["NUM-03"]
entry("NUM-03", "Free integer", "n", n["typed"], False, below("N", -INT_MAX))
expect("NUM-03_expectation_names_the_limit", ">= -%d" % INT_MAX in n["expect"], n["expect"])

# NUM-04: a float field with no Min/Max
accepted, refused = NUM["NUM-04"]["typed"]
entry("NUM-04_accepted", "Free float", "x", accepted, True, value=1e15)
entry("NUM-04_refused", "Free float", "x", refused, False, above("X", FLOAT_MAX))
entry("NUM-04_refused_negative", "Free float", "x", "-" + refused, False, below("X", -FLOAT_MAX))
entry("NUM-04_accepted_negative", "Free float", "x", "-" + accepted, True, value=-1e15)

# NUM-05: a declared Max of 10 refuses 11 (unchanged), and the other side of a declared range
entry("NUM-05", "Bounded integer", "n", NUM["NUM-05"]["typed"], False, above("N", 10))
entry("declared_max_itself", "Bounded integer", "n", "10", True, value=10)
entry("declared_min_itself", "Bounded integer", "n", "0", True, value=0)
entry("declared_below_min", "Bounded integer", "n", "-1", False, below("N", 0))
entry("declared_float_max", "Bounded float", "x", "2.5", True, value=2.5)
entry("declared_float_above", "Bounded float", "x", "2.5000000000000004", False, above("X", 2.5))
entry("declared_float_below", "Bounded float", "x", "0.49999999999999994", False, below("X", 0.5))

# a declared range wider than the form's own is cut to the form's: the sentence names the limit that applies
entry("wide_range_above", "Huge declared range", "n", str(2**55), False, above("N", INT_MAX))
entry("wide_range_below", "Huge declared range", "n", str(-(2**55)), False, below("N", -INT_MAX))
entry("wide_range_inside", "Huge declared range", "n", str(INT_MAX), True, value=INT_MAX)

# very long text is a number too far, not a crash and not the limit
entry("endless_digits_above", "Free integer", "n", "9" * 5000, False, above("N", INT_MAX))
entry("endless_digits_below", "Free integer", "n", "-" + "9" * 5000, False, below("N", -INT_MAX))

# pasted text takes the same road as typed text (the whole string arrives at once)
choose("Free integer")
paste_text("n", str(INT_MAX + 1))
inputs, refused = request()
expect("pasted_beyond_limit_refused", inputs is None and refused == above("N", INT_MAX), (inputs, refused))
expect("pasted_text_kept", w.gui["n"].native.text() == str(INT_MAX + 1), w.gui["n"].native.text())

# a refusal never leaves a run behind: no task, no worker started
expect("no_task_started", w.task is None or w.task.done.is_set())

finish()

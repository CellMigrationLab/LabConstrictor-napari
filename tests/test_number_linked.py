"""NUM-01..05 on the linked pixel-size field (docs/SPEC_WRONG_SCIENCE.md sections 2.2 and 6; CONFORMANCE.md NUM, CAL-T).

The linked field is a line of text like every number field, not a Qt spin box (which rounded at 10 decimals and clamped a typed value to its
range). Each case is entered into the real form and the check is on the REQUEST a click would send (`_prepare_inputs`) or on the sentence
it shows instead: a value beyond a limit is refused with the conformance sentence, never clamped; the request carries the exact typed number
as a float; the box keeps the text as typed. NUM-01..03 are integer cases: a float field has the float limit, so they are refused with it.
"""

import _paths  # noqa: F401  (must come first)
from _linkedhelpers import (
    FLOAT_MAX,
    LABEL,
    NOT_POSITIVE,
    NUM,
    above,
    below,
    finish,
    refuses,
    sends,
    start,
)

# the free field (no Min / Max): the form's own float limit, +-1e15
start("Linked free")
accepted, beyond = NUM["NUM-04"]["typed"]
sends("NUM-04_accepted", accepted, 1e15)
refuses("NUM-04_refused", beyond, above(LABEL, FLOAT_MAX))
refuses("NUM-04_refused_negative", "-" + beyond, below(LABEL, -FLOAT_MAX))
refuses("NUM-04_accepted_negative_is_not_a_pixel_size", "-" + accepted, NOT_POSITIVE)
for ident in (
    "NUM-01",
    "NUM-02",
):  # an integer typed into a float field: beyond 1e15, refused; never the integer limit or 32 bits
    refuses(ident + "_on_the_float_field", NUM[ident]["typed"], above(LABEL, FLOAT_MAX))
refuses("NUM-03_on_the_float_field", NUM["NUM-03"]["typed"], below(LABEL, -FLOAT_MAX))
refuses("beyond_a_double", "1e999", "⚠ '%s' must be a finite number, got '1e999'" % LABEL)
refuses("beyond_a_double_negative", "-1e999", "⚠ '%s' must be a finite number, got '-1e999'" % LABEL)
sends("beyond_32_bits_is_not_clamped", "3000000000", 3e9)

# NUM-05: a declared Max of 10 refuses 11 (unchanged), and the other side of the declared range
start("Linked bounded")
refuses("NUM-05", NUM["NUM-05"]["typed"], above(LABEL, 10))
sends("declared_max_itself", "10", 10.0)
refuses("declared_max_float_above", "10.000000000000002", above(LABEL, 10))
refuses("declared_min_below", "-0.5", below(LABEL, 0))
sends("declared_range_inside", "9.999999999999998", 9.999999999999998)
finish()

"""The grammar and the precision of number fields through the real form (docs/SPEC_WRONG_SCIENCE.md section 6, HOST_PARITY D02..D06, I06).

The REQUEST a click would send (`_prepare_inputs`) is what is checked. A number is what the person typed, no more and no less: no rounding to
a box's decimals, no exponent lost, no digit dropped; a text that is not a number, is not finite or would become 0.0 is refused with the
worker's sentence (`'L' must be an integer`, `'L' must be a finite number`, ...) followed by `, got 'text'`. Nothing is sent.
"""

import _paths  # noqa: F401  (must come first)
from _numhelpers import INT_MAX, finish, refuses, sends

# ---- integers: optional sign and ASCII digits, trimmed; nothing else -------------------------------------------------------------
sends("int_plain", "Free integer", "n", "42", 42)
sends("int_plus_sign", "Free integer", "n", "+7", 7)
sends("int_negative", "Free integer", "n", "-12", -12)
sends("int_leading_zeros", "Free integer", "n", "007", 7)
sends("int_three_billion_is_not_a_32_bit_box", "Free integer", "n", "3000000000", 3_000_000_000)
sends("int_just_below_the_limit", "Free integer", "n", str(INT_MAX - 1), INT_MAX - 1)
sends("int_negative_limit", "Free integer", "n", str(-INT_MAX), -INT_MAX)
sends("int_blanks_trimmed", "Free integer", "n", " 9 ", 9)
for tag, text in [
    ("int_fraction", "2.5"),
    ("int_whole_with_fraction", "2.0"),
    ("int_exponent", "1e3"),
    ("int_underscore", "1_000"),
    ("int_hex", "0x10"),
    ("int_words", "abc"),
    ("int_comma", "1,5"),
    ("int_arabic_digits", "١٢"),
    ("int_double_sign", "--1"),
    ("int_inside_blanks", "1 2"),
]:
    refuses(tag, "Free integer", "n", text, "'N' must be an integer, got '%s'" % text)

# ---- floats: sign, digits with an optional fraction (or only a fraction), optional exponent --------------------------------------
sends("float_plain", "Free float", "x", "0.5", 0.5)
sends("float_exponent_is_read", "Free float", "x", "1e3", 1000.0)
sends("float_upper_exponent", "Free float", "x", "2.5E-3", 0.0025)
sends("float_only_fraction", "Free float", "x", ".25", 0.25)
sends("float_integer_text", "Free float", "x", "7", 7.0)
sends("float_negative_zero_point_five", "Free float", "x", "-0.5", -0.5)
# precision: no decimals of a box, no rounding of the text the person typed
sends("float_three_decimals_not_rounded", "Free float", "x", "0.125", 0.125)
sends("float_sixteen_digits_kept", "Free float", "x", "0.1234567890123456", 0.1234567890123456)
sends("float_a_calibration_kept", "Free float", "x", "0.3250000001", 0.3250000001)
sends("float_tiny_kept", "Free float", "x", "1e-300", 1e-300)
sends(
    "float_beyond_17_digits_is_the_nearest_double",
    "Free float",
    "x",
    "0.30000000000000004",
    0.30000000000000004,
)
for tag, text in [
    ("float_words", "abc"),
    ("float_comma", "1,5"),
    ("float_underscore", "1_0"),
    ("float_hex", "0x1p3"),
    ("float_dot_only", "5."),
    ("float_exponent_only", "e5"),
]:
    refuses(tag, "Free float", "x", text, "'X' must be a number, got '%s'" % text)
for tag, text in [
    ("float_nan", "nan"),
    ("float_inf", "inf"),
    ("float_minus_infinity", "-Infinity"),
    ("float_overflow", "1e999"),
    ("float_negative_overflow", "-1e999"),
]:
    refuses(tag, "Free float", "x", text, "'X' must be a finite number, got '%s'" % text)
# a text that would silently become 0.0 is refused, not turned into zero
refuses(
    "float_underflow_to_zero",
    "Free float",
    "x",
    "1e-400",
    "'X' is too close to zero to be held exactly, got '1e-400'",
)
sends("float_real_zero", "Free float", "x", "0.0", 0.0)
sends("float_zero_with_exponent", "Free float", "x", "0e5", 0.0)

finish()

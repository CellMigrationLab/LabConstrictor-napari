"""Number fields of a form (docs/SPEC_WRONG_SCIENCE.md section 6): what the person typed is what is checked, and what is sent.

A number is held as TEXT (`_number_field.NumberField`), because no Qt spin box holds every whole number up to 2**53 - 1 and every
double without shortening it. The click reads that text (`check`): a value beyond a limit, declared or the form's own, is refused with
the worker's sentence (HOST_PARITY I06) and never clamped, rounded to the box's decimals, or replaced by another number. No Qt here.

Grammar (HOST_PARITY D02, D03; the conformance file carries no regex yet): an integer is an optional sign and ASCII digits; a float is an
optional sign, digits with an optional fraction (or only a fraction) and an optional exponent. Surrounding blanks are trimmed. Nothing
else is read as a number (no `1_000`, no `0x10`, no `5.`, no `nan` or `inf`, no non-ASCII digits).
"""

from __future__ import annotations

import math
import re
from typing import Any

MAX_FORM_INTEGER = 2**53 - 1  # conformance.json limits.form_integer_max
MAX_FORM_FLOAT = 1e15  # conformance.json limits.unbounded_float
INTEGER_RANGE = (-MAX_FORM_INTEGER, MAX_FORM_INTEGER)
FLOAT_RANGE = (-MAX_FORM_FLOAT, MAX_FORM_FLOAT)

ABOVE_MAXIMUM = "'{label}' must be <= {maximum}"  # conformance.json messages.number_above_maximum
BELOW_MINIMUM = "'{label}' must be >= {minimum}"  # messages.number_below_minimum
NOT_AN_INTEGER = "'{label}' must be an integer, got {got}"  # worker template + ", got 'x'" (HOST_PARITY I06)
NOT_A_NUMBER = "'{label}' must be a number, got {got}"
NOT_FINITE = "'{label}' must be a finite number, got {got}"
TOO_SMALL = "'{label}' is too close to zero to be held exactly, got {got}"  # SPEC GAP: a text that would silently become 0.0
REQUIRED = "'{label}' is required: type a number"  # worker template of B01 plus a hint
EMPTY = "'{label}' is empty: type a number"  # an optional field the person emptied: the default is never a stand-in

_INTEGER = re.compile(r"[+-]?[0-9]+")
_FLOAT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_NON_FINITE = re.compile(r"[+-]?(?:nan|inf|infinity)", re.IGNORECASE)
_INTEGER_DIGITS = 1000  # an integer text with more significant digits than this is never converted (Python limits int() at 4300)


def limits(param: dict[str, Any]) -> tuple[Any, Any]:
    """(lowest, highest) a value of `param` may have: the tool's Min / Max, cut to the form's own limit."""
    low, high = INTEGER_RANGE if param["type"] == "integer" else FLOAT_RANGE
    return max(param.get("minimum", low), low), min(param.get("maximum", high), high)


def _quoted(text: Any) -> str:
    return "'%s'" % text if isinstance(text, str) else "%s" % (text,)


class Beyond(ValueError):
    """An integer text too long to convert: beyond every limit, on the side its sign says."""

    def __init__(self, negative: bool) -> None:
        super().__init__("beyond every limit")
        self.negative = negative


def read(kind: str, text: str, label: str = "") -> int | float:
    """The number `text` reads as (grammar only, no limits), or ValueError with the sentence; `Beyond` for an endless integer."""
    stripped = text.strip()
    if kind == "integer":
        if not _INTEGER.fullmatch(stripped):
            raise ValueError(NOT_AN_INTEGER.format(label=label, got=_quoted(text)))
        if len(stripped.lstrip("+-").lstrip("0")) > _INTEGER_DIGITS:
            raise Beyond(stripped.startswith("-"))
        return int(stripped)
    if not _FLOAT.fullmatch(stripped):
        if _NON_FINITE.fullmatch(stripped):
            raise ValueError(NOT_FINITE.format(label=label, got=_quoted(text)))
        raise ValueError(NOT_A_NUMBER.format(label=label, got=_quoted(text)))
    number = float(stripped)
    if not math.isfinite(number):  # an exponent beyond the double range
        raise ValueError(NOT_FINITE.format(label=label, got=_quoted(text)))
    if number == 0.0 and any(c in "123456789" for c in re.split("[eE]", stripped)[0]):
        raise ValueError(TOO_SMALL.format(label=label, got=_quoted(text)))
    return number


def _range(param: dict[str, Any], value: Any) -> Any:
    low, high = limits(param)
    label = param["label"]
    if value < low:
        raise ValueError(BELOW_MINIMUM.format(label=label, minimum=low))
    if value > high:
        raise ValueError(ABOVE_MAXIMUM.format(label=label, maximum=high))
    return value


def check(param: dict[str, Any], value: Any) -> int | float:
    """The number a run sends for integer or float `param`, or ValueError with the sentence the person is shown.

    `value` is what the field holds: its text (as typed), a number, or None (empty). A number that is not exactly what the
    parameter's type holds (a boolean, an integer that is not whole, a float that is not finite) is refused as well.
    """
    label, kind = param["label"], param["type"]
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError((REQUIRED if param.get("required") else EMPTY).format(label=label))
    if isinstance(value, str):
        try:
            number: int | float = read(kind, value, label)
        except Beyond as beyond:
            low, high = limits(param)
            if beyond.negative:
                raise ValueError(BELOW_MINIMUM.format(label=label, minimum=low)) from None
            raise ValueError(ABOVE_MAXIMUM.format(label=label, maximum=high)) from None
    elif isinstance(value, bool):
        template = NOT_AN_INTEGER if kind == "integer" else NOT_A_NUMBER
        raise ValueError(template.format(label=label, got="true/false"))
    elif isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(NOT_FINITE.format(label=label, got=_quoted(repr(value))))
        if kind == "integer":
            if not value.is_integer():
                raise ValueError(NOT_AN_INTEGER.format(label=label, got=_quoted(repr(value))))
            number = int(value)
        else:
            number = value
    else:
        template = NOT_AN_INTEGER if kind == "integer" else NOT_A_NUMBER
        raise ValueError(template.format(label=label, got=_quoted(value)))
    _range(param, number)
    return number if kind == "integer" else float(number)


def nearest_to_zero(param: dict[str, Any]) -> int | float:
    """Where a required number with no default starts (HOST_PARITY B07): the allowed value nearest to 0."""
    low, high = limits(param)
    value = min(max(0, low), high)
    return int(value) if param["type"] == "integer" else float(value)


def as_text(value: Any) -> str:
    """A value the host sets (a default, a program) as the text the person would see: shortest text that reads back exactly."""
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    return str(value)

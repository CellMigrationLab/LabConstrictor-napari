"""The number rules of conformance.json against this host's constants and sentences (no Qt): limits, message templates, and NUM-01..05
through `_numbers.check`, the function every click and every copy goes through."""

import json
import sys
from typing import TYPE_CHECKING

import _paths  # noqa: F401  (must come first)
from labconstrictor_tools import conformance

from napari_labconstrictor import _numbers, _schema

if TYPE_CHECKING:
    from typing import Any

C = conformance.load()
NUM = {case["id"]: case for case in C["wrong_science"]["number_limits"]["cases"]}
report, failures = {}, []


def expect(name: str, ok: object, detail: object = "") -> None:
    report[name] = bool(ok)
    if not ok:
        failures.append("%s %s" % (name, detail))


def refused(param: "dict[str, Any]", value: object) -> str | None:
    try:
        _numbers.check(param, value)
    except ValueError as error:
        return str(error)
    return None


INT = {"name": "n", "label": "L", "type": "integer", "required": True}
FLOAT = {"name": "x", "label": "L", "type": "float", "required": True}
limit = C["limits"]
expect(
    "limits_of_an_unbounded_field",
    _numbers.limits(INT) == (-9007199254740991, 9007199254740991) and _numbers.limits(FLOAT) == (-1e15, 1e15),
)
expect(
    "limits_of_a_declared_field",
    _numbers.limits({**INT, "minimum": 0, "maximum": 10}) == (0, 10)
    and _numbers.limits({**FLOAT, "maximum": 2.5}) == (-1e15, 2.5),
)
expect(
    "declared_beyond_the_form_is_cut",
    _numbers.limits({**INT, "minimum": -(2**60), "maximum": 2**60}) == (-9007199254740991, 9007199254740991)
    and _numbers.limits({**FLOAT, "maximum": 1e20}) == (-1e15, 1e15),
)
expect(
    "integer_limit",
    _numbers.MAX_FORM_INTEGER == _schema.MAX_FORM_INTEGER == limit["form_integer_max"]["value"],
)
expect(
    "integer_range",
    _numbers.INTEGER_RANGE
    == (-limit["form_integer_max"]["value"], limit["form_integer_max"]["value"])
    == _schema._INT_RANGE,
)
expect(
    "float_limit",
    limit["unbounded_float"]["value"] == _numbers.MAX_FORM_FLOAT
    and _numbers.FLOAT_RANGE == _schema._FLOAT_RANGE,
)
expect("above_template", C["messages"]["number_above_maximum"]["template"] == _numbers.ABOVE_MAXIMUM)
expect("below_template", C["messages"]["number_below_minimum"]["template"] == _numbers.BELOW_MINIMUM)
expect(
    "limits_are_decided",
    limit["form_integer_max"]["status"] == "decided" and limit["unbounded_float"]["status"] == "decided",
)

expect(
    "NUM-01",
    _numbers.check(INT, NUM["NUM-01"]["typed"]) == 9007199254740991
    and refused(INT, NUM["NUM-01"]["typed"]) is None,
)
expect(
    "NUM-02",
    refused(INT, NUM["NUM-02"]["typed"]) == "'L' must be <= 9007199254740991",
    refused(INT, NUM["NUM-02"]["typed"]),
)
expect(
    "NUM-03",
    refused(INT, NUM["NUM-03"]["typed"]) == "'L' must be >= -9007199254740991",
    refused(INT, NUM["NUM-03"]["typed"]),
)
good, bad = NUM["NUM-04"]["typed"]
expect(
    "NUM-04",
    _numbers.check(FLOAT, good) == 1e15 and refused(FLOAT, bad) == "'L' must be <= 1000000000000000.0",
    refused(FLOAT, bad),
)
expect("NUM-05", refused({**INT, "maximum": 10}, NUM["NUM-05"]["typed"]) == "'L' must be <= 10")
# numbers that are not text (a default, a program) follow the same limits and types
expect(
    "number_beyond_limit",
    refused(INT, 2**53) == "'L' must be <= 9007199254740991"
    and refused(INT, -(2**53)) == "'L' must be >= -9007199254740991",
)
expect(
    "float_for_integer",
    refused(INT, 2.5) == "'L' must be an integer, got '2.5'"
    and _numbers.check(INT, 4.0) == 4
    and type(_numbers.check(INT, 4.0)) is int,
)
expect(
    "boolean_is_not_a_number",
    refused(INT, True) == "'L' must be an integer, got true/false"
    and refused(FLOAT, False) == "'L' must be a number, got true/false",
)
expect(
    "not_finite_number",
    refused(FLOAT, float("nan")) == "'L' must be a finite number, got 'nan'"
    and refused(FLOAT, float("inf")) is not None,
)
expect(
    "none_and_blank_are_empty",
    refused(INT, None) == "'L' is required: type a number"
    and refused({**INT, "required": False}, " ") == "'L' is empty: type a number",
)
expect("int_for_float_beyond_limit", refused(FLOAT, 10**16) == "'L' must be <= 1000000000000000.0")
expect(
    "float_result_is_a_float",
    type(_numbers.check(FLOAT, "7")) is float and type(_numbers.check(FLOAT, 7)) is float,
)
expect(
    "nearest_to_zero",
    _numbers.nearest_to_zero({**INT, "minimum": 5}) == 5
    and _numbers.nearest_to_zero({**FLOAT, "maximum": -2.5}) == -2.5
    and _numbers.nearest_to_zero(FLOAT) == 0.0,
)
expect(
    "text_of_a_set_value_reads_back",
    all(float(_numbers.as_text(v)) == v for v in (0.1, 0.325, 1e15, 1e-300, 0.30000000000000004)),
)

print(json.dumps(report, indent=2))
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)

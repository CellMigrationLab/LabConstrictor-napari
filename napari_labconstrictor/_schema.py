"""Schema -> `inspect.Signature` that magicgui turns into widgets. This is the whole schema->GUI translation."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Annotated, Any

from . import _numbers
from ._number_field import FloatField, IntegerField

Tool = dict[str, Any]  # one tool of a registry schema, as the JSON file holds it
Param = dict[str, Any]  # one input of a tool

MAX_FORM_INTEGER = (
    _numbers.MAX_FORM_INTEGER
)  # SPEC_WRONG_SCIENCE 6.1: +-(2**53 - 1), the largest whole number every double holds
_INT_RANGE = _numbers.INTEGER_RANGE  # used where the schema gives no bound, and as the cap of a declared one
_FLOAT_RANGE = _numbers.FLOAT_RANGE  # likewise for a float: +-1e15
_FINE_STEP = 1e-4  # Qt rounds to the step: small enough for calibrations such as 0.325 um/px (the linked pixel-size spin box only)
_COARSE_STEP = 0.01  # step of a float that is neither a unit-bearing value nor below 1 (likewise)
_PATH_TYPES = ("table", "file", "folder")
_NULLABLE_SCALARS = ("integer", "float", "string", "choice")
_LAYER_TYPES = ("image", "labels")


def presentation_order(tool: Tool) -> Tool:
    """The tool with its inputs in the order the form shows them: parameters of one `group` together (where the group first
    appears), `advanced` ones after all the others. Without group/advanced hints the tool is returned unchanged.
    """
    inputs = tool["inputs"]
    if not any(p.get("group") or p.get("advanced") for p in inputs):
        return tool
    first: dict[tuple[bool, str], int] = {}

    def rank(index: int, p: Param) -> int:
        group = p.get("group")
        if not group:
            return index
        return first.setdefault((bool(p.get("advanced")), group), index)

    order = sorted(enumerate(inputs), key=lambda ip: (bool(ip[1].get("advanced")), rank(*ip), ip[0]))
    return {**tool, "inputs": [p for _, p in order]}


def rule_satisfied(rule: dict[str, Any], value: Any) -> bool:
    """enabled_when: `equals` given = the value is one of them; otherwise the controlling parameter is set / true."""
    if "equals" in rule:
        return value in rule["equals"]
    return value is not None and value is not False and value != ""


def signature_from_schema(tool: Tool, layer_classes: dict[str, type]) -> inspect.Signature:
    """Build the signature for one tool. `layer_classes` maps 'image'/'labels' to napari layer classes."""
    parameters = [_parameter(p, layer_classes) for p in presentation_order(tool)["inputs"]]
    return inspect.Signature(parameters)


def _parameter(param: Param, layer_classes: dict[str, type]) -> inspect.Parameter:
    kind = param["type"]
    annotation, options = _annotation(param, layer_classes)
    if param.get("description"):
        options["tooltip"] = param["description"]
    if kind == "integer" and _int_limit_applies(param):
        note = "Whole numbers up to +-%d." % MAX_FORM_INTEGER
        options["tooltip"] = (options["tooltip"] + " " if "tooltip" in options else "") + note
    options["label"] = param["label"] + (" (%s)" % param["unit"] if param.get("unit") else "")
    if not param["required"] and kind in _LAYER_TYPES + _PATH_TYPES:
        annotation = annotation | None  # nullable widget
    elif param.get("nullable") and kind in _NULLABLE_SCALARS:
        annotation = (
            annotation | None
        )  # "unset" is a value: the widget gets a None state, and the request omits it
        options["nullable"] = True
    default = param.get("default", inspect.Parameter.empty if param["required"] else None)
    if default is inspect.Parameter.empty and kind in ("integer", "float") and not param.get("pixel_size_of"):
        default = _numbers.nearest_to_zero(
            param
        )  # a required number with no default starts at the allowed value nearest 0 (B07)
    if kind == "boolean" and default is None:
        default = False  # a check box cannot hold None; the form's "set" box decides whether the value is sent at all
    return inspect.Parameter(
        param["name"],
        inspect.Parameter.KEYWORD_ONLY,
        default=default,
        annotation=Annotated[annotation, options],
    )


def _int_limit_applies(param: Param) -> bool:
    """True when the box's own limit, not the tool's, bounds this integer (a missing or larger declared Min/Max)."""
    low, high = _INT_RANGE
    return not (low <= param.get("minimum", low - 1) and param.get("maximum", high + 1) <= high)


def _annotation(param: Param, layer_classes: dict[str, type]) -> tuple[Any, dict[str, Any]]:
    kind = param["type"]
    options: dict[str, Any] = {}
    if kind in _LAYER_TYPES:
        return layer_classes[kind], options
    if kind in _PATH_TYPES:
        if kind == "folder":
            options["mode"] = "d"
        else:
            options["filter"] = "*.csv" if kind == "table" else "*"
        return Path, options
    if kind == "string":
        return str, options
    if kind == "boolean":
        return bool, options
    if kind == "choice":
        options["choices"] = param["choices"]
        if param.get("widget") == "radio" and not param.get("nullable"):
            options["widget_type"] = "RadioButtons"
        return str, options
    if kind not in ("integer", "float"):
        raise ValueError("parameter %r has the unknown type %r" % (param["name"], kind))
    is_int = kind == "integer"
    low, high = _numbers.limits(param)
    slider = (
        param.get("widget") == "slider"
        and not param.get(
            "pixel_size_of"
        )  # a linked pixel size is a line of text: the person's entry is kept as typed
        and not param.get("nullable")
        and "minimum" in param
        and "maximum" in param
        and not (is_int and not (low >= -(2**31) and high < 2**31))  # a Qt slider holds a 32-bit integer
    )
    if slider:
        options["min"], options["max"] = low, high
        if not is_int:
            options["step"] = (
                _FINE_STEP if param.get("unit") or abs(param.get("default", 1)) < 1 else _COARSE_STEP
            )
        options["widget_type"] = (
            "Slider" if is_int else "FloatSlider"
        )  # the readout beside it is read-only (see _widget)
    else:
        options["widget_type"] = IntegerField if is_int else FloatField
        options["min"], options["max"] = low, high
    return (int if is_int else float), options

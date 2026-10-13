"""The form's integer and float field: a line of text, never a spin box (docs/SPEC_WRONG_SCIENCE.md section 6.2).

A Qt spin box shortens what is typed into it: it drops the keystroke that would pass its maximum, rounds to its decimals (0.125 in a
two-decimal box is 0.12 or 0.13), and does not read an exponent. A person who types 9007199254740992 then sees, and sends,
9007199254740991. This field keeps the text exactly as typed. Its value is the number the text reads as; a text that is not a number
(or is empty) is the value itself, as text, and `_numbers.check` refuses it with a sentence when Run is pressed. Nothing is clamped
here: the limits only decide the refusal.
"""

from __future__ import annotations

from typing import Any

from magicgui.types import Undefined
from magicgui.widgets import LineEdit

from . import _numbers


class NumberField(LineEdit):
    """Common part: `kind` is the schema type, `min` / `max` the effective limits (the tool's, cut to the form's own)."""

    kind = "float"

    def __init__(
        self, value: Any = Undefined, *, min: Any = None, max: Any = None, step: Any = None, **kwargs: Any
    ) -> None:
        low, high = _numbers.INTEGER_RANGE if self.kind == "integer" else _numbers.FLOAT_RANGE
        self._min = low if min is None else min
        self._max = high if max is None else max
        super().__init__(**kwargs)
        if value is not Undefined:
            self.set_value(value)

    @property
    def min(self) -> Any:
        return self._min

    @property
    def max(self) -> Any:
        return self._max

    def text(self) -> str:
        """The text in the box, exactly as typed."""
        return self._widget._mgui_get_value()

    def get_value(self) -> Any:
        """The number the text reads as; else the text itself (not a number: Run refuses it); None when empty."""
        text = self.text()
        if not text.strip():
            return None
        try:
            return _numbers.read(self.kind, text)
        except ValueError:  # includes Beyond
            return text

    def set_value(self, value: Any) -> None:
        self._widget._mgui_set_value(value if isinstance(value, str) else _numbers.as_text(value))

    def _on_value_change(self, value: Any = None) -> None:
        super()._on_value_change(self.get_value())


class IntegerField(NumberField):
    kind = "integer"


class FloatField(NumberField):
    kind = "float"

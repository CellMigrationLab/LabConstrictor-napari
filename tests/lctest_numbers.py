"""A small LabConstrictor app for the number-field tests (registered by them with --pythonpath; the worker imports it).

Every tool reports what it RECEIVED, as text with the Python type, so a test sees the exact integer or float, not a rounded display.
"""

from typing import Annotated, Optional

from labconstrictor_tools import Max, MessageOut, Min, Name, Widget, tool


def _said(**values) -> Annotated[MessageOut, Name("received")]:
    return "; ".join("%s=%r (%s)" % (k, v, type(v).__name__) for k, v in values.items())


@tool("Free integer")
def free_integer(n: int) -> Annotated[MessageOut, Name("received")]:
    return _said(n=n)


@tool("Free float")
def free_float(x: float) -> Annotated[MessageOut, Name("received")]:
    return _said(x=x)


@tool("Bounded integer")
def bounded_integer(n: Annotated[int, Min(0), Max(10)]) -> Annotated[MessageOut, Name("received")]:
    return _said(n=n)


@tool("Bounded float")
def bounded_float(x: Annotated[float, Min(0.5), Max(2.5)]) -> Annotated[MessageOut, Name("received")]:
    return _said(x=x)


@tool("Positive integer")
def positive_integer(n: Annotated[int, Min(1)] = 5) -> Annotated[MessageOut, Name("received")]:
    return _said(n=n)


@tool("Huge declared range")
def huge_declared(n: Annotated[int, Min(-(2**60)), Max(2**60)]) -> Annotated[MessageOut, Name("received")]:
    return _said(n=n)


@tool("Defaults")
def defaults(n: int = 3, x: float = 0.125) -> Annotated[MessageOut, Name("received")]:
    return _said(n=n, x=x)


@tool("Optional numbers")
def optional_numbers(
    n: Optional[int] = None,  # noqa: UP045
    x: Optional[float] = None,  # noqa: UP045
) -> Annotated[MessageOut, Name("received")]:
    return _said(n=n, x=x)


@tool("Slider")
def slider(
    level: Annotated[float, Min(0), Max(1), Widget("slider")] = 0.25,
) -> Annotated[MessageOut, Name("received")]:
    return _said(level=level)


@tool("Wide slider")
def wide_slider(
    n: Annotated[int, Min(0), Max(2**40), Widget("slider")] = 7,
) -> Annotated[MessageOut, Name("received")]:
    return _said(n=n)


@tool("Required positive")
def required_positive(n: Annotated[int, Min(5), Max(9)]) -> Annotated[MessageOut, Name("received")]:
    return _said(n=n)

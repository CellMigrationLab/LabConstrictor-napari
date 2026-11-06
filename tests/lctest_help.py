"""A small LabConstrictor app for the input help test (test_help_marker.py registers it with --pythonpath; the worker imports it).

`Help` has inputs with a description (Description, or an Args: entry of the docstring), one with a blank Description (counts as
none) and one with none, and a described boolean (a check box, behind Show advanced settings); `Help choices` has a described ChoicesFrom input, whose dropdown needs its own ⓘ.
"""

from typing import Annotated

from labconstrictor_tools import Advanced, ChoicesFrom, Description, Image, Scalars, tool


@tool("Help")
def help_tool(
    image: Annotated[Image, Description("The picture to measure")],
    threshold: Annotated[
        float, Description("Fraction of the intensity range that separates blobs from background")
    ] = 0.5,
    documented: int = 2,
    blank: Annotated[str, Description("   ")] = "x",
    bare: bool = False,
    flag: Annotated[bool, Description("Also count the blobs touching the edge"), Advanced()] = False,
    plain: int = 1,
) -> Scalars:
    """Inputs with and without help.

    Args:
        documented: How many rounds, from the docstring.
    """
    return {"threshold": threshold}


@tool("Help options")
def help_options() -> Scalars:
    return {"choices": ["first", "second"]}


@tool("Help choices")
def help_choices(
    mode: Annotated[str, ChoicesFrom("help_options"), Description("Which way to count")] = "",
) -> Scalars:
    return {"mode": mode}

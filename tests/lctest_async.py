"""A small LabConstrictor app for the async-lookup tests (registered by them with --pythonpath; the worker imports it).

Source tools write `started_<name>` into their `folder` when they begin and then wait for `release` there (a barrier the test
releases), polling `check_cancel` so that a cancel ends them.
"""

import time
from pathlib import Path
from typing import Annotated

from labconstrictor_tools import ChoicesFrom, Folder, Scalars, check_cancel, tool


def _answer(folder: str, name: str, choices: list[str]) -> Scalars:
    d = Path(folder)
    (d / ("started_" + name)).write_text("x", encoding="utf-8")
    end = time.time() + 120
    while not (d / "release").exists() and time.time() < end:
        check_cancel()
        time.sleep(0.02)
    return {"choices": choices}


@tool("Options: mode")
def opts_mode(folder: Folder) -> Scalars:
    return _answer(str(folder), "mode", ["m1", "m2"])


@tool("Options: kind")
def opts_kind(folder: Folder) -> Scalars:
    return _answer(str(folder), "kind", ["k1", "k2"])


@tool("Options: other")
def opts_other(folder: Folder) -> Scalars:
    return _answer(str(folder), "other", ["o1", "o2"])


@tool("Options: stubborn")
def opts_stubborn(folder: Folder) -> Scalars:
    """Never looks at a cancel: only the worker's death ends it."""
    d = Path(str(folder))
    (d / "started_stubborn").write_text("x", encoding="utf-8")
    end = time.time() + 120
    while not (d / "release").exists() and time.time() < end:
        time.sleep(0.02)
    return {"choices": ["s1"]}


@tool("Pick stubborn")
def pick_stubborn(
    folder: Folder, mode: Annotated[str, ChoicesFrom("opts_stubborn", depends=["folder"])] = ""
) -> Scalars:
    return {"mode": mode}


@tool("Pick one")
def pick_one(
    folder: Folder, mode: Annotated[str, ChoicesFrom("opts_mode", depends=["folder"])] = ""
) -> Scalars:
    return {"mode": mode}


@tool("Pick other")
def pick_other(
    folder: Folder, mode: Annotated[str, ChoicesFrom("opts_other", depends=["folder"])] = ""
) -> Scalars:
    return {"mode": mode}


@tool("Pick two")
def pick_two(
    folder: Folder,
    mode: Annotated[str, ChoicesFrom("opts_mode", depends=["folder"])] = "",
    kind: Annotated[str, ChoicesFrom("opts_kind", depends=["folder"])] = "",
) -> Scalars:
    return {"mode": mode, "kind": kind}


@tool("Slow run")
def slow_run(gate: Folder) -> Scalars:
    d = Path(str(gate))
    (d / "run_started").write_text("x", encoding="utf-8")
    end = time.time() + 120
    while not (d / "run_release").exists() and time.time() < end:
        check_cancel()
        time.sleep(0.02)
    return {"done": 1}

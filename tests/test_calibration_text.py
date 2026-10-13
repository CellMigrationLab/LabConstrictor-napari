"""CAL-T1..T9 on the text-backed linked field (docs/SPEC_WRONG_SCIENCE.md 2.2): what the box SHOWS at each step, next to the state and request
that test_calibration_transitions.py checks. The box is a line of text: empty with the placeholder '(not set)' while unset, the exact
digits of the value while auto, and the text as typed while user. The tooltip follows the state. Nothing here sets the box from code.
"""

import _paths  # noqa: F401  (must come first)
import _runtools as R  # noqa: F401  (the calibration helpers' recorder)
from _calhelpers import (
    FIELD,
    check_known,
    check_unknown,
    choose,
    expect,
    finish,
    fresh,
    link,
    not_set,
    settle,
    shown,
    tiff,
    type_value,
    viewer,
    w,
)
from napari.layers import Image

from napari_labconstrictor import _numbers

DATA = __import__("numpy").zeros((6, 6), "uint16")
A = Image(DATA, name="A", scale=(0.25, 0.25), units="micrometer")
B = Image(DATA, name="B", scale=(0.5, 0.5), units="micrometer")
U = Image(DATA, name="U", scale=(0.25, 0.25))
uncal = tiff("uncal_text.tif")


def start(*layers: Image) -> None:
    fresh()
    for layer in layers:
        viewer.add_layer(layer)
    settle()


def tip() -> str:
    return w.gui[FIELD].tooltip


start()
expect("start_shows_not_set", not_set() and link().state == "unset", (shown(), link().state))
for layer in (A, B, U):
    viewer.add_layer(layer)
settle()
choose(A)
expect("T1_A", shown() == "0.25" and "from the calibration of 'image'" in tip(), (shown(), tip()))
choose(B)
expect("T1_B", shown() == "0.5" and link().state == "auto", (shown(), link().state))
choose(U)
expect(
    "T2_unknown_clears_the_box",
    not_set() and tip() == "not calibrated: 'image' has no pixel size",
    (shown(), tip()),
)
check_unknown("T2")
choose(A)
type_value("0.3")
choose(B)
expect("T3_typed_text_stays", shown() == "0.3" and link().state == "user", (shown(), link().state))
type_value("0")
expect("T4_zero_shows_the_source", shown() == "0.5" and link().state == "auto", (shown(), link().state))
type_value("0.3")
type_value("")
expect("T4_empty_shows_the_source", shown() == "0.5" and link().state == "auto", (shown(), link().state))

start(A)
choose(A)
w.file_sources["image"].value = uncal
settle()
expect("T5_file_without_calibration_clears_the_box", not_set(), shown())
check_unknown("T5")
w.file_sources["image"].value = None
settle()
expect(
    "T6_file_cleared_shows_the_image", shown() == "0.25" and link().state == "auto", (shown(), link().state)
)

start()
choose(U)
expect("T8_unknown_source_shows_not_set", not_set() and link().state == "unset", (shown(), link().state))
type_value("0.25")
check_known("T8_typed", 0.25, source="user")
expect(
    "T8_typed_text_is_as_typed",
    shown() == "0.25" and tip().startswith("0.25 um per pixel, entered by you"),
    (shown(), tip()),
)

start(A, U)
choose(A)
type_value("0.25")
choose(U)
expect("T9_stays_as_typed", shown() == "0.25" and link().state == "user", (shown(), link().state))
expect("auto_text_is_the_shortest_exact", _numbers.as_text(0.1 + 0.2) == "0.30000000000000004")
finish()

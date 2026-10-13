"""The linked pixel-size field with a real worker (docs/SPEC_WRONG_SCIENCE.md 2.3 and 6): what the person typed is what the tool receives.

Run is pressed for real. The tool reports the value it RECEIVED with its Python type, so a value rounded to a box's decimals or clamped to
its range would show. A refused entry starts nothing: no task, no worker.
"""

from typing import TYPE_CHECKING

import _paths  # noqa: F401  (must come first)
from _linkedhelpers import (
    LABEL,
    NOT_POSITIVE,
    UM,
    above,
    enter,
    expect,
    finish,
    received,
    run,
    start,
    start_with_file,
    w,
)

if TYPE_CHECKING:
    from napari.layers import Image


def ran(tag: str, text: str | None, expected_text: str, layer: "Image | None" = None) -> None:
    start("Linked free", *([layer] if layer is not None else []))
    if text is not None:
        enter(text)
    task = run()
    said = received()
    expect(tag + "_completed", task is not None and task.status == "COMPLETE", (w.status.text(), said))
    expect(tag + "_received_exactly", expected_text in said, (expected_text, said))


ran("typed_more_than_10_decimals", "0.12345678901234567", "pixel_size=0.12345678901234566 (float)")
ran("typed_tiny", "0.00000000012345", "pixel_size=1.2345e-10 (float)")
ran("typed_float_limit", "1000000000000000", "pixel_size=1000000000000000.0 (float)")
ran("typed_beyond_32_bits", "3000000000", "pixel_size=3000000000.0 (float)")
ran("image_calibration", None, "pixel_size=0.25 (float)", UM)
ran("typed_over_the_image_calibration", "0.3", "pixel_size=0.3 (float)", UM)

# the exact value of the file's calibration, not shown or sent rounded
start_with_file("Linked free", 1.2345e-10, "run_exact")
task = run()
expect("file_value_received_exactly", "pixel_size=1.2345e-10 (float)" in received(), received())

# a refused entry starts nothing
workers_before = {app: list(items) for app, items in w._workers._workers.items()}
for tag, text, sentence in [
    ("beyond_the_limit", "1.0000000000000002e15", above(LABEL, 1e15)),
    ("not_a_number", "abc", "⚠ '%s' must be a number, got 'abc'" % LABEL),
    ("negative", "-0.5", NOT_POSITIVE),
]:
    start("Linked free")
    enter(text)
    w.last_task = None
    before = w.task
    w.gui()
    expect(tag + "_refused_on_click", w.status.text().lstrip("⚠ ") == sentence.lstrip("⚠ "), w.status.text())
    expect(tag + "_no_task", w.task is before and w.last_task is None, (w.task, w.last_task))
expect("refusals_started_no_worker", {a: list(i) for a, i in w._workers._workers.items()} == workers_before)
expect("the_button_is_usable_again", w.gui.call_button.enabled)
finish()

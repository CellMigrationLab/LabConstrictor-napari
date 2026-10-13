"""NUM-01..05 with a real worker (docs/SPEC_WRONG_SCIENCE.md section 6): what the person typed is what the tool receives.

Run is pressed for real. The tool reports the value it RECEIVED with its Python type, so a rounded float or an integer cut to 32 bits or to
2**53 - 1 shows. A refused entry starts nothing: no task, no worker.
"""

import _paths  # noqa: F401  (must come first)
from _numhelpers import INT_MAX, NUM, above, choose, expect, finish, received, run, type_text, w


def ran(tag: str, tool: str, typed: dict[str, str], expected_text: str) -> None:
    choose(tool)
    for name, text in typed.items():
        type_text(name, text)
    task = run()
    said = received()
    expect(tag + "_completed", task is not None and task.status == "COMPLETE", (w.status.text(), said))
    expect(tag + "_received_exactly", expected_text in said, (expected_text, said))


ran("NUM-01", "Free integer", {"n": NUM["NUM-01"]["typed"]}, "n=9007199254740991 (int)")
ran("negative_limit", "Free integer", {"n": "-9007199254740991"}, "n=-9007199254740991 (int)")
ran("beyond_32_bits", "Free integer", {"n": "3000000000"}, "n=3000000000 (int)")
ran("NUM-04_float_limit", "Free float", {"x": NUM["NUM-04"]["typed"][0]}, "x=1000000000000000.0 (float)")
ran("float_exponent", "Free float", {"x": "2.5e-3"}, "x=0.0025 (float)")
ran("float_not_rounded_to_a_box", "Free float", {"x": "0.1234567890123456"}, "x=0.1234567890123456 (float)")
ran("float_three_decimals", "Free float", {"x": "0.125"}, "x=0.125 (float)")
ran("a_float_that_is_whole_stays_a_float", "Free float", {"x": "7"}, "x=7.0 (float)")
ran("declared_bound_itself", "Bounded integer", {"n": "10"}, "n=10 (int)")
ran("defaults_as_shown", "Defaults", {}, "n=3 (int); x=0.125 (float)")

# a refused entry starts nothing
workers_before = {app: list(items) for app, items in w._workers._workers.items()}
for tag, tool, field, text, sentence in [
    ("NUM-02", "Free integer", "n", NUM["NUM-02"]["typed"], above("N", INT_MAX)),
    ("NUM-05", "Bounded integer", "n", NUM["NUM-05"]["typed"], above("N", 10)),
]:
    choose(tool)
    type_text(field, text)
    w.last_task = None
    before = w.task
    w.gui()
    expect(tag + "_refused_on_click", w.status.text() == sentence, w.status.text())
    expect(tag + "_no_task", w.task is before and w.last_task is None, (w.task, w.last_task))
expect("refusals_started_no_worker", {a: list(i) for a, i in w._workers._workers.items()} == workers_before)
expect("the_button_is_usable_again", w.gui.call_button.enabled)

finish()

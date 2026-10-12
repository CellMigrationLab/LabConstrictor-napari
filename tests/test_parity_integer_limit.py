"""Host parity A06 (NB-1, the Tools notebook's MAX_FORM_INTEGER): an integer box holds every whole number up to +-(2**53 - 1)
exactly, never clamps a value the tool declared, and says its limit in the tooltip when the limit is the box's own.
"""

import unittest

import _paths  # noqa: F401  (must come first)
from magicgui import magicgui
from napari.layers import Image, Labels
from qtpy.QtWidgets import QApplication

from napari_labconstrictor._schema import MAX_FORM_INTEGER, signature_from_schema

_app = QApplication.instance() or QApplication([])


def form(**param):
    def run(**values):
        return values

    tool = {"id": "t", "inputs": [{"name": "n", "label": "N", "type": "integer", "required": True, **param}]}
    run.__signature__ = signature_from_schema(tool, {"image": Image, "labels": Labels})
    return magicgui(run, persist=False)


class IntegerLimit(unittest.TestCase):
    def test_the_limit_is_the_notebooks(self):
        self.assertEqual(MAX_FORM_INTEGER, 2**53 - 1)

    def test_an_unbounded_integer_holds_the_limit_exactly(self):
        box = form().n
        self.assertEqual((box.min, box.max), (-MAX_FORM_INTEGER, MAX_FORM_INTEGER))
        box.value = MAX_FORM_INTEGER
        self.assertEqual(box.value, MAX_FORM_INTEGER)
        self.assertIsInstance(box.value, int)
        box.value = 3_000_000_000  # beyond a 32-bit box
        self.assertEqual(box.value, 3_000_000_000)

    def test_a_declared_range_is_kept_and_needs_no_note(self):
        gui = form(minimum=0, maximum=10, description="how many")
        self.assertEqual((gui.n.min, gui.n.max), (0, 10))
        self.assertEqual(gui.n.tooltip, "how many")

    def test_a_declared_range_beyond_the_limit_is_cut_and_says_so(self):
        gui = form(minimum=-(2**60), maximum=2**60)
        self.assertEqual((gui.n.min, gui.n.max), (-MAX_FORM_INTEGER, MAX_FORM_INTEGER))
        self.assertIn(str(MAX_FORM_INTEGER), gui.n.tooltip)

    def test_an_open_bound_says_the_limit(self):
        gui = form(minimum=0, description="count")
        self.assertEqual(gui.n.tooltip, "count Whole numbers up to +-%d." % MAX_FORM_INTEGER)

    def test_a_float_keeps_its_own_range(self):
        def run(**values):
            return values

        tool = {"id": "t", "inputs": [{"name": "x", "label": "X", "type": "float", "required": True}]}
        run.__signature__ = signature_from_schema(tool, {"image": Image, "labels": Labels})
        self.assertEqual(magicgui(run, persist=False).x.max, 1e15)


if __name__ == "__main__":
    unittest.main()

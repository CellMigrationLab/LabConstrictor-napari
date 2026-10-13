"""Calibration units (docs/SPEC_WRONG_SCIENCE.md section 2.1, conformance.json `wrong_science.calibration`): the unit catalog and CAL-01..20
at the level of the conversion. test_calibration.py drives the same cases through the widget and checks the request a worker receives.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import _paths  # noqa: F401  (must come first)
import numpy as np
import tifffile
from labconstrictor_tools import conformance

from napari_labconstrictor import _units

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any

C = conformance.load()
CAL = C["wrong_science"]["calibration"]
CASES = {case["id"]: case for case in CAL["cases"]}
MESSAGES = C["messages"]
TMP = Path(tempfile.mkdtemp(prefix="lcunits_"))

# The unit table written out by hand: the catalog in conformance.json is compared with it, so a wrong edit of the data fails here.
ORACLE = {
    "nm": (0.001, {"nm"}, {"nanometer", "nanometers", "nanometre", "nanometres"}),
    "um": (1.0, {"um", "µm", "μm"}, {"micron", "microns", "micrometer", "micrometers", "micrometre", "micrometres"}),
    "mm": (1000.0, {"mm"}, {"millimeter", "millimeters", "millimetre", "millimetres"}),
    "cm": (10000.0, {"cm"}, {"centimeter", "centimeters", "centimetre", "centimetres"}),
    "m": (1000000.0, {"m"}, {"meter", "meters", "metre", "metres"}),
    "angstrom": (0.0001, {"Å", "Å"}, {"angstrom", "angstroms"}),
}  # fmt: skip


def layer_like(scale: "float | Sequence[float]", units: "Any") -> SimpleNamespace:
    """What `calibration_of_layer` reads of a napari layer: `scale` and `units` (any text: a real layer's units must parse as pint)."""
    return SimpleNamespace(scale=scale, units=units)


def of_layer(scale: "float | Sequence[float]", unit: "Any") -> "Any":
    scale = scale if isinstance(scale, list | tuple) else (scale, scale)
    units = unit if isinstance(unit, list | tuple) else (unit, unit)
    return _units.calibration_of_layer(layer_like(scale, units))


def tiff(name: str, **kwargs: "Any") -> Path:
    path = TMP / name
    tifffile.imwrite(path, np.zeros((4, 4), np.uint8), **kwargs)
    return path


def expect_value(
    test: unittest.TestCase, calibration: "Any", expected: float | None, label: str = ""
) -> None:
    if expected == "unknown":
        test.assertIsNone(calibration.value, label)
    else:
        test.assertIsNotNone(calibration.value, label)
        test.assertLess(
            abs(calibration.value - expected) / expected, 1e-9, "%s: %r" % (label, calibration.value)
        )


class Catalog(unittest.TestCase):
    def test_the_catalog_is_the_one_written_out_here(self) -> None:
        units = CAL["length_units"]
        self.assertEqual(set(units), set(ORACLE))
        for name, (factor, symbols, words) in ORACLE.items():
            self.assertEqual(units[name]["um_per_unit"], factor, name)
            self.assertEqual(set(units[name]["symbols"]), symbols, name)
            self.assertEqual(set(units[name]["words"]), words, name)

    def test_the_module_reads_the_catalog_and_keeps_no_list_of_its_own(self) -> None:
        for name, (factor, symbols, words) in ORACLE.items():
            for text in symbols | words:
                self.assertEqual(_units.unit_factor(text)[0], factor, text)

    def test_the_micro_sign_has_three_spellings_and_a_damaged_one_is_refused(self) -> None:
        for micro in CAL["micro_sign_spellings"]:
            self.assertEqual(_units.unit_factor(micro + "m"), (1.0, None), micro)
        factor, warning = _units.unit_factor(CAL["damaged_micro_prefix"] + "m")
        self.assertIsNone(factor)
        self.assertEqual(warning, MESSAGES["unit_damaged_warning"]["template"].format(unit="�m"))

    def test_sentences_are_those_of_the_conformance_file(self) -> None:
        self.assertEqual(_units.NOT_SQUARE_TEXT, MESSAGES["pixels_not_square_warning"]["template"])
        self.assertEqual(_units.NOT_A_LENGTH_TEXT, MESSAGES["unit_not_length_warning"]["template"])
        self.assertEqual(_units.DAMAGED_TEXT, MESSAGES["unit_damaged_warning"]["template"])
        self.assertEqual(_units.SQUARE_PIXEL_TOLERANCE, CAL["anisotropy_tolerance"]["relative_to_larger"])


class LayerCases(unittest.TestCase):
    """CAL-01..07 and 15..20: a scale and a unit text."""

    def test_CAL_01_explicit_micrometres_at_scale_one_are_calibrated(self) -> None:
        cal = of_layer(1.0, "micrometer")
        self.assertEqual(cal.value, 1.0)
        self.assertEqual(cal.raw[1], _units.Raw(1.0, "micrometer"))

    def test_CAL_02_default_pixel_units_are_unknown(self) -> None:
        self.assertIsNone(of_layer(1.0, "pixel").value)

    def test_CAL_03_explicit_millimetres_at_scale_one(self) -> None:
        self.assertEqual(of_layer(1.0, "millimeter").value, 1000.0)

    def test_CAL_04_a_scale_with_pixel_units_or_none_is_never_read_as_micrometres(self) -> None:
        case = CASES["CAL-04"]
        for units in case["input"]["units"]:
            cal = of_layer(case["input"]["scale"][0], units)
            self.assertIsNone(cal.value, units)
            self.assertIsNone(cal.note, "no warning: an image without a physical unit is just not calibrated")

    def test_CAL_05_the_same_pixel_in_three_units(self) -> None:
        case = CASES["CAL-05"]
        for variant in case["input"]["variants"]:
            expect_value(
                self, of_layer(variant["scale"], variant["unit"]), case["expect"]["um_per_px"], variant
            )

    def test_CAL_06_anisotropic_pixels_are_unknown_with_a_warning(self) -> None:
        cal = of_layer(CASES["CAL-06"]["input"]["scale"], "um")
        self.assertIsNone(cal.value)
        self.assertEqual(cal.note, CASES["CAL-06"]["expect"]["warning"])
        self.assertEqual(
            cal.yx, (0.5, 0.25), "both axes stay known: only the scalar field is not filled from one of them"
        )

    def test_CAL_07_a_unit_that_is_not_a_length(self) -> None:
        cal = of_layer(1.0, "second")
        self.assertIsNone(cal.value)
        self.assertEqual(cal.note, CASES["CAL-07"]["expect"]["warning"])

    def test_CAL_08_unit_text_of_a_fiji_calibration(self) -> None:
        case = CASES["CAL-08"]
        for variant, expected in zip(
            case["input"]["variants"], case["expect"]["um_per_px_each"], strict=True
        ):
            expect_value(self, of_layer(variant["pixelWidth"], variant["unit"]), expected, variant)

    def test_CAL_15_the_three_micro_sign_spellings(self) -> None:
        case = CASES["CAL-15"]
        self.assertEqual(len(case["input"]["variants"]), 3)
        for variant, expected in zip(
            case["input"]["variants"], case["expect"]["um_per_px_each"], strict=True
        ):
            expect_value(self, of_layer(variant["scale"], variant["unit"]), expected, variant)

    def test_CAL_16_a_damaged_micro_sign_is_unknown_and_says_so(self) -> None:
        case = CASES["CAL-16"]
        cal = of_layer(case["input"]["scale"], case["input"]["unit"])
        self.assertIsNone(cal.value)
        self.assertEqual(cal.note, case["expect"]["warning"])

    def test_CAL_17_angstrom_in_its_three_spellings(self) -> None:
        case = CASES["CAL-17"]
        for variant, expected in zip(
            case["input"]["variants"], case["expect"]["um_per_px_each"], strict=True
        ):
            expect_value(self, of_layer(variant["scale"], variant["unit"]), expected, variant)

    def test_CAL_18_the_anisotropy_tolerance_is_one_in_a_thousand_of_the_larger(self) -> None:
        case = CASES["CAL-18"]
        within, beyond = case["input"]["variants"]
        expect_value(
            self, of_layer(within["scale"], within["unit"]), 0.5002, "8e-4 is within the tolerance: the mean"
        )
        cal = of_layer(beyond["scale"], beyond["unit"])
        self.assertIsNone(cal.value)
        self.assertEqual(cal.note, _units.NOT_SQUARE_TEXT)
        self.assertEqual(case["expect"]["um_per_px_each"], [0.5002, "unknown"])

    def test_CAL_19_every_refused_name_is_unknown(self) -> None:
        names = CAL["unit_match_refused"]
        self.assertGreaterEqual(len(names), 40)
        self.assertEqual(len(CASES["CAL-19"]["expect"]["um_per_px_each"]), len(names))
        for name in names:
            self.assertIsNone(of_layer(CASES["CAL-19"]["input"]["scale"], name).value, repr(name))

    def test_CAL_20_words_are_case_insensitive_and_trimmed(self) -> None:
        case = CASES["CAL-20"]
        for variant, expected in zip(
            case["input"]["variants"], case["expect"]["um_per_px_each"], strict=True
        ):
            expect_value(self, of_layer(variant["scale"], variant["unit"]), expected, variant)

    def test_a_real_napari_layer_is_read_through_its_pint_units(self) -> None:
        from napari.layers import Image

        layer = Image(np.zeros((4, 4)), scale=(0.65, 0.65), units="micrometer")
        self.assertEqual(_units.calibration_of_layer(layer).value, 0.65)
        self.assertIsNone(_units.calibration_of_layer(Image(np.zeros((4, 4)), scale=(0.65, 0.65))).value)

    def test_a_stack_uses_its_last_two_axes(self) -> None:
        cal = _units.calibration_of_layer(layer_like((2.0, 0.5, 0.5), ("second", "micrometer", "micrometer")))
        self.assertEqual(cal.value, 0.5)


class TiffCases(unittest.TestCase):
    """CAL-10..14 (and the units of the file): what a TIFF's own metadata says."""

    def cal(self, path: str | Path) -> "Any":
        return _units.calibration_from_tiff(path)[0]

    def test_CAL_10_imagej_unit_wins_and_no_tags_or_no_unit_are_unknown(self) -> None:
        self.assertEqual(
            self.cal(tiff("ij.tif", imagej=True, resolution=(1.0, 1.0), metadata={"unit": "micron"})).value,
            1.0,
        )
        self.assertIsNone(self.cal(tiff("plain.tif")).value)
        self.assertIsNone(self.cal(tiff("none.tif", resolution=(1.0, 1.0), resolutionunit="NONE")).value)

    def test_CAL_11_and_12_default_dpi_is_not_a_calibration(self) -> None:
        for dpi in (72, 96):
            self.assertIsNone(
                self.cal(tiff("dpi%d.tif" % dpi, resolution=(dpi, dpi), resolutionunit="INCH")).value, dpi
            )

    def test_the_default_dpi_rule_has_a_tolerance_of_half_a_percent(self) -> None:
        self.assertIsNone(
            self.cal(tiff("dpi72_3.tif", resolution=(72.3, 72.3), resolutionunit="INCH")).value
        )  # +0.4 %
        self.assertIsNotNone(
            self.cal(tiff("dpi72_9.tif", resolution=(72.6, 72.6), resolutionunit="INCH")).value
        )  # +0.8 %

    def test_CAL_13_default_looking_resolution_per_centimetre(self) -> None:
        for per_cm in (28.35, 37.8):
            self.assertIsNone(
                self.cal(
                    tiff("cm%g.tif" % per_cm, resolution=(per_cm, per_cm), resolutionunit="CENTIMETER")
                ).value
            )

    def test_CAL_14_a_resolution_that_does_not_look_like_a_default_is_a_calibration(self) -> None:
        cal = self.cal(tiff("dpi25400.tif", resolution=(25400, 25400), resolutionunit="INCH"))
        self.assertAlmostEqual(cal.value, 1.0, places=9)

    def test_centimetre_resolution_is_converted(self) -> None:
        cal = self.cal(tiff("cm100.tif", resolution=(100, 100), resolutionunit="CENTIMETER"))
        self.assertAlmostEqual(cal.value, 100.0, places=9)  # 100 pixels per cm: 100 um per pixel

    def test_an_imagej_unit_wins_over_the_resolution_unit_and_a_default_looking_number(self) -> None:
        cal = self.cal(
            tiff("ij72.tif", imagej=True, resolution=(1 / 0.5, 1 / 0.5), metadata={"unit": "micron"})
        )
        self.assertAlmostEqual(cal.value, 0.5, places=9)

    def test_an_imagej_unit_that_is_not_in_the_catalog_is_unknown_and_not_converted_by_the_tags(self) -> None:
        cal = self.cal(tiff("ijpx.tif", imagej=True, resolution=(1.0, 1.0), metadata={"unit": "pixel"}))
        self.assertIsNone(cal.value)
        cal = self.cal(tiff("ijsec.tif", imagej=True, resolution=(1.0, 1.0), metadata={"unit": "sec"}))
        self.assertIsNone(cal.value)
        self.assertEqual(cal.note, "unit 'sec' is not a length")

    def test_an_ome_physical_size_wins_over_the_tags(self) -> None:
        meta = {
            "axes": "YX",
            "PhysicalSizeX": 325.0,
            "PhysicalSizeXUnit": "nm",
            "PhysicalSizeY": 325.0,
            "PhysicalSizeYUnit": "nm",
        }
        cal = self.cal(tiff("ome.tif", ome=True, metadata=meta, resolution=(72, 72), resolutionunit="INCH"))
        self.assertAlmostEqual(cal.value, 0.325, places=9)

    def test_an_ome_size_without_a_unit_is_not_evidence(self) -> None:
        cal = self.cal(
            tiff("omenu.tif", ome=True, metadata={"axes": "YX", "PhysicalSizeX": 0.5, "PhysicalSizeY": 0.5})
        )
        self.assertIsNone(cal.value)

    def test_a_file_that_is_not_anisotropic_within_the_tolerance_fills_the_mean(self) -> None:
        cal = self.cal(
            tiff("aniso.tif", imagej=True, resolution=(1 / 0.5, 1 / 0.5004), metadata={"unit": "um"})
        )
        self.assertAlmostEqual(cal.value, 0.5002, places=9)

    def test_a_tiff_with_different_y_and_x_resolution_is_unknown_as_a_field_but_keeps_both_axes(self) -> None:
        path = tiff("yx.tif", imagej=True, resolution=(4.0, 2.0), metadata={"unit": "um"})
        cal = self.cal(path)
        self.assertIsNone(cal.value)
        self.assertEqual(cal.note, _units.NOT_SQUARE_TEXT)
        self.assertEqual(cal.yx, (0.5, 0.25))
        self.assertEqual(_units.microns_yx_from_tiff(path), (0.5, 0.25))

    def test_an_unreadable_tiff_is_reported_not_swallowed(self) -> None:
        from unittest import mock

        path = TMP / "bad.tif"
        path.write_bytes(b"not a tiff")
        with mock.patch.object(_units.log, "warning") as warn:
            cal, problem = _units.calibration_from_tiff(path)
            yx, problem2 = _units.microns_yx_from_tiff_checked(path)
        self.assertIsNone(cal.value)
        self.assertIn("bad.tif", problem)
        self.assertIsNone(yx)
        self.assertIn("bad.tif", problem2)
        self.assertEqual(warn.call_count, 2)
        self.assertIsNone(_units.microns_yx_from_tiff(path))
        self.assertIsNone(_units.microns_yx_from_tiff_checked(TMP / "gone.tif")[0])


class Conformance(unittest.TestCase):
    def test_every_case_of_the_file_is_known_to_this_test(self) -> None:
        self.assertEqual(sorted(CASES), ["CAL-%02d" % n for n in range(1, 21)])
        self.assertEqual([t["id"] for t in CAL["transitions"]], ["CAL-T%d" % n for n in range(1, 10)])


if __name__ == "__main__":
    unittest.main(verbosity=2)

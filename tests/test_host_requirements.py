"""An app's `host_requirements` for napari (Tools feature `host_requirements_v1`, docs/PROTOCOL.md "Host requirements", Tools #155), no Qt.

* Every napari case of conformance.json `host_requirements` gives Tools' verdict and exact sentence through `_hosts.requirement` when
  the case's version is passed; a missing section FAILS (never skips).
* This plugin reports its own installed version and its feature ids; a requirement it meets says nothing, one it does not is a
  warning (or a refusal with required: true) written to the Tools log.
* With a Tools that has no host_requirements module, nothing is checked (as before the rule).
"""

import builtins
import unittest
from typing import Any
from unittest import mock

import _paths  # noqa: F401  (must come first)
from labconstrictor_tools import conformance, log

from napari_labconstrictor import _hosts


def vectors() -> dict[str, Any]:
    section = conformance.load().get("host_requirements")
    if not isinstance(section, dict):
        raise AssertionError(
            "conformance.json has no `host_requirements` section: this Tools does not carry the rule"
        )
    return section


def log_text() -> str:
    path = log.log_path()
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def needs(**napari: Any) -> dict[str, Any]:
    return {"name": "Needy", "host_requirements": {"napari": napari}}


class Vectors(unittest.TestCase):
    def test_every_napari_case_gives_the_verdict_and_the_sentence_of_the_vector(self) -> None:
        cases = [c for c in vectors()["cases"] if c["host"] == _hosts.HOST and c["expect"] != "error"]
        self.assertGreaterEqual(len(cases), 3)
        for case in cases:
            with (
                self.subTest(case["case"]),
                mock.patch.object(_hosts, "HOST_FEATURES", tuple(case["host_features"])),
            ):
                got = _hosts.requirement(case["entry"], case["host_version"] or "")
                self.assertEqual(got, (case["expect"], case["sentence"]))

    def test_the_versions_sort_as_the_vectors_say(self) -> None:
        from labconstrictor_tools.host_requirements import version_key

        keys = [version_key(v) for v in vectors()["version_order"]]
        self.assertEqual(keys, sorted(keys))


class ThisPlugin(unittest.TestCase):
    def test_it_knows_its_version_and_features(self) -> None:
        version = _hosts.plugin_version()
        self.assertTrue(version, "napari-labconstrictor is not installed (pip install -e .)")
        self.assertIn("host_requirements_v1", _hosts.HOST_FEATURES)

    def test_a_met_requirement_says_nothing(self) -> None:
        self.assertEqual(
            _hosts.requirement(needs(min_version="0.0.1", features=["host_requirements_v1"])), ("ok", "")
        )
        self.assertEqual(_hosts.requirement({"name": "Plain"}), ("ok", ""))

    def test_a_newer_plugin_is_asked_for_in_the_log_and_the_notes(self) -> None:
        status, sentence = _hosts.requirement(needs(min_version="99.0", why="a test"))
        self.assertEqual(status, "warn")
        self.assertIn(
            "Needy needs LabConstrictor-napari 99.0 or newer (a test); this is %s." % _hosts.plugin_version(),
            sentence,
        )
        self.assertIn("LabConstrictor-napari/releases/latest", sentence)
        self.assertIn(sentence, log_text())
        notes = _hosts.requirement_notes(
            {"Needy": needs(min_version="99.0", required=True), "Plain": {"name": "Plain"}}
        )
        self.assertEqual(list(notes), ["Needy"])
        self.assertEqual(notes["Needy"][0], "refuse")

    def test_a_missing_feature_is_named(self) -> None:
        status, sentence = _hosts.requirement(needs(features=["not_a_napari_feature_v9"]))
        self.assertEqual(status, "warn")
        self.assertIn("with not_a_napari_feature_v9", sentence)

    def test_an_older_tools_without_the_rule_checks_nothing(self) -> None:
        real = builtins.__import__

        def no_rule(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "labconstrictor_tools.host_requirements":
                raise ImportError(name)
            return real(name, *args, **kwargs)

        with mock.patch.object(builtins, "__import__", no_rule):
            self.assertEqual(_hosts.requirement(needs(min_version="99.0", required=True)), ("ok", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)

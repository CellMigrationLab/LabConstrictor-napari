"""The per-host discovery rule (Tools feature `app_hosts_v1`, docs/PROTOCOL.md "App hosts"), no Qt.

* Every case of conformance.json `app_hosts` is run through `_hosts.is_listed` and must give the listed / not listed verdict and the
  exact sentence of the vector. The key missing from conformance.json FAILS the test (it never skips).
* Sabotage: the same check run against a decision that lists everything, and against one that drops the sentence, must report
  mismatches, so a test that cannot fail would be noticed.
* The compat rule (min_tools_version 0.3.0a1 + feature app_hosts_v1) is applied with Tools' `check_schema` to the vectors, and the
  plugin's own load check (`_retention.tools_problem`) refuses a Tools without the feature id.
* Every sentence reaches the Tools log; the "declares no hosts" sentence every time.
"""

import os
import unittest
from collections.abc import Callable, Mapping
from typing import Any

import _paths  # noqa: F401  (must come first)
from labconstrictor_tools import conformance, log
from labconstrictor_tools import runs as tools_runs
from labconstrictor_tools.compat import check_schema

from napari_labconstrictor import _hosts, _retention

Decide = Callable[[Mapping[str, Any]], tuple[bool, str]]


def vectors() -> dict[str, Any]:
    """The `app_hosts` section of conformance.json; a missing key is a failure, never a skip."""
    section = conformance.load().get("app_hosts")
    if not isinstance(section, dict):
        raise AssertionError(
            "conformance.json has no `app_hosts` section: this Tools does not carry the rule"
        )
    return section


def napari_cases() -> list[dict[str, Any]]:
    return [case for case in vectors()["cases"] if case["host"] == _hosts.HOST]


def mismatches(decide: Decide) -> list[str]:
    """The napari cases of the vectors whose verdict or sentence `decide` gets wrong."""
    wrong = []
    for case in napari_cases():
        listed, sentence = decide(case["entry"])
        if listed != (case["expect"] == "listed") or sentence != case["sentence"]:
            wrong.append("%s: got %r %r" % (case["case"], listed, sentence))
    return wrong


def lists_everything(entry: Mapping[str, Any]) -> tuple[bool, str]:
    return True, ""


def says_nothing(entry: Mapping[str, Any]) -> tuple[bool, str]:
    return _hosts.listed_for(entry, _hosts.HOST)[0], ""


def log_text() -> str:
    path = log.log_path()
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


class Vectors(unittest.TestCase):
    def test_the_section_is_there_and_has_napari_cases(self) -> None:
        self.assertEqual(vectors()["known_hosts"], ["notebook", "napari", "fiji", "qupath"])
        self.assertGreaterEqual(len(napari_cases()), 6)
        self.assertIn("not_listed", {case["expect"] for case in napari_cases()})

    def test_every_napari_case_gives_the_verdict_and_the_sentence_of_the_vector(self) -> None:
        self.assertEqual(mismatches(_hosts.is_listed), [])

    def test_an_unknown_asking_host_is_an_error_not_an_answer(self) -> None:
        for case in (c for c in vectors()["cases"] if c["expect"] == "error"):
            with self.subTest(case=case["case"]), self.assertRaises(ValueError):
                _hosts.listed_for(case["entry"], case["host"])

    def test_sabotage_a_host_that_lists_everything_is_caught(self) -> None:
        self.assertNotEqual(mismatches(lists_everything), [])

    def test_sabotage_a_host_that_drops_the_sentence_is_caught(self) -> None:
        self.assertNotEqual(mismatches(says_nothing), [])

    def test_the_matrix_of_the_apps(self) -> None:
        by_app = {c["entry"]["name"]: c for c in napari_cases() if c["case"].startswith("matrix: ")}
        self.assertEqual(by_app["CellTracksColab"]["expect"], "not_listed")
        for app in ("Playground", "NucleiSky", "GuessTheCondition", "VLab4Mic"):
            self.assertEqual(by_app[app]["expect"], "listed", app)


class Entries(unittest.TestCase):
    def test_listed_entries_keeps_the_listed_apps_and_returns_the_skip_sentences(self) -> None:
        entries = {
            "Both": {"name": "Both", "hosts": ["notebook", "napari"]},
            "Nb": {"name": "Nb", "hosts": ["notebook"]},
            "Old": {"name": "Old"},
            "Bad": {"name": "Bad", "hosts": []},
        }
        kept, skipped = _hosts.listed_entries(entries)
        self.assertEqual(list(kept), ["Both", "Old"])
        self.assertEqual(
            skipped,
            [
                "'Nb' is not listed in napari: the app declares hosts: notebook",
                "'Bad' is not listed in napari: its hosts declaration is not valid (hosts is empty; write at least notebook); "
                "register the app again with a valid one",
            ],
        )

    def test_every_sentence_is_written_to_the_tools_log_and_the_absent_one_every_time(self) -> None:
        marker = "LogCheck%d" % os.getpid()
        entries = {
            marker + "Nb": {"name": marker + "Nb", "hosts": ["notebook"]},
            marker + "Old": {"name": marker + "Old"},
        }
        absent = (
            "'%sOld' declares no hosts, so it is listed in every host; register it with --app-manifest (or --hosts) to choose"
            % marker
        )
        for count in (1, 2):
            _hosts.listed_entries(entries)
            text = log_text()
            self.assertEqual(text.count(absent), count)
            self.assertEqual(
                text.count("'%sNb' is not listed in napari: the app declares hosts: notebook" % marker), count
            )

    def test_a_listed_app_with_a_declaration_says_nothing(self) -> None:
        marker = "Quiet%d" % os.getpid()
        _hosts.listed_entries({marker: {"name": marker, "hosts": ["napari"]}})
        self.assertNotIn(marker, log_text())


class Compat(unittest.TestCase):
    def test_the_rule_is_the_one_the_plugin_enforces(self) -> None:
        rule = vectors()["compat_rule"]
        self.assertEqual(rule["min_tools_version"], _retention.TOOLS_MINIMUM)
        self.assertEqual(rule["required_features"], [_retention.HOSTS_FEATURE])

    def test_every_compat_case_of_the_vectors(self) -> None:
        rule = vectors()["compat_rule"]
        for case in vectors()["compat_cases"]:
            with self.subTest(case=case["case"]):
                result = check_schema(
                    case["schema"],
                    min_tools_version=rule["min_tools_version"],
                    required_features=rule["required_features"],
                )
                self.assertEqual(result.status == "refuse", case["expect"] == "refuse", result)
                self.assertIn(case.get("reason_contains", ""), result.reason)
                features = case["schema"].get("features", [])
                problem = _retention.tools_problem(
                    tools_runs, installed=case["schema"]["tools_version"], features=features
                )
                self.assertEqual(problem is not None, case["expect"] == "refuse", problem)

    def test_a_tools_without_the_feature_id_is_refused_with_a_sentence_that_says_what_to_do(self) -> None:
        problem = _retention.tools_problem(
            tools_runs, installed=_retention.TOOLS_MINIMUM, features=["retention_prune", "shm_order_v1"]
        )
        self.assertIsNotNone(problem)
        for text in ("lacks the feature app_hosts_v1", "update Tools", "v0.3.0-alpha.1"):
            self.assertIn(text, problem or "")

    def test_the_installed_tools_passes(self) -> None:
        self.assertIsNone(_retention.tools_problem())


if __name__ == "__main__":
    unittest.main(verbosity=2)

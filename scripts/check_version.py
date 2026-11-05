"""Release check: the package version in pyproject.toml is the version the git tag names (issue #73).

A tag `v0.1.0-alpha.5` names the version `0.1.0a5` (PEP 440): `-alpha.N` is `aN`, `-beta.N` is `bN`, `-rc.N` is `rcN`, and a
tag without a suffix (`v0.2.0`) is the plain version. Without this check every alpha was installed as `0.1.0a1`, so a support
bundle or `pip show` could not tell which release was installed.

Usage:  python scripts/check_version.py TAG     exit status 1, with the two versions, when they differ
        python scripts/check_version.py         prints the version in pyproject.toml
Standard library only.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUFFIXES = {"alpha": "a", "beta": "b", "rc": "rc"}
TAG = re.compile(r"^v(\d+\.\d+\.\d+)(?:-(alpha|beta|rc)\.(\d+))?$")


def tag_version(tag: str) -> str:
    """The PEP 440 version a release tag names; ValueError for a tag that is not `vX.Y.Z` or `vX.Y.Z-alpha|beta|rc.N`."""
    match = TAG.match(tag)
    if match is None:
        raise ValueError("%r is not a release tag (vX.Y.Z or vX.Y.Z-alpha.N, -beta.N, -rc.N)" % tag)
    release, kind, number = match.groups()
    return release + (SUFFIXES[kind] + number if kind else "")


def package_version() -> str:
    """The `version` of [project] in pyproject.toml."""
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def main(argv: list[str]) -> int:
    """Compare the tag in argv[0] with pyproject.toml, or print the package version when no tag is given."""
    version = package_version()
    if not argv:
        print(version)
        return 0
    try:
        expected = tag_version(argv[0])
    except ValueError as error:
        print("check_version: %s" % error)
        return 1
    if version != expected:
        print(
            "check_version: tag %s names version %s, but pyproject.toml says %s"
            % (argv[0], expected, version)
        )
        return 1
    print("check_version: tag %s and pyproject.toml agree on %s" % (argv[0], version))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Which registered apps napari lists: the per-host discovery rule of Tools (feature `app_hosts_v1`, docs/PROTOCOL.md "App hosts").

The rule is Tools' (`labconstrictor_tools.app_hosts.listed_for`), not a copy kept here. Every sentence it returns is written to the
Tools log (`<LC_HOME>/logs/labconstrictor.log`); a skip sentence is also handed back so the widget shows it with the other apps it
left out. The "declares no hosts" sentence is only logged, every time the list is read, because such an app is still listed.
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib import metadata
from typing import Any

from labconstrictor_tools import log
from labconstrictor_tools.app_hosts import listed_for

HOST = "napari"  # the name this host asks `listed_for` with
DISTRIBUTION = "napari-labconstrictor"  # whose version an app's host_requirements is compared with
# Host feature ids an app can require (Tools docs/HOST_FEATURES.md); an id is added in the release that implements it.
HOST_FEATURES = ("host_requirements_v1",)


def is_listed(entry: Mapping[str, Any]) -> tuple[bool, str]:
    """(listed, sentence) for one registry entry; a non-empty sentence has been written to the Tools log."""
    listed, sentence = listed_for(entry, HOST)
    if sentence:
        log.warning(sentence)
    return listed, sentence


def listed_entries(entries: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """(the entries napari may list, the sentences of the apps it left out), both in the order of `entries`."""
    kept: dict[str, Any] = {}
    skipped: list[str] = []
    for name, entry in entries.items():
        listed, sentence = is_listed(entry)
        if listed:
            kept[name] = entry
        else:
            skipped.append(sentence)
    return kept, skipped


def plugin_version() -> str | None:
    """This plugin's installed version (e.g. 0.1.0a5), or None when it is run from a folder that was not installed."""
    try:
        return metadata.version(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return None


def requirement(entry: Mapping[str, Any], version: str | None = None) -> tuple[str, str]:
    """(ok | warn | refuse, sentence) of the app's `host_requirements` for this plugin (Tools feature `host_requirements_v1`,
    docs/PROTOCOL.md "Host requirements"); a non-empty sentence has been written to the Tools log. A Tools older than the rule
    has no module for it: then nothing is checked, as before the rule existed."""
    try:
        from labconstrictor_tools.host_requirements import check
    except ImportError:
        return "ok", ""
    status, sentence = check(
        entry, HOST, plugin_version() if version is None else version, list(HOST_FEATURES)
    )
    if sentence:
        log.warning(sentence)
    return status, sentence


def requirement_notes(entries: Mapping[str, Mapping[str, Any]]) -> dict[str, tuple[str, str]]:
    """{app: (warn | refuse, sentence)} for the listed apps whose host_requirements this plugin does not meet."""
    notes = {}
    for name, entry in entries.items():
        status, sentence = requirement(entry)
        if status != "ok":
            notes[name] = (status, sentence)
    return notes

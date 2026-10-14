"""Which registered apps napari lists: the per-host discovery rule of Tools (feature `app_hosts_v1`, docs/PROTOCOL.md "App hosts").

The rule is Tools' (`labconstrictor_tools.app_hosts.listed_for`), not a copy kept here. Every sentence it returns is written to the
Tools log (`<LC_HOME>/logs/labconstrictor.log`); a skip sentence is also handed back so the widget shows it with the other apps it
left out. The "declares no hosts" sentence is only logged, every time the list is read, because such an app is still listed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from labconstrictor_tools import log
from labconstrictor_tools.app_hosts import listed_for

HOST = "napari"  # the name this host asks `listed_for` with


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

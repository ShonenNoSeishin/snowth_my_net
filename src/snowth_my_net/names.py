"""Names given by hand to MAC addresses: "imprimante compta", "poste de Julie".

A name belongs to the MAC, not to a row: positions move, IP addresses change, a collect
rewrites everything it read — the name stays. It lives in its own file next to the state
rather than in the database, so that a lost state, a schema upgrade or a fresh start never
takes the names with it, and so that the read-only interface can write them without ever
touching what the collector owns.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from snowth_my_net.snmp.values import normalize_mac

STORE_NAME = "node_names.json"
FORMAT = 2                                       # 1 held a bare name; 2 holds the fields below
FIELDS = ("name", "description")
MAX_LENGTH = {"name": 60, "description": 200}    # a label, and a line about it


class NameError_(ValueError):
    """What is wrong with a name or a MAC, in a sentence meant for the reader."""


def clean_field(field: str, text: str) -> str:
    """One line, trimmed, no control character: it is rendered in a table cell."""
    if field not in FIELDS:
        raise NameError_(f"unknown field {field!r}; it is one of {', '.join(FIELDS)}")
    value = " ".join(str(text).split())
    if len(value) > MAX_LENGTH[field]:
        raise NameError_(f"a {field} is at most {MAX_LENGTH[field]} characters")
    return value


def clean_mac(value: str) -> str:
    mac = normalize_mac(value)
    if mac is None:
        raise NameError_(f"{value!r} is not a MAC address")
    return mac


class Names:
    """``{mac: {field: value}}``. Reads never raise; writes replace the file atomically."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict[str, dict[str, str]]:
        """``{mac: {"name": …, "description": …}}``. A file written by an older version held
        the name alone; it is read as such and rewritten in the richer shape on the next
        change, so an upgrade never loses a name."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            names = data["names"]
        except (OSError, ValueError, KeyError, TypeError):
            return {}
        if not isinstance(names, dict):
            return {}
        found = {}
        for mac, entry in names.items():                     # JSON keys are always strings
            if isinstance(entry, str):                       # the shape of version 1
                entry = {"name": entry}
            if not isinstance(entry, dict):
                continue
            kept = {f: entry[f] for f in FIELDS
                    if isinstance(entry.get(f), str) and entry[f]}
            if kept:
                found[mac] = kept
        return found

    def get(self, mac: str, field: str = "name") -> str:
        return self.read().get(mac, {}).get(field, "")

    def set(self, mac: str, value: str, field: str = "name") -> str:
        """Set one field of a MAC, or forget it when the value is empty."""
        mac, value = clean_mac(mac), clean_field(field, value)
        names = self.read()
        entry = dict(names.get(mac, {}))
        if value:
            entry[field] = value
        else:
            entry.pop(field, None)
        if entry:
            names[mac] = entry
        else:
            names.pop(mac, None)                             # nothing left to remember
        self._write(names)
        return value

    def _write(self, names: dict[str, dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".new")
        text = json.dumps({"version": FORMAT, "names": names}, indent=2, sort_keys=True,
                          ensure_ascii=False) + "\n"
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                     stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(text)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, self.path)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise


def store_for(paths) -> Names:
    """The store of a loaded configuration (``loaded.paths``)."""
    return Names(paths.state_dir / STORE_NAME)

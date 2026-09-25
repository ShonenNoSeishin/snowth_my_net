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
FORMAT = 1
MAX_LENGTH = 60                                  # a label, not a comment


class NameError_(ValueError):
    """What is wrong with a name or a MAC, in a sentence meant for the reader."""


def clean_name(text: str) -> str:
    """One line, trimmed, no control character: a name is rendered in a table cell."""
    name = " ".join(str(text).split())
    if len(name) > MAX_LENGTH:
        raise NameError_(f"a name is at most {MAX_LENGTH} characters")
    return name


def clean_mac(value: str) -> str:
    mac = normalize_mac(value)
    if mac is None:
        raise NameError_(f"{value!r} is not a MAC address")
    return mac


class Names:
    """``{mac: name}``. Reads never raise; writes replace the file atomically."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            names = data["names"]
        except (OSError, ValueError, KeyError, TypeError):
            return {}
        if not isinstance(names, dict):
            return {}
        return {mac: name for mac, name in names.items()
                if isinstance(mac, str) and isinstance(name, str) and name}

    def get(self, mac: str) -> str:
        return self.read().get(mac, "")

    def set(self, mac: str, name: str) -> str:
        """Name a MAC, or forget it when the name is empty. Returns the stored name."""
        mac, name = clean_mac(mac), clean_name(name)
        names = self.read()
        if name:
            names[mac] = name
        else:
            names.pop(mac, None)
        self._write(names)
        return name

    def _write(self, names: dict[str, str]) -> None:
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

"""ENTITY-MIB: chassis model, serial number and software revision.

Collected in two steps to spare the device: walk only ``entPhysicalClass`` and
``entPhysicalContainedIn`` (small integers), then GET the text columns of the few chassis
(and first modules) rows instead of walking the whole table of a big modular box.
"""

from __future__ import annotations

from dataclasses import dataclass

from snowth_my_net.snmp.values import decode_text

CLASS_MODULE, CLASS_CHASSIS, CLASS_STACK = 9, 3, 11
TEXT_COLUMNS = {2: "descr", 7: "name", 10: "sw_rev", 11: "serial", 13: "model"}
MAX_MODULES_FOR_SW_REV = 4

_JUNK_SERIALS = {
    "", "0", "00", "n/a", "na", "none", "null", "unknown", "not available", "not specified",
    "serial number", "serialnumber", "to be filled by o.e.m.", "default string",
    "123456789", "1234567890", "0123456789", "system serial number",
}


_JUNK_TEXT = {
    "", "-", "--", "?", "n/a", "na", "none", "null", "unknown", "not available",
    "not specified", "to be filled by o.e.m.", "default string",
}


@dataclass
class Chassis:
    index: int
    model: str = ""
    serial: str = ""
    sw_rev: str = ""
    descr: str = ""
    name: str = ""


def clean_serial(value: str) -> str:
    """Return the serial, or "" when it is a placeholder that cannot identify anything."""
    s = value.strip()
    if s.lower() in _JUNK_SERIALS or len(s) < 3 or len(set(s)) == 1:
        return ""
    return s


def clean_text(value: str) -> str:
    """A model or a software revision, or "" when it is a placeholder: "N/A" must not win over
    the model read from sysDescr."""
    return "" if value.strip().lower() in _JUNK_TEXT else value.strip()


def chassis_of(index: int, classes: dict[int, int], contained: dict[int, int]) -> int | None:
    """The chassis a row sits in, however many slots and containers lie between (a module is
    usually in a slot, the slot in the chassis)."""
    seen = set()
    while index and index not in seen and len(seen) < 16:
        seen.add(index)
        index = contained.get(index, 0)
        if classes.get(index) == CLASS_CHASSIS:
            return index
    return None


def rows_to_fetch(classes: dict[int, int], contained: dict[int, int]) -> list[int]:
    """Chassis rows, plus a few modules per chassis (software revision fallback)."""
    chassis = sorted(i for i, c in classes.items() if c == CLASS_CHASSIS)
    wanted = list(chassis)
    for ch in chassis:
        modules = sorted(i for i, c in classes.items()
                         if c == CLASS_MODULE and chassis_of(i, classes, contained) == ch)
        wanted += modules[:MAX_MODULES_FOR_SW_REV]
    return wanted


def build_chassis(
    classes: dict[int, int], contained: dict[int, int], rows: dict[int, dict[int, object]]
) -> list[Chassis]:
    """Chassis ordered with the main one first (top level, then lowest index)."""

    def text(idx: int, col: int) -> str:
        v = rows.get(idx, {}).get(col)
        return decode_text(v) if isinstance(v, bytes | str) else ""

    stacks = {i for i, c in classes.items() if c == CLASS_STACK}
    result = []
    for idx in sorted(i for i, c in classes.items() if c == CLASS_CHASSIS):
        ch = Chassis(index=idx, descr=text(idx, 2), name=text(idx, 7),
                     sw_rev=clean_text(text(idx, 10)),
                     serial=clean_serial(text(idx, 11)), model=clean_text(text(idx, 13)))
        if not ch.sw_rev:
            for mod in sorted(i for i, c in classes.items()
                              if c == CLASS_MODULE and chassis_of(i, classes, contained) == idx):
                if rev := clean_text(text(mod, 10)):
                    ch.sw_rev = rev
                    break
        result.append(ch)

    def top_level(ch: Chassis) -> int:
        parent = contained.get(ch.index, 0)
        return 0 if parent == 0 or parent in stacks else 1

    result.sort(key=lambda ch: (top_level(ch), ch.index))
    return result

"""IP-MIB neighbour caches: ``ipNetToPhysicalTable`` (v4 + v6) and ``ipNetToMediaTable``.

Both are always read: some agents only fill the legacy one (typical of firewalls), others only
the new one. Invalid, local and incomplete entries are dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

from snowth_my_net.snmp.index import decode_inet_address, decode_ipv4_index
from snowth_my_net.snmp.values import is_multicast, normalize_mac

TYPE_INVALID, TYPE_LOCAL = 2, 5
STATE_INCOMPLETE = 7

Column = dict[tuple[int, ...], object]


@dataclass(frozen=True)
class ArpEntry:
    mac: str
    ip: str
    family: int          # 4 | 6
    ifindex: int | None
    table: str           # physical | media


def _mac(value: object) -> str | None:
    if not isinstance(value, bytes) or len(value) != 6:
        return None
    mac = normalize_mac(value)
    if mac is None or is_multicast(mac):
        return None
    return mac


def parse_net_to_physical(phys: Column, types: Column, states: Column) -> list[ArpEntry]:
    entries = []
    for suffix, value in phys.items():
        if len(suffix) < 3:
            continue
        if types.get(suffix) in (TYPE_INVALID, TYPE_LOCAL):
            continue
        if states.get(suffix) == STATE_INCOMPLETE:
            continue
        mac = _mac(value)
        if mac is None:
            continue
        ip, _used = decode_inet_address(suffix[2:], suffix[1])
        if ip is None or ip.is_unspecified or ip.is_multicast or ip.is_loopback:
            continue
        entries.append(ArpEntry(mac, str(ip), ip.version, suffix[0], "physical"))
    return entries


def parse_net_to_media(phys: Column, types: Column) -> list[ArpEntry]:
    entries = []
    for suffix, value in phys.items():
        if len(suffix) != 5 or types.get(suffix) == TYPE_INVALID:
            continue
        mac = _mac(value)
        ip = decode_ipv4_index(suffix[1:])
        if mac is None or ip is None or ip.is_unspecified or ip.is_multicast:
            continue
        entries.append(ArpEntry(mac, str(ip), 4, suffix[0], "media"))
    return entries


def merge_tables(*lists: list[ArpEntry]) -> list[ArpEntry]:
    """One entry per (mac, ip); the first table listing it wins (``physical`` is read first)."""
    seen: dict[tuple[str, str], ArpEntry] = {}
    for entries in lists:
        for entry in entries:
            seen.setdefault((entry.mac, entry.ip), entry)
    return list(seen.values())

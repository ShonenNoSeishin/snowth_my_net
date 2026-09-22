"""LLDP-MIB and CISCO-CDP-MIB neighbour tables: pure parsers.

Only raw facts are produced here (what the device says it sees on which local port). Resolving
the remote end to a polled device, and deciding what a neighbour means for port roles, happens
when reading the state (``merge``), so that it always uses the latest inventory.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field

from snowth_my_net.collect.tables.interfaces import Interface, short_port_name
from snowth_my_net.collect.tables.system import caps_names, decode_lldp_caps
from snowth_my_net.snmp.values import decode_text, normalize_mac

Column = dict[tuple[int, ...], object]

# LldpChassisIdSubtype / LldpPortIdSubtype values that carry a MAC or a network address
CHASSIS_MAC, CHASSIS_NETWORK = 4, 5
PORT_ALIAS, PORT_MAC, PORT_NETWORK, PORT_NAME, PORT_LOCAL = 1, 3, 4, 5, 7

# CDP capability bits (CISCO-CDP-MIB cdpCacheCapabilities)
CDP_CAPS = ((0x01, "router"), (0x02, "bridge"), (0x04, "bridge"), (0x08, "bridge"),
            (0x10, "station"), (0x40, "repeater"), (0x80, "telephone"))
# Cisco access points announce themselves through their CDP platform string.
CISCO_AP_PLATFORM = re.compile(r"^(cisco\s+)?(AIR-|C91\d\d|CW91\d\d|AP\d{4})", re.IGNORECASE)
NXOS_SERIAL_SUFFIX = re.compile(r"^(?P<name>.+?)\((?P<serial>[A-Za-z0-9]{6,})\)$")


@dataclass
class Neighbor:
    protocol: str                   # lldp | cdp
    local_port_num: int             # lldpRemLocalPortNum, or the ifIndex for CDP
    local_ifindex: int | None = None
    local_method: str = ""
    chassis_id: str = ""
    port_id: str = ""
    port_is_mac: bool = False
    port_desc: str = ""
    sys_name: str = ""
    sys_descr: str = ""
    platform: str = ""
    caps: frozenset[str] = frozenset()
    mgmt_addresses: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Identity of the remote system, stable across walks."""
        return self.chassis_id or self.sys_name.casefold() or f"port:{self.port_id}"


# --------------------------------------------------------------------------- decoding helpers


def _text(value: object) -> str:
    return decode_text(value) if isinstance(value, bytes | str) else ""


def _network_address(raw: bytes) -> str:
    """``IANA address family`` octet followed by the address (LLDP networkAddress subtype)."""
    if len(raw) == 5 and raw[0] == 1:
        return str(ipaddress.IPv4Address(raw[1:]))
    if len(raw) == 17 and raw[0] == 2:
        return str(ipaddress.IPv6Address(raw[1:]))
    return raw.hex()


def decode_chassis_id(subtype: object, value: object) -> str:
    if isinstance(value, bytes):
        if subtype == CHASSIS_MAC and len(value) == 6:
            return normalize_mac(value) or value.hex()
        if subtype == CHASSIS_NETWORK:
            return _network_address(value)
    return _text(value)


def decode_port_id(subtype: object, value: object) -> tuple[str, bool]:
    """``(port id, is_mac)``."""
    if isinstance(value, bytes):
        if subtype == PORT_MAC and len(value) == 6:
            return normalize_mac(value) or value.hex(), True
        if subtype == PORT_NETWORK:
            return _network_address(value), False
    return _text(value), False


def _split_rem_index(suffix: tuple[int, ...]) -> tuple[int, int] | None:
    """lldpRemTable index: timeMark.localPortNum.index -> (localPortNum, index)."""
    if len(suffix) != 3:
        return None
    return suffix[1], suffix[2]


def _man_addr(parts: tuple[int, ...]) -> str | None:
    """lldpRemManAddr index part: addrSubtype[.len].address."""
    if len(parts) < 2:
        return None
    family, rest = parts[0], parts[1:]
    size = {1: 4, 2: 16}.get(family)
    if size is None:
        return None
    if len(rest) == size + 1 and rest[0] == size:
        rest = rest[1:]
    if len(rest) != size or any(not 0 <= b <= 255 for b in rest):
        return None
    ip = ipaddress.ip_address(bytes(rest))
    return str(ip)


# --------------------------------------------------------------------------- LLDP


def parse_lldp(rem: dict[int, Column], man_addr: Column) -> list[Neighbor]:
    """``rem`` maps an lldpRemEntry column number to its values."""
    return _build_lldp(rem, man_addr, _split_rem_index, man_addr_offset=3)


def _build_lldp(rem: dict[int, Column], man_addr: Column, split, man_addr_offset: int
                ) -> list[Neighbor]:
    """Shared by LLDP-MIB and LLDP-V2-MIB: ``split`` reads (local port, index) from an index."""
    neighbors: dict[tuple[int, int], Neighbor] = {}
    sys_names = rem.get(9, {})
    keys = set()
    for column in (4, 5, 6, 7, 9):
        keys |= set(rem.get(column, {}))
    for suffix in keys:
        parts = split(suffix)
        if parts is None:
            continue
        port_id, is_mac = decode_port_id(rem.get(6, {}).get(suffix), rem.get(7, {}).get(suffix))
        caps_raw = rem.get(12, {}).get(suffix)
        neighbors[parts] = Neighbor(
            protocol="lldp",
            local_port_num=parts[0],
            chassis_id=decode_chassis_id(rem.get(4, {}).get(suffix), rem.get(5, {}).get(suffix)),
            port_id=port_id,
            port_is_mac=is_mac,
            port_desc=_text(rem.get(8, {}).get(suffix)),
            sys_name=_text(sys_names.get(suffix)),
            sys_descr=_text(rem.get(10, {}).get(suffix)),
            caps=frozenset(caps_names(decode_lldp_caps(caps_raw if isinstance(caps_raw, bytes)
                                                       else None))),
        )
    for suffix in man_addr:
        if len(suffix) < man_addr_offset + 1:
            continue
        parts = split(suffix[:man_addr_offset])
        neighbor = neighbors.get(parts) if parts else None
        address = _man_addr(suffix[man_addr_offset:])
        if neighbor is not None and address and address not in neighbor.mgmt_addresses:
            neighbor.mgmt_addresses.append(address)
    for neighbor in neighbors.values():
        neighbor.mgmt_addresses.sort(key=lambda a: (ipaddress.ip_address(a).version,
                                                    ipaddress.ip_address(a)))
    return [neighbors[k] for k in sorted(neighbors)]


def _split_v2_index(suffix: tuple[int, ...]) -> tuple[int, int] | None:
    """lldpV2RemTable index: timeMark.localIfIndex.destMAC(6 sub-ids).index."""
    if len(suffix) != 9:
        return None
    return suffix[1], suffix[8]


# lldpV2RemEntry columns hold the same values as lldpRemEntry, one number further along.
V2_COLUMNS = {4: 5, 5: 6, 6: 7, 7: 8, 8: 9, 9: 10, 10: 11, 12: 13}


def parse_lldp_v2(rem: dict[int, Column], man_addr: Column) -> list[Neighbor]:
    """Same neighbours as :func:`parse_lldp`, read from LLDP-V2-MIB.

    The index carries the local ifIndex, so every neighbour is mapped to its port without the
    guesswork of ``map_local_ports``.
    """
    as_v1 = {v1: rem.get(v2, {}) for v1, v2 in V2_COLUMNS.items()}
    neighbors = _build_lldp(as_v1, man_addr, _split_v2_index, man_addr_offset=9)
    for neighbor in neighbors:
        neighbor.local_ifindex = neighbor.local_port_num
        neighbor.local_method = "lldpv2_ifindex"
    return neighbors


def map_local_ports(loc: dict[int, Column], interfaces: dict[int, Interface],
                    bridge_ports: dict[int, int]) -> dict[int, tuple[int, str]]:
    """lldpLocPortNum -> (ifIndex, method), trying the methods of DESIGN.md §9.2 in order."""
    by_label: dict[str, set[int]] = {}
    by_mac: dict[str, set[int]] = {}
    for idx, itf in interfaces.items():
        for label in (itf.name, itf.descr, itf.alias, short_port_name(itf.descr)):
            if label:
                by_label.setdefault(label.casefold(), set()).add(idx)
        if itf.phys_mac:
            by_mac.setdefault(itf.phys_mac, set()).add(idx)

    def unique(candidates: set[int] | None) -> int | None:
        return next(iter(candidates)) if candidates and len(candidates) == 1 else None

    result: dict[int, tuple[int, str]] = {}
    port_nums = set()
    for column in loc.values():
        port_nums |= {s[0] for s in column if len(s) == 1}
    for num in sorted(port_nums):
        subtype = loc.get(2, {}).get((num,))
        raw = loc.get(3, {}).get((num,))
        desc = _text(loc.get(4, {}).get((num,)))
        found = None
        if subtype == PORT_MAC and isinstance(raw, bytes) and len(raw) == 6:
            found = unique(by_mac.get(normalize_mac(raw) or ""))
            method = "port_id_mac"
        if found is None:
            text = _text(raw)
            for label in (text, short_port_name(text)):
                found = unique(by_label.get(label.casefold())) if label else None
                if found is not None:
                    break
            method = "port_id_name"
        if found is None and desc:
            found = unique(by_label.get(desc.casefold()))
            method = "port_desc"
        if found is None and num in interfaces:
            found, method = num, "port_num_ifindex"
        if found is None and num in bridge_ports:
            found, method = bridge_ports[num], "port_num_bridge_port"
        if found is not None:
            result[num] = (found, method)
    return result


def assign_local_ports(neighbors: list[Neighbor], mapping: dict[int, tuple[int, str]]) -> None:
    for neighbor in neighbors:
        if neighbor.local_port_num in mapping:
            neighbor.local_ifindex, neighbor.local_method = mapping[neighbor.local_port_num]
        else:
            neighbor.local_method = "unmapped"


# --------------------------------------------------------------------------- CDP


def cdp_caps(value: object) -> frozenset[str]:
    if isinstance(value, bytes) and value:
        mask = int.from_bytes(value[-4:], "big")
    elif isinstance(value, int):
        mask = value
    else:
        return frozenset()
    return frozenset(name for bit, name in CDP_CAPS if mask & bit)


def clean_cdp_device_id(device_id: str) -> tuple[str, str]:
    """NX-OS reports ``hostname(SERIAL)``: returns ``(hostname, serial)``."""
    m = NXOS_SERIAL_SUFFIX.match(device_id.strip())
    if m:
        return m["name"], m["serial"]
    return device_id.strip(), ""


def parse_cdp(cache: dict[int, Column]) -> list[Neighbor]:
    """``cache`` maps a cdpCacheEntry column number to its values (index ifIndex.deviceIndex)."""
    result = []
    keys = set()
    for column in (4, 6, 7):
        keys |= {s for s in cache.get(column, {}) if len(s) == 2}
    for suffix in sorted(keys):
        name, _serial = clean_cdp_device_id(_text(cache.get(6, {}).get(suffix)))
        platform = _text(cache.get(8, {}).get(suffix))
        caps = set(cdp_caps(cache.get(9, {}).get(suffix)))
        if CISCO_AP_PLATFORM.match(platform):
            caps.add("wlan_ap")
        addresses = []
        address_type = cache.get(3, {}).get(suffix)
        raw_address = cache.get(4, {}).get(suffix)
        if address_type == 1 and isinstance(raw_address, bytes) and len(raw_address) == 4:
            addresses.append(str(ipaddress.IPv4Address(raw_address)))
        port = _text(cache.get(7, {}).get(suffix))
        result.append(Neighbor(
            protocol="cdp", local_port_num=suffix[0], local_ifindex=suffix[0],
            local_method="cdp_ifindex", chassis_id="", port_id=short_port_name(port),
            sys_name=name, sys_descr=_text(cache.get(5, {}).get(suffix)), platform=platform,
            caps=frozenset(caps), mgmt_addresses=addresses))
    return result

"""IP-MIB: the device's own addresses (``ipAddrTable`` and ``ipAddressTable``)."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from snowth_my_net.snmp.index import decode_inet_address, decode_ipv4_index

ADDRESS_TYPE_BROADCAST = 3


@dataclass(frozen=True)
class DeviceAddress:
    address: str
    ifindex: int | None
    prefix_len: int | None


def _usable(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (ip.is_loopback or ip.is_unspecified or ip.is_multicast)


def parse_ip_addr_table(
    if_index: dict[tuple[int, ...], object], net_mask: dict[tuple[int, ...], object]
) -> list[DeviceAddress]:
    """Legacy IPv4 table; both dicts are keyed by the index suffix (the address)."""
    result = []
    for suffix, idx in if_index.items():
        ip = decode_ipv4_index(suffix)
        if ip is None or not _usable(ip):
            continue
        prefix = None
        mask = net_mask.get(suffix)
        if isinstance(mask, str):
            try:
                prefix = ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
            except ValueError:
                prefix = None
        result.append(DeviceAddress(str(ip), idx if isinstance(idx, int) else None, prefix))
    return result


def parse_ip_address_table(
    if_index: dict[tuple[int, ...], object],
    addr_type: dict[tuple[int, ...], object],
    prefix: dict[tuple[int, ...], object],
) -> list[DeviceAddress]:
    """``ipAddressTable`` (v4 and v6), index ``type.len.addr``; broadcast rows are skipped."""
    result = []
    for suffix, idx in if_index.items():
        if not suffix:
            continue
        ip, _ = decode_inet_address(suffix[1:], suffix[0])
        if ip is None or not _usable(ip) or addr_type.get(suffix) == ADDRESS_TYPE_BROADCAST:
            continue
        plen = None
        pointer = prefix.get(suffix)
        if isinstance(pointer, tuple) and len(pointer) > 1 and pointer[-1] <= 128:
            plen = pointer[-1]  # RowPointer into ipAddressPrefixTable ends with the length
        result.append(DeviceAddress(str(ip), idx if isinstance(idx, int) else None, plen))
    return result


def merge_addresses(*lists: list[DeviceAddress]) -> list[DeviceAddress]:
    """One entry per address; the first list providing a prefix length wins."""
    merged: dict[str, DeviceAddress] = {}
    for items in lists:
        for item in items:
            known = merged.get(item.address)
            if known is None or (known.prefix_len is None and item.prefix_len is not None):
                merged[item.address] = item
    return sorted(merged.values(), key=lambda a: ipaddress.ip_address(a.address).packed)

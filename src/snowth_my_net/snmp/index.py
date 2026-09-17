"""Decoding of composite table indexes (InetAddress, fixed-length octet strings)."""

from __future__ import annotations

import ipaddress

IpAddr = ipaddress.IPv4Address | ipaddress.IPv6Address

# InetAddressType values (RFC 4001)
INET_IPV4, INET_IPV6, INET_IPV4Z, INET_IPV6Z = 1, 2, 3, 4
_ADDR_LEN = {INET_IPV4: 4, INET_IPV6: 16, INET_IPV4Z: 8, INET_IPV6Z: 20}


def decode_inet_address(parts: tuple[int, ...], addr_type: int) -> tuple[IpAddr | None, int]:
    """Decode an ``InetAddress`` index component that follows its ``InetAddressType``.

    ``parts`` starts at the (expected) length sub-identifier. Returns ``(address, consumed)``;
    ``address`` is None for unsupported types. Agents that omit the length prefix (a common
    bug) are tolerated when exactly the address bytes remain. Zones (``ipv4z``/``ipv6z``) are
    dropped.
    """
    size = _ADDR_LEN.get(addr_type)
    if size is None:
        return None, len(parts)
    if len(parts) >= size + 1 and parts[0] == size:
        raw, consumed = parts[1 : 1 + size], 1 + size
    elif len(parts) >= size:
        raw, consumed = parts[:size], size
    else:
        return None, len(parts)
    if any(not 0 <= b <= 255 for b in raw):
        return None, consumed
    data = bytes(raw)
    if addr_type in (INET_IPV4, INET_IPV4Z):
        return ipaddress.IPv4Address(data[:4]), consumed
    return ipaddress.IPv6Address(data[:16]), consumed


def decode_ipv4_index(parts: tuple[int, ...]) -> ipaddress.IPv4Address | None:
    if len(parts) != 4 or any(not 0 <= b <= 255 for b in parts):
        return None
    return ipaddress.IPv4Address(bytes(parts))


def decode_mac_index(parts: tuple[int, ...]) -> str | None:
    if len(parts) != 6 or any(not 0 <= b <= 255 for b in parts):
        return None
    return ":".join(f"{b:02x}" for b in parts)

"""SNMP agent address: IP literal plus UDP port."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

DEFAULT_PORT = 161


class AddressError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    host: str  # IP literal (host names are resolved before a Target is built)
    port: int = DEFAULT_PORT

    @property
    def ip(self) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
        return ipaddress.ip_address(self.host)

    @property
    def is_ipv6(self) -> bool:
        return self.ip.version == 6

    def __str__(self) -> str:
        if self.port == DEFAULT_PORT:
            return self.host
        return f"[{self.host}]:{self.port}" if ":" in self.host else f"{self.host}:{self.port}"

    def sort_key(self) -> tuple:
        return (self.ip.version, self.ip.packed, self.port)


def split_host_port(text: str) -> tuple[str, int]:
    """``host``, ``host:port``, ``[v6]:port`` or bare IPv6 -> ``(host, port)``."""
    t = text.strip()
    if not t:
        raise AddressError("empty address")
    if t.startswith("["):
        host, sep, rest = t[1:].partition("]")
        if not sep:
            raise AddressError(f"invalid address {text!r}")
        port_text = rest[1:] if rest.startswith(":") else ""
    elif t.count(":") == 1:
        host, port_text = t.split(":")
    else:
        host, port_text = t, ""
    port = DEFAULT_PORT
    if port_text:
        if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            raise AddressError(f"invalid port in {text!r}")
        port = int(port_text)
    return host, port


def has_explicit_port(text: str) -> bool:
    t = text.strip()
    return (t.startswith("[") and "]:" in t) or (not t.startswith("[") and t.count(":") == 1)


def parse_target(text: str) -> Target:
    """Parse an address whose host part is an IP literal."""
    host, port = split_host_port(text)
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise AddressError(f"{host!r} is not an IP address") from None
    return Target(str(ip), port)

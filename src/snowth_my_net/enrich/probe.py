"""Asking a host its own name, when no DNS zone holds it.

A reverse zone is declared by whoever runs the DNS; these three ask the host itself, which is
what ``ping -a``, ``nbtstat -A`` and a scanner do. The difference matters and is kept visible: a
PTR is what the network says about a host, a NetBIOS or mDNS answer is what the host says about
itself. Both are useful; only one is authoritative.

Nothing here writes anything or changes a device: one small UDP question each, and a timeout.
"""

from __future__ import annotations

import asyncio
import ipaddress
import random
import socket
from dataclasses import dataclass

NBNS_PORT, MDNS_PORT, LLMNR_PORT = 137, 5353, 5355
NBSTAT, IN = 0x0021, 0x0001
GROUP_FLAG = 0x8000
WORKSTATION = 0x00                           # the computer's own name
SERVER = 0x20


@dataclass(frozen=True)
class Answer:
    """What one way of asking replied."""

    source: str                              # ptr | netbios | mdns
    name: str = ""
    detail: str = ""                         # why there is no name, when there is none
    mac: str = ""                            # NetBIOS also states the adapter's address

    @property
    def found(self) -> bool:
        return bool(self.name)


def _first_level(name: str) -> bytes:
    """NetBIOS first-level encoding: each byte becomes two letters ('*' -> 'CK')."""
    padded = name.ljust(16, "\x00")[:16].encode("ascii", "replace")
    out = bytearray()
    for byte in padded:
        out += bytes((0x41 + (byte >> 4), 0x41 + (byte & 0x0F)))
    return bytes((len(out),)) + bytes(out) + b"\x00"


def nbstat_query() -> bytes:
    """The question ``nbtstat -A`` asks: a node status request for the wildcard name."""
    # A transaction id only has to differ from the last one; it protects nothing.
    header = bytes((random.randrange(256), random.randrange(256),
                    0x00, 0x00, 0x00, 0x01, 0, 0, 0, 0, 0, 0))
    return header + _first_level("*") + NBSTAT.to_bytes(2) + IN.to_bytes(2)


def parse_nbstat(payload: bytes) -> Answer:
    """The workstation name of a node status reply, and the adapter address it states."""
    body = payload[12:]                      # past the header
    end = body.find(b"\x00")                 # past the encoded question name
    if end < 0 or len(body) < end + 11:
        return Answer("netbios", detail="truncated answer")
    rdata = body[end + 11:]
    if not rdata:
        return Answer("netbios", detail="no names in the answer")
    count, rdata = rdata[0], rdata[1:]
    names: list[tuple[str, int, int]] = []
    for index in range(count):
        entry = rdata[index * 18:(index + 1) * 18]
        if len(entry) < 18:
            break
        names.append((entry[:15].decode("latin-1").strip(), entry[15],
                      int.from_bytes(entry[16:18])))
    mac = rdata[count * 18:count * 18 + 6]
    address = ":".join(f"{byte:02x}" for byte in mac) if len(mac) == 6 else ""
    for name, kind, flags in names:
        if kind in (WORKSTATION, SERVER) and not flags & GROUP_FLAG and name:
            return Answer("netbios", name=name, mac=address)
    if names:
        return Answer("netbios", detail="only group names", mac=address)
    return Answer("netbios", detail="no names in the answer", mac=address)


async def ask_netbios(ip: str, timeout: float = 2.0) -> Answer:
    """``nbtstat -A <ip>``: Windows hosts, Samba, many printers. Unicast UDP/137."""
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    try:
        await loop.sock_sendto(sock, nbstat_query(), (ip, NBNS_PORT))
        payload = await asyncio.wait_for(loop.sock_recv(sock, 1024), timeout)
    except TimeoutError:
        return Answer("netbios", detail="no answer")
    except OSError as exc:
        return Answer("netbios", detail=str(exc))
    finally:
        sock.close()
    return parse_nbstat(payload)


async def _reverse_on(ip: str, port: int, source: str, timeout: float) -> Answer:
    """A reverse question asked to the host itself, in DNS form, on one of its name ports."""
    import dns.asyncquery
    import dns.exception
    import dns.message
    import dns.rdatatype
    import dns.reversename

    try:
        question = dns.message.make_query(dns.reversename.from_address(ip), dns.rdatatype.PTR)
    except (ValueError, dns.exception.SyntaxError) as exc:   # not a ValueError in dnspython
        return Answer(source, detail=str(exc) or "not an address")
    try:
        reply = await dns.asyncquery.udp(question, ip, port=port, timeout=timeout)
    except dns.exception.Timeout:
        return Answer(source, detail="no answer")
    except (OSError, dns.exception.DNSException) as exc:
        return Answer(source, detail=type(exc).__name__)
    for answer in reply.answer:
        for record in answer:
            return Answer(source, name=record.to_text().rstrip("."))
    return Answer(source, detail="answered without a name")


async def ask_mdns(ip: str, timeout: float = 2.0) -> Answer:
    """UDP/5353: Apple, Avahi, printers, cameras, anything that publishes a ``.local`` name."""
    return await _reverse_on(ip, MDNS_PORT, "mdns", timeout)


async def ask_llmnr(ip: str, timeout: float = 2.0) -> Answer:
    """UDP/5355: what Windows answers with, when a group policy has not turned it off.

    Windows runs no mDNS responder for its own name — it uses this instead — so a Windows host
    that says nothing on 137 and 5353 may still answer here.
    """
    return await _reverse_on(ip, LLMNR_PORT, "llmnr", timeout)


async def ask_all(ip: str, timeout: float = 2.0) -> list[Answer]:
    """Every way of asking, at once; the caller decides what to trust."""
    ipaddress.ip_address(ip)                 # raises for anything that is not an address
    return list(await asyncio.gather(ask_netbios(ip, timeout), ask_llmnr(ip, timeout),
                                     ask_mdns(ip, timeout)))

"""Port scans of a known address, to learn what a device is: nmap, run without privilege.

Everything here is a TCP connection from an unprivileged process: no raw packet, no operating
system guess, nothing the container would need a capability for. The tool decides what is asked
and of whom — only addresses ``discovery`` would query, never a name (so never an option) —
and keeps what nmap found, per address, so that the answer outlives the page that asked.
"""

from __future__ import annotations

import ipaddress
import shutil
import subprocess
import time
from dataclasses import dataclass
from xml.etree import ElementTree

from snowth_my_net.collect.discovery import Scope

# profile -> (nmap arguments, seconds one host may take)
PROFILES: dict[str, tuple[tuple[str, ...], int]] = {
    "quick": (("--top-ports", "100"), 60),
    "common": (("--top-ports", "1000", "-sV", "--version-light"), 300),
    "all": (("-p-", "-sV", "--version-light"), 1800),
}
DEFAULT_PROFILE = "common"
MAX_HOSTS = 1024                               # one command, one /22: a mistake costs minutes


class ScanError(Exception):
    pass


@dataclass
class Skipped:
    address: str
    reason: str


def addresses_of(targets: list[str]) -> list[str]:
    """Every host address the targets stand for, as written by ``ipaddress``.

    A network gives its hosts (all of a /31 or /32). Names are refused: they would be resolved
    behind the reader's back, and what starts with ``-`` would be an option.
    """
    found: dict[str, None] = {}
    for item in targets:
        text = item.strip()
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError:
            raise ScanError(f"{text!r} is not an IP address or a network (names are not "
                            "resolved here)") from None
        if network.num_addresses > MAX_HOSTS * 2:
            raise ScanError(f"{text} is larger than {MAX_HOSTS} hosts: scan it in parts")
        hosts = network.hosts() if network.num_addresses > 2 else iter(network)
        for host in hosts:
            found[str(host)] = None
            if len(found) > MAX_HOSTS:
                raise ScanError(f"more than {MAX_HOSTS} hosts: scan them in parts")
    return list(found)


def in_scope(cfg, addresses: list[str]) -> tuple[list[str], list[Skipped]]:
    """``(allowed, skipped)``: the rule that bounds discovery bounds this, and says what it left."""
    seeds = set()
    for seed in cfg.discovery.seeds:
        try:
            seeds.add(str(ipaddress.ip_address(seed)))
        except ValueError:
            continue
    scope = Scope(cfg.discovery.allowed, cfg.discovery.exclude, seeds)
    allowed, skipped = [], []
    for address in addresses:
        reason = scope.check(ipaddress.ip_address(address))
        (skipped.append(Skipped(address, reason)) if reason else allowed.append(address))
    return allowed, skipped


def command(addresses: list[str], profile: str, binary: str = "nmap") -> tuple[list[str], int]:
    """``(argv, seconds allowed)``; the argv is for ``subprocess`` with no shell."""
    arguments, per_host = PROFILES[profile]
    argv = [binary, "--unprivileged", "-sT", "-n", "--max-retries", "2",
            "--host-timeout", f"{per_host}s", *arguments]
    if len(addresses) == 1:
        argv.append("-Pn")        # one known address: ask it, even if it ignores the discovery
    argv += ["-oX", "-", *addresses]
    return argv, per_host * (len(addresses) // 32 + 1) + 60


def parse(xml: str) -> list[dict]:
    """The hosts of an nmap XML report: ``address, status, detail, ports``."""
    if "<!ENTITY" in xml:                     # nmap writes none; refuse a document that defines any
        raise ScanError("the scanner's report defines entities; refused")
    try:
        root = ElementTree.fromstring(xml)  # noqa: S314 - no entity is ever defined (checked above)
    except ElementTree.ParseError as exc:
        raise ScanError(f"the scanner's report cannot be read: {exc}") from None
    hosts = []
    for host in root.findall("host"):
        address = next((a.get("addr") for a in host.findall("address")
                        if a.get("addrtype") in ("ipv4", "ipv6")), "")
        if not address:
            continue
        up = (host.find("status") is None) or host.find("status").get("state") == "up"
        ports = []
        for port in host.findall("./ports/port"):
            state = port.find("state")
            if state is None or state.get("state") != "open":
                continue
            service = port.find("service")
            attributes = service.attrib if service is not None else {}
            version = " ".join(part for part in (attributes.get("version", ""),
                                                 attributes.get("extrainfo", "")) if part)
            ports.append({"port": int(port.get("portid", 0)), "proto": port.get("protocol", ""),
                          "state": "open", "service": attributes.get("name", ""),
                          "product": attributes.get("product", ""), "version": version})
        hidden = [f"{e.get('count')} {e.get('state')}" for e in host.findall("./ports/extraports")]
        hosts.append({"address": address, "status": "ok" if up else "down",
                      "detail": ", ".join(hidden) if not ports else "", "ports": ports})
    return hosts


def run(addresses: list[str], profile: str, binary: str | None = None) -> list[dict]:
    """Scan, and return one result per address asked — one nmap did not report is ``down``."""
    exe = binary or shutil.which("nmap")
    if not exe:
        raise ScanError("nmap is not installed here (the Docker image includes it; "
                        "outside Docker, install the nmap package)")
    argv, allowed = command(addresses, profile, exe)
    started = time.monotonic()
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=allowed,  # noqa: S603
                              check=False)
    except subprocess.TimeoutExpired:
        raise ScanError(f"nmap did not finish in {allowed} s") from None
    except OSError as exc:
        raise ScanError(f"nmap cannot be started: {exc}") from None
    if done.returncode != 0 and not done.stdout.strip():
        lines = (done.stderr or "").strip().splitlines()
        raise ScanError(f"nmap failed: {lines[-1] if lines else 'exit ' + str(done.returncode)}")
    seconds = round(time.monotonic() - started, 1)
    reported = {host["address"]: host for host in parse(done.stdout)}
    results = []
    for address in addresses:
        host = reported.get(address) or {"address": address, "status": "down",
                                         "detail": "no answer to the host discovery", "ports": []}
        results.append({**host, "profile": profile,
                        "seconds": seconds if len(addresses) == 1 else 0.0})   # a share is no time
    return results

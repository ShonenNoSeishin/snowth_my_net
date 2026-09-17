"""Where is each MAC? Pure resolution of FDB and ARP observations into nodes (DESIGN.md §9-10).

Everything is decided when reading the state, never frozen at collect time, so that a change of
configuration (uplinks, access ports, threshold, ignored MACs, manual settings) applies at once
and so that ``explain`` can show exactly why a MAC is where it is.

Rules, in short:

* A port is an **uplink** when declared (``uplinks``), when it is a link aggregation (only if
  ``lag_is_uplink``), or when it carried more than ``uplink_mac_threshold`` learned MACs in the
  last FDB walk of its device. ``access_ports`` forces a port to access. (Neighbor-based rules
  arrive with LLDP/CDP.)
* A MAC is positioned on **access ports only**. Seen on several access ports within
  ``transit_window``: the port with the fewest MACs wins, the others are transit ("shadowed").
  Older access sightings stay as the roaming history; the most recent one is the current one.
* A MAC seen only on uplinks has no position (strict), unless ``uplink_fallback`` and all its
  uplinks are "soft" (threshold only): then the soft uplink with the fewest MACs is used.
* The current IP is the most recently seen one that no other MAC claimed later, IPv4 first
  (``prefer_ipv4``), within ``current_ip_window`` of the MAC's newest IP sighting.
"""

from __future__ import annotations

import ipaddress
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from snowth_my_net.collect.tables.interfaces import IFTYPE_LAG, short_port_name
from snowth_my_net.config.schema import NodesCfg
from snowth_my_net.snmp.values import (
    is_locally_administered,
    is_multicast,
    mac_matches_prefix,
    normalize_mac,
    normalize_mac_prefix,
)

DAY = 86400
HARD, SOFT = "hard", "soft"


# --------------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class FdbObs:
    mac: str
    device_id: int
    ifindex: int
    vlan: int
    vlan_source: str
    first_seen: int
    last_seen: int
    last_run_id: int


@dataclass(frozen=True)
class ArpObs:
    mac: str
    ip: str
    family: int
    device_id: int
    table: str
    first_seen: int
    last_seen: int


@dataclass(frozen=True)
class PortInfo:
    name: str = ""
    descr: str = ""
    if_type: int | None = None
    lag_ifindex: int | None = None
    pvid: int | None = None

    def labels(self) -> set[str]:
        return {x.casefold() for x in (self.name, self.descr, short_port_name(self.name),
                                       short_port_name(self.descr)) if x}


@dataclass(frozen=True)
class DeviceInfo:
    name: str
    uplinks: tuple[str, ...] = ()
    access_ports: tuple[str, ...] = ()
    uplink_mac_threshold: int = 50


@dataclass
class MergeInputs:
    devices: dict[int, DeviceInfo]
    ports: dict[tuple[int, int], PortInfo]
    fdb: list[FdbObs]
    arp: list[ArpObs]
    device_macs: dict[str, int]          # MAC -> device id owning it


# --------------------------------------------------------------------------- outputs


@dataclass(frozen=True)
class PortRole:
    role: str                            # access | uplink
    reasons: tuple[tuple[str, str], ...]  # (code, detail)
    strength: str = HARD                 # for uplinks: hard | soft

    @property
    def uplink(self) -> bool:
        return self.role == "uplink"


@dataclass
class Sighting:
    device_id: int
    ifindex: int
    vlan: int
    vlan_source: str
    first_seen: int
    last_seen: int
    last_run_id: int
    mac_count: int
    role: PortRole
    verdict: str = ""        # position | uplink | shadowed | fallback
    shadowed_by: Sighting | None = None


@dataclass
class IpSighting:
    ip: str
    family: int
    first_seen: int
    last_seen: int
    sources: list[tuple[int, str, int]] = field(default_factory=list)  # device, table, seen
    superseded_by: str | None = None     # MAC that claimed this IP later


@dataclass
class Node:
    mac: str
    random_mac: bool
    excluded: str | None = None
    sightings: list[Sighting] = field(default_factory=list)
    positions: list[Sighting] = field(default_factory=list)   # most recent first
    position_kind: str = "none"          # access | behind_uplink | none
    ips: list[IpSighting] = field(default_factory=list)
    current_ip: IpSighting | None = None
    first_seen: int = 0
    last_seen: int = 0

    @property
    def current(self) -> Sighting | None:
        return self.positions[0] if self.positions else None


# --------------------------------------------------------------------------- resolution


def classify_port(port: PortInfo | None, mac_count: int, device: DeviceInfo,
                  cfg: NodesCfg) -> PortRole:
    labels = port.labels() if port else set()
    if labels & {p.casefold() for p in device.access_ports}:
        return PortRole("access", (("config_access", "listed in access_ports"),))
    hard: list[tuple[str, str]] = []
    soft: list[tuple[str, str]] = []
    if labels & {p.casefold() for p in device.uplinks}:
        hard.append(("config", "listed in uplinks"))
    if cfg.lag_is_uplink and port and (port.if_type == IFTYPE_LAG or port.lag_ifindex):
        hard.append(("lag", "link aggregation"))
    if mac_count > device.uplink_mac_threshold:
        soft.append(("mac_count", f"{mac_count} MACs > {device.uplink_mac_threshold}"))
    if hard or soft:
        return PortRole("uplink", tuple(hard + soft), HARD if hard else SOFT)
    return PortRole("access", ())


class MergeContext:
    """Pre-computed indexes shared by the resolution of every MAC."""

    def __init__(self, inputs: MergeInputs, cfg: NodesCfg, now: int) -> None:
        self.inputs, self.cfg, self.now = inputs, cfg, now
        horizon = now - cfg.retention_days * DAY
        self.fdb_by_mac: dict[str, list[FdbObs]] = defaultdict(list)
        latest_run: dict[int, int] = {}
        kept = [o for o in inputs.fdb if o.last_seen >= horizon and o.device_id in inputs.devices]
        for o in kept:
            self.fdb_by_mac[o.mac].append(o)
            latest_run[o.device_id] = max(latest_run.get(o.device_id, 0), o.last_run_id)
        # MACs per port in the most recent FDB walk of each device
        counted = {(o.device_id, o.ifindex, o.mac) for o in kept
                   if o.last_run_id == latest_run[o.device_id]}
        self.mac_count = Counter((d, i) for d, i, _m in counted)
        self._roles: dict[tuple[int, int], PortRole] = {}

        self.arp_by_mac: dict[str, list[ArpObs]] = defaultdict(list)
        self.latest_by_ip: dict[str, tuple[int, str]] = {}
        for a in inputs.arp:
            if a.last_seen < horizon:
                continue
            self.arp_by_mac[a.mac].append(a)
            best = self.latest_by_ip.get(a.ip)
            if best is None or a.last_seen > best[0]:
                self.latest_by_ip[a.ip] = (a.last_seen, a.mac)

        self.ignored_macs = {m for m in (normalize_mac(x) for x in cfg.ignore_macs) if m}
        self.ignored_prefixes = [p for p in (normalize_mac_prefix(x)
                                             for x in cfg.ignore_mac_prefixes) if p]

    def role(self, device_id: int, ifindex: int) -> PortRole:
        key = (device_id, ifindex)
        if key not in self._roles:
            self._roles[key] = classify_port(self.inputs.ports.get(key), self.mac_count[key],
                                             self.inputs.devices[device_id], self.cfg)
        return self._roles[key]

    def exclusion(self, mac: str) -> str | None:
        if is_multicast(mac):
            return "multicast or broadcast address"
        if not self.cfg.include_device_macs and mac in self.inputs.device_macs:
            owner = self.inputs.devices.get(self.inputs.device_macs[mac])
            return f"MAC of a polled device ({owner.name if owner else 'unknown'})"
        if mac in self.ignored_macs:
            return "listed in nodes.ignore_macs"
        for prefix in self.ignored_prefixes:
            if mac_matches_prefix(mac, prefix):
                return f"matches nodes.ignore_mac_prefixes ({prefix})"
        return None

    def all_macs(self) -> list[str]:
        return sorted(set(self.fdb_by_mac) | set(self.arp_by_mac))


def _ip_rank(ip: IpSighting, prefer_ipv4: bool) -> tuple:
    address = ipaddress.ip_address(ip.ip)
    return (0 if (prefer_ipv4 and ip.family == 4) else 1,
            1 if address.is_link_local else 0,
            -ip.last_seen, address.version, address.packed)


def resolve_mac(ctx: MergeContext, mac: str) -> Node:
    cfg = ctx.cfg
    node = Node(mac=mac, random_mac=is_locally_administered(mac), excluded=ctx.exclusion(mac))

    # --- FDB sightings, one per (device, port): the latest VLAN wins
    per_port: dict[tuple[int, int], FdbObs] = {}
    first: dict[tuple[int, int], int] = {}
    for o in ctx.fdb_by_mac.get(mac, []):
        key = (o.device_id, o.ifindex)
        first[key] = min(first.get(key, o.first_seen), o.first_seen)
        if key not in per_port or o.last_seen > per_port[key].last_seen:
            per_port[key] = o
    for key, o in per_port.items():
        port = ctx.inputs.ports.get(key)
        vlan, source = o.vlan, o.vlan_source
        if not vlan and port and port.pvid:
            vlan, source = port.pvid, "pvid"
        node.sightings.append(Sighting(o.device_id, o.ifindex, vlan, source, first[key],
                                       o.last_seen, o.last_run_id, ctx.mac_count[key],
                                       ctx.role(*key)))
    node.sightings.sort(key=lambda s: (-s.last_seen, s.mac_count, s.device_id, s.ifindex))

    access = [s for s in node.sightings if not s.role.uplink]
    for s in node.sightings:
        if s.role.uplink:
            s.verdict = "uplink"
    if access:
        newest = max(s.last_seen for s in access)
        window = [s for s in access if s.last_seen >= newest - cfg.transit_window]
        if len(window) > 1:
            keep = min(window, key=lambda s: (s.mac_count, -s.last_seen, s.device_id, s.ifindex))
            for s in window:
                if s is not keep:
                    s.verdict, s.shadowed_by = "shadowed", keep
        node.positions = [s for s in access if s.verdict != "shadowed"]
        for s in node.positions:
            s.verdict = "position"
        node.position_kind = "access"
    elif node.sightings and cfg.uplink_fallback and all(
            s.role.strength == SOFT for s in node.sightings):
        best = min(node.sightings, key=lambda s: (s.mac_count, -s.last_seen))
        best.verdict = "fallback"
        node.positions = [best]
        node.position_kind = "behind_uplink"
    node.positions.sort(key=lambda s: (-s.last_seen, s.device_id, s.ifindex))

    # --- IP addresses
    by_ip: dict[str, IpSighting] = {}
    for a in ctx.arp_by_mac.get(mac, []):
        ip = by_ip.get(a.ip)
        if ip is None:
            ip = by_ip[a.ip] = IpSighting(a.ip, a.family, a.first_seen, a.last_seen)
        ip.first_seen = min(ip.first_seen, a.first_seen)
        ip.last_seen = max(ip.last_seen, a.last_seen)
        ip.sources.append((a.device_id, a.table, a.last_seen))
    for ip in by_ip.values():
        latest_seen, latest_mac = ctx.latest_by_ip[ip.ip]
        if latest_mac != mac and latest_seen > ip.last_seen:
            ip.superseded_by = latest_mac
        ip.sources.sort(key=lambda src: -src[2])
    node.ips = sorted(by_ip.values(), key=lambda i: -i.last_seen)
    candidates = [i for i in node.ips if i.superseded_by is None]
    if candidates:
        newest_ip = max(i.last_seen for i in candidates)
        recent = [i for i in candidates if i.last_seen >= newest_ip - cfg.current_ip_window]
        node.current_ip = min(recent, key=lambda i: _ip_rank(i, cfg.prefer_ipv4))

    seen = [s.last_seen for s in node.sightings] + [i.last_seen for i in node.ips]
    firsts = [s.first_seen for s in node.sightings] + [i.first_seen for i in node.ips]
    node.last_seen = max(seen, default=0)
    node.first_seen = min(firsts, default=0)
    return node


def resolve_nodes(inputs: MergeInputs, cfg: NodesCfg, now: int) -> list[Node]:
    """Every node that is not excluded, in MAC order."""
    ctx = MergeContext(inputs, cfg, now)
    nodes = []
    for mac in ctx.all_macs():
        node = resolve_mac(ctx, mac)
        if node.excluded is None:
            nodes.append(node)
    return nodes

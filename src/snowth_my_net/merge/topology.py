"""Neighbours and links, resolved when reading the state.

* The remote end of an LLDP/CDP neighbour is matched to a polled device by management address,
  then chassis MAC, then sysName (first label, when unique); its port by MAC, name,
  description or alias.
* A neighbour makes the local port an uplink when it is a polled device that serves a MAC table
  (``neighbor_managed``, hard), or an unpolled bridge/router (``neighbor_infra``, soft). A
  telephone never does (IP phones announce ``bridge`` for their built-in PC port), nor does an
  access point when ``ap_ports_are_access``.
* A physical link seen from both ends, and by both LLDP and CDP, is one link.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from snowth_my_net.collect.tables.interfaces import short_port_name
from snowth_my_net.merge.nodes import HARD, SOFT, PortInfo
from snowth_my_net.snmp.values import normalize_mac

INFRA_CAPS = frozenset({"bridge", "router", "wlan_ap"})


@dataclass(frozen=True)
class NeighborObs:
    device_id: int
    ifindex: int | None
    protocol: str
    remote_key: str
    chassis_id: str
    sys_name: str
    port_id: str
    port_desc: str
    mgmt_addresses: tuple[str, ...]
    caps: frozenset[str]
    platform: str
    first_seen: int
    last_seen: int
    local_method: str = ""             # how the local port was found (collect/tables/neighbors)


# A local port found only because its LLDP number equals an ifIndex or a bridge port number is a
# coincidence of numbering, not a statement by the device.
GUESSED_LOCAL_PORTS = frozenset({"port_num_ifindex", "port_num_bridge_port"})


@dataclass
class DeviceKeys:
    device_id: int
    name: str
    sys_name: str
    addresses: set[str] = field(default_factory=set)
    macs: set[str] = field(default_factory=set)
    has_fdb: bool = False


@dataclass
class ResolvedNeighbor:
    obs: NeighborObs
    remote_device_id: int | None
    remote_ifindex: int | None
    remote_name: str
    remote_port: str

    @property
    def endpoint(self) -> bool:
        """A phone, a station or anything that is not network infrastructure."""
        if self.remote_device_id is not None:
            return False
        return "telephone" in self.obs.caps or not (self.obs.caps & INFRA_CAPS)


def _first_label(name: str) -> str:
    return name.split(".", 1)[0].strip().casefold()


class DeviceIndex:
    def __init__(self, devices: dict[int, DeviceKeys], ports: dict[tuple[int, int], PortInfo],
                 phys_macs: dict[tuple[int, int], str]) -> None:
        self.devices = devices
        self.by_address = {a: d.device_id for d in devices.values() for a in d.addresses}
        self.by_mac = {m: d.device_id for d in devices.values() for m in d.macs}
        names: dict[str, list[int]] = {}
        for d in devices.values():
            if d.sys_name:
                names.setdefault(_first_label(d.sys_name), []).append(d.device_id)
        self.by_name = {k: v[0] for k, v in names.items() if len(v) == 1}
        self.labels: dict[int, dict[str, set[int]]] = {}
        for (dev, ifx), port in ports.items():
            table = self.labels.setdefault(dev, {})
            for label in port.labels():
                table.setdefault(label, set()).add(ifx)
        for (dev, ifx), mac in phys_macs.items():
            self.labels.setdefault(dev, {}).setdefault(mac, set()).add(ifx)

    def device_of(self, n: NeighborObs) -> int | None:
        for address in n.mgmt_addresses:
            if address in self.by_address:
                return self.by_address[address]
        mac = normalize_mac(n.chassis_id) if n.chassis_id else None
        if mac and mac in self.by_mac:
            return self.by_mac[mac]
        if n.sys_name:
            return self.by_name.get(_first_label(n.sys_name))
        return None

    def port_of(self, device_id: int, n: NeighborObs) -> int | None:
        table = self.labels.get(device_id, {})
        candidates = []
        mac = normalize_mac(n.port_id) if n.port_id else None
        if mac:
            candidates.append(mac)
        for label in (n.port_id, n.port_desc):
            if label:
                candidates += [label.casefold(), short_port_name(label).casefold()]
        for label in candidates:
            found = table.get(label)
            if found and len(found) == 1:
                return next(iter(found))
        return None


def resolve_neighbors(neighbors: list[NeighborObs], index: DeviceIndex,
                      port_name) -> list[ResolvedNeighbor]:
    """``port_name(device_id, ifindex)`` renders a resolved remote port."""
    result = []
    for n in neighbors:
        remote = index.device_of(n)
        if remote == n.device_id:
            remote = None        # a device seeing itself (loop, shared chassis id): ignore
        remote_ifindex = index.port_of(remote, n) if remote is not None else None
        if remote is not None:
            name = index.devices[remote].name
        else:
            name = (n.sys_name.split(".", 1)[0] if n.sys_name else "") or n.chassis_id or "?"
        if remote is not None and remote_ifindex is not None:
            port = port_name(remote, remote_ifindex)
        elif normalize_mac(n.port_id) and n.port_desc:
            port = short_port_name(n.port_desc)
        else:
            port = short_port_name(n.port_id) or n.port_desc
        result.append(ResolvedNeighbor(n, remote, remote_ifindex, name, port))
    return result


def uplink_reason(rn: ResolvedNeighbor, index: DeviceIndex,
                  ap_ports_are_access: bool) -> tuple[str, str, str] | None:
    """(code, detail, strength) when this neighbour makes its local port an uplink."""
    caps, proto = rn.obs.caps, rn.obs.protocol.upper()
    if "telephone" in caps:
        return None
    if rn.remote_device_id is not None and index.devices[rn.remote_device_id].has_fdb:
        if rn.obs.local_method in GUESSED_LOCAL_PORTS:
            return ("neighbor_managed",
                    f"{rn.remote_name} ({proto}, local port guessed from its number)", SOFT)
        return "neighbor_managed", f"{rn.remote_name} ({proto})", HARD
    if "wlan_ap" in caps and "router" not in caps and ap_ports_are_access:
        return None
    if caps & {"bridge", "router"}:
        return "neighbor_infra", (f"{rn.remote_name} ({proto}, "
                                  f"{'/'.join(sorted(caps & {'bridge', 'router'}))})"), SOFT
    return None


@dataclass
class Link:
    a_device: str
    a_port: str
    b_device: str
    b_port: str
    protocols: set[str]
    first_seen: int
    last_seen: int
    b_device_id: int | None = None
    endpoint: bool = False

    @property
    def protocol(self) -> str:
        order = {"lldp": 0, "cdp": 1}
        return "+".join(p.upper() for p in sorted(self.protocols, key=lambda p: order.get(p, 9)))


def build_links(resolved: list[ResolvedNeighbor], names: dict[int, str],
                port_name) -> list[Link]:
    links: dict[frozenset, Link] = {}
    for rn in resolved:
        n = rn.obs
        if n.device_id not in names:
            continue
        local_port = port_name(n.device_id, n.ifindex) if n.ifindex is not None else "?"
        local = ("dev", n.device_id, n.ifindex if n.ifindex is not None
                 else local_port.casefold())
        if rn.remote_device_id is not None:
            remote = ("dev", rn.remote_device_id, rn.remote_ifindex
                      if rn.remote_ifindex is not None else rn.remote_port.casefold())
        else:
            remote = ("ext", rn.remote_name.casefold(), short_port_name(rn.remote_port).casefold())
        key = frozenset({local, remote})
        link = links.get(key)
        if link is None:
            a, b = (names[n.device_id], local_port), (rn.remote_name, rn.remote_port)
            swap = rn.remote_device_id is not None and b[0].casefold() < a[0].casefold()
            if swap:
                a, b = b, a
            link = links[key] = Link(a[0], a[1], b[0], b[1], set(), n.first_seen, n.last_seen,
                                     None if swap else rn.remote_device_id, rn.endpoint)
        link.protocols.add(n.protocol)
        link.first_seen = min(link.first_seen, n.first_seen)
        link.last_seen = max(link.last_seen, n.last_seen)
        link.endpoint = link.endpoint and rn.endpoint
    return sorted(links.values(), key=lambda lk: (lk.a_device.casefold(), lk.a_port,
                                                  lk.b_device.casefold(), lk.b_port))

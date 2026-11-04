"""The ports of a device, each with what is known to sit at the other end.

One reading for the web "Ports" page and the terminal interface. Nothing is guessed here: a
neighbour is on a port only because the device announced it there (LLDP/CDP), the role is the
one the merge already decided, and the MAC count is the number of MACs the device's own table
holds on that port.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from snowth_my_net.collect.tables.interfaces import short_port_name
from snowth_my_net.merge.view import NodeView
from snowth_my_net.state.repo import Repo

# ifType values that are not a cable: software loopback, VLAN interfaces, tunnels, bridges…
# They stay reachable through the "virtual" view, and any of them that carries a neighbour or
# a MAC is shown regardless — hiding something that has evidence on it would be a lie.
VIRTUAL_TYPES = frozenset({1, 24, 53, 131, 135, 136, 142, 150, 209, 244})

UP, DOWN, DISABLED, UNKNOWN = "up", "down", "disabled", ""


@dataclass(frozen=True)
class PortNeighbor:
    name: str                  # as announced, or the polled device's final name
    port: str                  # remote port, resolved when the device is polled
    protocol: str              # "LLDP", "CDP" or "LLDP+CDP"
    device_id: int | None      # set when the neighbour is a polled device
    endpoint: bool             # a phone, a station: not network infrastructure
    platform: str
    last_seen: int


@dataclass
class PortRow:
    ifindex: int | None        # None: a neighbour whose local port could not be told
    name: str
    descr: str                 # ifAlias, the description a person typed on the device
    status: str                # up | down | disabled | "" (not reported)
    speed_mbps: int | None
    vlan: int | None           # PVID
    lag: str                   # name of the aggregate this port belongs to
    role: str                  # access | uplink | ""
    strength: str              # hard | soft, for an uplink
    reason: str
    macs: int
    virtual: bool
    neighbors: list[PortNeighbor] = field(default_factory=list)


def _status(admin: int | None, oper: int | None) -> str:
    if admin == 2:
        return DISABLED
    if oper == 1:
        return UP
    if oper is None:
        return UNKNOWN
    return DOWN


def _merged(neighbors: list) -> list[PortNeighbor]:
    """A neighbour announced by LLDP and by CDP on one port is one neighbour."""
    found: dict[tuple, dict] = {}
    for rn in neighbors:
        key = (rn.remote_device_id, rn.remote_name.casefold(), rn.remote_port.casefold())
        one = found.setdefault(key, {"rn": rn, "protocols": set(), "last": 0})
        one["protocols"].add(rn.obs.protocol.lower())
        one["last"] = max(one["last"], rn.obs.last_seen)
    order = {"lldp": 0, "cdp": 1}
    result = []
    for one in found.values():
        rn = one["rn"]
        protocols = "+".join(p.upper() for p in sorted(one["protocols"],
                                                       key=lambda p: order.get(p, 9)))
        result.append(PortNeighbor(rn.remote_name, rn.remote_port, protocols,
                                   rn.remote_device_id, rn.endpoint, rn.obs.platform,
                                   one["last"]))
    result.sort(key=lambda n: (n.endpoint, n.name.casefold(), n.port.casefold()))
    return result


def device_ports(view: NodeView, repo: Repo, device_id: int) -> list[PortRow]:
    """Every port of a device, then the neighbours whose local port is unknown, last."""
    ctx = view.ctx
    by_port: dict[int | None, list] = {}
    for rn in view.neighbors:
        if rn.obs.device_id == device_id:
            by_port.setdefault(rn.obs.ifindex, []).append(rn)
    names = {r["ifindex"]: r["name"] or r["descr"] or "" for r in repo.conn.execute(
        "SELECT ifindex, name, descr FROM interfaces WHERE device_id = ?", (device_id,))}
    rows = []
    for r in repo.conn.execute("SELECT * FROM interfaces WHERE device_id = ? ORDER BY ifindex",
                               (device_id,)):
        ifindex = r["ifindex"]
        role = ctx.role(device_id, ifindex)
        macs = ctx.mac_count.get((device_id, ifindex), 0)
        lag = r["lag_ifindex"]
        neighbors = _merged(by_port.pop(ifindex, []))
        virtual = r["if_type"] in VIRTUAL_TYPES and not neighbors and not macs
        rows.append(PortRow(
            ifindex, view.port_name(device_id, ifindex), r["alias"] or "",
            _status(r["admin_status"], r["oper_status"]), r["speed_mbps"] or None,
            r["pvid"] or None,
            short_port_name(names.get(lag, "")) if lag and lag != ifindex else "",
            role.role if role.uplink or macs or neighbors else "",
            role.strength if role.uplink else "",
            "; ".join(detail for _code, detail in role.reasons) if role.uplink else "",
            macs, virtual, neighbors))
    rows.sort(key=lambda p: natural_key(p.name))
    for ifindex, group in sorted(by_port.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
        rows.append(PortRow(ifindex, view.port_name(device_id, ifindex) if ifindex is not None
                            else "?", "", UNKNOWN, None, None, "", "", "", "", 0, False,
                            _merged(group)))
    return rows


def natural_key(name: str) -> tuple:
    """``Gi1/0/2`` before ``Gi1/0/10``, and a name that has no number after the rest."""
    parts: list[tuple[int, int, str]] = []
    digits = ""
    text = ""
    for ch in name + "\0":
        if ch.isdigit():
            if text:
                parts.append((1, 0, text.casefold()))
                text = ""
            digits += ch
            continue
        if digits:
            parts.append((0, int(digits), ""))
            digits = ""
        if ch != "\0":
            text += ch
    if text:
        parts.append((1, 0, text.casefold()))
    return tuple(parts)


@dataclass(frozen=True)
class PortTotals:
    ports: int
    up: int
    with_neighbor: int
    uplinks: int


def totals(ports: list[PortRow]) -> PortTotals:
    real = [p for p in ports if p.ifindex is not None and not p.virtual]
    return PortTotals(len(real), sum(1 for p in real if p.status == UP),
                      sum(1 for p in real if p.neighbors),
                      sum(1 for p in real if p.role == "uplink"))


def speed_text(mbps: int | None) -> str:
    if not mbps:
        return ""
    if mbps >= 1000:
        value = mbps / 1000
        return f"{value:g} Gb/s"
    return f"{mbps} Mb/s"

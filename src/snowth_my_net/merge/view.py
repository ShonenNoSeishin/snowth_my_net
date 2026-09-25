"""Node view: merge inputs loaded from the state, resolved nodes, names, vendors, DNS names.

Shared by ``export`` (nodes.csv), ``show nodes``, ``explain`` and the terminal interface, so
that all of them always agree.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field

from snowth_my_net.clock import iso_z
from snowth_my_net.collect.tables.interfaces import short_port_name
from snowth_my_net.config.effective import settings_for
from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.enrich.oui import OuiDatabase, load_database
from snowth_my_net.export.run import exported_devices
from snowth_my_net.merge.nodes import (
    DAY,
    ArpObs,
    DeviceInfo,
    FdbObs,
    MergeContext,
    MergeInputs,
    Node,
    PortInfo,
    Sighting,
    resolve_mac,
)
from snowth_my_net.merge.topology import (
    DeviceIndex,
    DeviceKeys,
    Link,
    NeighborObs,
    ResolvedNeighbor,
    build_links,
    resolve_neighbors,
    uplink_reason,
)
from snowth_my_net.snmp.target import split_host_port
from snowth_my_net.snmp.values import normalize_mac
from snowth_my_net.state.repo import Repo

_OUI_CACHE: dict[tuple[str, str], OuiDatabase] = {}


def oui_database(loaded: LoadedConfig) -> OuiDatabase:
    explicit = loaded.cfg.oui.file
    state_copy = loaded.paths.oui_file
    stamp = str(state_copy.stat().st_mtime_ns) if state_copy.exists() else ""
    key = (explicit or str(state_copy), stamp)
    if key not in _OUI_CACHE:
        from pathlib import Path

        _OUI_CACHE.clear()
        _OUI_CACHE[key] = load_database(state_copy, Path(explicit) if explicit else None)
    return _OUI_CACHE[key]


def load_inputs(loaded: LoadedConfig, repo: Repo, now: int) -> tuple[MergeInputs, dict[int, str]]:
    cfg = loaded.cfg
    devices, names = exported_devices(loaded, repo, now)
    manual = repo.manual_settings()
    infos = {}
    for d in devices:
        s = settings_for(cfg, split_host_port(d["mgmt_address"])[0], manual)
        infos[d["id"]] = DeviceInfo(names[d["id"]], tuple(s.uplinks), tuple(s.access_ports),
                                    s.uplink_mac_threshold)
    conn = repo.conn
    ports = {(r["device_id"], r["ifindex"]): PortInfo(r["name"] or "", r["descr"] or "",
                                                      r["if_type"], r["lag_ifindex"], r["pvid"])
             for r in conn.execute("SELECT device_id, ifindex, name, descr, if_type, "
                                   "lag_ifindex, pvid FROM interfaces")}
    horizon = now - cfg.nodes.retention_days * DAY
    fdb = [FdbObs(r["mac"], r["device_id"], r["ifindex"], r["vlan"], r["vlan_source"] or "",
                  r["first_seen"], r["last_seen"], r["last_run_id"] or 0)
           for r in conn.execute("SELECT * FROM fdb_obs WHERE last_seen >= ?", (horizon,))]
    arp = [ArpObs(r["mac"], r["address"], r["family"], r["device_id"], r["source_table"] or "",
                  r["first_seen"], r["last_seen"])
           for r in conn.execute("SELECT * FROM arp_obs WHERE last_seen >= ?", (horizon,))]
    device_macs = {r["mac"]: r["device_id"]
                   for r in conn.execute("SELECT mac, device_id FROM device_macs")}
    inputs = MergeInputs(infos, ports, fdb, arp, device_macs)
    return inputs, names


ACTIVE_NEIGHBORS = """
SELECT n.* FROM neighbors n WHERE n.last_run_id = COALESCE(
  (SELECT MAX(s.run_id) FROM collect_status s WHERE s.device_id = n.device_id
     AND s.function = n.protocol AND s.status IN ('ok', 'absent', 'partial')),
  (SELECT MAX(m.last_run_id) FROM neighbors m WHERE m.device_id = n.device_id
     AND m.protocol = n.protocol))
"""


def load_topology(loaded: LoadedConfig, repo: Repo, inputs: MergeInputs, names: dict[int, str],
                  port_name) -> tuple[list[ResolvedNeighbor], list[Link]]:
    """Resolve the current neighbours, feed the neighbour-based port roles, build links."""
    conn = repo.conn
    keys: dict[int, DeviceKeys] = {}
    fdb_devices = {o.device_id for o in inputs.fdb}
    for row in conn.execute("SELECT id, sys_name FROM devices"):
        if row["id"] in names:
            keys[row["id"]] = DeviceKeys(row["id"], names[row["id"]], row["sys_name"] or "",
                                         has_fdb=row["id"] in fdb_devices)
    for row in conn.execute("SELECT device_id, address FROM device_addresses"):
        if row["device_id"] in keys:
            keys[row["device_id"]].addresses.add(row["address"])
    for mac, device_id in inputs.device_macs.items():
        if device_id in keys:
            keys[device_id].macs.add(mac)
    phys = {(r["device_id"], r["ifindex"]): r["phys_mac"] for r in conn.execute(
        "SELECT device_id, ifindex, phys_mac FROM interfaces WHERE phys_mac IS NOT NULL")}
    index = DeviceIndex(keys, inputs.ports, phys)
    observations = [
        NeighborObs(r["device_id"], r["ifindex"], r["protocol"], r["remote_key"],
                    r["remote_chassis_id"] or "", r["remote_sys_name"] or "",
                    r["remote_port_id"] or "", r["remote_port_desc"] or "",
                    tuple(a for a in (r["remote_mgmt_address"] or "").split(",") if a),
                    frozenset(c for c in (r["remote_caps"] or "").split(",") if c),
                    r["remote_platform"] or "", r["first_seen"], r["last_seen"])
        for r in conn.execute(ACTIVE_NEIGHBORS) if r["device_id"] in keys]
    resolved = resolve_neighbors(observations, index, port_name)
    for rn in resolved:
        if rn.obs.ifindex is None:
            continue
        reason = uplink_reason(rn, index, loaded.cfg.nodes.ap_ports_are_access)
        if reason:
            inputs.neighbor_reasons.setdefault((rn.obs.device_id, rn.obs.ifindex),
                                               []).append(reason)
    return resolved, build_links(resolved, names, port_name)


@dataclass
class NodeView:
    loaded: LoadedConfig
    ctx: MergeContext
    names: dict[int, str]
    oui: OuiDatabase
    dns: dict[str, str] = field(default_factory=dict)       # ip -> name (cache)
    given: dict[str, dict[str, str]] = field(default_factory=dict)   # mac -> what was typed
    neighbors: list[ResolvedNeighbor] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    _nodes: list[Node] | None = None

    @property
    def nodes(self) -> list[Node]:
        if self._nodes is None:
            self._nodes = [n for mac in self.ctx.all_macs()
                           if (n := resolve_mac(self.ctx, mac)).excluded is None]
        return self._nodes

    def given_name(self, mac: str) -> str:
        """The name someone gave this MAC, or nothing. It outlives every collect."""
        return self.given.get(mac, {}).get("name", "")

    def given_description(self, mac: str) -> str:
        return self.given.get(mac, {}).get("description", "")

    def vendor(self, node: Node) -> str:
        return "" if node.random_mac else self.oui.lookup(node.mac,
                                                          self.loaded.cfg.oui.clean_names)

    def device_name(self, device_id: int) -> str:
        return self.names.get(device_id, f"#{device_id}")

    @staticmethod
    def port_name_of(inputs: MergeInputs):
        def port_name(device_id: int, ifindex: int | None) -> str:
            port = inputs.ports.get((device_id, ifindex)) if ifindex is not None else None
            if port is None:
                return "" if ifindex is None else str(ifindex)
            return short_port_name(port.name or port.descr) or str(ifindex)

        return port_name

    def port_name(self, device_id: int, ifindex: int) -> str:
        return self.port_name_of(self.ctx.inputs)(device_id, ifindex)

    def link_rows(self) -> list[list[str]]:
        include = self.loaded.cfg.export.links.include_endpoints
        return [[lk.a_device, lk.a_port, lk.b_device, lk.b_port, lk.protocol,
                 iso_z(lk.last_seen)] for lk in self.links if include or not lk.endpoint]

    def dns_name(self, ip: str) -> str:
        name = self.dns.get(ip, "")
        if name and self.loaded.cfg.dns.strip_domain:
            name = name.split(".", 1)[0]
        return name

    def rows(self) -> list[list[str]]:
        """nodes.csv rows, most recent first."""
        cfg = self.loaded.cfg.nodes
        rows = []
        for node in self.nodes:
            vendor = self.vendor(node)
            ip = node.current_ip.ip if node.current_ip else ""
            dns = self.dns_name(ip) if ip else ""
            positions = node.positions if cfg.positions == "all" else node.positions[:1]
            for p in positions:
                rows.append([node.mac, vendor, ip, dns, self.device_name(p.device_id),
                             self.port_name(p.device_id, p.ifindex), str(p.vlan or ""),
                             iso_z(p.last_seen)])
            if not positions and cfg.include_unlocated:
                rows.append([node.mac, vendor, ip, dns, "", "", "", iso_z(node.last_seen)])
        rows.sort(key=lambda r: (r[7], r[0], r[4], r[5]))
        rows.sort(key=lambda r: r[7], reverse=True)
        given = self.loaded.cfg.export.nodes
        if given.include_name or given.include_description:
            return [[*([self.given_name(row[0])] if given.include_name else []),
                     *([self.given_description(row[0])] if given.include_description else []),
                     *row] for row in rows]
        return rows

    def find(self, query: str) -> list[Node]:
        """Nodes (excluded ones included, for explanation) matching a MAC or an IP address."""
        mac = normalize_mac(query)
        if mac is not None:
            if mac in self.ctx.fdb_by_mac or mac in self.ctx.arp_by_mac:
                return [resolve_mac(self.ctx, mac)]
            return []
        try:
            ip = str(ipaddress.ip_address(query.strip()))
        except ValueError:
            return []
        macs = {(a.last_seen, a.mac) for obs in self.ctx.arp_by_mac.values()
                for a in obs if a.ip == ip}
        return [resolve_mac(self.ctx, m) for _seen, m in sorted(macs, reverse=True)]

    def sighting_label(self, s: Sighting) -> str:
        return f"{self.device_name(s.device_id)} {self.port_name(s.device_id, s.ifindex)}"


def build_view(loaded: LoadedConfig, repo: Repo, now: int) -> NodeView:
    from snowth_my_net.names import store_for

    inputs, names = load_inputs(loaded, repo, now)
    view = NodeView(loaded, None, names, oui_database(loaded), repo.dns_names(now),
                    given=store_for(loaded.paths).read())
    view.neighbors, view.links = load_topology(loaded, repo, inputs, names, view.port_name_of(
        inputs))
    view.ctx = MergeContext(inputs, loaded.cfg.nodes, now)
    return view

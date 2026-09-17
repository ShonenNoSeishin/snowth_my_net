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
    return MergeInputs(infos, ports, fdb, arp, device_macs), names


@dataclass
class NodeView:
    loaded: LoadedConfig
    ctx: MergeContext
    names: dict[int, str]
    oui: OuiDatabase
    dns: dict[str, str] = field(default_factory=dict)       # ip -> name (cache)
    _nodes: list[Node] | None = None

    @property
    def nodes(self) -> list[Node]:
        if self._nodes is None:
            self._nodes = [n for mac in self.ctx.all_macs()
                           if (n := resolve_mac(self.ctx, mac)).excluded is None]
        return self._nodes

    def vendor(self, node: Node) -> str:
        return "" if node.random_mac else self.oui.lookup(node.mac,
                                                          self.loaded.cfg.oui.clean_names)

    def device_name(self, device_id: int) -> str:
        return self.names.get(device_id, f"#{device_id}")

    def port_name(self, device_id: int, ifindex: int) -> str:
        port = self.ctx.inputs.ports.get((device_id, ifindex))
        if port is None:
            return str(ifindex)
        return short_port_name(port.name or port.descr) or str(ifindex)

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
    inputs, names = load_inputs(loaded, repo, now)
    ctx = MergeContext(inputs, loaded.cfg.nodes, now)
    return NodeView(loaded, ctx, names, oui_database(loaded), repo.dns_names(now))

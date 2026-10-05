"""Node view: merge inputs loaded from the state, resolved nodes, names, vendors, DNS names.

Shared by ``export`` (nodes.csv), ``show nodes``, ``explain`` and the terminal interface, so
that all of them always agree.
"""

from __future__ import annotations

import ipaddress
from collections import Counter
from dataclasses import dataclass, field

from snowth_my_net.clock import iso_z
from snowth_my_net.collect.tables.interfaces import short_port_name
from snowth_my_net.config.effective import settings_for
from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.enrich.oui import OuiDatabase, load_database
from snowth_my_net.export.run import exported_devices
from snowth_my_net.merge.nodes import (
    DAY,
    SOFT,
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
    HARD,
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
    full = repo.last_successful_collect()
    inputs = MergeInputs(infos, ports, fdb, arp, device_macs,
                         last_full_walk=full["started_at"] if full else 0)
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
    inherit_lag_reasons(inputs, port_name)
    return resolved, build_links(resolved, names, port_name)


def inherit_lag_reasons(inputs: MergeInputs, port_name) -> None:
    """A trunk is an uplink when one of its members has an infrastructure neighbour.

    LLDP and CDP are seen on the physical port, while the MAC table reports the aggregate
    (``Trk1``, ``Po1``, ``lag3``). Without this, a trunk between two switches is recognised
    only by the "too many MACs" fallback — so a quiet trunk passes for an access port and the
    MACs of the whole switch behind it are placed on it.
    """
    for (device_id, ifindex), reasons in list(inputs.neighbor_reasons.items()):
        port = inputs.ports.get((device_id, ifindex))
        lag = port.lag_ifindex if port else None
        if not lag or lag == ifindex:
            continue
        member = port_name(device_id, ifindex) or str(ifindex)
        inherited = [(code, f"{detail} on {member}, a member of this trunk", strength)
                     for code, detail, strength in reasons]
        inputs.neighbor_reasons.setdefault((device_id, lag), []).extend(inherited)


@dataclass
class NodeView:
    loaded: LoadedConfig
    ctx: MergeContext
    names: dict[int, str]
    oui: OuiDatabase
    dns: dict[str, str] = field(default_factory=dict)       # ip -> name (cache)
    given: dict[str, dict[str, str]] = field(default_factory=dict)   # mac -> what was typed
    probed: dict[str, tuple[str, str]] = field(default_factory=dict)   # ip -> (name, source)
    claimed: dict[str, str] = field(default_factory=dict)   # ip -> MAC the host stated
    neighbors: list[ResolvedNeighbor] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    _nodes: list[Node] | None = None

    @property
    def nodes(self) -> list[Node]:
        if self._nodes is None:
            self._nodes = [n for mac in self.ctx.all_macs()
                           if (n := resolve_mac(self.ctx, mac)).excluded is None]
        return self._nodes

    def left_out(self) -> list[dict]:
        """Every MAC the node list leaves out, why, and what else is known about its family.

        The counterpart of the exclusions: a reader who wonders where a MAC went, or what the
        hundreds of addresses a neighbour cache holds actually are, gets an answer here instead
        of a query to write by hand. ``siblings`` is how many MACs of the same first three
        octets — the same maker, usually the same box — *are* in a MAC table: that is what tells
        a second interface of known equipment from a device nobody ever saw on a port.
        """
        on_a_port = set(self.ctx.fdb_by_mac)
        families = Counter(mac[:8] for mac in on_a_port)
        rows = []
        for mac in self.ctx.all_macs():
            node = resolve_mac(self.ctx, mac)
            if node.excluded is None:
                continue
            rows.append({
                "mac": mac, "reason": node.excluded.code, "detail": node.excluded.detail,
                "vendor": self.vendor(node),
                "addresses": [ip.ip for ip in node.ips],
                "seen_by": sorted({self.device_name(device) for ip in node.ips
                                   for device, _table, _when in ip.sources}),
                "last_seen": node.last_seen,
                "siblings": families.get(mac[:8], 0),
            })
        rows.sort(key=lambda row: (row["reason"], row["mac"]))
        return rows

    def load_probes(self, repo: Repo, now: int) -> None:
        self.probed = repo.probe_names(now)
        self.claimed = repo.probe_claims(now)

    def given_name(self, mac: str) -> str:
        """The name someone gave this MAC, or nothing. It outlives every collect."""
        return self.given.get(mac, {}).get("name", "")

    def probed_name(self, node: Node) -> str:
        """The name the host stated about itself, when it is that host that stated it.

        NetBIOS answers with the adapter's own address: when it contradicts the MAC of the node
        being named, the answer came from something else — a relay, an address that changed
        hands — and attributing the name here would be exactly the false positive to refuse.
        """
        if not node.current_ip:
            return ""
        found = self.probed.get(node.current_ip.ip)
        if not found:
            return ""
        claimed = self.claimed.get(node.current_ip.ip, "")
        if claimed and claimed != node.mac:
            return ""
        return found[0]

    def hostname(self, node: Node) -> tuple[str, str]:
        """``(name, source)``: by hand, else DNS, else what the host says about itself.

        The order is the order of trust: a name someone wrote down beats a zone, which beats
        what a machine says about itself.
        """
        manual = self.given_name(node.mac)
        if manual:
            return manual, "manual"
        resolved = self.dns_name(node.current_ip.ip) if node.current_ip else ""
        if resolved:
            return resolved, "dns"
        probed = self.probed_name(node)
        return (probed, self.probed[node.current_ip.ip][1]) if probed else ("", "")

    def hostnames_disagree(self, node: Node) -> bool:
        """A name written by hand and a zone that says another thing: one of them is wrong, and
        which one is not for this tool to decide. The domain and the case are ignored, so
        ``poste-julie`` and ``poste-julie.example.net`` agree."""
        manual = self.given_name(node.mac)
        resolved = self.dns_name(node.current_ip.ip) if node.current_ip else ""
        if not manual or not resolved:
            return False
        return manual.split(".")[0].casefold() != resolved.split(".")[0].casefold()

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
        merge = self.loaded.cfg.export.nodes.merge_hostnames
        rows = []
        for node in self.nodes:
            vendor = self.vendor(node)
            ip = node.current_ip.ip if node.current_ip else ""
            dns = self.hostname(node)[0] if merge else (self.dns_name(ip) if ip else "")
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

    def uplink_ports(self) -> list[dict]:
        """Every port treated as an uplink, why, and what it costs.

        ``orphans`` is the number of MACs that have no position *because* of this port — seen
        there and nowhere else. A port held as an uplink by the MAC count alone and with many
        orphans is the one to look at: a Wi-Fi access point or a hypervisor that announces no
        LLDP looks exactly like an uplink to the count.
        """
        orphans: Counter = Counter()
        for node in self.nodes:
            if node.positions or not node.sightings:
                continue
            for sighting in {(s.device_id, s.ifindex) for s in node.sightings}:
                orphans[sighting] += 1
        rows = []
        for key in sorted(self.ctx.mac_count):
            role = self.ctx.role(*key)
            if not role.uplink:
                continue
            rows.append({
                "device": self.device_name(key[0]), "port": self.port_name(*key),
                "macs": self.ctx.mac_count[key],
                "evidence": "proof" if role.strength == HARD else "guess",
                "why": "; ".join(detail for _code, detail in role.reasons),
                "codes": [code for code, _detail in role.reasons],
                "orphans": orphans.get(key, 0),
            })
        rows.sort(key=lambda row: (row["evidence"] != "guess", -row["orphans"], -row["macs"]))
        return rows

    def behind_soft_uplinks(self) -> int:
        """MACs with no position that ``nodes.uplink_fallback`` would place.

        Every one of them was seen only behind a port held as an uplink by weak evidence — the
        MAC count, or a bridge nobody polls — which is exactly the shape of an unmanaged switch.
        The fallback puts them on that port, as a tool that reports the learning port would;
        this counts them first, so the choice is made on a number rather than on a guess.
        """
        return sum(1 for node in self.nodes
                   if not node.positions and node.sightings
                   and all(s.role.strength == SOFT for s in node.sightings))

    def sighting_label(self, s: Sighting) -> str:
        return f"{self.device_name(s.device_id)} {self.port_name(s.device_id, s.ifindex)}"


def build_view(loaded: LoadedConfig, repo: Repo, now: int) -> NodeView:
    from snowth_my_net.names import store_for

    inputs, names = load_inputs(loaded, repo, now)
    view = NodeView(loaded, None, names, oui_database(loaded), repo.dns_names(now),
                    given=store_for(loaded.paths).read(),
                    probed=repo.probe_names(now), claimed=repo.probe_claims(now))
    view.neighbors, view.links = load_topology(loaded, repo, inputs, names, view.port_name_of(
        inputs))
    view.ctx = MergeContext(inputs, loaded.cfg.nodes, now)
    return view

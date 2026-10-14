"""Report datasets: named tables built from the state, with a documented field catalog.

Every dataset reads the same views as the exports (devices within the retention window and their
exported names, nodes as in nodes.csv, links as in links.csv), so a report never disagrees with
the standard files. Nothing here writes to the state: DNS names come from the cache only.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from snowth_my_net.collect.tables.interfaces import short_port_name
from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.snmp.target import split_host_port
from snowth_my_net.state.repo import Repo

FieldType = Literal["text", "integer", "time", "bool"]
IF_STATUS = {1: "up", 2: "down", 3: "testing", 4: "unknown", 5: "dormant", 6: "notPresent",
             7: "lowerLayerDown"}


@dataclass(frozen=True)
class Field:
    name: str
    type: FieldType = "text"
    description: str = ""
    default: bool = True            # part of the columns shown when a report selects none


@dataclass
class Dataset:
    name: str
    description: str
    fields: list[Field]
    build: Callable[[ReportContext], list[dict[str, Any]]]

    def field(self, name: str) -> Field | None:
        return next((f for f in self.fields if f.name == name), None)

    @property
    def default_columns(self) -> list[str]:
        return [f.name for f in self.fields if f.default]


class DatasetError(ValueError):
    pass


@dataclass
class ReportContext:
    """Lazily built, shared state views for one report run (or one TUI preview)."""

    loaded: LoadedConfig
    repo: Repo
    now: int
    collectors: list = field(default_factory=list)          # LoadedCollector, files + TUI
    extra: list = field(default_factory=list)               # Datasets from Python extensions
    _devices: tuple | None = None
    _view: Any = None
    _rows: dict = field(default_factory=dict)

    def datasets(self) -> dict[str, Dataset]:
        return all_datasets(self.collectors, self.extra)

    def dataset_rows(self, name: str) -> list[dict]:
        """Rows of any dataset by name (for Python datasets that join other data)."""
        return self.rows(get_dataset(name, self.collectors, self.extra))

    @property
    def config_dir(self):
        return self.loaded.paths.config_file.resolve().parent

    def rows(self, dataset: Dataset) -> list[dict]:
        """Rows of a dataset, built once per context (filters never modify them)."""
        if dataset.name not in self._rows:
            self._rows[dataset.name] = dataset.build(self)
        return self._rows[dataset.name]

    def devices(self) -> tuple[list[dict], dict[int, str]]:
        if self._devices is None:
            from snowth_my_net.export.run import exported_devices

            self._devices = exported_devices(self.loaded, self.repo, self.now)
        return self._devices

    def view(self):
        if self._view is None:
            from snowth_my_net.merge.view import build_view

            self._view = build_view(self.loaded, self.repo, self.now)
        return self._view

    def device_columns(self) -> dict[int, tuple[str, str]]:
        """device id -> (exported name, management IP) for devices within retention."""
        devices, names = self.devices()
        return {d["id"]: (names[d["id"]], split_host_port(d["mgmt_address"])[0])
                for d in devices}

    def port_names(self) -> dict[tuple[int, int], str]:
        return {(r["device_id"], r["ifindex"]): short_port_name(r["name"] or r["descr"] or "")
                or str(r["ifindex"]) for r in self.repo.conn.execute(
                    "SELECT device_id, ifindex, name, descr FROM interfaces")}


def _f(name: str, type_: FieldType = "text", description: str = "", default: bool = True) -> Field:
    return Field(name, type_, description, default)


# --------------------------------------------------------------------------- builders


def _devices(ctx: ReportContext) -> list[dict]:
    devices, names = ctx.devices()
    counts = {r[0]: (r[1], r[2]) for r in ctx.repo.conn.execute(
        "SELECT device_id, COUNT(*), SUM(oper_status = 1) FROM interfaces GROUP BY device_id")}
    rows = []
    for d in devices:
        total, up = counts.get(d["id"], (0, 0))
        rows.append({
            "name": names[d["id"]], "ip": split_host_port(d["mgmt_address"])[0],
            "mgmt_address": d["mgmt_address"], "sys_name": d["sys_name"] or "",
            "description": d["sys_descr"] or "", "location": d["sys_location"] or "",
            "contact": d["sys_contact"] or "", "vendor": d["vendor"] or "",
            "model": d["model"] or "", "serial": d["serial"] or "", "os": d["os_name"] or "",
            "os_version": d["os_version"] or "", "mac": d["base_mac"] or "",
            "device_type": d["device_type"] or "", "type_rule": d["type_rule"] or "",
            "type_reason": d["type_reason"] or "", "detected_type": d["detected_type"],
            "sys_object_id": d["sys_object_id"] or "", "driver": d["driver"] or "",
            "credential": d["credential"] or "",
            "uptime_days": (d["sys_uptime"] or 0) // 8_640_000 if d["sys_uptime"] else None,
            "interfaces": total, "interfaces_up": up or 0,
            "first_seen": d["first_seen"], "last_seen": d["last_seen"],
            "last_collect": d["last_collect_at"], "last_collect_status":
                d["last_collect_status"] or "",
        })
    from snowth_my_net.export.csvout import natural_key

    rows.sort(key=lambda r: natural_key(r["name"]))
    return rows


def _interfaces(ctx: ReportContext) -> list[dict]:
    devices = ctx.device_columns()
    view = ctx.view()
    merge = view.ctx
    neighbors: dict[tuple[int, int], set[str]] = {}
    for rn in view.neighbors:
        if rn.obs.ifindex is not None:
            neighbors.setdefault((rn.obs.device_id, rn.obs.ifindex), set()).add(rn.remote_name)
    rows = []
    for r in ctx.repo.conn.execute("SELECT * FROM interfaces ORDER BY device_id, ifindex"):
        if r["device_id"] not in devices:
            continue
        key = (r["device_id"], r["ifindex"])
        role = merge.role(*key) if r["device_id"] in merge.inputs.devices else None
        name, ip = devices[r["device_id"]]
        rows.append({
            "device": name, "device_ip": ip, "ifindex": r["ifindex"],
            "port": short_port_name(r["name"] or r["descr"] or "") or str(r["ifindex"]),
            "name": r["name"] or "", "description": r["descr"] or "", "alias": r["alias"] or "",
            "if_type": r["if_type"], "admin_status": IF_STATUS.get(r["admin_status"], ""),
            "oper_status": IF_STATUS.get(r["oper_status"], ""), "speed_mbps": r["speed_mbps"],
            "mac": r["phys_mac"] or "", "pvid": r["pvid"],
            "lag_member": r["lag_ifindex"] is not None,
            "role": role.role if role else "",
            "role_reasons": ", ".join(code for code, _d in role.reasons) if role else "",
            "mac_count": merge.mac_count.get(key, 0),
            "neighbors": ", ".join(sorted(neighbors.get(key, ()))),
            "last_seen": r["last_seen"],
        })
    return rows


def _nodes(ctx: ReportContext) -> list[dict]:
    view = ctx.view()
    include_unlocated = ctx.loaded.cfg.nodes.include_unlocated
    rows = []
    for node in view.nodes:
        vendor = view.vendor(node)
        ip = node.current_ip.ip if node.current_ip else ""
        common = {"mac": node.mac, "vendor": vendor, "ip": ip,
                  "dns_name": view.dns_name(ip) if ip else "", "random_mac": node.random_mac,
                  "ip_count": len(node.ips), "ip_churn": view.ip_churn(node),
                  "position_kind": node.position_kind,
                  "node_first_seen": node.first_seen}
        for rank, p in enumerate(node.positions):
            rows.append({**common, "device": view.device_name(p.device_id),
                         "port": view.port_name(p.device_id, p.ifindex), "vlan": p.vlan or None,
                         "current": rank == 0, "verdict": p.verdict,
                         "mac_count": p.mac_count, "first_seen": p.first_seen,
                         "last_seen": p.last_seen})
        if not node.positions and include_unlocated:
            rows.append({**common, "device": "", "port": "", "vlan": None, "current": True,
                         "verdict": "", "mac_count": None, "first_seen": node.first_seen,
                         "last_seen": node.last_seen})
    return rows


def _ip_history(ctx: ReportContext) -> list[dict]:
    view = ctx.view()
    rows = []
    for node in view.nodes:
        vendor = view.vendor(node)
        for sighting in node.ips:
            rows.append({
                "mac": node.mac, "vendor": vendor, "ip": sighting.ip,
                "family": "ipv6" if sighting.family == 6 else "ipv4",
                "current": node.current_ip is sighting,
                "superseded_by": sighting.superseded_by or "",
                "seen_by": ", ".join(sorted({view.device_name(d) for d, _t, _s
                                             in sighting.sources})),
                "first_seen": sighting.first_seen, "last_seen": sighting.last_seen,
            })
    return rows


def _vlans(ctx: ReportContext) -> list[dict]:
    devices = ctx.device_columns()
    return [{"device": devices[r["device_id"]][0], "device_ip": devices[r["device_id"]][1],
             "vlan": r["vlan_id"], "name": r["name"] or "", "last_seen": r["last_seen"]}
            for r in ctx.repo.conn.execute("SELECT * FROM vlans ORDER BY device_id, vlan_id")
            if r["device_id"] in devices]


def _links(ctx: ReportContext) -> list[dict]:
    return [{"local_device": lk.a_device, "local_port": lk.a_port, "remote_device": lk.b_device,
             "remote_port": lk.b_port, "protocol": lk.protocol, "endpoint": lk.endpoint,
             "managed_remote": lk.b_device_id is not None, "first_seen": lk.first_seen,
             "last_seen": lk.last_seen} for lk in ctx.view().links]


def _neighbors(ctx: ReportContext) -> list[dict]:
    view = ctx.view()
    return [{"device": view.device_name(rn.obs.device_id),
             "port": view.port_name(rn.obs.device_id, rn.obs.ifindex)
             if rn.obs.ifindex is not None else "",
             "protocol": rn.obs.protocol.upper(), "remote_name": rn.remote_name,
             "remote_sys_name": rn.obs.sys_name, "remote_port": rn.remote_port,
             "remote_port_description": rn.obs.port_desc,
             "remote_address": ", ".join(rn.obs.mgmt_addresses),
             "remote_chassis_id": rn.obs.chassis_id, "remote_platform": rn.obs.platform,
             "remote_caps": ", ".join(sorted(rn.obs.caps)), "managed": rn.remote_device_id
             is not None, "endpoint": rn.endpoint, "first_seen": rn.obs.first_seen,
             "last_seen": rn.obs.last_seen} for rn in view.neighbors]


def _runs(ctx: ReportContext) -> list[dict]:
    rows = []
    for r in ctx.repo.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 5000"):
        stats = json.loads(r["stats"]) if r["stats"] else {}
        rows.append({
            "id": r["id"], "command": r["command"], "status": r["status"] or "running",
            "started": r["started_at"], "finished": r["finished_at"],
            "duration_s": r["finished_at"] - r["started_at"] if r["finished_at"] else None,
            "devices": stats.get("devices"), "reachable": stats.get("reachable"),
            "failing": stats.get("failing"),
            "stats": json.dumps(stats, sort_keys=True) if stats else "",
        })
    return rows


CURRENT_CUSTOM = """
SELECT v.*, r.status AS run_status, r.run_at FROM custom_values v
JOIN custom_runs r ON r.device_id = v.device_id AND r.collector = v.collector
 AND r.run_at = v.last_seen
{where} ORDER BY v.device_id, v.collector, v.idx, v.column
"""


def _custom(ctx: ReportContext) -> list[dict]:
    devices = ctx.device_columns()
    return [{"device": devices[r["device_id"]][0], "device_ip": devices[r["device_id"]][1],
             "collector": r["collector"], "index": r["idx"], "column": r["column"],
             "value": r["value"] or "", "raw": r["raw"] or "", "status": r["run_status"],
             "collected": r["run_at"]}
            for r in ctx.repo.conn.execute(CURRENT_CUSTOM.format(where=""))
            if r["device_id"] in devices]


def _custom_named(name: str, columns: list[str], port_index: bool):
    def build(ctx: ReportContext) -> list[dict]:
        devices = ctx.device_columns()
        ports = ctx.port_names() if port_index else {}
        grouped: dict[tuple[int, str], dict] = {}
        for r in ctx.repo.conn.execute(CURRENT_CUSTOM.format(where="WHERE v.collector = ?"),
                                       (name,)):
            if r["device_id"] not in devices:
                continue
            key = (r["device_id"], r["idx"])
            if key not in grouped:
                device, ip = devices[r["device_id"]]
                grouped[key] = {"device": device, "device_ip": ip, "index": r["idx"],
                                **dict.fromkeys(columns, ""), "status": r["run_status"],
                                "collected": r["run_at"]}
                if port_index:
                    idx = int(r["idx"]) if r["idx"].isdigit() else None
                    grouped[key]["port"] = ports.get((r["device_id"], idx), r["idx"])
            if r["column"] in columns:
                grouped[key][r["column"]] = r["value"] or ""
        return list(grouped.values())

    return build


# --------------------------------------------------------------------------- catalog


STATIC: dict[str, Dataset] = {d.name: d for d in (
    Dataset("devices", "Managed devices within the retention window (as devices.csv)", [
        _f("name", description="exported device name (the join key of nodes.csv and links.csv)"),
        _f("ip", description="management IP address"),
        _f("mgmt_address", description="address actually polled (ip or [ip]:port)", default=False),
        _f("sys_name", description="sysName as announced", default=False),
        _f("description", description="sysDescr", default=False),
        _f("location", description="sysLocation"),
        _f("contact", description="sysContact", default=False),
        _f("vendor"), _f("model"), _f("serial"), _f("os"), _f("os_version"),
        _f("mac", description="base MAC address", default=False),
        _f("device_type", description="effective type (manual, configured or detected; "
                                      "empty without sure evidence)"),
        _f("type_rule", description="rule that decided the type", default=False),
        _f("type_reason", description="evidence of the type", default=False),
        _f("detected_type", description="type detected before manual settings", default=False),
        _f("sys_object_id", default=False), _f("driver", default=False),
        _f("credential", description="name of the working credential (never the secret)",
           default=False),
        _f("uptime_days", "integer", "sysUpTime in whole days", default=False),
        _f("interfaces", "integer", "number of interfaces", default=False),
        _f("interfaces_up", "integer", "interfaces with ifOperStatus up", default=False),
        _f("first_seen", "time", default=False), _f("last_seen", "time"),
        _f("last_collect", "time", default=False),
        _f("last_collect_status", description="ok, partial or failed", default=False),
    ], _devices),
    Dataset("interfaces", "Interfaces of the managed devices", [
        _f("device"), _f("device_ip", default=False),
        _f("ifindex", "integer", default=False),
        _f("port", description="short port name (Gi1/0/5)"),
        _f("name", description="ifName", default=False),
        _f("description", description="ifDescr", default=False),
        _f("alias", description="ifAlias (the description set by administrators)"),
        _f("if_type", "integer", "IANA ifType number", default=False),
        _f("admin_status", description="up, down…"), _f("oper_status", description="up, down…"),
        _f("speed_mbps", "integer"), _f("mac", default=False),
        _f("pvid", "integer", "untagged VLAN"),
        _f("lag_member", "bool", "member of an aggregate", default=False),
        _f("role", description="access or uplink (as used for nodes.csv)"),
        _f("role_reasons", description="why the port has this role", default=False),
        _f("mac_count", "integer", "MAC addresses learned at the last walk"),
        _f("neighbors", description="LLDP/CDP neighbours on the port"),
        _f("last_seen", "time", default=False),
    ], _interfaces),
    Dataset("nodes", "End nodes and their positions (as nodes.csv, one row per position)", [
        _f("mac"), _f("vendor"), _f("ip", description="current IP address"),
        _f("dns_name", description="PTR name from the cache"),
        _f("device", description="switch or access point"), _f("port"),
        _f("vlan", "integer"),
        _f("current", "bool", "most recent position of the node", default=False),
        _f("verdict", description="position or fallback", default=False),
        _f("position_kind", description="access, behind_uplink or none", default=False),
        _f("mac_count", "integer", "MAC addresses on the port", default=False),
        _f("random_mac", "bool", "locally administered MAC (phone private MAC, container, VM)",
           default=False),
        _f("ip_count", "integer", "IP addresses seen for this MAC", default=False),
        _f("ip_churn", "integer", "IPv4 addresses seen lately when that is often, else 0",
           default=False),
        _f("first_seen", "time", "first seen at this position", default=False),
        _f("last_seen", "time"),
        _f("node_first_seen", "time", "first seen anywhere", default=False),
    ], _nodes),
    Dataset("ip_history", "Every IP address seen for each node (ARP and neighbour caches)", [
        _f("mac"), _f("vendor", default=False), _f("ip"), _f("family", default=False),
        _f("current", "bool", "elected current IP"),
        _f("superseded_by", description="MAC that claimed this IP later"),
        _f("seen_by", description="devices whose caches held the entry", default=False),
        _f("first_seen", "time"), _f("last_seen", "time"),
    ], _ip_history),
    Dataset("vlans", "VLANs declared on the managed devices", [
        _f("device"), _f("device_ip", default=False), _f("vlan", "integer"), _f("name"),
        _f("last_seen", "time", default=False),
    ], _vlans),
    Dataset("links", "Links between devices (as links.csv, endpoints included)", [
        _f("local_device"), _f("local_port"), _f("remote_device"), _f("remote_port"),
        _f("protocol"),
        _f("endpoint", "bool", "remote is a phone, station… (links.include_endpoints)"),
        _f("managed_remote", "bool", "remote is a managed device", default=False),
        _f("first_seen", "time", default=False), _f("last_seen", "time"),
    ], _links),
    Dataset("neighbors", "Current LLDP/CDP neighbours as announced", [
        _f("device"), _f("port"), _f("protocol"), _f("remote_name"),
        _f("remote_sys_name", default=False), _f("remote_port"),
        _f("remote_port_description", default=False), _f("remote_address"),
        _f("remote_chassis_id", default=False), _f("remote_platform"),
        _f("remote_caps", description="announced capabilities", default=False),
        _f("managed", "bool", "resolved to a managed device"),
        _f("endpoint", "bool", "phone, station or other non-infrastructure", default=False),
        _f("first_seen", "time", default=False), _f("last_seen", "time"),
    ], _neighbors),
    Dataset("runs", "Recent runs (collect, export, push…)", [
        _f("id", "integer"), _f("command"), _f("status"), _f("started", "time"),
        _f("finished", "time", default=False), _f("duration_s", "integer"),
        _f("devices", "integer", "devices polled (collect)", default=False),
        _f("reachable", "integer", "devices that answered (collect)", default=False),
        _f("failing", "integer", "devices in failure, tolerated ones excluded", default=False),
        _f("stats", description="statistics as JSON", default=False),
    ], _runs),
    Dataset("custom", "Current values of every custom collector (one row per value)", [
        _f("device"), _f("device_ip", default=False), _f("collector"),
        _f("index", description="table index ('' for get: collectors)"), _f("column"),
        _f("value"), _f("raw", description="raw value (hex or number)", default=False),
        _f("status", description="status of the last pass", default=False),
        _f("collected", "time", default=False),
    ], _custom),
)}


def custom_dataset(collector) -> Dataset:
    """``custom:<name>``: one row per device (get:) or per table row (walk:), one column per
    collected value."""
    cfg = collector.cfg
    columns = list(cfg.value_specs())
    port_index = cfg.walk is not None and cfg.walk.index == "port"
    fields = [_f("device"), _f("device_ip", default=False)]
    if cfg.walk is not None:
        fields.append(_f("index", description="table index", default=not port_index))
        if port_index:
            fields.append(_f("port", description="interface of the ifIndex"))
    for name in columns:
        spec = cfg.value_specs()[name]
        fields.append(_f(name, description=f"from Python ({getattr(cfg, 'extension', '')})"
                         if cfg.kind == "python" else f"{spec.oid} ({spec.type})"))
    fields += [_f("status", description="status of the last pass", default=False),
               _f("collected", "time", default=False)]
    return Dataset(f"custom:{cfg.name}", cfg.description or f"values of collector {cfg.name}",
                   fields, _custom_named(cfg.name, columns, port_index))


def all_datasets(collectors: list, extra: list = ()) -> dict[str, Dataset]:
    result = dict(STATIC)
    for collector in collectors:
        dataset = custom_dataset(collector)
        result[dataset.name] = dataset
    for dataset in extra:
        result[dataset.name] = dataset
    return result


def get_dataset(name: str, collectors: list, extra: list = ()) -> Dataset:
    datasets = all_datasets(collectors, extra)
    if name not in datasets:
        known = ", ".join(datasets)
        raise DatasetError(f"unknown dataset {name!r} (known: {known})")
    return datasets[name]

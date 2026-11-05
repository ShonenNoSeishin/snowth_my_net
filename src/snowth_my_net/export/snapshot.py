"""snapshot.json: everything snowth_my_net knows, with a versioned schema for scripts."""

from __future__ import annotations

import dataclasses
import json

from snowth_my_net import __version__
from snowth_my_net.clock import iso_z
from snowth_my_net.collect.model import FAILURE_STATUSES
from snowth_my_net.merge.explain import node_json
from snowth_my_net.snmp.target import split_host_port

SCHEMA = "snowth_my_net/snapshot/1"


def build_snapshot(loaded, repo, view, devices: list[dict], now: int) -> dict:
    from snowth_my_net.merge.ports import device_ports, totals

    conn = repo.conn
    ids = [d["id"] for d in devices]
    by_device: dict[str, dict[int, list]] = {k: {i: [] for i in ids} for k in (
        "chassis", "addresses", "interfaces", "vlans", "outcomes")}

    def fill(key: str, query: str) -> None:
        for row in conn.execute(query):
            if row["device_id"] in by_device[key]:
                by_device[key][row["device_id"]].append(dict(row))

    fill("chassis", "SELECT * FROM device_chassis ORDER BY device_id, ent_index")
    fill("addresses", "SELECT * FROM device_addresses ORDER BY device_id, address")
    fill("interfaces", "SELECT * FROM interfaces ORDER BY device_id, ifindex")
    fill("vlans", "SELECT * FROM vlans ORDER BY device_id, vlan_id")
    for device_id in ids:
        by_device["outcomes"][device_id] = [dict(r) for r in repo.last_outcomes(device_id)]

    neighbors: dict[int, list[dict]] = {i: [] for i in ids}
    for rn in view.neighbors:
        if rn.obs.device_id in neighbors:
            neighbors[rn.obs.device_id].append({
                "protocol": rn.obs.protocol,
                "local_port": view.port_name(rn.obs.device_id, rn.obs.ifindex)
                if rn.obs.ifindex is not None else None,
                "remote_device": rn.remote_name, "remote_port": rn.remote_port,
                "remote_polled": rn.remote_device_id is not None,
                "capabilities": sorted(rn.obs.caps), "platform": rn.obs.platform or None,
                "management_addresses": list(rn.obs.mgmt_addresses),
                "last_seen": iso_z(rn.obs.last_seen)})

    ctx = view.ctx
    out_devices, errors = [], []
    for d in sorted(devices, key=lambda x: view.names[x["id"]].casefold()):
        name = view.names[d["id"]]
        shown = device_ports(view, repo, d["id"])
        by_ifindex = {p.ifindex: p for p in shown if p.ifindex is not None}
        interfaces = []
        for itf in by_device["interfaces"][d["id"]]:
            role = ctx.role(d["id"], itf["ifindex"]) if d["id"] in ctx.inputs.devices else None
            interfaces.append({
                "ifindex": itf["ifindex"], "name": itf["name"], "descr": itf["descr"],
                "alias": itf["alias"], "type": itf["if_type"], "admin_status": itf["admin_status"],
                "oper_status": itf["oper_status"], "speed_mbps": itf["speed_mbps"],
                "mac": itf["phys_mac"], "pvid": itf["pvid"], "lag_ifindex": itf["lag_ifindex"],
                "role": role.role if role else None,
                "role_reasons": [code for code, _d in role.reasons] if role else [],
                "mac_count": ctx.mac_count.get((d["id"], itf["ifindex"]), 0),
                "status": by_ifindex[itf["ifindex"]].status or None,
                "virtual": by_ifindex[itf["ifindex"]].virtual,
                "lag": by_ifindex[itf["ifindex"]].lag or None})
        functions = {o["function"]: {"status": o["status"], "rows": o["rows"],
                                     "duration_ms": o["duration_ms"], "detail": o["detail"]}
                     for o in by_device["outcomes"][d["id"]]}
        for function, outcome in functions.items():
            if outcome["status"] in FAILURE_STATUSES:
                errors.append({"device": name, "function": function, **outcome})
        out_devices.append({
            "name": name, "ip": split_host_port(d["mgmt_address"])[0],
            "address": d["mgmt_address"], "sys_name": d["sys_name"],
            "description": d["sys_descr"], "location": d["sys_location"],
            "contact": d["sys_contact"], "object_id": d["sys_object_id"],
            "vendor": d["vendor"], "model": d["model"], "serial": d["serial"],
            "os": d["os_name"], "os_version": d["os_version"], "base_mac": d["base_mac"],
            "device_type": d["device_type"], "type_rule": d["type_rule"],
            "type_reason": d["type_reason"], "detected_type": d.get("detected_type"),
            "credential": d["credential"], "driver": d["driver"],
            "first_seen": iso_z(d["first_seen"]),
            "last_seen": iso_z(d["last_seen"]), "last_collect_status": d["last_collect_status"],
            "chassis": [{k: c[k] for k in ("model", "serial", "sw_rev", "descr")}
                        for c in by_device["chassis"][d["id"]]],
            "addresses": [{"address": a["address"], "ifindex": a["ifindex"],
                           "prefix_len": a["prefix_len"]} for a in by_device["addresses"][d["id"]]],
            "interfaces": interfaces,
            "ports": dataclasses.asdict(totals(shown)),
            "vlans": [{"id": v["vlan_id"], "name": v["name"]} for v in by_device["vlans"][d["id"]]],
            "neighbors": neighbors[d["id"]],
            "custom": {name: {"status": entry["status"], "run_at": iso_z(entry["run_at"]),
                              "detail": entry["detail"], "values": entry["values"],
                              "table": [{"index": i, "column": c, "value": v}
                                        for i, c, v in entry["table"]]}
                       for name, entry in sorted(repo.custom_current(d["id"]).items())},
            "collection": functions,
        })

    for target in repo.targets():
        if target["device_id"] is None and target["last_error"]:
            errors.append({"device": target["address"], "function": "system",
                           "status": "failed", "detail": target["last_error"]})

    last = repo.last_successful_collect()
    include_endpoints = loaded.cfg.export.links.include_endpoints
    return {
        "schema": SCHEMA,
        "generated_at": iso_z(now),
        "tool_version": __version__,
        "last_collect": None if last is None else {
            "run_id": last["id"], "finished_at": iso_z(last["finished_at"]),
            "status": last["status"], "stats": json.loads(last["stats"] or "{}")},
        "devices": out_devices,
        "nodes": [node_json(view, n) for n in view.nodes],
        "links": [{"a": {"device": lk.a_device, "port": lk.a_port},
                   "b": {"device": lk.b_device, "port": lk.b_port},
                   "protocols": lk.protocol.split("+"),
                   "endpoint": lk.endpoint, "first_seen": iso_z(lk.first_seen),
                   "last_seen": iso_z(lk.last_seen)}
                  for lk in view.links if include_endpoints or not lk.endpoint],
        "errors": errors,
    }

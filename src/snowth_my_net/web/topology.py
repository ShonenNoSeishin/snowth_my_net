"""The Topology page: devices as boxes, links as lines, laid out by ``merge.layout``.

Everything drawn comes from the links the devices announced (LLDP/CDP), as in the Links table:
nothing is inferred from a MAC table. A neighbour that is not polled is drawn dashed and cannot
be opened; the end hosts (phones, stations) are left out until asked for.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote

from snowth_my_net.clock import local_time
from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.export.run import exported_devices
from snowth_my_net.merge.layout import DX, DY, layered
from snowth_my_net.merge.ports import device_ports, totals
from snowth_my_net.merge.view import build_view
from snowth_my_net.snmp.target import split_host_port
from snowth_my_net.state.repo import Repo

AUTO = ""


@dataclass
class Topology:
    data: dict                      # what the page script draws
    devices: list[tuple[str, str]]  # (node id, name) of the polled devices, for the root chooser
    hidden_endpoints: int           # links to end hosts left out of the picture
    endpoints: bool
    links: int
    root: str                       # node id of the top of the largest network, "" when empty


def state_label(t, status: str) -> str:
    return t(f"st.{status}") if status in ("ok", "partial", "failed") else status


def _json(data: dict) -> str:
    """Safe to put inside a ``<script type="application/json">`` block."""
    return (json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def render_data(top: Topology) -> str:
    return _json(top.data)


def build(loaded: LoadedConfig, repo: Repo, now: int, t, root_name: str = AUTO,
          endpoints: bool = False) -> Topology:
    view = build_view(loaded, repo, now)
    found, names = exported_devices(loaded, repo, now)
    ports = {d["id"]: totals(device_ports(view, repo, d["id"])) for d in found}
    nodes: dict[str, dict] = {}
    by_name: dict[str, str] = {}
    for d in found:
        name = names[d["id"]]
        node_id = f"d{d['id']}"
        by_name[name.casefold()] = node_id
        count = ports[d["id"]]
        status = d["last_collect_status"] or ""
        nodes[node_id] = {
            "id": node_id, "label": name, "kind": "device", "type": d["device_type"] or "",
            "typeLabel": t(f"type.{d['device_type']}") if d["device_type"] else "",
            "ip": split_host_port(d["mgmt_address"])[0], "vendor": d["vendor"] or "",
            "model": d["model"] or "",
            "os": f"{d['os_name'] or ''} {d['os_version'] or ''}".strip(),
            "status": status, "statusLabel": state_label(t, status),
            "ports": count.ports, "up": count.up,
            "href": "/ports?device=" + quote(name, safe=""), "seen": local_time(d["last_seen"]),
        }

    edges = []
    hidden = 0
    for link in view.links:
        if link.endpoint and not endpoints:
            hidden += 1
            continue
        ends = []
        for name in (link.a_device, link.b_device):
            key = name.casefold()
            if key not in by_name:
                node_id = f"x{len(by_name)}"
                by_name[key] = node_id
                nodes[node_id] = {"id": node_id, "label": name, "kind": "external",
                                  "endpoint": link.endpoint, "type": "", "typeLabel": "",
                                  "ip": "", "vendor": "", "model": "", "os": "", "status": "",
                                  "statusLabel": "", "ports": 0, "up": 0, "href": "",
                                  "seen": local_time(link.last_seen)}
            ends.append(by_name[key])
        if ends[0] == ends[1]:          # a cable from a device to itself: a loop, not a link
            continue
        edges.append({"a": ends[0], "b": ends[1], "ap": link.a_port, "bp": link.b_port,
                      "proto": link.protocol, "seen": local_time(link.last_seen)})

    wanted = by_name.get(root_name.casefold(), "") if root_name else ""
    placed = layered({k: v["label"] for k, v in nodes.items()},
                     [(e["a"], e["b"]) for e in edges], wanted or None)
    # parallel links (a trunk made of several cables) are drawn side by side
    seen: dict[frozenset, int] = {}
    for e in edges:
        key = frozenset((e["a"], e["b"]))
        e["i"] = seen[key] = seen.get(key, -1) + 1
    for e in edges:
        e["n"] = seen[frozenset((e["a"], e["b"]))] + 1
    degree: dict[str, int] = {}
    for e in edges:
        for end in (e["a"], e["b"]):
            degree[end] = degree.get(end, 0) + 1
    for node_id, node in nodes.items():
        p = placed[node_id]
        node.update(x=p.x, y=p.y, layer=p.layer, network=p.network,
                    links=degree.get(node_id, 0))
    top = next((n["id"] for n in nodes.values() if n["layer"] == 0 and n["network"] == 0), "")
    devices = sorted(((n["id"], n["label"]) for n in nodes.values() if n["kind"] == "device"),
                     key=lambda pair: pair[1].casefold())
    labels = {key: t(f"web.topology.{key}") for key in (
        "ip", "vendor", "model", "os", "type", "status", "ports", "ports_up", "seen", "links",
        "open", "not_polled", "endpoint", "close", "fit", "zoom_in", "zoom_out", "no_match",
        "isolated", "root", "neighbors", "port_names")}
    data = {"nodes": list(nodes.values()), "edges": edges, "root": top,
            "grid": {"dx": DX, "dy": DY}, "labels": labels, "colors": TYPE_CLASSES}
    return Topology(data, devices, hidden, endpoints, len(edges), top)


# The CSS class a type is drawn with (the colours live in the stylesheet, which knows the theme).
TYPE_CLASSES = ["switch", "router", "firewall", "wireless", "server", "printer", "facility",
                "other"]

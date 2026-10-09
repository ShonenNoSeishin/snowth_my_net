"""Maps: Graphviz (map.dot), Mermaid (map.mmd) and a self-contained HTML page (map.html).

All three are rendered from one graph: polled devices, unpolled neighbours (dashed), links, and
optionally the end hosts, grouped by port or one by one.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from importlib import resources

from snowth_my_net.clock import iso_z
from snowth_my_net.logs import get_logger
from snowth_my_net.snmp.target import split_host_port

log = get_logger("export.map")
MAX_ENDPOINT_NODES = 2000

TYPE_COLORS = {"switch": "#4c78a8", "router": "#f58518", "firewall": "#e45756",
               "wireless": "#72b7b2", "server": "#54a24b", "printer": "#b279a2",
               "facility": "#9d7660", "other": "#79706e", "": "#8c8c8c"}
TYPE_SHAPES = {"switch": "box", "router": "ellipse", "firewall": "octagon",
               "wireless": "triangle", "server": "box3d", "printer": "note",
               "facility": "cylinder", "other": "box", "": "box"}


@dataclass
class GraphNode:
    id: str
    label: str
    kind: str                      # device | external | group | host
    device_type: str = ""
    details: dict[str, str] = field(default_factory=dict)


@dataclass
class GraphEdge:
    a: str
    b: str
    label: str
    kind: str                      # link | host
    details: dict[str, str] = field(default_factory=dict)


@dataclass
class Graph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def build_graph(view, devices: list[dict], endpoints: str) -> Graph:
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    by_name: dict[str, str] = {}
    for d in devices:
        name = view.names[d["id"]]
        node_id = f"d{d['id']}"
        by_name[name] = node_id
        nodes[node_id] = GraphNode(node_id, name, "device", d["device_type"] or "", {
            "IP": split_host_port(d["mgmt_address"])[0], "Type": d["device_type"] or "—",
            "Vendor": d["vendor"] or "—", "Model": d["model"] or "—",
            "OS": " ".join(x for x in (d["os_name"], d["os_version"]) if x) or "—",
            "Location": d["sys_location"] or "—", "Last seen": iso_z(d["last_seen"])})
    include_endpoints = view.loaded.cfg.export.links.include_endpoints
    for link in view.links:
        if link.endpoint and not include_endpoints:
            continue
        ends = []
        for name in (link.a_device, link.b_device):
            if name not in by_name:
                node_id = f"x{len(by_name)}"
                by_name[name] = node_id
                nodes[node_id] = GraphNode(node_id, name, "external", "",
                                           {"Status": "not polled"})
            ends.append(by_name[name])
        edges.append(GraphEdge(ends[0], ends[1], f"{link.a_port} — {link.b_port}", "link", {
            "Ports": f"{link.a_device} {link.a_port} — {link.b_device} {link.b_port}",
            "Protocol": link.protocol, "Last seen": iso_z(link.last_seen)}))

    if endpoints != "none":
        hosts = [(n, n.current) for n in view.exported_nodes() if n.current is not None]
        mode = endpoints
        if mode == "all" and len(hosts) > MAX_ENDPOINT_NODES:
            log.warning("map: %d hosts, more than %d: grouping them by port", len(hosts),
                        MAX_ENDPOINT_NODES)
            mode = "grouped"
        if mode == "grouped":
            groups: dict[tuple[int, int], list] = defaultdict(list)
            for node, pos in hosts:
                groups[(pos.device_id, pos.ifindex)].append(node)
            for (device_id, ifindex), members in sorted(groups.items()):
                port = view.port_name(device_id, ifindex)
                node_id = f"g{device_id}_{ifindex}"
                label = f"{port} · {len(members)} host{'s' if len(members) > 1 else ''}"
                nodes[node_id] = GraphNode(node_id, label, "group", "", {
                    "Hosts": ", ".join(m.mac for m in members[:20])
                    + (" …" if len(members) > 20 else "")})
                if f"d{device_id}" in nodes:
                    edges.append(GraphEdge(f"d{device_id}", node_id, port, "host"))
        else:
            for node, pos in hosts:
                node_id = "h" + node.mac.replace(":", "")
                ip = node.current_ip.ip if node.current_ip else ""
                nodes[node_id] = GraphNode(node_id, view.dns_name(ip) or ip or node.mac, "host",
                                           "", {"MAC": node.mac, "IP": ip or "—",
                                                "Vendor": view.vendor(node) or "—",
                                                "VLAN": str(pos.vlan or "—")})
                if f"d{pos.device_id}" in nodes:
                    edges.append(GraphEdge(f"d{pos.device_id}", node_id,
                                           view.port_name(pos.device_id, pos.ifindex), "host"))
    return Graph(list(nodes.values()), edges)


# --------------------------------------------------------------------------- Graphviz


def _dot(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def render_dot(graph: Graph) -> str:
    out = ["graph snowth_my_net {",
           '  graph [overlap=false, splines=true, fontname="Helvetica", rankdir=LR];',
           '  node [fontname="Helvetica", fontsize=10];',
           '  edge [fontname="Helvetica", fontsize=8, color="#666666"];']
    for n in graph.nodes:
        if n.kind == "device":
            ip = n.details.get("IP", "")
            label = "\n".join(x for x in (n.label, ip, n.device_type) if x)
            out.append(f"  {_dot(n.id)} [label={_dot(label)}, "
                       f"shape={TYPE_SHAPES.get(n.device_type, 'box')}, style=filled, "
                       f'fillcolor="{TYPE_COLORS.get(n.device_type, "#8c8c8c")}", '
                       'fontcolor="white"];')
        elif n.kind == "external":
            out.append(f"  {_dot(n.id)} [label={_dot(n.label + chr(10) + '(not polled)')}, "
                       "shape=box, style=dashed];")
        else:
            out.append(f"  {_dot(n.id)} [label={_dot(n.label)}, shape=plaintext, "
                       "fontsize=8];")
    for e in graph.edges:
        style = ", style=dotted" if e.kind == "host" else ""
        out.append(f"  {_dot(e.a)} -- {_dot(e.b)} [label={_dot(e.label)}{style}];")
    out.append("}")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- Mermaid


def _mmd(text: str) -> str:
    return text.replace('"', "#quot;").replace("\n", "<br/>")


def render_mermaid(graph: Graph) -> str:
    ids = {n.id: f"n{i}" for i, n in enumerate(graph.nodes)}
    out = ["graph LR"]
    for n in graph.nodes:
        label = n.label
        if n.kind == "device" and n.details.get("IP"):
            label += "\n" + n.details["IP"]
        if n.kind == "external":
            label += "\n(not polled)"
        css = {"device": f":::{n.device_type or 'unknown'}", "external": ":::external",
               "group": ":::hosts", "host": ":::hosts"}[n.kind]
        out.append(f'  {ids[n.id]}["{_mmd(label)}"]{css}')
    for e in graph.edges:
        arrow = "-.-" if e.kind == "host" else "---"
        out.append(f'  {ids[e.a]} {arrow}|"{_mmd(e.label)}"| {ids[e.b]}')
    for kind, color in TYPE_COLORS.items():
        out.append(f"  classDef {kind or 'unknown'} fill:{color},color:#fff,stroke:#333")
    out.append("  classDef external stroke-dasharray: 5 3")
    out.append("  classDef hosts fill:#f4f4f4,color:#333,stroke:#bbb")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- HTML


def render_html(graph: Graph, title: str, generated_at: str) -> str:
    data = {
        "title": title, "generated": generated_at, "colors": TYPE_COLORS,
        "nodes": [{"id": n.id, "label": n.label, "kind": n.kind, "type": n.device_type,
                   "details": n.details} for n in graph.nodes],
        "edges": [{"a": e.a, "b": e.b, "label": e.label, "kind": e.kind, "details": e.details}
                  for e in graph.edges],
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    template = resources.files("snowth_my_net.export").joinpath("map_template.html").read_text(
        "utf-8")
    safe_title = re.sub(r"[<>&\"']", "", title)
    return template.replace("__TITLE__", safe_title).replace("__DATA__", payload)

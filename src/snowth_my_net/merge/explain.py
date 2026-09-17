"""``explain <mac|ip>``: why a MAC is where it is, as styled lines and as JSON."""

from __future__ import annotations

from snowth_my_net.clock import iso_z
from snowth_my_net.merge.nodes import Node
from snowth_my_net.merge.view import NodeView

# (text, kind): kind is one of title, ok, bad, transit, dim, text — renderers pick the style.
Line = tuple[str, str]

REASON_TEXT = {"config": "declared in uplinks", "lag": "link aggregation",
               "config_access": "declared in access_ports"}


def _reasons(reasons) -> str:
    return ", ".join(REASON_TEXT.get(code, code) if code != "mac_count" else detail
                     for code, detail in reasons)


def explain_node(view: NodeView, node: Node) -> list[Line]:
    cfg = view.loaded.cfg.nodes
    vendor = view.vendor(node)
    kind = ("locally administered (random or virtual)" if node.random_mac
            else "universally administered")
    lines: list[Line] = [(f"MAC {node.mac} — {vendor or 'unknown vendor'} ({kind})", "title")]
    if node.excluded:
        lines.append((f"Not a node: {node.excluded}", "bad"))

    current = node.current
    if current:
        vlan = f" VLAN {current.vlan}" if current.vlan else ""
        lines.append((f"Current position : {view.sighting_label(current)}{vlan} — last seen "
                      f"{iso_z(current.last_seen)}", "ok"))
    else:
        lines.append(("Current position : none (no access port known)", "dim"))

    if node.position_kind == "access":
        shadowed = [s for s in node.sightings if s.verdict == "shadowed"]
        uplinks = [s for s in node.sightings if s.verdict == "uplink"]
        rule = f"access port ({current.mac_count} MAC(s) on the port)"
        if shadowed:
            rule += f"; {len(shadowed)} simultaneous sighting(s) on ports with more MACs " \
                    f"treated as transit (window {cfg.transit_window // 60} min)"
        if uplinks:
            rule += f"; {len(uplinks)} uplink sighting(s) discarded"
    elif node.position_kind == "behind_uplink":
        rule = "seen only on soft uplinks: placed on the one with the fewest MACs (uplink_fallback)"
    elif node.sightings:
        rule = ("seen only on uplinks: no position (set nodes.uplink_fallback, or declare the "
                "port in access_ports)")
    else:
        rule = "never seen in a MAC table: known from ARP only"
    lines.append((f"Rule             : {rule}", "text"))

    lines.append(("", "text"))
    lines.append((f"MAC table sightings (retention {cfg.retention_days} d)", "title"))
    if not node.sightings:
        lines.append(("  none", "dim"))
    for s in node.sightings:
        vlan = f"vlan {s.vlan:<4}" if s.vlan else "vlan -   "
        base = (f"{view.sighting_label(s):<28} {vlan} macs={s.mac_count:<4} "
                f"last {iso_z(s.last_seen)}")
        if s.verdict == "position":
            label = "current position" if s is current else "previous position (roaming)"
            lines.append((f"  ✔ {base}  {label}", "ok"))
        elif s.verdict == "fallback":
            lines.append((f"  ✔ {base}  behind soft uplink: {_reasons(s.role.reasons)}", "ok"))
        elif s.verdict == "shadowed" and s.shadowed_by is not None:
            lines.append((f"  ↷ {base}  transit (same time on "
                          f"{view.sighting_label(s.shadowed_by)}, fewer MACs)", "transit"))
        else:
            lines.append((f"  ✘ {base}  uplink: {_reasons(s.role.reasons)}", "bad"))

    lines.append(("", "text"))
    lines.append(("ARP sightings", "title"))
    if not node.ips:
        lines.append(("  none", "dim"))
    for ip in node.ips:
        sources = ", ".join(f"{view.device_name(d)} ({table})" for d, table, _s in ip.sources[:3])
        base = f"{ip.ip:<39} {sources:<34} last {iso_z(ip.last_seen)}"
        if node.current_ip is ip:
            lines.append((f"  {base}  ← current IP", "ok"))
        elif ip.superseded_by:
            lines.append((f"  {base}  superseded (now {ip.superseded_by})", "dim"))
        else:
            lines.append((f"  {base}", "text"))
    if node.current_ip:
        name = view.dns_name(node.current_ip.ip)
        lines.append(("", "text"))
        lines.append((f"DNS  {name or '(no PTR name cached)'}", "text" if name else "dim"))
    return lines


def explain(view: NodeView, query: str) -> list[Line]:
    nodes = view.find(query)
    if not nodes:
        return [(f"{query}: not seen in any MAC or ARP table within the retention period",
                 "bad")]
    lines: list[Line] = []
    for i, node in enumerate(nodes):
        if i:
            lines += [("", "text"), ("─" * 78, "dim"), ("", "text")]
        lines += explain_node(view, node)
    return lines


def node_json(view: NodeView, node: Node) -> dict:
    def sighting(s):
        return {"device": view.device_name(s.device_id), "port": view.port_name(s.device_id,
                                                                                s.ifindex),
                "ifindex": s.ifindex, "vlan": s.vlan or None, "vlan_source": s.vlan_source,
                "mac_count": s.mac_count, "role": s.role.role,
                "role_reasons": [code for code, _d in s.role.reasons], "verdict": s.verdict,
                "first_seen": iso_z(s.first_seen), "last_seen": iso_z(s.last_seen)}

    return {
        "mac": node.mac, "vendor": view.vendor(node), "random_mac": node.random_mac,
        "excluded": node.excluded, "position_kind": node.position_kind,
        "first_seen": iso_z(node.first_seen), "last_seen": iso_z(node.last_seen),
        "current_ip": node.current_ip.ip if node.current_ip else None,
        "dns_name": view.dns_name(node.current_ip.ip) if node.current_ip else None,
        "positions": [dict(sighting(s), current=s is node.current) for s in node.positions],
        "sightings": [sighting(s) for s in node.sightings],
        "ips": [{"ip": i.ip, "first_seen": iso_z(i.first_seen), "last_seen": iso_z(i.last_seen),
                 "superseded_by": i.superseded_by,
                 "sources": [{"device": view.device_name(d), "table": t, "last_seen": iso_z(s)}
                             for d, t, s in i.sources]} for i in node.ips],
    }

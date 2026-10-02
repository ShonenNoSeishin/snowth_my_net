"""``explain <mac|ip>``: why a MAC is where it is, as styled lines and as JSON.

The text follows a language: English for the CLI, the interface's language in the TUI.
"""

from __future__ import annotations

from collections.abc import Callable

from snowth_my_net.clock import iso_z
from snowth_my_net.i18n import Translator
from snowth_my_net.merge.nodes import Node, derived_link_local, is_link_local
from snowth_my_net.merge.view import NodeView

# (text, kind): kind is one of title, ok, bad, transit, dim, text — renderers pick the style.
Line = tuple[str, str]
Text = Callable[..., str]
ENGLISH = Translator("en")


def _reasons(reasons, t: Text) -> str:
    return ", ".join(t(f"xp.reason.{code}", detail=detail) for code, detail in reasons)


def _label(t: Text, key: str) -> str:
    """Left column of the two summary lines, padded so both align in either language."""
    width = max(len(t("xp.position")), len(t("xp.rule")))
    return f"{t(key):<{width}} : "


def explain_node(view: NodeView, node: Node, t: Text = ENGLISH) -> list[Line]:
    cfg = view.loaded.cfg.nodes
    vendor = view.vendor(node)
    kind = t("xp.random") if node.random_mac else t("xp.universal")
    lines: list[Line] = [(t("xp.title", mac=node.mac, vendor=vendor or t("xp.vendor_unknown"),
                            kind=kind), "title")]
    if given := view.given_name(node.mac):
        lines.append((t("xp.given_name", name=given), "text"))
    if about := view.given_description(node.mac):
        lines.append((t("xp.given_description", text=about), "text"))
    if node.excluded:
        reason = t(f"xp.excl.{node.excluded.code}", detail=node.excluded.detail)
        lines.append((t("xp.not_node", reason=reason), "bad"))

    current = node.current
    if current:
        vlan = t("xp.vlan", vlan=current.vlan) if current.vlan else ""
        lines.append((_label(t, "xp.position") + t(
            "xp.position_value", where=view.sighting_label(current), vlan=vlan,
            when=iso_z(current.last_seen)), "ok"))
    else:
        lines.append((_label(t, "xp.position") + t("xp.position_none"), "dim"))

    if node.position_kind == "access":
        shadowed = [s for s in node.sightings if s.verdict == "shadowed"]
        uplinks = [s for s in node.sightings if s.verdict == "uplink"]
        rule = t("xp.rule_access", count=current.mac_count)
        if shadowed:
            rule += t("xp.rule_transit", count=len(shadowed),
                      minutes=cfg.transit_window // 60)
        if uplinks:
            rule += t("xp.rule_uplinks", count=len(uplinks))
    elif node.position_kind == "behind_uplink":
        rule = t("xp.rule_fallback")
    elif node.sightings:
        rule = t("xp.rule_uplinks_only")
    else:
        rule = t("xp.rule_arp_only")
    lines.append((_label(t, "xp.rule") + rule, "text"))

    lines.append(("", "text"))
    lines.append((t("xp.fdb_title", days=cfg.retention_days), "title"))
    if not node.sightings:
        lines.append((t("xp.none"), "dim"))
    for s in node.sightings:
        vlan = f"vlan {s.vlan:<4}" if s.vlan else "vlan -   "
        base = (f"{view.sighting_label(s):<28} {vlan} macs={s.mac_count:<4} "
                f"{t('xp.last')} {iso_z(s.last_seen)}")
        if s.verdict == "position":
            label = t("xp.verdict_current" if s is current else "xp.verdict_previous")
            lines.append((f"  ✔ {base}  {label}", "ok"))
        elif s.verdict == "fallback":
            lines.append((f"  ✔ {base}  " + t("xp.verdict_fallback",
                                              reasons=_reasons(s.role.reasons, t)), "ok"))
        elif s.verdict == "shadowed" and s.shadowed_by is not None:
            lines.append((f"  ↷ {base}  " + t(
                "xp.verdict_transit", where=view.sighting_label(s.shadowed_by)), "transit"))
        else:
            lines.append((f"  ✘ {base}  " + t("xp.verdict_uplink",
                                              reasons=_reasons(s.role.reasons, t)), "bad"))

    lines.append(("", "text"))
    lines.append((t("xp.arp_title"), "title"))
    if not node.ips:
        lines.append((t("xp.none"), "dim"))
    for ip in node.ips:
        sources = ", ".join(f"{view.device_name(d)} ({table})" for d, table, _s in ip.sources[:3])
        base = f"{ip.ip:<39} {sources:<34} {t('xp.last')} {iso_z(ip.last_seen)}"
        if derived_link_local(ip.ip, node.mac):
            base += "  " + t("xp.is_the_mac")
        elif is_link_local(ip.ip):
            base += "  " + t("xp.link_local")
        if node.current_ip is ip:
            lines.append((f"  {base}  " + t("xp.current_ip"), "ok"))
        elif ip.superseded_by:
            lines.append((f"  {base}  " + t("xp.superseded", mac=ip.superseded_by), "dim"))
        else:
            lines.append((f"  {base}", "text"))
    if node.current_ip:
        name = view.dns_name(node.current_ip.ip)
        lines.append(("", "text"))
        lines.append((t("xp.dns", name=name or t("xp.dns_none")), "text" if name else "dim"))
    return lines


def explain(view: NodeView, query: str, t: Text = ENGLISH) -> list[Line]:
    nodes = view.find(query)
    if not nodes:
        return [(t("xp.not_found", query=query), "bad")]
    lines: list[Line] = []
    for i, node in enumerate(nodes):
        if i:
            lines += [("", "text"), ("─" * 78, "dim"), ("", "text")]
        lines += explain_node(view, node, t)
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
        "mac": node.mac, "name": view.given_name(node.mac) or None,
        "description": view.given_description(node.mac) or None,
        "vendor": view.vendor(node), "random_mac": node.random_mac,
        "excluded": str(node.excluded) if node.excluded else None,
        "position_kind": node.position_kind,
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

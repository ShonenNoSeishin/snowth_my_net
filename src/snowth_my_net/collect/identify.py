"""Vendor, model, OS and device type — the type only on sure evidence, else empty.

Type rules, first conclusive one wins (DESIGN.md §7.5):

0. ``config``        — ``devices[].type`` declared by a human
1. ``lldp_caps``     — the device's OWN LLDP capabilities: wlanAccessPoint without router
1b. ``function_mib`` — Printer-MIB -> printer, UPS-MIB -> facility (standard, vendor-neutral)
2. ``catalog``       — sysObjectID sub-tree, or model family scoped to its vendor
3. ``os``            — an OS that only runs on one kind of box
4. ``vendor``        — every SNMP-managed product of the vendor is of one type (with vetoes)

Never evidence: sysServices, multi-type vendors, bare part numbers, "Linux"/"net-snmp",
vague sysDescr keywords.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from snowth_my_net.collect import catalog
from snowth_my_net.collect.model import Identification, TypeEvidence
from snowth_my_net.collect.tables.entity import Chassis
from snowth_my_net.collect.tables.system import SystemInfo
from snowth_my_net.snmp.values import one_line

OuiLookup = Callable[[str], str]


def vendor_of(system: SystemInfo, oui_lookup: OuiLookup | None = None) -> str:
    pen = system.pen
    for scope, pattern, name in catalog.VENDOR_SPLITS:
        if scope == pen and pattern.search(system.descr):
            return name
    info = catalog.VENDORS.get(pen) if pen is not None else None
    if info and not info.generic:
        return info.name
    for pattern, name in catalog.VENDOR_FROM_DESCR:
        if pattern.search(system.descr):
            return name
    if oui_lookup and system.base_mac:
        return oui_lookup(system.base_mac) or ""
    return ""


def _version(rule: catalog.OsRule, descr: str) -> str:
    if rule.version is None:
        return ""
    m = rule.version.search(descr)
    if not m:
        return ""
    groups = {k: v for k, v in m.groupdict().items() if v}
    needed = set(re.findall(r"\{(\w+)\}", rule.version_format))
    if needed <= groups.keys():
        return rule.version_format.format(**groups)
    return groups.get("v", "")


def os_of(system: SystemInfo, vendor: str) -> tuple[str, str, catalog.OsRule | None]:
    for rule in catalog.OS_RULES:
        if rule.vendors is not None and vendor not in rule.vendors:
            continue
        if rule.oid is not None:
            ok = (system.object_id == rule.oid if rule.exact
                  else catalog.oid_under(system.object_id, rule.oid))
            if not ok:
                continue
        if rule.match is not None and not rule.match.search(system.descr):
            continue
        return rule.os, _version(rule, system.descr), rule
    return "", "", None


def model_of(chassis: list[Chassis], system: SystemInfo, vendor: str) -> str:
    if chassis and chassis[0].model:
        return one_line(chassis[0].model)
    for pattern in catalog.MODEL_FROM_DESCR.get(vendor, ()):
        m = pattern.search(system.descr)
        if m:
            return one_line(m.group("m"))
    return ""


def decide_type(
    system: SystemInfo,
    evidence: TypeEvidence,
    vendor: str,
    model: str,
    os_rule: catalog.OsRule | None,
    override: str | None = None,
    override_source: str = "config",
) -> tuple[str, str, str]:
    """Return ``(device_type, rule, reason)``; ``("", "", "")`` without sure evidence."""
    if override:
        if override_source == "manual":
            return override, "manual", "set by hand (TUI or 'device set')"
        return override, "config", "declared in config.yml devices[].type"

    caps = system.lldp_cap_names()
    if "wlan_ap" in caps and "router" not in caps:
        return "wireless", "lldp_caps", "own LLDP capabilities: wlanAccessPoint enabled"

    if evidence.printer_mib:
        return "printer", "function_mib", "Printer-MIB (RFC 3805) prtGeneralTable answered"
    if evidence.ups_mib:
        return "facility", "function_mib", "UPS-MIB (RFC 1628) upsIdent answered"

    oid = system.object_id
    if oid:
        for rule in catalog.TYPE_BY_OID:
            if rule.matches(oid):
                return rule.device_type, "catalog", f"{rule.label} (sysObjectID {oid})"
    if model:
        for rule in catalog.TYPE_BY_MODEL.get(vendor, ()):
            if rule.pattern.search(model):
                return rule.device_type, "catalog", f"{rule.label} (model {model})"

    if os_rule is not None and os_rule.sole_type:
        return (os_rule.sole_type, "os",
                f"{os_rule.os} only runs on {os_rule.sole_type} devices")

    vendor_rule = catalog.TYPE_BY_VENDOR.get(system.pen) if system.pen is not None else None
    if vendor_rule is not None:
        excluded = any(catalog.oid_under(oid, e) for e in vendor_rule.exclude)
        vetoed = vendor_rule.veto is not None and (
            vendor_rule.veto.search(system.descr) or vendor_rule.veto.search(model))
        if not excluded and not vetoed:
            return vendor_rule.device_type, "vendor", vendor_rule.label
    return "", "", ""


def effective_type(detected_type: str, detected_rule: str, detected_reason: str,
                   declared: str | None, declared_source: str) -> tuple[str, str, str]:
    """Declared type (config.yml or manual) wins over the detected one."""
    if declared:
        if declared_source == "manual":
            return declared, "manual", "set by hand (TUI or 'device set')"
        return declared, "config", "declared in config.yml devices[].type"
    return detected_type, detected_rule, detected_reason


def identify(
    system: SystemInfo,
    chassis: list[Chassis],
    evidence: TypeEvidence,
    override_type: str | None = None,
    oui_lookup: OuiLookup | None = None,
    override_source: str = "config",
) -> Identification:
    vendor = vendor_of(system, oui_lookup)
    main = chassis[0] if chassis else None
    os_name, os_version, os_rule = os_of(system, vendor)
    if not os_version and main and main.sw_rev:
        os_version = main.sw_rev
    model = model_of(chassis, system, vendor)
    device_type, rule, reason = decide_type(system, evidence, vendor, model, os_rule,
                                            override_type, override_source)
    return Identification(
        vendor=vendor, pen=system.pen, model=model, serial=main.serial if main else "",
        os_name=os_name, os_version=one_line(os_version),
        device_type=device_type, type_rule=rule, type_reason=reason,
    )


# --------------------------------------------------------------------------- factory names

GENERIC_SYSNAMES = frozenset({
    "switch", "router", "firewall", "gateway", "ap", "access point", "wap", "localhost",
    "localhost.localdomain", "default", "unknown", "none", "(none)", "sysname", "hostname",
    "device", "system", "linux", "openwrt", "dd-wrt", "mikrotik", "ubnt", "unifi",
    "edgeswitch", "fortigate", "sophos", "procurve switch", "hp switch", "aruba", "cisco",
    "juniper", "dell", "netgear", "tp-link", "zyxel", "printer", "ups",
})


def factory_name_reason(sys_name: str, model: str, sys_descr: str) -> str | None:
    """Why ``sys_name`` looks like a factory default (to be fixed on the device), or None."""
    name = one_line(sys_name).casefold()
    if not name:
        return "sysName is empty"
    if name in GENERIC_SYSNAMES:
        return f"sysName {sys_name!r} is a generic factory name"
    if model and name == model.casefold():
        return f"sysName {sys_name!r} is the model name"
    tokens = name.split()
    descr_tokens = set(re.split(r"[\s,]+", sys_descr.casefold()))
    if len(tokens) >= 2 and all(t in descr_tokens for t in tokens):
        return f"sysName {sys_name!r} repeats the product description"
    return None

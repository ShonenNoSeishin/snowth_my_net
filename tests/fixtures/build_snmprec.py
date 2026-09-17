"""Build the synthetic snmpsim fixtures used by the integration tests.

    python tests/fixtures/build_snmprec.py        # rewrites tests/fixtures/snmprec/*

Every value is invented for the tests (documentation MAC range 00:00:5e:00:53:xx from RFC 7042,
documentation IP ranges from RFC 5737, PEN 99999 for "unknown vendor" devices). Formats
mimic what real agents return, but nothing is copied from any third-party recording.
``tests/unit/test_fixtures_fresh.py`` fails when the committed files drift from this script.
"""

from __future__ import annotations

import ipaddress
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "snmprec"

Record = tuple[str, str, str]  # (oid, tag, value)


def _key(oid: str) -> tuple[int, ...]:
    return tuple(int(p) for p in oid.split("."))


def text(oid: str, value: str) -> Record:
    raw = value.encode("utf-8")
    if all(32 <= b < 127 for b in raw) and "|" not in value:
        return (oid, "4", value)
    return (oid, "4x", raw.hex())


def octets(oid: str, raw: bytes) -> Record:
    return (oid, "4x", raw.hex())


def mac(oid: str, value: str) -> Record:
    return octets(oid, bytes.fromhex(value.replace(":", "")))


def integer(oid: str, value: int) -> Record:
    return (oid, "2", str(value))


def gauge(oid: str, value: int) -> Record:
    return (oid, "66", str(value))


def ticks(oid: str, value: int) -> Record:
    return (oid, "67", str(value))


def objid(oid: str, value: str) -> Record:
    return (oid, "6", value)


def ipaddr(oid: str, value: str) -> Record:
    return (oid, "64", value)


# --------------------------------------------------------------------------- MIB builders


def system(descr: str, object_id: str, name: str, location: str = "", contact: str = "",
           services: int | None = None, uptime: int = 123_456_700) -> list[Record]:
    recs = [text("1.3.6.1.2.1.1.1.0", descr), objid("1.3.6.1.2.1.1.2.0", object_id),
            ticks("1.3.6.1.2.1.1.3.0", uptime), text("1.3.6.1.2.1.1.4.0", contact),
            text("1.3.6.1.2.1.1.5.0", name), text("1.3.6.1.2.1.1.6.0", location)]
    if services is not None:
        recs.append(integer("1.3.6.1.2.1.1.7.0", services))
    return recs


def bridge_address(value: str) -> list[Record]:
    return [mac("1.3.6.1.2.1.17.1.1.0", value)]


def lldp_local(chassis_mac: str | None, caps_hex: str) -> list[Record]:
    recs = [octets("1.0.8802.1.1.2.1.3.6.0", bytes.fromhex(caps_hex)),
            octets("1.0.8802.1.1.2.1.3.5.0", bytes.fromhex(caps_hex))]
    if chassis_mac:
        recs += [integer("1.0.8802.1.1.2.1.3.1.0", 4), mac("1.0.8802.1.1.2.1.3.2.0", chassis_mac)]
    return recs


def entity(rows: list[dict]) -> list[Record]:
    base = "1.3.6.1.2.1.47.1.1.1.1"
    recs = []
    for r in rows:
        i = r["index"]
        recs += [text(f"{base}.2.{i}", r.get("descr", "")),
                 integer(f"{base}.4.{i}", r.get("contained", 0)),
                 integer(f"{base}.5.{i}", r["class"]),
                 text(f"{base}.7.{i}", r.get("name", "")),
                 text(f"{base}.10.{i}", r.get("sw", "")),
                 text(f"{base}.11.{i}", r.get("serial", "")),
                 text(f"{base}.13.{i}", r.get("model", ""))]
    return recs


def interfaces(rows: list[dict]) -> list[Record]:
    recs = []
    for r in rows:
        i = r["index"]
        speed = r.get("speed", 1000)
        recs += [integer(f"1.3.6.1.2.1.2.2.1.1.{i}", i),
                 text(f"1.3.6.1.2.1.2.2.1.2.{i}", r["descr"]),
                 integer(f"1.3.6.1.2.1.2.2.1.3.{i}", r.get("type", 6)),
                 gauge(f"1.3.6.1.2.1.2.2.1.5.{i}", min(speed * 1_000_000, 4294967295)),
                 mac(f"1.3.6.1.2.1.2.2.1.6.{i}", r["mac"]) if r.get("mac")
                 else octets(f"1.3.6.1.2.1.2.2.1.6.{i}", b""),
                 integer(f"1.3.6.1.2.1.2.2.1.7.{i}", r.get("admin", 1)),
                 integer(f"1.3.6.1.2.1.2.2.1.8.{i}", r.get("oper", 1)),
                 text(f"1.3.6.1.2.1.31.1.1.1.1.{i}", r.get("name", r["descr"])),
                 gauge(f"1.3.6.1.2.1.31.1.1.1.15.{i}", speed),
                 text(f"1.3.6.1.2.1.31.1.1.1.18.{i}", r.get("alias", ""))]
    return recs


def ip_addresses(rows: list[tuple[str, int, int]]) -> list[Record]:
    """Both ipAddrTable and ipAddressTable, as most modern agents do."""
    recs = []
    for address, ifindex, prefix in rows:
        ip = ipaddress.IPv4Address(address)
        mask = str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)
        recs += [ipaddr(f"1.3.6.1.2.1.4.20.1.1.{ip}", str(ip)),
                 integer(f"1.3.6.1.2.1.4.20.1.2.{ip}", ifindex),
                 ipaddr(f"1.3.6.1.2.1.4.20.1.3.{ip}", mask)]
        net = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False).network_address
        idx = f"1.4.{ip}"
        recs += [integer(f"1.3.6.1.2.1.4.34.1.3.{idx}", ifindex),
                 integer(f"1.3.6.1.2.1.4.34.1.4.{idx}", 1),
                 objid(f"1.3.6.1.2.1.4.34.1.5.{idx}",
                       f"1.3.6.1.2.1.4.32.1.5.{ifindex}.1.4.{net}.{prefix}")]
    return recs


def printer_mib(name: str, serial: str) -> list[Record]:
    return [text("1.3.6.1.2.1.43.5.1.1.16.1", name), text("1.3.6.1.2.1.43.5.1.1.17.1", serial)]


def ups_mib(manufacturer: str, model: str) -> list[Record]:
    return [text("1.3.6.1.2.1.33.1.1.1.0", manufacturer), text("1.3.6.1.2.1.33.1.1.2.0", model)]


def ip_net_to_media(rows: list[tuple[int, str, str]]) -> list[Record]:
    recs = []
    for ifindex, address, hw in rows:
        idx = f"{ifindex}.{address}"
        recs += [integer(f"1.3.6.1.2.1.4.22.1.1.{idx}", ifindex),
                 mac(f"1.3.6.1.2.1.4.22.1.2.{idx}", hw),
                 ipaddr(f"1.3.6.1.2.1.4.22.1.3.{idx}", address),
                 integer(f"1.3.6.1.2.1.4.22.1.4.{idx}", 3)]
    return recs


def _mac_index(mac: str) -> str:
    return ".".join(str(int(part, 16)) for part in mac.split(":"))


def base_ports(mapping: dict[int, int]) -> list[Record]:
    return [integer(f"1.3.6.1.2.1.17.1.4.1.2.{bp}", ifx) for bp, ifx in mapping.items()]


def qbridge_fdb(entries: list[tuple[int, str, int, int]], vlan_fdb: dict[int, int],
                names: dict[int, str], pvid: dict[int, int]) -> list[Record]:
    """entries: (fdb id, mac, bridge port, status)."""
    recs = []
    for fdb_id, mac, port, status in entries:
        idx = f"{fdb_id}.{_mac_index(mac)}"
        recs += [integer(f"1.3.6.1.2.1.17.7.1.2.2.1.2.{idx}", port),
                 integer(f"1.3.6.1.2.1.17.7.1.2.2.1.3.{idx}", status)]
    recs += [gauge(f"1.3.6.1.2.1.17.7.1.4.2.1.3.0.{vlan}", fdb) for vlan, fdb in vlan_fdb.items()]
    recs += [text(f"1.3.6.1.2.1.17.7.1.4.3.1.1.{vlan}", name) for vlan, name in names.items()]
    recs += [gauge(f"1.3.6.1.2.1.17.7.1.4.5.1.1.{bp}", vlan) for bp, vlan in pvid.items()]
    return recs


def dot1d_fdb(entries: list[tuple[str, int]], status: int = 3) -> list[Record]:
    recs = []
    for mac, port in entries:
        idx = _mac_index(mac)
        recs += [integer(f"1.3.6.1.2.1.17.4.3.1.2.{idx}", port),
                 integer(f"1.3.6.1.2.1.17.4.3.1.3.{idx}", status)]
    return recs


def ip_net_to_physical(rows: list[tuple[int, str, str, int]]) -> list[Record]:
    """rows: (ifIndex, address, mac, state)."""
    recs = []
    for ifindex, address, hw, state in rows:
        ip = ipaddress.ip_address(address)
        kind = 1 if ip.version == 4 else 2
        idx = f"{ifindex}.{kind}.{len(ip.packed)}.{'.'.join(str(b) for b in ip.packed)}"
        recs += [mac(f"1.3.6.1.2.1.4.35.1.4.{idx}", hw),
                 integer(f"1.3.6.1.2.1.4.35.1.6.{idx}", 3),
                 integer(f"1.3.6.1.2.1.4.35.1.7.{idx}", state)]
    return recs


def lldp_local_ports(ports: dict[int, tuple[int, str, str]]) -> list[Record]:
    """portNum -> (portIdSubtype, portId, portDesc)."""
    base = "1.0.8802.1.1.2.1.3.7.1"
    recs = []
    for num, (subtype, port_id, desc) in ports.items():
        recs += [integer(f"{base}.2.{num}", subtype), text(f"{base}.3.{num}", port_id),
                 text(f"{base}.4.{num}", desc)]
    return recs


def lldp_remote(entries: list[dict]) -> list[Record]:
    base = "1.0.8802.1.1.2.1.4.1.1"
    recs = []
    for e in entries:
        idx = f"0.{e['port']}.{e.get('index', 1)}"
        recs += [integer(f"{base}.4.{idx}", 4), mac(f"{base}.5.{idx}", e["chassis"]),
                 integer(f"{base}.6.{idx}", e["port_subtype"]),
                 mac(f"{base}.7.{idx}", e["port_id"]) if e["port_subtype"] == 3
                 else text(f"{base}.7.{idx}", e["port_id"]),
                 text(f"{base}.8.{idx}", e.get("port_desc", "")),
                 text(f"{base}.9.{idx}", e["sys_name"]),
                 text(f"{base}.10.{idx}", e.get("sys_descr", "")),
                 octets(f"{base}.11.{idx}", bytes.fromhex(e["caps"])),
                 octets(f"{base}.12.{idx}", bytes.fromhex(e["caps"]))]
        if e.get("address"):
            recs.append(integer(f"1.0.8802.1.1.2.1.4.2.1.3.{idx}.1.4.{e['address']}", 2))
    return recs


def cdp_cache(entries: list[dict]) -> list[Record]:
    base = "1.3.6.1.4.1.9.9.23.1.2.1.1"
    recs = []
    for e in entries:
        idx = f"{e['ifindex']}.{e.get('index', 1)}"
        recs += [integer(f"{base}.3.{idx}", 1),
                 octets(f"{base}.4.{idx}", ipaddress.IPv4Address(e["address"]).packed),
                 text(f"{base}.5.{idx}", e.get("version", "")),
                 text(f"{base}.6.{idx}", e["device_id"]), text(f"{base}.7.{idx}", e["port"]),
                 text(f"{base}.8.{idx}", e["platform"]),
                 octets(f"{base}.9.{idx}", e["caps"].to_bytes(4, "big"))]
    return recs


def filler_macs(prefix: str, count: int) -> list[str]:
    return [f"{prefix}:{i:02x}" for i in range(1, count + 1)]


# Hosts (documentation MAC range): a0/a1 on sw-access, b0 behind its trunk, c0 on sw-generic,
# c1 only in the firewall ARP table, d0/d1 on the Cisco per-VLAN switch.
A0, A1, B0 = "00:00:5e:00:53:a0", "00:00:5e:00:53:a1", "00:00:5e:00:53:b0"
C0, C1, D0, D1 = "00:00:5e:00:53:c0", "00:00:5e:00:53:c1", "00:00:5e:00:53:d0", "00:00:5e:00:53:d1"
# d2 behind a CDP router neighbour; f0 an IP phone with f1 (a PC) behind it; f2 a Wi-Fi client.
D2, F0, F1, F2 = "00:00:5e:00:53:d2", "00:00:5e:00:53:f0", "00:00:5e:00:53:f1", "00:00:5e:00:53:f2"
# LLDP capability bits as BITS octets: bridge 0x20, wlanAccessPoint 0x10, bridge+telephone 0x24
CAP_BRIDGE, CAP_AP, CAP_PHONE = "20", "10", "24"

# --------------------------------------------------------------------------- agents


def _ports(prefix_descr: str, count: int, base_mac: str, name_fmt: str | None = None,
           start: int = 1) -> list[dict]:
    device = int(base_mac[-2:], 16)   # port MACs live in 00:00:5e:<device>:01:<port>
    return [{"index": start + n, "descr": prefix_descr.format(n + 1),
             "name": (name_fmt or prefix_descr).format(n + 1),
             "mac": f"00:00:5e:{device:02x}:01:{n + 1:02x}",
             "oper": 1 if n % 3 else 2} for n in range(count)]


def agents() -> dict[str, list[Record]]:
    a: dict[str, list[Record]] = {}

    # Access switch whose type comes from its sysObjectID (AOS-CX device tree).
    sw_mac = "00:00:5e:00:53:11"
    a["sw-access"] = [
        *system("Aruba JL679A 6100 12G CL4 2SFP+ 139W Swch PL.10.13.1005",
                "1.3.6.1.4.1.47196.4.1.1.1.254", "sw-access-01.example.net",
                location="Building A, floor 1, rack 2", contact="noc@example.net", services=2),
        *bridge_address(sw_mac), *lldp_local(sw_mac, "2800"),
        *entity([{"index": 1, "class": 3, "descr": "6100 12G CL4 2SFP+ 139W Switch",
                  "name": "chassis", "model": "JL679A", "serial": "SG12KW1234",
                  "sw": "PL.10.13.1005"},
                 {"index": 100, "class": 10, "contained": 1, "descr": "port 1/1/1"}]),
        *interfaces(_ports("1/1/{}", 12, sw_mac)
                    + [{"index": 1000, "descr": "vlan1", "type": 136, "mac": sw_mac}]),
        *ip_addresses([("192.0.2.11", 1000, 24)]),
        *base_ports({bp: bp for bp in range(1, 13)}),
        # FDB ids 5 and 6 are internal ids of VLANs 10 and 20 (not the VLAN numbers).
        *qbridge_fdb(
            [(5, A0, 3, 3), (6, A1, 4, 3),
             (5, "00:00:5e:00:53:14", 5, 3),           # a polled device (the printer)
             (5, "00:00:5e:00:01:0a", 6, 3),           # VRRP virtual MAC
             (5, sw_mac, 12, 4),                       # "self" entry
             (5, B0, 12, 3),
             (5, F0, 7, 3), (5, F1, 7, 3),             # phone and the PC behind it
             *[(5, m, 12, 3) for m in filler_macs("00:00:5e:00:54", 5)]],   # trunk: 6 MACs
            vlan_fdb={10: 5, 20: 6}, names={10: "USERS", 20: "VOICE"},
            pvid={**{bp: 10 for bp in range(1, 12)}, 12: 1}),
        *lldp_local_ports({n: (7, f"1/1/{n}", f"1/1/{n}") for n in range(1, 13)}),
        *lldp_remote([
            {"port": 12, "chassis": "00:00:5e:00:53:21", "port_subtype": 5, "port_id": "Gi1/0/4",
             "port_desc": "GigabitEthernet1/0/4", "sys_name": "sw-cisco-03.example.net",
             "caps": CAP_BRIDGE, "address": "127.0.0.21"},
            {"port": 7, "chassis": F0, "port_subtype": 3, "port_id": F0, "port_desc": "WAN",
             "sys_name": "SEP00005E0053F0", "caps": CAP_PHONE, "address": "192.0.2.77"},
        ]),
    ]

    # Unknown vendor, bridge-only LLDP capabilities: the type must stay EMPTY.
    gen_mac = "00:00:5e:00:53:12"
    a["sw-generic"] = [
        *system("Managed Gigabit Switch, firmware 2.4.1", "1.3.6.1.4.1.99999.1.7",
                "sw-generic-02", location="Building B", services=2),
        *bridge_address(gen_mac), *lldp_local(gen_mac, "20"),
        *interfaces(_ports("Port {}", 4, gen_mac, name_fmt="{}")),
        *ip_addresses([("192.0.2.12", 1, 24)]),
        # BRIDGE-MIB only (no Q-BRIDGE FDB); PVID 30 on port 1. Port 2 leads to sw-access
        # without LLDP: a0 and a1 are seen there too (transit), with 3 local hosts.
        *base_ports({1: 1, 2: 2, 3: 3, 4: 4}),
        gauge("1.3.6.1.2.1.17.7.1.4.5.1.1.1", 30),
        *dot1d_fdb([(C0, 1), (A0, 2), (A1, 2), (F2, 3),
                    *[(m, 2) for m in filler_macs("00:00:5e:00:55", 3)]]),
        *dot1d_fdb([("00:00:00:00:00:00", 3)]),        # garbage entry, dropped
        *lldp_local_ports({n: (5, str(n), f"Port {n}") for n in range(1, 5)}),
        *lldp_remote([{"port": 3, "chassis": "00:00:5e:00:53:20", "port_subtype": 5,
                       "port_id": "eth0", "sys_name": "ap-lobby", "caps": CAP_AP,
                       "address": "127.0.0.20"}]),
    ]

    # Sophos-like firewall: no layer 3 in sysServices, no ENTITY-MIB, no bridge, v2c only,
    # ARP only through the legacy ipNetToMediaTable.
    a["fw"] = [
        *system("Linux localhost 6.6.44 #1 SMP Tue Jan 14 08:00:00 UTC 2026 x86_64",
                "1.3.6.1.4.1.2604.5", "fw-edge.example.net", location="Server room",
                services=72),
        *interfaces([{"index": i, "descr": f"Port{i}", "mac": f"00:00:5e:00:53:3{i}"}
                     for i in range(1, 5)]),
        *ip_addresses([("192.0.2.1", 1, 24), ("198.51.100.1", 2, 24)]),
        *ip_net_to_media([(1, "192.0.2.50", "00:00:5e:00:53:a0"),
                          (1, "192.0.2.51", "00:00:5e:00:53:a1"),
                          (2, "198.51.100.20", "00:00:5e:00:53:b0"),
                          (1, "192.0.2.40", C0), (1, "192.0.2.60", C1)]),
    ]

    # Printer of an unknown vendor: typed by the standard Printer-MIB only.
    a["printer"] = [
        *system("Office printer MFP-1000", "1.3.6.1.4.1.99999.2.1", "PRN-2F-01",
                location="2nd floor, copy room"),
        *interfaces([{"index": 1, "descr": "eth0", "mac": "00:00:5e:00:53:14"}]),
        *printer_mib("MFP-1000", "PRN123456"),
    ]

    # UPS network card of an unknown vendor: typed by the standard UPS-MIB only.
    a["ups"] = [
        *system("Network Management Card for UPS", "1.3.6.1.4.1.99999.3.1", "ups-rack-a"),
        *interfaces([{"index": 1, "descr": "eth0", "mac": "00:00:5e:00:53:15"}]),
        *ups_mib("ACME Power", "SMART 3000"),
    ]

    # Linux host with net-snmp: "Linux" is never evidence of a type.
    a["linux"] = [
        *system("Linux backup01 6.1.0-18-amd64 #1 SMP PREEMPT_DYNAMIC Debian 6.1.76-1 "
                "(2024-02-01) x86_64", "1.3.6.1.4.1.8072.3.2.10", "backup01.example.net",
                services=72),
        *interfaces([{"index": 1, "descr": "lo", "type": 24},
                     {"index": 2, "descr": "ens18", "mac": "00:00:5e:00:53:16"}]),
        *ip_addresses([("192.0.2.16", 2, 24)]),
        *ip_net_to_physical([(2, "2001:db8::50", A0, 1), (2, "fe80::50", A0, 2),
                             (2, "192.0.2.99", "00:00:5e:00:53:e0", 7)]),   # incomplete
    ]

    # One switch answering on two addresses (two endpoints of the same agent).
    dual_mac = "00:00:5e:00:53:17"
    a["dual"] = [
        *system("Juniper Networks, Inc. ex2300-24p Ethernet Switch, kernel JUNOS 21.4R3-S5.4, "
                "Build date: 2024-01-10 00:00:00 UTC Copyright (c) 1996-2024 Juniper Networks, "
                "Inc.", "1.3.6.1.4.1.2636.1.1.1.2.132", "sw-core-01", services=6),
        *bridge_address(dual_mac),
        *entity([{"index": 1, "class": 3, "descr": "EX2300-24P", "model": "EX2300-24P",
                  "serial": "JW3619AB0001"}]),
        *interfaces(_ports("ge-0/0/{}", 4, dual_mac)),
        *ip_addresses([("192.0.2.17", 1, 24), ("192.0.2.18", 2, 24)]),
    ]

    # Access point of an unknown vendor announcing wlanAccessPoint in its own LLDP data.
    ap_mac = "00:00:5e:00:53:20"
    a["ap"] = [
        *system("Wireless Access Point AP-100, firmware 1.2", "1.3.6.1.4.1.99999.4.1",
                "ap-lobby"),
        *lldp_local(ap_mac, "30"),
        *interfaces([{"index": 1, "descr": "eth0", "mac": ap_mac}]),
    ]
    # Cisco IOS switch with per-VLAN bridge instances (community@vlan, context vlan-N): the
    # default instance only shows VLAN 1. Extra instances are returned by vlan_instances().
    cisco_mac = "00:00:5e:00:53:21"
    a["sw-cisco"] = [
        *system("Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M), Version 15.2(7)E4, "
                "RELEASE SOFTWARE (fc2)", "1.3.6.1.4.1.9.1.1208", "sw-cisco-03.example.net",
                services=2),
        *bridge_address(cisco_mac),
        *interfaces([{"index": 10100 + n, "descr": f"GigabitEthernet1/0/{n}",
                      "name": f"Gi1/0/{n}", "mac": f"00:00:5e:00:56:{n:02x}"}
                     for n in range(1, 5)]),
        *ip_addresses([("192.0.2.21", 10101, 24)]),
        *base_ports({n: 10100 + n for n in range(1, 5)}),
        *dot1d_fdb([(D1, 2)]),
        integer("1.3.6.1.4.1.9.9.46.1.3.1.1.2.1.1", 1),
        integer("1.3.6.1.4.1.9.9.46.1.3.1.1.2.1.10", 1),
        integer("1.3.6.1.4.1.9.9.46.1.3.1.1.2.1.1002", 1),
        text("1.3.6.1.4.1.9.9.46.1.3.1.1.4.1.1", "default"),
        text("1.3.6.1.4.1.9.9.46.1.3.1.1.4.1.10", "OFFICE"),
        integer("1.3.6.1.4.1.9.9.68.1.2.2.1.2.10101", 10),
        *lldp_local_ports({n: (5, f"Gi1/0/{n}", f"GigabitEthernet1/0/{n}") for n in range(1, 5)}),
        *lldp_remote([{"port": 4, "chassis": "00:00:5e:00:53:11", "port_subtype": 7,
                       "port_id": "1/1/12", "sys_name": "sw-access-01", "caps": CAP_BRIDGE,
                       "address": "127.0.0.11"}]),
        *cdp_cache([
            {"ifindex": 10104, "device_id": "sw-access-01.example.net", "port": "1/1/12",
             "platform": "Aruba JL679A", "caps": 0x08, "address": "127.0.0.11"},
            {"ifindex": 10103, "device_id": "core-rtr(FGL2233X0ZZ)",
             "port": "GigabitEthernet0/0/1", "platform": "cisco ISR4331/K9", "caps": 0x01,
             "address": "203.0.113.1"},
        ]),
    ]
    return a


def vlan_instances() -> dict[str, dict[int, list[Record]]]:
    """Per-VLAN bridge instances: agent -> {vlan: records}."""
    ports = base_ports({n: 10100 + n for n in range(1, 5)})
    return {"sw-cisco": {
        1: [*ports, *dot1d_fdb([(D1, 2)])],
        10: [*ports, *dot1d_fdb([(D0, 1), (D2, 3)])],
    }}


def render(records: list[Record]) -> str:
    return "".join(f"{oid}|{tag}|{value}\n" for oid, tag, value in sorted(records,
                                                                         key=lambda r: _key(r[0])))


def build(out: Path = OUT) -> dict[str, Path]:
    written = {}
    for name, records in agents().items():
        path = out / name / "public.snmprec"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(records), encoding="ascii")
        written[name] = path
        for vlan, vlan_records in vlan_instances().get(name, {}).items():
            vlan_path = out / name / f"public@{vlan}.snmprec"
            vlan_path.write_text(render(vlan_records), encoding="ascii")
            written[f"{name}@{vlan}"] = vlan_path
    return written


if __name__ == "__main__":
    for name, path in build(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT).items():
        print(f"{name}: {path}")

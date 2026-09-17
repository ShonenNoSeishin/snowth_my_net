"""Views built from a small synthetic state (no SNMP): node resolution, explain, links,
exports, snapshot, maps and every report dataset."""

from __future__ import annotations

import asyncio
import json

import pytest

from snowth_my_net.clock import Clock
from snowth_my_net.collect.custom import CustomResult
from snowth_my_net.collect.model import OK, TIMEOUT, DeviceResult, Identification, Outcome
from snowth_my_net.collect.tables.arp import ArpEntry
from snowth_my_net.collect.tables.bridge import FdbEntry
from snowth_my_net.collect.tables.interfaces import Interface
from snowth_my_net.collect.tables.neighbors import Neighbor
from snowth_my_net.collect.tables.system import SystemInfo
from snowth_my_net.config.effective import DeviceSettings
from snowth_my_net.config.loader import LoadedConfig, Paths, parse_config_text
from snowth_my_net.export import maps
from snowth_my_net.export.csvout import EmptyExport
from snowth_my_net.export.run import (
    ViewCache,
    export,
    exported_devices,
    links_csv,
    nodes_csv,
    refresh_dns,
)
from snowth_my_net.export.snapshot import build_snapshot
from snowth_my_net.merge.explain import explain, node_json
from snowth_my_net.merge.view import build_view
from snowth_my_net.snmp.target import parse_target
from snowth_my_net.state.db import open_db
from snowth_my_net.state.repo import Repo

NOW = 1_800_000_000
HOUR = 3600
A, B, C, D = "00:00:5e:00:53:a0", "00:00:5e:00:53:b0", "00:00:5e:00:53:c0", "00:00:5e:00:53:d0"
E, F, G, H = "00:00:5e:00:53:e0", "00:00:5e:00:53:f0", "00:00:5e:00:53:a9", "00:00:5e:00:53:aa"
RANDOM, MULTI, IGNORED = "02:00:00:00:00:01", "01:00:5e:00:00:01", "00:00:5e:00:53:ee"
SW1_MAC, SW2_MAC = "00:00:5e:00:53:01", "00:00:5e:00:53:02"
FILLERS = [f"00:00:5e:00:57:{i:02x}" for i in range(21)]


class FixedClock(Clock):
    def __init__(self, now):
        self._now = now

    def now(self):
        return self._now


def device(address, name, mac, dtype="switch", **kwargs) -> DeviceResult:
    r = DeviceResult(parse_target(address), "seed", 0, DeviceSettings(), credential="v3")
    r.system = SystemInfo(descr=f"{name} descr", object_id="1.3.6.1.4.1.9.1.1", name=name,
                          bridge_mac=mac, location="Lab")
    r.ident = Identification(vendor="Cisco", model="C1", os_name="IOS", os_version="15",
                             device_type=dtype, type_rule="catalog", type_reason="test")
    r.outcomes = {f: Outcome(f, OK) for f in ("entity", "ipaddr", "interfaces", "fdb", "arp",
                                              "lldp", "cdp")}
    for key, value in kwargs.items():
        setattr(r, key, value)
    return r


def fdb(mac, port, vlan=10):
    return FdbEntry(mac, port, vlan, "fdb" if vlan else "none", "qbridge")


YAML = """
general: {{device_name: {{strip_domain: first_dot}}}}
dns: {{enabled: {dns}, strip_domain: true, budget: 5}}
nodes: {{ignore_macs: ["{ignored}"], uplink_fallback: {fallback}, retention_days: 30}}
export:
  files: [devices, nodes, links, snapshot, map]
  map: {{formats: [dot, mmd, html], endpoints: {endpoints}}}
  links: {{include_endpoints: {endpoints_in_links}}}
"""


def make_loaded(tmp_path, dns="false", fallback="false", endpoints="grouped",
                endpoints_in_links="false") -> LoadedConfig:
    cfg = parse_config_text(YAML.format(dns=dns, ignored=IGNORED, fallback=fallback,
                                        endpoints=endpoints,
                                        endpoints_in_links=endpoints_in_links))
    return LoadedConfig(cfg, Paths(tmp_path / "c.yml", tmp_path / "state", tmp_path / "out",
                                   tmp_path))


def build_state(tmp_path) -> Repo:
    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    # --- an hour and more ago: D sits on sw2 Gi0/7, then leaves (roaming).
    early = repo.start_run("collect", NOW - 2 * HOUR)
    sw2 = device("192.0.2.2", "sw2.example.net", SW2_MAC,
                 interfaces={3: Interface(3, "Gi0/3"), 5: Interface(5, "Gi0/5"),
                             7: Interface(7, "Gi0/7"), 9: Interface(9, "Gi0/9"),
                             11: Interface(11, "Gi0/11"), 13: Interface(13, "Gi0/13")},
                 fdb=[fdb(D, 7)])
    sw2_id = repo.save_device(sw2, NOW - 2 * HOUR, early)
    fw = device("192.0.2.254", "fw", "00:00:5e:00:53:fe", "firewall",
                arp=[ArpEntry(D, "192.0.2.60", 4, 1, "physical")])
    fw_id = repo.save_device(fw, NOW - 3 * HOUR, early)
    old = device("192.0.2.99", "retired", "00:00:5e:00:53:99",
                 interfaces={1: Interface(1, "Gi9/1")}, vlans={1: "default"},
                 neighbors=[Neighbor("lldp", 1, 1, sys_name="sw1", port_id="x",
                                     caps=frozenset({"bridge"}))],
                 custom={"poe": (Outcome("custom:poe", OK, 1), CustomResult(
                     rows=[("1", "status", "old", None)]))})
    repo.save_device(old, NOW - 200 * 86400, early)
    repo.finish_run(early, "ok", NOW - 2 * HOUR, {"devices": 3})

    # --- now
    run = repo.start_run("collect", NOW)
    sw1 = device(
        "192.0.2.1", "sw1.example.net", SW1_MAC,
        interfaces={1: Interface(1, "Gi1/0/1", alias="users"), 2: Interface(2, "Gi1/0/2"),
                    24: Interface(24, "Gi1/0/24", phys_mac="00:00:5e:01:01:18", if_type=6,
                                  oper_status=1, admin_status=1, speed_mbps=1000)},
        fdb=[fdb(A, 1), fdb(RANDOM, 1), fdb(D, 1), fdb(MULTI, 1), fdb(IGNORED, 1),
             fdb(C, 2, vlan=0), fdb(F, 2), fdb(B, 24), fdb(E, 24), fdb(SW2_MAC, 24)],
        pvid={2: 20}, vlans={10: "USERS", 20: "VOICE"},
        neighbors=[
            Neighbor("lldp", 24, 24, "port_name", chassis_id=SW2_MAC, port_id="Gi0/5",
                     sys_name="sw2.example.net", caps=frozenset({"bridge"}),
                     mgmt_addresses=["192.0.2.2"]),
            Neighbor("cdp", 24, 24, "cdp", chassis_id="", port_id="GigabitEthernet0/5",
                     sys_name="sw2.example.net", platform="cisco WS-C2960",
                     caps=frozenset({"bridge"}), mgmt_addresses=["192.0.2.2"]),
            Neighbor("lldp", 2, 2, "port_name", chassis_id="00:00:5e:00:53:77",
                     port_id="00:00:5e:00:53:77", port_is_mac=True, port_desc="WAN",
                     sys_name="SEP00005E005377", caps=frozenset({"bridge", "telephone"})),
            Neighbor("lldp", 50, None, "", chassis_id="00:00:5e:00:53:88", port_id="ge-0/0/1",
                     sys_name="", caps=frozenset({"router"}), mgmt_addresses=["203.0.113.9"]),
        ])
    sw1.outcomes["fdb"] = Outcome("fdb", OK, 10)
    sw1_id = repo.save_device(sw1, NOW, run)
    sw2.device_id = sw2_id
    sw2.fdb = [fdb(B, 3), fdb(F, 3), fdb(G, 9), *[fdb(m, 7) for m in FILLERS]]
    sw2.neighbors = [
        Neighbor("lldp", 5, 5, "port_name", chassis_id=SW1_MAC, port_id="Gi1/0/24",
                 sys_name="sw1", caps=frozenset({"bridge"})),
        Neighbor("cdp", 9, 9, "cdp", chassis_id="", port_id="GigabitEthernet0/0/1",
                 sys_name="core-rtr.example.net", platform="cisco ISR",
                 caps=frozenset({"router"}), mgmt_addresses=["203.0.113.1"]),
        Neighbor("lldp", 11, 11, "port_name", chassis_id=SW2_MAC, port_id="Gi0/11",
                 sys_name="sw2", caps=frozenset({"bridge"})),        # sees itself
        Neighbor("lldp", 13, 13, "port_name", chassis_id="00:00:5e:00:53:fe",
                 port_id="00:00:5e:00:53:fe", port_is_mac=True, sys_name="fw",
                 caps=frozenset({"router"})),
    ]
    sw2.outcomes["arp"] = Outcome("arp", TIMEOUT, detail="no answer")
    sw2.custom = {
        "poe": (Outcome("custom:poe", OK, 3), CustomResult(rows=[
            ("3", "status", "delivering", "3"), ("x", "status", "odd", None),
            ("3", "other", "ignored", None)])),
        "sysinfo": (Outcome("custom:sysinfo", OK, 1), CustomResult(rows=[
            ("", "firmware", "1.2", None)])),
    }
    repo.save_device(sw2, NOW, run)
    fw.device_id = fw_id
    fw.arp = [ArpEntry(A, "192.0.2.50", 4, 1, "physical"), ArpEntry(B, "192.0.2.51", 4, 1, "media"),
              ArpEntry(D, "2001:db8::60", 6, 1, "physical"), ArpEntry(D, "fe80::60", 6, 1,
                                                                       "physical"),
              ArpEntry(H, "192.0.2.60", 4, 1, "physical")]
    repo.save_device(fw, NOW, run)
    repo.finish_run(run, "partial", NOW + 30, {"devices": 3, "reachable": 3, "failing": 1})
    repo.start_run("export", NOW + 40)                       # still running
    repo.save_dns({"192.0.2.50": ("host-a.example.net", "ok")}, NOW, 86400, 3600)
    repo.ensure_target("192.0.2.200", "seed", 0, NOW)
    repo.target_failed("192.0.2.200", NOW, "no answer (v3: timeout)")
    repo.save_custom_collector("poe", {"name": "poe", "walk": {
        "index": "port", "columns": {"status": "1.3.6.1.2.1.105.1.1.1.6",
                                     "other": "1.3.6.1.2.1.105.1.1.1.7"}}}, NOW)
    repo.save_custom_collector("sysinfo", {"name": "sysinfo", "get": {
        "firmware": {"oid": "1.3.6.1.4.1.9.9.1.0", "type": "text"}}}, NOW)
    repo.save_custom_collector("rawtable", {"name": "rawtable", "walk": {
        "columns": {"v": "1.3.6.1.4.1.9.9.2"}}}, NOW)
    assert sw1_id
    return repo


@pytest.fixture
def state(tmp_path):
    repo = build_state(tmp_path)
    yield repo
    repo.conn.close()


# --------------------------------------------------------------------------- view & explain


def test_node_view_positions_links_and_find(tmp_path, state):
    loaded = make_loaded(tmp_path)
    view = build_view(loaded, state, NOW)
    assert sorted(view.names.values()) == ["fw", "sw1", "sw2"]          # retired: out of scope
    nodes = {n.mac: n for n in view.nodes}
    assert MULTI not in nodes and IGNORED not in nodes and SW2_MAC not in nodes
    where = {mac: [(view.device_name(p.device_id), view.port_name(p.device_id, p.ifindex))
                   for p in n.positions] for mac, n in nodes.items()}
    assert where[A] == [("sw1", "Gi1/0/1")] and where[C] == [("sw1", "Gi1/0/2")]
    assert where[B] == [("sw2", "Gi0/3")] and where[E] == [] and where[G] == []
    assert where[D] == [("sw1", "Gi1/0/1"), ("sw2", "Gi0/7")]          # roaming history
    assert where[F] == [("sw2", "Gi0/3")]           # same MAC count: transit on sw1 (lower id)
    assert nodes[C].positions[0].vlan == 20                            # from the PVID
    assert nodes[D].current_ip.ip == "2001:db8::60"                    # IPv4 taken by H
    assert nodes[H].positions == [] and nodes[RANDOM].random_mac

    rows = view.link_rows()
    assert sorted(r[:5] for r in rows) == [
        ["fw", "00:00:5e:00:53:fe", "sw2", "Gi0/13", "LLDP"],
        ["sw1", "?", "00:00:5e:00:53:88", "ge-0/0/1", "LLDP"],
        ["sw1", "Gi1/0/24", "sw2", "Gi0/5", "LLDP+CDP"],
        ["sw2", "Gi0/11", "sw2", "Gi0/11", "LLDP"],
        ["sw2", "Gi0/9", "core-rtr", "Gi0/0/1", "CDP"]]
    assert view.port_name(1, 999) == "999" and view.device_name(12345) == "#12345"
    assert view.dns_name("192.0.2.50") == "host-a" and view.dns_name("192.0.2.1") == ""

    assert [n.mac for n in view.find("192.0.2.60")] == [H, D]
    assert view.find("not an address") == [] and view.find("00:00:5e:00:5f:ff") == []
    assert view.find(A.upper())[0].mac == A
    endpoint_view = build_view(make_loaded(tmp_path, endpoints_in_links="true"), state, NOW)
    assert ["sw1", "Gi1/0/2", "SEP00005E005377", "WAN", "LLDP"] in [
        r[:5] for r in endpoint_view.link_rows()]


def text_of(view, query):
    return "\n".join(line for line, _kind in explain(view, query))


def test_explain_every_kind_of_node(tmp_path, state):
    view = build_view(make_loaded(tmp_path), state, NOW)
    a = text_of(view, A)
    assert "Current position : sw1 Gi1/0/1 VLAN 10" in a and "host-a" in a
    assert "access port (5 MAC(s) on the port)" in a and "← current IP" in a
    d = text_of(view, D)
    assert "previous position (roaming)" in d and "superseded (now 00:00:5e:00:53:aa)" in d
    assert "fe80::60" in d
    f = text_of(view, F)
    assert "1 simultaneous sighting(s) on ports with more MACs treated as transit" in f
    assert "↷ sw1 Gi1/0/2" in f
    b = text_of(view, B)
    assert "1 uplink sighting(s) discarded" in b and "neighbor sw2 (LLDP)" in b
    e = text_of(view, E)
    assert "seen only on uplinks: no position" in e and "Current position : none" in e
    assert "ARP sightings\n  none" in e
    h = text_of(view, H)
    assert "never seen in a MAC table: known from ARP only" in h
    assert "MAC table sightings (retention 30 d)\n  none" in h
    assert "DNS  (no PTR name cached)" in h
    assert "Not a node: multicast or broadcast address" in text_of(view, MULTI)
    assert "Not a node: MAC of a polled device (sw2)" in text_of(view, SW2_MAC)
    assert "listed in nodes.ignore_macs" in text_of(view, IGNORED)
    assert "locally administered" in text_of(view, RANDOM)
    both = text_of(view, "192.0.2.60")
    assert both.count("MAC 00:00:5e:00:53") == 2 and "─" * 78 in both
    assert "not seen in any MAC or ARP table" in text_of(view, "198.51.100.1")

    data = node_json(view, view.find(D)[0])
    assert data["current_ip"] == "2001:db8::60" and len(data["positions"]) == 2

    fallback = build_view(make_loaded(tmp_path, fallback="true"), state, NOW)
    g = text_of(fallback, G)
    assert "placed on the one with the fewest MACs (uplink_fallback)" in g
    assert "behind soft uplink: neighbor core-rtr (CDP, router)" in g


# --------------------------------------------------------------------------- exports


def test_export_writes_everything(tmp_path, state):
    loaded = make_loaded(tmp_path)
    result = export(loaded, state, FixedClock(NOW), only=["devices", "nodes", "links", "snapshot",
                                                          "map", "inventory"])
    assert result.pending == ["inventory"] and result.failed == [] and result.exit_code == 0
    names = sorted(p.name for p in result.written)
    assert names == ["devices.csv", "links.csv", "map.dot", "map.html", "map.mmd",
                     "nodes.csv", "snapshot.json"]
    out = tmp_path / "out"
    nodes = (out / "nodes.csv").read_text()
    assert "00:00:5e:00:53:e0,\"ICANN, IANA Department\",,,,,," in nodes     # unlocated
    snapshot = json.loads((out / "snapshot.json").read_text())
    assert [d["name"] for d in snapshot["devices"]] == ["fw", "sw1", "sw2"]
    assert {"device": "sw2", "function": "arp", "status": "timeout"}.items() <= \
        snapshot["errors"][0].items()
    assert {"device": "192.0.2.200", "function": "system", "status": "failed",
            "detail": "no answer (v3: timeout)"} in snapshot["errors"]
    sw2 = snapshot["devices"][2]
    assert sw2["custom"]["sysinfo"]["values"] == {"firmware": "1.2"}
    dot = (out / "map.dot").read_text()
    assert "(not polled)" in dot and "style=dotted" in dot and "host" in dot


def test_exports_fail_when_empty_and_python_exporters(tmp_path):
    from snowth_my_net.api import Extension

    loaded = make_loaded(tmp_path)
    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    ext = Extension("demo")

    @ext.exporter("a/text.txt")
    def as_text(snapshot):
        return "devices: " + str(len(snapshot["devices"]))

    @ext.exporter("b.bin")
    def as_bytes(snapshot):
        return bytearray(b"\x00\x01")

    @ext.exporter("c.txt")
    def wrong(snapshot):
        return 42

    @ext.exporter("d.txt")
    def raises(snapshot):
        raise RuntimeError("exporter bug")

    loaded.exporters = [("demo", e) for e in ext.exporters]
    result = export(loaded, repo, FixedClock(NOW))
    failed = dict(result.failed)
    assert set(failed) == {"devices", "nodes", "links", "py:demo:c.txt", "py:demo:d.txt"}
    assert failed["py:demo:c.txt"] == "TypeError: an exporter returns bytes, not int"
    assert failed["py:demo:d.txt"] == "RuntimeError: exporter bug"
    assert (tmp_path / "out" / "a" / "text.txt").read_text() == "devices: 0"
    assert (tmp_path / "out" / "b.bin").read_bytes() == b"\x00\x01"
    assert result.exit_code == 1
    views = ViewCache(loaded, repo, NOW)
    with pytest.raises(EmptyExport, match=r"links\.csv"):
        links_csv(loaded, views)
    with pytest.raises(EmptyExport, match=r"nodes\.csv"):
        nodes_csv(loaded, repo, NOW)
    loaded.cfg.export.allow_empty = ["nodes", "links"]
    assert nodes_csv(loaded, repo, NOW).count(b"\r\n") == 1
    assert links_csv(loaded, views).count(b"\r\n") == 1
    only = export(loaded, repo, FixedClock(NOW), only=["links"])
    assert [p.name for p in only.written] == ["links.csv"]             # no Python exporters
    repo.conn.close()


def test_dns_refresh_uses_the_cache_and_the_budget(tmp_path, state, caplog):
    loaded = make_loaded(tmp_path, dns="true")
    looked_up = []

    async def lookup(ip):
        looked_up.append(ip)
        if ip == "192.0.2.51":
            await asyncio.sleep(10)
        return (f"n-{ip.replace('.', '-')}.example", "ok") if ip != "192.0.2.60" else (
            None, "nxdomain")

    loaded.cfg.dns.budget = 1
    assert refresh_dns(loaded, state, ["192.0.2.50", "192.0.2.51", "192.0.2.60", ""], NOW,
                       lookup) == 1
    assert looked_up == ["192.0.2.51", "192.0.2.60"]         # 192.0.2.50 is cached
    assert "DNS budget spent" in caplog.text
    assert refresh_dns(loaded, state, ["192.0.2.60"], NOW, lookup) == 0      # negative cache
    assert refresh_dns(make_loaded(tmp_path), state, ["192.0.2.51"], NOW, lookup) == 0
    view = ViewCache(loaded, state, NOW, lookup).get()
    assert view.dns_name("192.0.2.60") == ""


def test_map_endpoint_modes(tmp_path, state, monkeypatch):
    loaded = make_loaded(tmp_path, endpoints="all", endpoints_in_links="true")
    view = build_view(loaded, state, NOW)
    devices, _names = exported_devices(loaded, state, NOW)
    graph = maps.build_graph(view, devices, "all")
    hosts = [n for n in graph.nodes if n.kind == "host"]
    assert any(n.label == "host-a" for n in hosts)
    assert any(e.b.startswith("h") and e.kind == "host" for e in graph.edges)
    assert "SEP00005E005377" in {n.label for n in graph.nodes}
    monkeypatch.setattr(maps, "MAX_ENDPOINT_NODES", 1)
    grouped = maps.build_graph(view, devices, "all")
    labels = {n.label: n for n in grouped.nodes if n.kind == "group"}
    assert "Gi0/7 · 21 hosts" in labels and labels["Gi0/7 · 21 hosts"].details["Hosts"].endswith(
        " …")
    assert "Gi1/0/2 · 1 host" in labels
    without_sw2 = [d for d in devices if d["sys_name"] != "sw2.example.net"]
    partial = maps.build_graph(view, without_sw2, "all")
    sw2_node = "d" + str(next(d["id"] for d in devices if d["sys_name"] == "sw2.example.net"))
    assert all(sw2_node not in (e.a, e.b) for e in partial.edges)
    partial_grouped = maps.build_graph(view, without_sw2, "grouped")
    assert any(n.id.startswith("g") for n in partial_grouped.nodes)
    none = maps.build_graph(build_view(make_loaded(tmp_path), state, NOW), devices, "none")
    assert all(n.kind in ("device", "external") for n in none.nodes)
    assert "SEP00005E005377" not in {n.label for n in none.nodes}
    assert maps.render_mermaid(grouped).startswith("graph LR")
    assert "<html" in maps.render_html(grouped, "t", "now").lower()


def test_snapshot_ignores_devices_not_exported(tmp_path, state):
    loaded = make_loaded(tmp_path)
    view = build_view(loaded, state, NOW)
    devices, _ = exported_devices(loaded, state, NOW)
    subset = [d for d in devices if d["sys_name"] == "fw"]
    snapshot = build_snapshot(loaded, state, view, subset, NOW)
    assert [d["name"] for d in snapshot["devices"]] == ["fw"]
    assert [e["device"] for e in snapshot["errors"]] == ["192.0.2.200"]


# --------------------------------------------------------------------------- report datasets


def test_every_dataset_from_the_state(tmp_path, state):
    from snowth_my_net.reports.engine import run_report
    from snowth_my_net.reports.service import context, generate

    loaded = make_loaded(tmp_path)
    ctx = context(loaded, state, NOW)
    assert ctx.config_dir == tmp_path.resolve()
    datasets = ctx.datasets()
    rows = {name: ctx.rows(ds) for name, ds in datasets.items()}
    assert [d["name"] for d in rows["devices"]] == ["fw", "sw1", "sw2"]
    interfaces = {(r["device"], r["port"]): r for r in rows["interfaces"]}
    assert interfaces[("sw1", "Gi1/0/24")]["role"] == "uplink"
    assert interfaces[("sw1", "Gi1/0/24")]["neighbors"] == "sw2"
    assert interfaces[("sw1", "Gi1/0/1")]["alias"] == "users"
    assert ("retired", "Gi9/1") not in interfaces
    assert {(r["device"], r["vlan"]) for r in rows["vlans"]} == {("sw1", 10), ("sw1", 20)}
    history = {(r["mac"], r["ip"]): r for r in rows["ip_history"]}
    assert history[(D, "192.0.2.60")]["superseded_by"] == H
    assert history[(D, "2001:db8::60")]["current"] and history[(D, "fe80::60")]["family"] == "ipv6"
    assert history[(A, "192.0.2.50")]["seen_by"] == "fw"
    assert {r["protocol"] for r in rows["links"]} == {"LLDP+CDP", "LLDP", "CDP"}
    neighbors = {(r["device"], r["remote_name"]) for r in rows["neighbors"]}
    assert ("sw1", "00:00:5e:00:53:88") in neighbors and ("sw1", "SEP00005E005377") in neighbors
    assert [r["port"] for r in rows["neighbors"] if r["remote_name"] == "00:00:5e:00:53:88"] == [""]
    runs = {r["id"]: r for r in rows["runs"]}
    assert runs[3]["status"] == "running" and runs[3]["duration_s"] is None
    assert runs[2]["failing"] == 1 and runs[2]["duration_s"] == 30
    assert {(r["collector"], r["column"]) for r in rows["custom"]} == {
        ("poe", "status"), ("poe", "other"), ("sysinfo", "firmware")}
    poe = rows["custom:poe"]
    assert {(r["index"], r["port"], r["status"], r["other"]) for r in poe} == {
        ("3", "Gi0/3", "delivering", "ignored"), ("x", "x", "odd", "")}
    assert rows["custom:sysinfo"] == [{"device": "sw2", "device_ip": "192.0.2.2", "index": "",
                                       "firmware": "1.2", "status": "ok", "collected": NOW}]
    assert rows["custom:rawtable"] == []
    assert [f.name for f in datasets["custom:rawtable"].fields][:3] == ["device", "device_ip",
                                                                        "index"]
    assert ctx.dataset_rows("devices") is rows["devices"]

    sql = run_report(parse_sql("select device, count(*) n from nodes where device <> '' "
                               "group by device order by device"), ctx)
    assert sql.rows == [["sw1", 4], ["sw2", 24]]
    generated = generate(loaded, ctx, parse_sql("select mac from nodes limit 1"), fmt="html")
    assert generated.path == tmp_path / "out" / "reports" / "q.html"
    written = generate(loaded, ctx, parse_sql("select mac from nodes limit 1"),
                       output=tmp_path / "x.csv")
    assert written.path == tmp_path / "x.csv" and written.path.exists()
    preview = generate(loaded, ctx, parse_sql("select 1 from devices"), write=False)
    assert preview.path is None


def parse_sql(query):
    from snowth_my_net.reports.service import parse_report

    return parse_report({"name": "q", "sql": query})


def test_empty_state_datasets_and_report_errors(tmp_path):
    from snowth_my_net.push.http import PushError
    from snowth_my_net.reports.service import (
        EmptyReport,
        Generated,
        context,
        generate,
        push_report,
    )

    loaded = make_loaded(tmp_path)
    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    ctx = context(loaded, repo, NOW)
    with pytest.raises(EmptyReport, match="has no row"):
        generate(loaded, ctx, parse_sql("select mac from nodes"))
    table_only = Generated(parse_sql("select 1 from devices"), None, b"x")
    table_only.cfg.push = ["nowhere"]
    outcomes, warnings = push_report(loaded, table_only)
    assert outcomes[0].detail == "unknown push target" and warnings == []
    loaded.cfg.push.targets = parse_config_text(
        "push: {targets: [{name: t, url: 'https://x', auth: {bearer_token_env: SNOWTH_NONE_X}},"
        " {name: dry, url: 'https://y'}]}").push.targets
    with pytest.raises(PushError, match="not written"):
        push_report(loaded, table_only, targets=["t"])
    table_only.path = tmp_path / "r.csv"
    outcomes, warnings = push_report(loaded, table_only, targets=["dry"], dry_run=True)
    assert outcomes[0].ok and outcomes[0].detail.startswith("dry run: would POST")
    outcomes, warnings = push_report(loaded, table_only, targets=["t"])
    assert not outcomes[0].ok and "SNOWTH_NONE_X" in warnings[0]
    repo.conn.close()


def test_links_of_devices_outside_the_export_are_ignored():
    from snowth_my_net.merge.topology import NeighborObs, ResolvedNeighbor, build_links

    obs = NeighborObs(99, 1, "lldp", "k", "", "x", "p", "", (), frozenset(), "", NOW, NOW)
    assert build_links([ResolvedNeighbor(obs, None, None, "x", "p")], {}, lambda d, i: "") == []

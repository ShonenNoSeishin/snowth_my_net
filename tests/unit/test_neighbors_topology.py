from snowth_my_net.collect.tables import neighbors as nb
from snowth_my_net.collect.tables.interfaces import Interface
from snowth_my_net.export import maps
from snowth_my_net.merge.nodes import PortInfo
from snowth_my_net.merge.topology import (
    DeviceIndex,
    DeviceKeys,
    NeighborObs,
    build_links,
    resolve_neighbors,
    uplink_reason,
)

MAC21 = bytes.fromhex("00005e005321")


def test_lldp_remote_table_and_management_addresses():
    idx = (0, 12, 1)
    rem = {4: {idx: 4}, 5: {idx: MAC21}, 6: {idx: 5}, 7: {idx: b"Gi1/0/4"}, 8: {idx: b"uplink"},
           9: {idx: b"sw-cisco-03.example.net"}, 12: {idx: bytes([0x24])}}
    man = {(0, 12, 1, 1, 4, 127, 0, 0, 21): 2, (0, 12, 1, 1, 10, 0, 0, 9): 2,
           (0, 99, 1, 1, 4, 10, 0, 0, 1): 2}
    [n] = nb.parse_lldp(rem, man)
    assert (n.local_port_num, n.chassis_id, n.port_id, n.sys_name) == (
        12, "00:00:5e:00:53:21", "Gi1/0/4", "sw-cisco-03.example.net")
    assert n.caps == {"bridge", "telephone"}
    assert n.mgmt_addresses == ["10.0.0.9", "127.0.0.21"]     # length prefix optional


def test_chassis_and_port_id_subtypes():
    assert nb.decode_chassis_id(5, bytes([1, 192, 0, 2, 1])) == "192.0.2.1"
    assert nb.decode_chassis_id(7, b"sw1") == "sw1"
    assert nb.decode_port_id(3, MAC21) == ("00:00:5e:00:53:21", True)
    assert nb.decode_port_id(5, b"ge-0/0/1") == ("ge-0/0/1", False)


def iface(idx, name, descr="", alias="", mac=None):
    return Interface(idx, name=name, descr=descr, alias=alias, phys_mac=mac)


def test_local_port_mapping_tries_every_method_in_order():
    interfaces = {10101: iface(10101, "Gi1/0/1", "GigabitEthernet1/0/1"),
                  10102: iface(10102, "Gi1/0/2", "GigabitEthernet1/0/2", mac="00:00:5e:00:56:02"),
                  3: iface(3, "3", "Port 3"),
                  50: iface(50, "xe-0/0/0", alias="to-core")}
    loc = {
        2: {(1,): 5, (2,): 3, (3,): 7, (4,): 7, (5,): 7, (6,): 7},
        3: {(1,): b"GigabitEthernet1/0/1", (2,): bytes.fromhex("00005e005602"), (3,): b"zz",
            (4,): b"zz", (5,): b"zz", (6,): b"zz"},
        4: {(4,): b"to-core"},
    }
    mapping = nb.map_local_ports(loc, interfaces, {6: 10101, 5: 99})
    assert mapping[1] == (10101, "port_id_name")
    assert mapping[2] == (10102, "port_id_mac")
    assert mapping[3] == (3, "port_num_ifindex")
    assert mapping[4] == (50, "port_desc")
    assert mapping[6] == (10101, "port_num_bridge_port")
    assert mapping[5] == (99, "port_num_bridge_port")


def test_cdp_cache():
    cache = {3: {(10104, 1): 1, (10103, 1): 1},
             4: {(10104, 1): bytes([127, 0, 0, 11]), (10103, 1): bytes([10, 0, 0, 1])},
             6: {(10104, 1): b"n9k-core(FDO12345678)", (10103, 1): b"SEP001122334455",
                 (10102, 1): b"ap-3f"},
             7: {(10104, 1): b"Ethernet1/49", (10103, 1): b"Port 1",
                 (10102, 1): b"GigabitEthernet0"},
             8: {(10104, 1): b"N9K-C93180YC-FX", (10103, 1): b"Cisco IP Phone 8845",
                 (10102, 1): b"cisco AIR-AP2802I-E-K9"},
             9: {(10104, 1): bytes.fromhex("00000028"), (10103, 1): bytes.fromhex("00000490"),
                 (10102, 1): bytes.fromhex("00000002")}}
    by_name = {n.sys_name: n for n in nb.parse_cdp(cache)}
    assert by_name["n9k-core"].caps == {"bridge"} and by_name["n9k-core"].mgmt_addresses == [
        "127.0.0.11"]
    assert "telephone" in by_name["SEP001122334455"].caps
    assert "wlan_ap" in by_name["ap-3f"].caps and by_name["ap-3f"].port_id == "Gi0"


def obs(device_id, ifindex, caps, name="peer", address=(), chassis="", port="Gi0/1",
        protocol="lldp", seen=100):
    return NeighborObs(device_id, ifindex, protocol, chassis or name, chassis, name, port, "",
                       tuple(address), frozenset(caps), "", seen, seen)


def index():
    devices = {1: DeviceKeys(1, "sw1", "sw1.example.net", {"10.0.0.1"}, {"00:00:5e:00:53:01"},
                             has_fdb=True),
               2: DeviceKeys(2, "sw2", "sw2", {"10.0.0.2"}, set(), has_fdb=True),
               3: DeviceKeys(3, "ap1", "ap1", {"10.0.0.3"}, set(), has_fdb=False)}
    ports = {(1, 48): PortInfo("Te1/1/1"), (2, 1): PortInfo("Gi0/1"), (3, 1): PortInfo("eth0")}
    return DeviceIndex(devices, ports, {})


def names(dev, ifx):
    return {(1, 48): "Te1/1/1", (2, 1): "Gi0/1", (3, 1): "eth0"}.get((dev, ifx), str(ifx))


def test_remote_resolution_and_uplink_reasons():
    idx = index()
    managed, phone, ap, infra, station, by_mac = resolve_neighbors([
        obs(2, 1, {"bridge"}, name="whatever", address=["10.0.0.1"], port="Te1/1/1"),
        obs(1, 7, {"bridge", "telephone"}, name="SEP1"),
        obs(1, 8, {"wlan_ap"}, name="ap1", port="eth0"),
        obs(1, 9, {"router"}, name="core-rtr"),
        obs(1, 10, {"station"}, name="pc"),
        obs(2, 2, {"bridge"}, name="x", chassis="00:00:5e:00:53:01"),
    ], idx, names)
    assert (managed.remote_device_id, managed.remote_ifindex, managed.remote_port) == (1, 48,
                                                                                    "Te1/1/1")
    assert by_mac.remote_device_id == 1
    assert uplink_reason(managed, idx, True)[0] == "neighbor_managed"
    assert uplink_reason(phone, idx, True) is None and phone.endpoint
    assert ap.remote_device_id == 3 and uplink_reason(ap, idx, True) is None
    assert uplink_reason(ap, idx, False) is None           # wlan_ap alone is not a bridge
    assert uplink_reason(infra, idx, True)[:3:2] == ("neighbor_infra", "soft")
    assert uplink_reason(station, idx, True) is None and station.endpoint


def test_links_are_deduplicated_across_ends_and_protocols():
    idx = index()
    resolved = resolve_neighbors([
        obs(1, 48, {"bridge"}, name="sw2", address=["10.0.0.2"], port="Gi0/1"),
        obs(1, 48, {"bridge"}, name="sw2", address=["10.0.0.2"], port="Gi0/1", protocol="cdp"),
        obs(2, 1, {"bridge"}, name="sw1", address=["10.0.0.1"], port="Te1/1/1", seen=200),
        obs(1, 9, {"router"}, name="core-rtr.example.net", port="GigabitEthernet0/0/1"),
        obs(1, 9, {"router"}, name="core-rtr", port="Gi0/0/1", protocol="cdp"),
        obs(1, 7, {"telephone", "bridge"}, name="SEP1", port="Port 1"),
    ], idx, names)
    links = build_links(resolved, {1: "sw1", 2: "sw2"}, names)
    summary = [(lk.a_device, lk.a_port, lk.b_device, lk.b_port, lk.protocol, lk.endpoint)
               for lk in links]
    assert summary == [
        ("sw1", "7", "SEP1", "Port 1", "LLDP", True),
        ("sw1", "9", "core-rtr", "Gi0/0/1", "LLDP+CDP", False),
        ("sw1", "Te1/1/1", "sw2", "Gi0/1", "LLDP+CDP", False),
    ]
    assert links[2].last_seen == 200


def test_map_renderers_escape_and_stay_offline():
    graph = maps.Graph(
        [maps.GraphNode("d1", 'sw "1"', "device", "switch", {"IP": "10.0.0.1"}),
         maps.GraphNode("x1", "</script><b>x", "external")],
        [maps.GraphEdge("d1", "x1", "Te1/1/1 — Gi0/1", "link")])
    dot = maps.render_dot(graph)
    assert '"sw \\"1\\"\\n10.0.0.1\\nswitch"' in dot and dot.startswith("graph snowth_my_net {")
    mmd = maps.render_mermaid(graph)
    assert 'n0["sw #quot;1#quot;<br/>10.0.0.1"]:::switch' in mmd
    html = maps.render_html(graph, "map", "2026-09-17T10:00:00Z")
    assert "</script><b>" not in html and "<\\/script>" in html
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in html

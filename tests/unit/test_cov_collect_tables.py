"""Table parsers and collection functions: malformed agents and less common encodings."""

from __future__ import annotations

import pytest

from snowth_my_net.collect import functions
from snowth_my_net.collect.functions import Rows
from snowth_my_net.collect.identify import decide_type, identify, os_of, vendor_of
from snowth_my_net.collect.model import DeviceResult, TypeEvidence
from snowth_my_net.collect.tables import arp, bridge, entity, ipaddr
from snowth_my_net.collect.tables import neighbors as nb
from snowth_my_net.collect.tables.interfaces import Interface, build_interfaces
from snowth_my_net.collect.tables.system import SystemInfo
from snowth_my_net.config.effective import settings_for
from snowth_my_net.config.loader import parse_config_text
from snowth_my_net.snmp import oids
from snowth_my_net.snmp.client import SnmpError, SnmpTimeout
from snowth_my_net.snmp.target import Target
from tests.unit.test_cov_collect_engine import FakeClient

MAC = b"\x00\x00\x5e\x00\x53\x01"


def test_lldp_encodings_and_malformed_rows():
    v6 = bytes([2]) + bytes(range(32, 48))
    rem = {
        4: {(0, 1, 1): 5, (0, 2, 1): 7, (0, 3, 1): 5, (9, 9): 4},
        5: {(0, 1, 1): bytes([1, 192, 0, 2, 9]), (0, 2, 1): 12345, (0, 3, 1): v6},
        6: {(0, 1, 1): 4, (0, 2, 1): 3, (0, 3, 1): 4},
        7: {(0, 1, 1): bytes([9, 1]), (0, 2, 1): b"\x01\x02", (0, 3, 1): MAC},
        9: {(0, 1, 1): b"r1", (0, 2, 1): b"r2", (0, 3, 1): b"r3"},
    }
    man = {(0, 1, 1, 1, 4, 192, 0, 2, 9): 2,            # with the length prefix
           (0, 1, 1, 1, 192, 0, 2, 10): 2,              # without it
           (0, 1, 1, 1, 4, 192, 0, 2, 9, 7): 2,         # wrong size
           (0, 1, 1, 3, 1, 2): 2,                       # unknown family
           (0, 1, 1, 1, 4, 300, 0, 2, 1): 2,            # octet out of range
           (0, 1, 1, 1): 2,                             # too short once split
           (0, 1): 2,                                   # too short
           (0, 5, 1, 1, 4, 192, 0, 2, 50): 2}           # no such neighbour
    found = {n.sys_name: n for n in nb.parse_lldp(rem, man)}
    assert set(found) == {"r1", "r2", "r3"}
    assert found["r1"].chassis_id == "192.0.2.9" and found["r1"].port_id == "0901"
    assert sorted(found["r1"].mgmt_addresses) == ["192.0.2.10", "192.0.2.9"]
    assert found["r2"].chassis_id == "" and found["r2"].port_id == "\x01\x02"
    assert not found["r2"].port_is_mac and found["r2"].caps == frozenset()
    assert found["r3"].chassis_id == "2021:2223:2425:2627:2829:2a2b:2c2d:2e2f"
    assert (found["r3"].port_id, found["r3"].port_is_mac) == (MAC.hex(), False)  # not an address
    assert nb.decode_port_id(4, bytes([1, 192, 0, 2, 1])) == ("192.0.2.1", False)
    assert nb.decode_chassis_id(4, b"\x01\x02") == "\x01\x02"
    assert nb.decode_port_id(3, b"\x01\x02") == ("\x01\x02", False)
    assert nb.decode_port_id(5, 7) == ("", False)                   # not an OCTET STRING


def test_local_ports_unmapped_and_cdp_caps():
    interfaces = {10: Interface(10, "Gi1/0/1"), 11: Interface(11, "Gi1/0/1")}  # ambiguous name
    loc = {2: {(1,): 5, (2,): 5}, 3: {(1,): b"Gi1/0/1", (2,): b"nothing"}}
    mapping = nb.map_local_ports(loc, interfaces, {})
    assert mapping == {}
    neighbor = nb.Neighbor("lldp", 1)
    nb.assign_local_ports([neighbor], mapping)
    assert neighbor.local_method == "unmapped" and neighbor.local_ifindex is None
    assert nb.cdp_caps(0x81) == frozenset({"router", "telephone"})
    assert nb.cdp_caps("x") == frozenset() and nb.cdp_caps(b"") == frozenset()
    assert nb.clean_cdp_device_id(" sw1 ") == ("sw1", "")


def test_arp_bridge_entity_ipaddr_edges():
    phys = {(1, 1, 4, 192, 0, 2, 1): MAC, (1, 1): MAC, (1, 1, 4, 127, 0, 0, 1): MAC,
            (1, 1, 4, 192, 0, 2, 2): b"\x01\x02", (1, 1, 4, 192, 0, 2, 3): 5}
    entries = arp.parse_net_to_physical(phys, {}, {})
    assert [(e.ip, e.ifindex) for e in entries] == [("192.0.2.1", 1)]

    assert bridge.fdb_id_to_vlan({(): 5, (0, 10): "x", (0, 20): 7}) == {7: 20}
    assert bridge.vlan_names({(1,): b"USERS", (1, 2): b"skip", (3,): 5, (4,): "Voice "}) == {
        1: "USERS", 4: "Voice"}
    qbridge = {(3,) + tuple(MAC): 9}
    assert [(e.vlan, e.vlan_source) for e in bridge.parse_qbridge(qbridge, {}, {7: 20}, {}, {})
            ] == [(0, "none")]

    chassis = entity.build_chassis({1: 3, 2: 9, 3: 9}, {2: 1, 3: 1},
                                   {1: {13: b"M1"}, 2: {10: b""}, 3: {10: b"1.2.3"}})
    assert chassis[0].sw_rev == "1.2.3"

    legacy = ipaddr.parse_ip_addr_table({(192, 0, 2, 1): 1, (192, 0, 2, 2): 2, (0, 0, 0, 0): 3},
                                        {(192, 0, 2, 1): (1, 2), (192, 0, 2, 2): "bad-mask"})
    assert [(a.address, a.prefix_len) for a in legacy] == [("192.0.2.1", None),
                                                           ("192.0.2.2", None)]
    assert ipaddr.parse_ip_address_table({(): 1}, {}, {}) == []


def test_interfaces_speed_fallback_and_lag_to_itself():
    cols = {"ifDescr": {1: b"eth0", 2: b"eth1"}, "ifSpeed": {1: 100_000_000},
            "ifType": {1: 6, 2: 6}}
    ifs = build_interfaces(cols, lag_attached={1: 1, 2: 0})
    assert ifs[1].speed_mbps == 100 and ifs[1].lag_ifindex is None
    assert ifs[2].lag_ifindex is None


def device_result():
    return DeviceResult(Target("192.0.2.1"), "seed", 0,
                        settings_for(parse_config_text(""), "192.0.2.1"))


async def test_interfaces_keyed_by_ifname_when_ifdescr_is_missing():
    r = device_result()
    rows = Rows()
    await functions.interfaces(FakeClient({oids.IF_NAME + (1,): b"ge-0/0/1"}), r, rows)
    assert rows.key == "ifName" and rows.count == 1 and r.interfaces[1].name == "ge-0/0/1"


class VlanAgent(FakeClient):
    """Default context answers; every per-VLAN instance fails with ``error``."""

    def __init__(self, values, error):
        super().__init__(values)
        self.error = error

    def for_vlan(self, vlan):
        return FakeClient(fail={oids.DOT1D_TP_FDB_PORT: self.error})


async def test_cisco_per_vlan_instances_failures_are_reported():
    vtp = {oids.VTP_VLAN_STATE + (1, n): 1 for n in range(10, 17)}
    r = device_result()
    with pytest.raises(SnmpError) as caught:
        await functions.fdb(VlanAgent(vtp, SnmpTimeout("t")), r, Rows())
    assert str(caught.value) == ("per-VLAN bridge instances failed: VLAN 10: timeout; VLAN 11: "
                                 "timeout; VLAN 12: timeout; VLAN 13: timeout; VLAN 14: timeout "
                                 "(+2 more)")
    with pytest.raises(SnmpError, match=r"failed: VLAN 10: noAccess$"):
        await functions.fdb(VlanAgent({oids.VTP_VLAN_STATE + (1, 10): 1}, SnmpError("noAccess")),
                            device_result(), Rows())


def test_identify_edges():
    unknown = SystemInfo(descr="thing", object_id="1.3.6.1.4.1.8072.3.2.10",
                         bridge_mac="00:00:5e:00:53:01")
    assert vendor_of(unknown, lambda mac: "OUI Vendor") == "OUI Vendor"
    assert vendor_of(unknown, lambda mac: None) == ""
    comware = SystemInfo(descr="HPE Comware Platform Software, Software Version 7.1.070",
                         object_id="1.3.6.1.4.1.25506.11.1.1")
    name, version, _rule = os_of(comware, "HPE")
    assert (name, version) == ("Comware", "7.1.070")
    assert decide_type(SystemInfo(), TypeEvidence(), "", "", None, "switch", "manual")[1] == \
        "manual"
    ident = identify(SystemInfo(descr="x"), [], TypeEvidence(), "printer")
    assert (ident.device_type, ident.type_rule) == ("printer", "config")

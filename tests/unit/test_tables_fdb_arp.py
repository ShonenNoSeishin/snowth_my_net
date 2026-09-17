from snowth_my_net.collect.tables import arp, bridge

A0 = (0, 0, 0x5E, 0, 0x53, 0xA0)
A1 = (0, 0, 0x5E, 0, 0x53, 0xA1)
MULTI = (1, 0, 0x5E, 0, 0, 1)


def test_qbridge_translates_fdb_ids_into_vlans():
    ports = {(5, *A0): 3, (6, *A1): 4, (5, *MULTI): 1, (5, 0, 0, 0x5E, 0, 0x53, 0xB0): 0,
             (7, *A1): 2}
    status = {(5, *A0): 3, (6, *A1): 3, (7, *A1): 4}
    fdb_vlans = bridge.fdb_id_to_vlan({(0, 10): 5, (0, 20): 6, (0, 30): 9, (0, 31): 9})
    assert fdb_vlans == {5: 10, 6: 20}                      # shared id 9 is not a VLAN
    entries = bridge.parse_qbridge(ports, status, fdb_vlans, {3: 1003, 4: 1004}, {})
    assert sorted((e.mac, e.ifindex, e.vlan, e.vlan_source) for e in entries) == [
        ("00:00:5e:00:53:a0", 1003, 10, "fdb"),
        ("00:00:5e:00:53:a1", 1004, 20, "fdb"),
    ]


def test_qbridge_without_vlan_table_assumes_valid_ids_else_pvid():
    entries = bridge.parse_qbridge({(10, *A0): 3, (0, *A1): 4}, {}, {}, {}, {4: 30})
    assert {(e.mac[-2:], e.vlan, e.vlan_source) for e in entries} == {
        ("a0", 10, "fdb_assumed"), ("a1", 30, "pvid")}


def test_dot1d_uses_pvid_or_context_vlan_and_identity_ports():
    entries = bridge.parse_dot1d({A0: 3, A1: 9}, {A1: 5}, {}, {3: 30})
    assert [(e.mac, e.ifindex, e.vlan, e.vlan_source, e.method) for e in entries] == [
        ("00:00:5e:00:53:a0", 3, 30, "pvid", "bridge")]      # mgmt entry dropped
    context = bridge.parse_dot1d({A0: 1}, {}, {1: 10101}, {}, vlan=10, method="cisco_vlan")
    assert (context[0].ifindex, context[0].vlan, context[0].vlan_source) == (10101, 10, "context")


def test_bridge_helpers():
    assert bridge.base_ports({(1,): 1001, (2,): 0, (3, 4): 5}) == {1: 1001}
    assert bridge.pvids({(1,): 10, (2,): 5000}) == {1: 10}
    assert bridge.operational_vlans({(1, 1): 1, (1, 10): 1, (1, 20): 2, (1, 1002): 1}) == [1, 10]
    assert bridge.vlan_names({(1, 10): b"OFFICE\x00"}, index_len=2) == {10: "OFFICE"}


def test_arp_tables():
    mac = bytes(A0)
    phys = {(2, 1, 4, 192, 0, 2, 50): mac, (2, 2, 16, *([0xFE, 0x80] + [0] * 13 + [0x50])): mac,
            (2, 1, 4, 192, 0, 2, 99): bytes(6), (2, 1, 4, 192, 0, 2, 98): mac,
            (2, 1, 4, 192, 0, 2, 97): mac}
    types = {(2, 1, 4, 192, 0, 2, 98): 5}
    states = {(2, 1, 4, 192, 0, 2, 97): 7}
    entries = arp.parse_net_to_physical(phys, types, states)
    assert sorted((e.ip, e.family, e.ifindex) for e in entries) == [
        ("192.0.2.50", 4, 2), ("fe80::50", 6, 2)]
    media = arp.parse_net_to_media({(1, 192, 0, 2, 50): mac, (1, 192, 0, 2, 51): bytes(MULTI),
                                    (1, 192, 0, 2, 52): mac}, {(1, 192, 0, 2, 52): 2})
    assert [(e.ip, e.table) for e in media] == [("192.0.2.50", "media")]
    merged = arp.merge_tables(entries, media)
    assert len(merged) == 2 and next(e for e in merged if e.ip == "192.0.2.50").table == "physical"

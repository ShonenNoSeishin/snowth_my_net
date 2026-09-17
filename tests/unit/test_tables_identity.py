from snowth_my_net.collect.tables.entity import build_chassis, clean_serial, rows_to_fetch
from snowth_my_net.collect.tables.interfaces import build_interfaces, short_port_name
from snowth_my_net.collect.tables.ipaddr import (
    merge_addresses,
    parse_ip_addr_table,
    parse_ip_address_table,
)
from snowth_my_net.collect.tables.system import caps_names, decode_lldp_caps, parse_system
from snowth_my_net.config.schema import DeviceNameCfg
from snowth_my_net.export.naming import NameInput, assign_names, base_name
from snowth_my_net.snmp import oids
from snowth_my_net.snmp.target import AddressError, Target, parse_target, split_host_port


def test_system_group_and_identity_scalars():
    s = parse_system({
        oids.SYS_DESCR: b"Cisco IOS Software\r\nsecond line",
        oids.SYS_OBJECT_ID: (1, 3, 6, 1, 4, 1, 9, 1, 1208),
        oids.SYS_UPTIME: 12345,
        oids.SYS_NAME: b"sw1.example.com",
        oids.SYS_LOCATION: None,
        oids.SYS_SERVICES: 6,
        oids.DOT1D_BASE_BRIDGE_ADDRESS: b"\x00\x11\x22\x33\x44\x55",
        oids.LLDP_LOC_CHASSIS_ID_SUBTYPE: 4,
        oids.LLDP_LOC_CHASSIS_ID: b"\x00\x11\x22\x33\x44\x66",
        oids.LLDP_LOC_SYS_CAP_ENABLED: b"\x28",
    })
    assert s.pen == 9
    assert s.object_id == "1.3.6.1.4.1.9.1.1208"
    assert s.name == "sw1.example.com" and s.location == ""
    assert s.base_mac == "00:11:22:33:44:55"      # bridge address wins over chassis id
    assert s.chassis_mac == "00:11:22:33:44:66"
    assert s.lldp_cap_names() == {"bridge", "router"}


def test_lldp_capability_bits_are_msb_first():
    assert caps_names(decode_lldp_caps(b"\x10")) == {"wlan_ap"}
    assert caps_names(decode_lldp_caps(b"\x04\x00")) == {"telephone"}
    assert decode_lldp_caps(b"") is None


def test_chassis_selection_in_a_stack():
    classes = {1: 11, 2: 3, 3: 3, 4: 9, 5: 10}
    contained = {1: 0, 2: 1, 3: 1, 4: 2, 5: 4}
    assert rows_to_fetch(classes, contained) == [2, 3, 4]
    rows = {
        2: {13: b"C9300-48P", 11: b"FOC2345X0AB", 10: b""},
        3: {13: b"C9300-24T", 11: b"0"},
        4: {10: b"17.9.4"},
    }
    chassis = build_chassis(classes, contained, rows)
    assert [c.index for c in chassis] == [2, 3]
    assert (chassis[0].model, chassis[0].serial, chassis[0].sw_rev) == (
        "C9300-48P", "FOC2345X0AB", "17.9.4")
    assert chassis[1].serial == ""


def test_placeholder_serials_are_discarded():
    assert clean_serial("  FOC2345X0AB ") == "FOC2345X0AB"
    for junk in ("N/A", "0000000", "ab", "123456789", "To Be Filled By O.E.M."):
        assert clean_serial(junk) == ""


def test_interfaces_short_names_speed_and_lag():
    cols = {
        "ifDescr": {1: b"GigabitEthernet1/0/1", 2: b"GigabitEthernet1/0/2", 10: b"Port-channel1",
                    20: b"Vlan1"},
        "ifName": {1: b"Gi1/0/1", 2: b"", 10: b"Po1"},
        "ifType": {1: 6, 2: 6, 10: 161, 20: 136},
        "ifSpeed": {1: 1_000_000_000, 2: 4294967295, 10: 4294967295},
        "ifHighSpeed": {1: 1000, 2: 0, 10: 20000},
        "ifPhysAddress": {1: b"\x00\x11\x22\x33\x44\x01", 20: b""},
    }
    ifs = build_interfaces(cols, stack=[(10, 1), (0, 10)], lag_attached={2: 10})
    assert [ifs[i].port_name for i in (1, 2, 10, 20)] == ["Gi1/0/1", "Gi1/0/2", "Po1", "Vlan1"]
    assert ifs[1].lag_ifindex == 10 and ifs[2].lag_ifindex == 10 and ifs[10].lag_ifindex is None
    assert (ifs[1].speed_mbps, ifs[2].speed_mbps, ifs[10].speed_mbps) == (1000, None, 20000)
    assert ifs[1].phys_mac == "00:11:22:33:44:01" and ifs[20].phys_mac is None


def test_short_port_names_only_touch_unambiguous_long_forms():
    assert short_port_name("TenGigabitEthernet1/1/1") == "Te1/1/1"
    assert short_port_name("GigabitEthernet 0/1") == "Gi0/1"
    assert short_port_name("Port-channel12") == "Po12"
    for unchanged in ("Ethernet1/1", "ge-0/0/5", "1/1/5", "port5", "ether1", "Gi1/0/5"):
        assert short_port_name(unchanged) == unchanged


def test_device_addresses_from_both_ip_tables():
    legacy = parse_ip_addr_table({(10, 0, 0, 1): 5, (127, 0, 0, 1): 1},
                                 {(10, 0, 0, 1): "255.255.255.0"})
    assert [(a.address, a.ifindex, a.prefix_len) for a in legacy] == [("10.0.0.1", 5, 24)]
    v6 = (2, 16, 0x20, 0x01, 0x0D, 0xB8) + (0,) * 11 + (1,)
    modern = parse_ip_address_table(
        {(1, 4, 10, 0, 0, 1): 5, v6: 7, (1, 4, 10, 0, 0, 255): 5},
        {(1, 4, 10, 0, 0, 1): 1, v6: 1, (1, 4, 10, 0, 0, 255): 3},
        {(1, 4, 10, 0, 0, 1): (1, 3, 6, 1, 2, 1, 4, 32, 1, 5, 5, 1, 4, 10, 0, 0, 0, 24)},
    )
    assert [(a.address, a.prefix_len) for a in modern] == [("10.0.0.1", 24), ("2001:db8::1", None)]
    merged = merge_addresses(modern, legacy)
    assert [a.address for a in merged] == ["10.0.0.1", "2001:db8::1"]


def test_target_parsing():
    assert split_host_port("10.0.0.1") == ("10.0.0.1", 161)
    assert split_host_port("10.0.0.1:1161") == ("10.0.0.1", 1161)
    assert split_host_port("[2001:db8::1]:1161") == ("2001:db8::1", 1161)
    assert split_host_port("2001:db8::1") == ("2001:db8::1", 161)
    assert str(parse_target("10.0.0.1:161")) == "10.0.0.1"
    assert str(Target("2001:db8::1", 1161)) == "[2001:db8::1]:1161"
    for bad in ("host.example.com", "10.0.0.1:0", "10.0.0.1:x", "[::1"):
        try:
            parse_target(bad)
        except AddressError:
            continue
        raise AssertionError(bad)


def test_device_names():
    cfg = DeviceNameCfg()
    assert base_name("sw1.corp.example.com", "10.0.0.1", None, cfg) == "sw1"
    assert base_name("10.0.0.9", "10.0.0.1", None, cfg) == "10.0.0.9"
    assert base_name("", "10.0.0.1", None, cfg) == "10.0.0.1"
    assert base_name("sw1.example.com", "10.0.0.1", "core-01", cfg) == "core-01"
    suffixes = DeviceNameCfg(strip_domain="suffixes", domain_suffixes=["example.com"])
    assert base_name("sw1.lab.example.com", "10.0.0.1", None, suffixes) == "sw1.lab"
    assert base_name("sw1.other.org", "10.0.0.1", None, suffixes) == "sw1.other.org"
    none = DeviceNameCfg(strip_domain="none")
    assert base_name("sw1.example.com", "10.0.0.1", None, none) == "sw1.example.com"


def test_duplicate_names_get_an_ip_suffix():
    names = assign_names(
        [NameInput(1, "Switch", "10.0.0.1"), NameInput(2, "switch", "10.0.0.2"),
         NameInput(3, "core", "10.0.0.3")],
        DeviceNameCfg(),
    )
    assert names == {1: "Switch (10.0.0.1)", 2: "switch (10.0.0.2)", 3: "core"}


def test_logical_units_are_folded_into_their_physical_port_only_when_named_after_it():
    cols = {
        "ifName": {510: b"ge-0/0/1", 530: b"ge-0/0/1.0", 511: b"ge-0/0/2", 531: b"ge-0/0/2.100",
                   540: b"irb.0", 600: b"gr-0/0/0", 601: b"gr-0/0/0.0", 700: b"ae0",
                   701: b"ae0.0", 702: b"ge-0/0/9", 800: b"eth0.x"},
        "ifType": {510: 6, 530: 53, 511: 6, 531: 53, 540: 53, 600: 131, 601: 53, 700: 161,
                   701: 53, 702: 6, 800: 135},
    }
    stack = [(530, 510), (531, 511), (540, 0), (601, 600), (701, 700), (700, 702),
             (800, 510)]
    ifs = build_interfaces(cols, stack=stack)
    assert {i: ifs[i].parent_ifindex for i in (530, 531, 540, 601, 701, 800)} == {
        530: 510, 531: 511, 540: None, 601: 600, 701: 700, 800: None}
    both = build_interfaces(cols, stack=[(530, 510), (530, 511)])
    assert both[530].parent_ifindex is None          # two lower layers: ambiguous, untouched


def test_fold_subinterfaces_merges_sightings_and_pvid():
    from snowth_my_net.collect.engine import fold_subinterfaces
    from snowth_my_net.collect.model import DeviceResult
    from snowth_my_net.collect.tables.bridge import FdbEntry
    from snowth_my_net.collect.tables.interfaces import Interface

    r = DeviceResult(target=None, origin="seed", depth=0, settings=None)
    r.interfaces = {510: Interface(510, "ge-0/0/1"), 530: Interface(530, "ge-0/0/1.0",
                                                                    parent_ifindex=510)}
    r.fdb = [FdbEntry("00:00:5e:00:53:01", 530, 10, "fdb", "qbridge"),
             FdbEntry("00:00:5e:00:53:01", 510, 10, "fdb", "qbridge"),
             FdbEntry("00:00:5e:00:53:02", 530, 10, "fdb", "qbridge")]
    r.pvid = {530: 10}
    fold_subinterfaces(r)
    assert sorted((e.mac, e.ifindex) for e in r.fdb) == [("00:00:5e:00:53:01", 510),
                                                         ("00:00:5e:00:53:02", 510)]
    assert r.pvid == {530: 10, 510: 10}

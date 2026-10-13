from snowth_my_net.config.schema import NodesCfg
from snowth_my_net.merge.nodes import (
    ArpObs,
    DeviceInfo,
    FdbObs,
    MergeContext,
    MergeInputs,
    PortInfo,
    resolve_mac,
    resolve_nodes,
)

NOW = 1_800_000_000
HOST = "00:00:5e:00:53:a0"


def fdb(mac, dev, ifx, seen=NOW, run=10, vlan=10, first=None):
    return FdbObs(mac, dev, ifx, vlan, "fdb", first or seen, seen, run)


def arp(mac, ip, seen=NOW, dev=9, family=4, first=None):
    return ArpObs(mac, ip, family, dev, "media", first or seen, seen)


def filler(dev, ifx, count, run=10, seen=NOW):
    return [fdb(f"00:00:5e:00:5{dev}:{i:02x}", dev, ifx, seen, run) for i in range(count)]


def inputs(fdbs=(), arps=(), ports=None, devices=None, device_macs=None):
    return MergeInputs(
        devices=devices or {1: DeviceInfo("sw1"), 2: DeviceInfo("sw2"), 9: DeviceInfo("fw")},
        ports=ports or {}, fdb=list(fdbs), arp=list(arps), device_macs=device_macs or {})


def node(data, mac=HOST, cfg=None, now=NOW):
    return resolve_mac(MergeContext(data, cfg or NodesCfg(), now), mac)


def where(n):
    return [(p.device_id, p.ifindex) for p in n.positions]


def test_trunk_with_many_macs_is_an_uplink_and_the_access_port_wins():
    data = inputs([fdb(HOST, 1, 3), fdb(HOST, 1, 48), *filler(1, 48, 60)])
    n = node(data)
    assert where(n) == [(1, 3)]
    trunk = next(s for s in n.sightings if s.ifindex == 48)
    assert trunk.verdict == "uplink" and trunk.role.reasons[0][0] == "mac_count"


def test_threshold_is_per_device_and_counts_only_the_last_walk():
    data = inputs([fdb(HOST, 1, 48), *filler(1, 48, 60, run=5)],
                  devices={1: DeviceInfo("sw1", uplink_mac_threshold=50)})
    assert node(data).positions and node(data).positions[0].mac_count == 1   # old walk ignored
    data = inputs([fdb(HOST, 1, 48), *filler(1, 48, 60)],
                  devices={1: DeviceInfo("sw1", uplink_mac_threshold=100)})
    assert where(node(data)) == [(1, 48)]


def test_mac_seen_only_on_uplinks_has_no_position_unless_fallback():
    data = inputs([fdb(HOST, 1, 48), *filler(1, 48, 60)])
    assert node(data).positions == []
    fallback = node(data, cfg=NodesCfg(uplink_fallback=True))
    assert where(fallback) == [(1, 48)] and fallback.position_kind == "behind_uplink"
    hard = inputs([fdb(HOST, 1, 48)], devices={1: DeviceInfo("sw1", uplinks=("Te1/1/1",))},
                  ports={(1, 48): PortInfo(name="Te1/1/1")})
    assert node(hard, cfg=NodesCfg(uplink_fallback=True)).positions == []


def test_simultaneous_sightings_keep_the_port_with_fewest_macs():
    data = inputs([fdb(HOST, 1, 3), fdb(HOST, 2, 2, seen=NOW - 60), *filler(2, 2, 4)])
    n = node(data)
    assert where(n) == [(1, 3)]
    transit = next(s for s in n.sightings if s.device_id == 2)
    assert transit.verdict == "shadowed" and transit.shadowed_by.device_id == 1


def test_roaming_keeps_history_and_the_latest_is_current():
    data = inputs([fdb(HOST, 1, 3, seen=NOW - 3 * 86400), fdb(HOST, 2, 7)])
    n = node(data)
    assert where(n) == [(2, 7), (1, 3)]
    assert n.current.device_id == 2 and n.position_kind == "access"


def test_config_access_ports_and_lag():
    ports = {(1, 100): PortInfo(name="Po10", if_type=161)}
    data = inputs([fdb(HOST, 1, 100), *filler(1, 100, 80)], ports=ports,
                  devices={1: DeviceInfo("sw1", access_ports=("po10",))})
    assert where(node(data)) == [(1, 100)]
    lag_only = inputs([fdb(HOST, 1, 100)], ports=ports)
    assert where(node(lag_only)) == [(1, 100)]                          # lag_is_uplink false
    assert node(lag_only, cfg=NodesCfg(lag_is_uplink=True)).positions == []


def test_vlan_falls_back_to_the_port_pvid():
    data = inputs([FdbObs(HOST, 1, 3, 0, "none", NOW, NOW, 10)],
                  ports={(1, 3): PortInfo(name="Gi0/3", pvid=30)})
    position = node(data).current
    assert (position.vlan, position.vlan_source) == (30, "pvid")


def test_retention_drops_old_observations():
    data = inputs([fdb(HOST, 1, 3, seen=NOW - 40 * 86400)],
                  [arp(HOST, "192.0.2.50", seen=NOW - 40 * 86400)])
    assert resolve_nodes(data, NodesCfg(retention_days=30), NOW) == []


def test_current_ip_prefers_ipv4_and_ignores_reassigned_addresses():
    other = "00:00:5e:00:53:ff"
    data = inputs(arps=[
        arp(HOST, "192.0.2.50", seen=NOW - 600),
        arp(HOST, "2001:db8::50", family=6),
        arp(HOST, "fe80::50", family=6),
        arp(HOST, "192.0.2.77", seen=NOW - 3600),
        arp(other, "192.0.2.77", seen=NOW - 60),          # took .77 later
    ])
    n = node(data)
    assert n.current_ip.ip == "192.0.2.50"
    assert next(i for i in n.ips if i.ip == "192.0.2.77").superseded_by == other
    assert node(data, cfg=NodesCfg(prefer_ipv4=False)).current_ip.ip == "2001:db8::50"


def test_current_ip_window_prefers_a_recent_ipv6_over_an_old_ipv4():
    data = inputs(arps=[arp(HOST, "192.0.2.50", seen=NOW - 3 * 86400),
                        arp(HOST, "2001:db8::50", family=6)])
    assert node(data).current_ip.ip == "2001:db8::50"


def test_exclusions():
    data = inputs([fdb("00:00:5e:00:53:11", 2, 1), fdb("00:00:5e:00:01:01", 1, 5),
                   fdb("02:11:22:33:44:55", 1, 6)],
                  device_macs={"00:00:5e:00:53:11": 1})
    nodes = resolve_nodes(data, NodesCfg(), NOW)
    assert [n.mac for n in nodes] == ["02:11:22:33:44:55"]              # device MAC and VRRP out
    assert nodes[0].random_mac
    ctx = MergeContext(data, NodesCfg(), NOW)
    excluded = resolve_mac(ctx, "00:00:5e:00:53:11").excluded
    assert (excluded.code, excluded.detail) == ("device_mac", "sw1")
    assert str(excluded) == "MAC of a polled device (sw1)"
    assert resolve_nodes(data, NodesCfg(include_device_macs=True, ignore_mac_prefixes=[]),
                         NOW)[0].mac == "00:00:5e:00:01:01"


def test_arp_only_mac_is_a_node_without_position():
    n = resolve_nodes(inputs(arps=[arp(HOST, "192.0.2.50")]), NodesCfg(), NOW)[0]
    assert n.positions == [] and n.current_ip.ip == "192.0.2.50" and n.last_seen == NOW


def test_a_radio_is_never_an_uplink_because_of_its_station_count():
    ports = {(1, 7): PortInfo(name="wlan1", if_type=71), (1, 8): PortInfo(name="ether8")}
    data = inputs([fdb(HOST, 1, 7), *filler(1, 7, 80)], ports=ports)
    assert where(node(data)) == [(1, 7)]
    data = inputs([fdb(HOST, 1, 8), *filler(1, 8, 80)], ports=ports)
    assert where(node(data)) == []


def test_a_mac_that_moved_is_on_its_new_port_not_the_empty_one_it_left():
    """sw1 walked again (run 11) and no longer lists the laptop; sw2 lists it among 3 others."""
    data = inputs([fdb(HOST, 1, 3, seen=NOW - 600, run=10), *filler(1, 9, 2, run=11),
                   fdb(HOST, 2, 7, run=11), *filler(2, 7, 3, run=11)])
    n = node(data)
    assert where(n) == [(2, 7)]
    old = next(s for s in n.sightings if s.device_id == 1)
    assert old.verdict == "shadowed" and old.shadowed_by.device_id == 2


def test_two_ports_both_still_listed_keep_the_quieter_one():
    data = inputs([fdb(HOST, 1, 3, run=11), fdb(HOST, 2, 7, run=11), *filler(2, 7, 3, run=11),
                   *filler(1, 9, 1, run=11)])
    assert where(node(data)) == [(1, 3)]


def test_when_no_candidate_is_current_the_old_rule_still_decides():
    data = inputs([fdb(HOST, 1, 3, seen=NOW - 60, run=9), fdb(HOST, 2, 7, seen=NOW - 60, run=9),
                   *filler(1, 9, 1, run=11), *filler(2, 9, 1, run=11)])
    assert len(where(node(data))) == 1


# ---- the current IP is only the node's own while it is fresh and unambiguous


def test_an_address_kept_by_an_arp_cache_for_weeks_is_not_the_nodes_ip():
    data = inputs([fdb(HOST, 1, 3)], [arp(HOST, "10.0.0.5", seen=NOW - 25 * 86400)])
    n = node(data)
    assert n.current_ip is None and [i.ip for i in n.ips] == ["10.0.0.5"]
    fresh = inputs([fdb(HOST, 1, 3)], [arp(HOST, "10.0.0.5", seen=NOW - 3 * 86400)])
    assert node(fresh).current_ip.ip == "10.0.0.5"          # a quiet host keeps its address


def test_two_addresses_seen_at_the_same_instant_elect_none():
    data = inputs([fdb(HOST, 1, 3)], [arp(HOST, "10.0.0.9"), arp(HOST, "10.0.0.5")])
    n = node(data)
    assert n.current_ip is None and "same time" in n.ip_ambiguous
    older = inputs([fdb(HOST, 1, 3)], [arp(HOST, "10.0.0.9"), arp(HOST, "10.0.0.5", seen=NOW - 60)])
    assert node(older).current_ip.ip == "10.0.0.9"          # a clear newest still wins


def test_a_mac_answering_for_many_addresses_gets_none_of_them():
    many = [arp(HOST, f"10.0.0.{i}", seen=NOW - i) for i in range(1, 6)]
    n = node(inputs([fdb(HOST, 1, 3)], many))
    assert n.current_ip is None and "more than 3" in n.ip_ambiguous and len(n.ips) == 5
    three = node(inputs([fdb(HOST, 1, 3)], many[:3]))
    assert three.current_ip.ip == "10.0.0.1"


def test_an_ipv4_and_an_ipv6_seen_together_still_elect_the_ipv4():
    data = inputs([fdb(HOST, 1, 3)], [arp(HOST, "10.0.0.5"),
                                      arp(HOST, "2001:db8::5", family=6)])
    assert node(data).current_ip.ip == "10.0.0.5"


def test_a_port_the_mac_left_is_not_its_position_once_an_uplink_hears_it_later():
    later = NOW + 3600
    # sw1 listed it on port 3 in run 5, walked again (run 6) without it; sw2's trunk hears it now
    data = inputs([fdb(HOST, 1, 3, seen=NOW - 7200, run=5), *filler(1, 4, 1, run=6),
                   fdb(HOST, 2, 48, seen=later, run=10), *filler(2, 48, 60, run=10, seen=later)])
    data.devices[2] = DeviceInfo("sw2", uplinks=("48",))
    data.ports[(2, 48)] = PortInfo(name="48")
    n = node(data, now=later)
    assert n.positions == [] and n.position_kind == "none"
    assert next(s for s in n.sightings if s.ifindex == 3).verdict == "left"


def test_a_port_still_listing_the_mac_stays_its_position_whatever_the_uplink_says():
    later = NOW + 3600
    data = inputs([fdb(HOST, 1, 3, seen=later, run=6), fdb(HOST, 2, 48, seen=later, run=10)],
                  devices={1: DeviceInfo("sw1"), 2: DeviceInfo("sw2", uplinks=("48",))},
                  ports={(2, 48): PortInfo(name="48")})
    assert where(node(data, now=later)) == [(1, 3)]


def test_hsrp_ipv6_and_glbp_virtual_macs_are_not_nodes():
    from snowth_my_net.config.schema import DEFAULT_IGNORED_PREFIXES
    cfg = NodesCfg(ignore_mac_prefixes=list(DEFAULT_IGNORED_PREFIXES))
    for mac in ("00:05:73:a0:00:0a", "00:07:b4:00:01:02"):
        assert node(inputs([fdb(mac, 1, 3)]), mac=mac, cfg=cfg).excluded is not None

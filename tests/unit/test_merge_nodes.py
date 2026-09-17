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
    assert "polled device (sw1)" in resolve_mac(ctx, "00:00:5e:00:53:11").excluded
    assert resolve_nodes(data, NodesCfg(include_device_macs=True, ignore_mac_prefixes=[]),
                         NOW)[0].mac == "00:00:5e:00:01:01"


def test_arp_only_mac_is_a_node_without_position():
    n = resolve_nodes(inputs(arps=[arp(HOST, "192.0.2.50")]), NodesCfg(), NOW)[0]
    assert n.positions == [] and n.current_ip.ip == "192.0.2.50" and n.last_seen == NOW

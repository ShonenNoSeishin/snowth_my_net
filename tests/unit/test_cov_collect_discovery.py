"""Discovery planning: seeds (incl. host names), known targets, sweep, neighbour exploration."""

from __future__ import annotations

from snowth_my_net.collect import discovery
from snowth_my_net.collect.discovery import (
    Scope,
    neighbor_targets,
    plan_targets,
    resolve_seeds,
    sweep_addresses,
)
from snowth_my_net.collect.tables.neighbors import Neighbor
from snowth_my_net.config.loader import parse_config_text
from snowth_my_net.snmp.target import Target


def cfg(text: str):
    return parse_config_text(text)


def known(address, origin="state", depth=0, credential=None, device_id=None, is_alias=0,
          device_status="ok", device_mgmt=None):
    return {"address": address, "origin": origin, "depth": depth, "credential": credential,
            "device_id": device_id, "is_alias": is_alias, "device_status": device_status,
            "device_mgmt": device_mgmt}


async def test_resolve_seeds_ports_names_and_errors(monkeypatch):
    calls = []

    async def fake_resolve(resolver, host):
        calls.append(host)
        if host == "missing.example.net":
            raise LookupError("NXDOMAIN")
        return "192.0.2.80"

    monkeypatch.setattr(discovery, "resolve_host", fake_resolve)
    monkeypatch.setattr(discovery, "make_resolver", lambda dns_cfg: object())
    c = cfg("general: {snmp: {port: 1161}}\ndiscovery:\n  seeds: ['192.0.2.1', '192.0.2.2:162',"
            " 'core.example.net', 'missing.example.net', '[bad']\n")
    result = await resolve_seeds(c)
    assert [(str(t), rank) for t, rank in result.targets] == [
        ("192.0.2.1:1161", 0), ("192.0.2.2:162", 1), ("192.0.2.80:1161", 2)]
    assert calls == ["core.example.net", "missing.example.net"]
    assert len(result.errors) == 2
    assert "missing.example.net" in result.errors[0] and "NXDOMAIN" in result.errors[0]
    assert "'[bad'" in result.errors[1]


def test_plan_targets_merges_filters_and_orders():
    c = cfg("""
discovery:
  allowed: [192.0.2.0/24]
  exclude: [192.0.2.66/32]
devices:
  - {address: 192.0.2.30, disabled: true}
""")
    seeds = [(Target("192.0.2.10"), 0), (Target("203.0.113.5"), 1), (Target("192.0.2.66"), 2)]
    rows = [
        known("192.0.2.10", origin="seed", credential="v3", device_id=4, device_mgmt="192.0.2.10"),
        known("192.0.2.20", origin="neighbor", depth=2, device_id=5, device_mgmt="192.0.2.21"),
        known("192.0.2.21", is_alias=1, device_id=5),                       # alias: skipped
        known("192.0.2.22", is_alias=1, device_id=6, device_status="failed"),  # primary failed
        known("198.51.100.9", origin="manual"),                             # manual: allowed
        known("198.51.100.10"),                                             # out of scope
        known("192.0.2.30"),                                                # disabled
        known("not-an-address"),
    ]
    planned, notes = plan_targets(c, seeds, rows)
    assert [(str(p.target), p.origin, p.depth) for p in planned] == [
        ("192.0.2.10", "seed", 0), ("203.0.113.5", "seed", 0), ("192.0.2.20", "neighbor", 2),
        ("192.0.2.22", "state", 0), ("198.51.100.9", "manual", 0)]
    seed = planned[0]
    assert (seed.remembered_credential, seed.device_id, seed.is_current_mgmt) == ("v3", 4, True)
    assert planned[2].is_current_mgmt is False
    assert "not-an-address: invalid address in state, ignored" in notes
    assert "192.0.2.66: skipped (excluded)" in notes
    assert "198.51.100.10: skipped (outside discovery.allowed)" in notes
    assert "192.0.2.30: skipped (disabled in devices:)" in notes

    only, _ = plan_targets(c, seeds, rows, only={"192.0.2.20"})
    assert [str(p.target) for p in only] == ["192.0.2.20"]
    manual_disabled, notes = plan_targets(c, [], [known("192.0.2.40")],
                                          manual={"192.0.2.40": {"disabled": True}})
    assert manual_disabled == [] and notes == ["192.0.2.40: skipped (disabled in devices:)"]


def test_scope_seed_exception_and_exclude_priority():
    c = cfg("discovery: {allowed: [192.0.2.0/24], exclude: [192.0.2.0/28]}")
    import ipaddress

    scope = Scope(c.discovery.allowed, c.discovery.exclude, {"203.0.113.1", "192.0.2.5"})
    assert scope.check(ipaddress.ip_address("203.0.113.1")) is None
    assert scope.check(ipaddress.ip_address("192.0.2.5")) == "excluded"
    assert scope.check(ipaddress.ip_address("2001:db8::1")) == "outside discovery.allowed"


def test_sweep_addresses_skip_known_excluded_and_handle_tiny_networks():
    c = cfg("""
general: {snmp: {port: 1161}}
discovery:
  allowed: [192.0.2.0/24]
  exclude: [192.0.2.2/32]
  sweep: [192.0.2.0/29, 192.0.2.100/32, 192.0.2.200/31]
""")
    targets = sweep_addresses(c, {"192.0.2.3"})
    assert [str(t) for t in targets] == ["192.0.2.1:1161", "192.0.2.4:1161", "192.0.2.5:1161",
                                         "192.0.2.6:1161", "192.0.2.100:1161",
                                         "192.0.2.200:1161", "192.0.2.201:1161"]


def neighbor(name, address=None, caps=("bridge",)):
    return Neighbor("lldp", 1, sys_name=name, caps=frozenset(caps),
                    mgmt_addresses=[address] if address else [])


def test_neighbor_targets_rules():
    c = cfg("""
general: {snmp: {port: 1161}}
discovery:
  allowed: [192.0.2.0/24]
  exclude: [192.0.2.99/32]
  max_depth: 2
devices:
  - {address: 192.0.2.50, disabled: true}
""")
    known_hosts = {"192.0.2.1"}
    found, notes = neighbor_targets(c, [
        neighbor("no-address"),
        neighbor("self", "192.0.2.1"),
        neighbor("phone", "192.0.2.40", caps=("bridge", "telephone")),
        neighbor("station", "192.0.2.41", caps=()),
        neighbor("weird", "not-an-ip"),
        neighbor("outside", "203.0.113.9"),
        neighbor("excluded", "192.0.2.99"),
        neighbor("disabled", "192.0.2.50"),
        neighbor("ok", "192.0.2.60", caps=("router",)),
        neighbor("ok-again", "192.0.2.60"),
    ], depth=1, known_hosts=known_hosts)
    assert [(str(p.target), p.origin, p.depth) for p in found] == [
        ("192.0.2.60:1161", "neighbor", 2)]
    assert "192.0.2.60" in known_hosts
    assert notes == [
        "neighbor phone (192.0.2.40): skipped (capabilities bridge,telephone)",
        "neighbor station (192.0.2.41): skipped (capabilities none)",
        "neighbor outside (203.0.113.9): skipped (outside discovery.allowed)",
        "neighbor excluded (192.0.2.99): skipped (excluded)",
        "neighbor disabled (192.0.2.50): skipped (disabled)",
    ]
    deep, notes = neighbor_targets(c, [neighbor("far", "192.0.2.70")], depth=2, known_hosts=set())
    assert deep == [] and notes == ["neighbor far (192.0.2.70): skipped (max_depth 2)"]
    off = cfg("discovery: {follow_neighbors: false, allowed: [192.0.2.0/24]}")
    assert neighbor_targets(off, [neighbor("x", "192.0.2.8")], 0, set()) == ([], [])


def test_neighbor_with_several_addresses_is_explored_on_the_one_in_scope():
    from snowth_my_net.collect.discovery import neighbor_targets
    from snowth_my_net.collect.tables.neighbors import Neighbor
    from snowth_my_net.config.loader import parse_config_text

    cfg = parse_config_text("discovery:\n  allowed: [192.0.2.0/24]\n")
    oob = Neighbor(protocol="lldp", local_port_num=1, sys_name="core",
                   mgmt_addresses=["10.0.0.9", "192.0.2.10", "2001:db8::1"],
                   caps=frozenset({"bridge"}))
    targets, notes = neighbor_targets(cfg, [oob], 0, set())
    assert [str(t.target) for t in targets] == ["192.0.2.10"] and notes == []

    outside = Neighbor(protocol="lldp", local_port_num=2, sys_name="far",
                       mgmt_addresses=["10.0.0.9", "10.0.0.10"], caps=frozenset({"bridge"}))
    targets, notes = neighbor_targets(cfg, [outside], 0, set())
    assert targets == [] and notes == [
        "neighbor far (10.0.0.9, 10.0.0.10): skipped (outside discovery.allowed)"]

    known = {"192.0.2.10"}
    assert neighbor_targets(cfg, [oob], 0, known)[0] == []      # any known address: skip

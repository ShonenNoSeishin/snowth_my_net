"""VRF discovery and the LLDP-V2 fallback, on fake agents (no lab)."""

from __future__ import annotations

import asyncio

import pytest

from snowth_my_net.collect import functions
from snowth_my_net.collect.model import DeviceResult
from snowth_my_net.collect.tables.neighbors import _split_v2_index, parse_lldp_v2
from snowth_my_net.config.effective import DeviceSettings
from snowth_my_net.snmp import oids
from snowth_my_net.snmp.client import SnmpError, SnmpTimeout
from snowth_my_net.snmp.values import parse_oid
from tests.unit.test_cov_collect_engine import FakeClient

MPLS = oids.MPLS_L3VPN_VRF_OPER_STATUS
CISCO = oids.CV_VRF_NAME


def names(values, setting="auto"):
    return asyncio.run(functions.vrf_names(FakeClient(values), setting))


def test_vrf_names_come_from_cisco_then_mpls_and_are_checked():
    assert names({CISCO + (1,): b"blue", CISCO + (2,): b"dmz"}) == ["blue", "dmz"]
    assert names({CISCO + (1,): b"blue", CISCO + (2,): b"blue"}) == ["blue"]   # no duplicate
    assert names({CISCO + (1,): b"a space", CISCO + (2,): 42}) == []          # not VRF names
    # MPLS-L3VPN: the index is the name, as length + characters
    mpls = {MPLS + (4, 98, 108, 117, 101): 1, MPLS + (3, 100, 109, 122): 1}
    assert sorted(names(mpls)) == ["blue", "dmz"]
    assert names({**mpls, CISCO + (1,): b"cisco-wins"}) == ["cisco-wins"]
    assert names({MPLS + (9, 98, 108, 117, 101): 1}) == []                    # wrong length
    assert names({}) == []


def test_vrf_setting_off_and_explicit_lists():
    values = {CISCO + (1,): b"blue"}
    assert names(values, "off") == []
    assert names(values, ["dmz", "a space", "ok"]) == ["dmz", "ok"]
    assert len(names({}, [f"vrf{i}" for i in range(100)])) == functions.MAX_VRFS


def result(vrfs="auto") -> DeviceResult:
    return DeviceResult(target=None, origin="seed", depth=0,
                        settings=DeviceSettings(vrfs=vrfs))


def run_arp(values, vrfs="auto", context_values=None, fail=None):
    client = FakeClient(values, fail=fail)
    contexts = {}

    def for_context(name, community_suffix=None):
        if fail and name in fail:
            raise fail[name]
        contexts[name] = FakeClient((context_values or {}).get(name, {}))
        return contexts[name]

    client.for_context = for_context
    r = result(vrfs)
    rows = functions.Rows()
    asyncio.run(functions.arp(client, r, rows))
    return r, contexts


def media(ifindex, ip, mac):
    ip_parts = tuple(int(p) for p in ip.split("."))
    return {oids.IP_NET_TO_MEDIA_PHYS_ADDRESS + (ifindex, *ip_parts): bytes.fromhex(
        mac.replace(":", "")),
        oids.IP_NET_TO_MEDIA_TYPE + (ifindex, *ip_parts): 3}


def physical(ifindex, ip, mac):
    ip_parts = tuple(int(p) for p in ip.split("."))
    index = (ifindex, 1, 4, *ip_parts)
    return {oids.IP_NET_TO_PHYSICAL_PHYS_ADDRESS + index: bytes.fromhex(mac.replace(":", "")),
            oids.IP_NET_TO_PHYSICAL_TYPE + index: 3,
            oids.IP_NET_TO_PHYSICAL_STATE + index: 1}


def test_vrf_arp_is_read_in_each_context_and_tagged():
    r, contexts = run_arp(
        {**media(1, "192.0.2.1", "00:00:5e:00:53:01"), **{CISCO + (1,): b"blue"}},
        context_values={"blue": physical(2, "10.0.0.5", "00:00:5e:00:53:02")})
    assert sorted(contexts) == ["blue"]
    assert {(e.ip, e.table) for e in r.arp} == {("192.0.2.1", "media"),
                                                ("10.0.0.5", "physical@blue")}


def test_a_vrf_context_that_fails_is_reported_but_keeps_the_rest():
    with pytest.raises(SnmpError, match="VRF contexts failed: VRF blue: timeout"):
        run_arp({**media(1, "192.0.2.1", "00:00:5e:00:53:01"), CISCO + (1,): b"blue"},
                fail={"blue": SnmpTimeout("no answer")})


def test_many_failing_vrfs_are_summarised():
    values = {CISCO + (i,): f"vrf{i}".encode() for i in range(8)}
    with pytest.raises(SnmpError, match=r"\(\+3 more\)"):
        run_arp(values, fail={f"vrf{i}": SnmpError("boom") for i in range(8)})


def test_lldp_v2_index_and_fallback():
    assert _split_v2_index((1, 42, 1, 128, 194, 0, 0, 14, 7)) == (42, 7)
    assert _split_v2_index((1, 42, 7)) is None                       # an LLDP-MIB index
    rem = {6: {(1, 5, 1, 128, 194, 0, 0, 14, 1): b"\x00\x00\x5e\x00\x53\x01"},
           10: {(1, 5, 1, 128, 194, 0, 0, 14, 1): b"core"}}
    man = {(1, 5, 1, 128, 194, 0, 0, 14, 1, 1, 4, 192, 0, 2, 9): 2,
           (1, 5): 2}                                                # too short: ignored
    neighbours = parse_lldp_v2(rem, man)
    assert len(neighbours) == 1
    assert (neighbours[0].sys_name, neighbours[0].local_ifindex,
            neighbours[0].local_method) == ("core", 5, "lldpv2_ifindex")
    assert neighbours[0].mgmt_addresses == ["192.0.2.9"]


def test_lldp_falls_back_only_when_lldp_mib_is_silent():
    v2 = parse_oid("1.3.111.2.802.1.1.13.1.4.1.1")
    values = {v2 + (10, 1, 5, 1, 128, 194, 0, 0, 14, 1): b"core",
              v2 + (6, 1, 5, 1, 128, 194, 0, 0, 14, 1): b"\x00\x00\x5e\x00\x53\x01"}
    r, rows = DeviceResult(target=None, origin="seed", depth=0, settings=DeviceSettings()), \
        functions.Rows()
    asyncio.run(functions.lldp(FakeClient(values), r, rows))
    assert [n.sys_name for n in r.neighbors] == ["core"]
    empty, rows2 = DeviceResult(target=None, origin="seed", depth=0,
                                settings=DeviceSettings()), functions.Rows()
    asyncio.run(functions.lldp(FakeClient({}), empty, rows2))
    assert empty.neighbors == [] and rows2.count == 0

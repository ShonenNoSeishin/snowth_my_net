"""Two ways a node landed in the wrong place: a quiet trunk, and an address that is the MAC.

Both were found on a real network: HP trunks (``Trk2``) taken for access ports because they
carried fewer MACs than the fallback threshold, and hundreds of Ubiquiti rows whose only
address was the ``fe80::`` form of their own MAC.
"""

from __future__ import annotations

import ipaddress

import pytest

from snowth_my_net.clock import FrozenClock
from snowth_my_net.collect.tables.interfaces import Interface
from snowth_my_net.collect.tables.neighbors import Neighbor
from snowth_my_net.i18n import Translator
from snowth_my_net.merge.nodes import derived_link_local, resolve_mac
from snowth_my_net.merge.view import build_view
from snowth_my_net.state.db import open_db
from snowth_my_net.state.repo import Repo
from tests.unit.test_cov_views import NOW, device, fdb, make_loaded

PHONE = "80:5e:c0:3b:1f:4f"
AP = "1c:0b:8b:c0:eb:62"
LAG_IFINDEX, MEMBER = 300, 5
IFTYPE_LAG = 161


def lab(tmp_path, *, lldp_on_member: bool = True, macs_on_trunk: int = 3):
    """The real shape of the problem: a phone seen on an access port six days ago, then only
    behind the trunk of another switch. LLDP is on the member port, the MAC table reports the
    trunk — exactly what an HP or Aruba switch says."""
    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    week_ago = NOW - 6 * 86400
    early = repo.start_run("collect", week_ago)
    access = device("192.0.2.10", "SW-Access-01", "00:00:5e:00:53:10",
                    interfaces={1: Interface(1, "0/1")}, fdb=[fdb(PHONE, 1)])
    repo.save_device(access, week_ago, early)
    repo.finish_run(early, "ok", week_ago, {"devices": 1})

    run = repo.start_run("collect", NOW)
    filler = [f"00:00:5e:00:60:{i:02x}" for i in range(macs_on_trunk)]
    neighbours = [Neighbor("lldp", MEMBER, MEMBER, "port_name",
                           chassis_id="00:00:5e:00:53:10", port_id="0/1",
                           sys_name="SW-Access-01", caps=frozenset({"bridge"}),
                           mgmt_addresses=["192.0.2.10"])] if lldp_on_member else []
    core = device("192.0.2.11", "Office-SW02", "00:00:5e:00:53:11",
                  interfaces={MEMBER: Interface(MEMBER, "5", lag_ifindex=LAG_IFINDEX),
                              LAG_IFINDEX: Interface(LAG_IFINDEX, "Trk2", if_type=IFTYPE_LAG),
                              7: Interface(7, "7")},
                  fdb=[fdb(PHONE, LAG_IFINDEX), *[fdb(m, LAG_IFINDEX) for m in filler],
                       fdb(AP, 7)],
                  neighbors=neighbours)
    repo.save_device(core, NOW, run)
    repo.finish_run(run, "ok", NOW, {"devices": 2})
    repo.conn.close()
    return make_loaded(tmp_path)


def view_of(loaded):
    """A resolved view; the connection is closed once every node has been read."""
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        view = build_view(loaded, repo, FrozenClock(NOW).now())
        assert view.nodes is not None    # resolve while the connection is open
        return view
    finally:
        repo.conn.close()


# --------------------------------------------------------------------------- the quiet trunk


def test_a_trunk_is_an_uplink_because_its_member_sees_a_switch(tmp_path):
    """The node is behind the trunk, not on it: one position, not two."""
    view = view_of(lab(tmp_path))
    node = next(n for n in view.nodes if n.mac == PHONE)
    places = {(view.device_name(s.device_id), view.port_name(s.device_id, s.ifindex)): s
              for s in node.sightings}
    trunk = places[("Office-SW02", "Trk2")]
    assert trunk.role.role == "uplink"
    assert any("member of this trunk" in detail for _code, detail in trunk.role.reasons)
    assert [view.port_name(p.device_id, p.ifindex) for p in node.positions] == ["0/1"]


def test_without_lldp_anywhere_the_trunk_still_passes_for_an_access_port(tmp_path):
    """What the network showed: a quiet trunk is indistinguishable from a port with a phone."""
    view = view_of(lab(tmp_path, lldp_on_member=False))
    node = next(n for n in view.nodes if n.mac == PHONE)
    ports = sorted(view.port_name(p.device_id, p.ifindex) for p in node.positions)
    assert ports == ["0/1", "Trk2"]              # the two rows the network showed


def test_the_knob_catches_a_trunk_that_carries_no_lldp(tmp_path):
    loaded = lab(tmp_path, lldp_on_member=False)
    loaded.cfg.nodes.lag_is_uplink = True
    view = view_of(loaded)
    node = next(n for n in view.nodes if n.mac == PHONE)
    assert [view.port_name(p.device_id, p.ifindex) for p in node.positions] == ["0/1"]


def test_the_member_port_keeps_its_own_evidence(tmp_path):
    """Inheriting upwards must not take anything away from the member."""
    view = view_of(lab(tmp_path))
    node = next(n for n in view.nodes if n.mac == PHONE)
    assert all(s.role.role in ("uplink", "access") for s in node.sightings)
    links = [(lk.a_port, lk.b_port) for lk in view.links]
    assert ("5", "0/1") in links or ("0/1", "5") in links     # the link itself is unchanged


# --------------------------------------------------------------------------- the address


@pytest.mark.parametrize(("mac", "ip", "expected"), [
    ("1c:0b:8b:c0:eb:62", "fe80::1e0b:8bff:fec0:eb62", True),
    ("1c:6a:1b:62:37:34", "fe80::1e6a:1bff:fe62:3734", True),
    ("1c:0b:8b:c0:eb:62", "fe80::1e0b:8bff:fec0:eb63", False),   # another device's address
    ("1c:0b:8b:c0:eb:62", "fe80::1", False),                     # a configured link-local
    ("1c:0b:8b:c0:eb:62", "192.0.2.5", False),
    ("1c:0b:8b:c0:eb:62", "2001:db8::1e0b:8bff:fec0:eb62", False),   # global, not link-local
    ("1c:0b:8b:c0:eb:62", "not-an-address", False),
    ("00:11:22", "fe80::1e0b:8bff:fec0:eb62", False),            # not a MAC
])
def test_which_addresses_are_only_the_mac_rewritten(mac, ip, expected):
    assert derived_link_local(ip, mac) is expected


def arp_lab(tmp_path, *addresses):
    from snowth_my_net.collect.tables.arp import ArpEntry

    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    run = repo.start_run("collect", NOW)
    router = device("192.0.2.1", "router", "00:00:5e:00:53:01",
                    interfaces={1: Interface(1, "Gi0/1")},
                    arp=[ArpEntry(AP, ip, ipaddress.ip_address(ip).version, 1, "physical")
                         for ip in addresses])
    repo.save_device(router, NOW, run)
    repo.finish_run(run, "ok", NOW, {"devices": 1})
    repo.conn.close()
    return make_loaded(tmp_path)


def test_an_address_that_repeats_the_mac_is_kept_but_never_elected(tmp_path):
    loaded = arp_lab(tmp_path, "fe80::1e0b:8bff:fec0:eb62")
    loaded.cfg.nodes.include_link_local_only = True         # keep the row, to look at it
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        view = build_view(loaded, repo, NOW)
        node = next(n for n in view.nodes if n.mac == AP)
        assert node.current_ip is None                      # honestly: no address known
        assert [i.ip for i in node.ips] == ["fe80::1e0b:8bff:fec0:eb62"]   # still in the list
        loaded.cfg.nodes.elect_link_local = True
        again = build_view(loaded, repo, NOW)
        assert next(n for n in again.nodes if n.mac == AP).current_ip is not None
    finally:
        repo.conn.close()


def test_a_mac_known_by_nothing_but_that_address_is_not_a_row(tmp_path):
    """What a router's IPv6 neighbour cache produces by the hundred: a MAC and six empty
    columns. Left out of the list, still explained when asked about."""
    loaded = arp_lab(tmp_path, "fe80::1e0b:8bff:fec0:eb62")
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        view = build_view(loaded, repo, NOW)
        assert [n.mac for n in view.nodes] == []            # no row at all
        found = view.find(AP)                               # explain still answers for it
        assert found and found[0].excluded.code == "link_local_only"
        assert "neighbour cache" in str(found[0].excluded)
    finally:
        repo.conn.close()


def test_the_same_mac_with_anything_else_stays_a_row(tmp_path):
    """One real address, or one MAC table sighting, and the row is worth showing."""
    with_address = arp_lab(tmp_path / "ip", "fe80::1e0b:8bff:fec0:eb62", "10.1.50.42")
    repo = Repo(open_db(with_address.paths.state_file, readonly=True))
    try:
        assert [n.mac for n in build_view(with_address, repo, NOW).nodes] == [AP]
    finally:
        repo.conn.close()
    seen_on_a_port = lab(tmp_path / "port")                 # the AP is in a MAC table there
    assert AP in [n.mac for n in view_of(seen_on_a_port).nodes]


def test_a_real_address_is_elected_as_before(tmp_path):
    loaded = arp_lab(tmp_path, "fe80::1e0b:8bff:fec0:eb62", "10.1.50.42")
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        view = build_view(loaded, repo, NOW)
        node = next(n for n in view.nodes if n.mac == AP)
        assert node.current_ip.ip == "10.1.50.42"
        assert len(node.ips) == 2                           # the other one is still there
    finally:
        repo.conn.close()


def test_a_link_local_that_is_not_the_mac_is_not_an_answer_either(tmp_path):
    """Windows gives its link-local a random identifier, so it does not repeat the MAC — and it
    is still an address nothing can be reached by."""
    from snowth_my_net.collect.tables.arp import ArpEntry

    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    run = repo.start_run("collect", NOW)
    other = "00:00:5e:00:53:aa"
    router = device("192.0.2.1", "router", "00:00:5e:00:53:01",
                    interfaces={1: Interface(1, "Gi0/1")},
                    arp=[ArpEntry(other, "fe80::1e0b:8bff:fec0:eb62", 6, 1, "physical")])
    repo.save_device(router, NOW, run)
    repo.finish_run(run, "ok", NOW, {"devices": 1})
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    loaded.cfg.nodes.include_link_local_only = True
    rw = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        node = next(n for n in build_view(loaded, rw, NOW).nodes if n.mac == other)
        assert node.current_ip is None                      # nothing elected
        assert [i.ip for i in node.ips] == ["fe80::1e0b:8bff:fec0:eb62"]
        loaded.cfg.nodes.elect_link_local = True
        again = next(n for n in build_view(loaded, rw, NOW).nodes if n.mac == other)
        assert again.current_ip.ip == "fe80::1e0b:8bff:fec0:eb62"
    finally:
        rw.conn.close()


def test_resolve_mac_is_not_confused_by_an_empty_state(tmp_path):
    loaded = arp_lab(tmp_path)
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        view = build_view(loaded, repo, NOW)
        assert resolve_mac(view.ctx, AP).current_ip is None
    finally:
        repo.conn.close()


# --------------------------------------------------------------------------- what it costs


def test_the_report_separates_proof_from_guesswork(tmp_path):
    """"Am I losing data?" is answered by this list, not by reasoning about thresholds."""
    proven = view_of(lab(tmp_path, macs_on_trunk=60)).uplink_ports()
    assert [row["port"] for row in proven] == ["Trk2"]
    assert proven[0]["evidence"] == "proof"           # LLDP on a member, not the count
    assert "member of this trunk" in proven[0]["why"]
    assert proven[0]["macs"] == 61

    guessed = view_of(lab(tmp_path / "other", lldp_on_member=False,
                          macs_on_trunk=60)).uplink_ports()
    assert guessed[0]["evidence"] == "guess"
    assert guessed[0]["codes"] == ["mac_count"]
    assert guessed[0]["orphans"] == 60                # what it costs if the guess is wrong


def test_a_port_under_the_threshold_is_not_in_the_report(tmp_path):
    assert view_of(lab(tmp_path, lldp_on_member=False, macs_on_trunk=3)).uplink_ports() == []


def test_the_guesses_come_first(tmp_path):
    """The rows to look at are the ones held by nothing but a count."""
    rows = view_of(lab(tmp_path, macs_on_trunk=60)).uplink_ports()
    assert [row["evidence"] for row in rows] == sorted(
        (row["evidence"] for row in rows), key=lambda e: e != "guess")


# --------------------------------------------------------------------------- memory vs now


def old_and_new(tmp_path):
    """One MAC seen at both collects, one seen only at the first: memory."""
    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    gone = "00:00:5e:00:70:01"
    week_ago = NOW - 6 * 86400
    early = repo.start_run("collect", week_ago)
    switch = device("192.0.2.20", "sw", "00:00:5e:00:53:20",
                    interfaces={1: Interface(1, "1"), 2: Interface(2, "2")},
                    fdb=[fdb(PHONE, 1), fdb(gone, 2)])
    device_id = repo.save_device(switch, week_ago, early)
    repo.finish_run(early, "ok", week_ago, {"devices": 1})
    run = repo.start_run("collect", NOW)
    again = device("192.0.2.20", "sw", "00:00:5e:00:53:20",
                   interfaces={1: Interface(1, "1"), 2: Interface(2, "2")},
                   fdb=[fdb(PHONE, 1)])
    again.device_id = device_id            # the same switch, polled again
    repo.save_device(again, NOW, run)
    repo.finish_run(run, "ok", NOW, {"devices": 1})
    repo.conn.close()
    return make_loaded(tmp_path), gone


def test_what_the_last_collect_saw_and_what_is_only_remembered(tmp_path):
    loaded, gone = old_and_new(tmp_path)
    view = view_of(loaded)
    live = {n.mac: n.live for n in view.nodes}
    assert live[PHONE] is True
    assert live[gone] is False                    # still listed, but it is memory


def test_a_collect_of_one_address_does_not_make_the_rest_look_gone(tmp_path):
    """The reference is the last full collect: a single-device test must not change the view."""
    loaded, gone = old_and_new(tmp_path)
    repo = Repo(open_db(loaded.paths.state_file))
    try:
        single = repo.start_run("collect", NOW + 60)
        repo.finish_run(single, "ok", NOW + 60, {"devices": 1, "only": ["192.0.2.99"]})
    finally:
        repo.conn.close()
    live = {n.mac: n.live for n in view_of(loaded).nodes}
    assert live[PHONE] is True and live[gone] is False


def test_with_no_collect_yet_nothing_is_called_memory(tmp_path):
    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    run = repo.start_run("collect", NOW)
    repo.save_device(device("192.0.2.20", "sw", "00:00:5e:00:53:20",
                            interfaces={1: Interface(1, "1")}, fdb=[fdb(PHONE, 1)]), NOW, run)
    repo.conn.close()                             # the run was never finished
    assert all(n.live for n in view_of(make_loaded(tmp_path)).nodes)


def test_the_page_can_show_only_what_is_there_now(tmp_path):
    from snowth_my_net.web import pages

    loaded, _gone = old_and_new(tmp_path)
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        everything = pages.nodes(loaded, repo, NOW, Translator("en"), 2000)
        only_live = pages.nodes(loaded, repo, NOW, Translator("en"), 2000, live_only=True)
    finally:
        repo.conn.close()
    assert everything.total == 2 and only_live.total == 1
    assert "1 row(s) are memory" in everything.note
    assert only_live.note == ""
    labels = [label for label, _href, _active in everything.views]
    assert "Seen at the last collect (1)" in labels[0]
    assert "Everything, history included (2)" in labels[1]
    assert [active for _label, _href, active in only_live.views] == [True, False]


def test_forgetting_the_memory_leaves_the_inventory_alone(tmp_path):
    loaded, _gone = old_and_new(tmp_path)
    repo = Repo(open_db(loaded.paths.state_file))
    try:
        counts = repo.forget_nodes()
        assert counts["fdb"] == 2 and counts["arp"] == 0
        assert repo.conn.execute("SELECT COUNT(*) FROM fdb_obs").fetchone()[0] == 0
        assert repo.conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 1
        assert repo.conn.execute("SELECT COUNT(*) FROM interfaces").fetchone()[0] == 2
        assert repo.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
    finally:
        repo.conn.close()
    assert view_of(loaded).nodes == []


def test_the_table_promises_nothing_it_cannot_show(tmp_path):
    """A bare "+1" offered an address to read and held only the MAC again."""
    from snowth_my_net.web import pages

    loaded = arp_lab(tmp_path, "fe80::1e0b:8bff:fec0:eb62")
    loaded.cfg.nodes.include_link_local_only = True          # whoever wants the row anyway
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        table = pages.nodes(loaded, repo, NOW, Translator("en"), 2000)
    finally:
        repo.conn.close()
    row = next(r for r in table.rows if any(AP in str(cell) for cell in r))
    address = row[4]
    assert address.text == "" and address.more == ()        # nothing, honestly
    loaded.cfg.nodes.elect_link_local = True
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        again = pages.nodes(loaded, repo, NOW, Translator("en"), 2000)
    finally:
        repo.conn.close()
    shown = next(r for r in again.rows if any(AP in str(cell) for cell in r))[4]
    assert shown.text == "fe80::1e0b:8bff:fec0:eb62"        # for whoever wants it anyway


# --------------------------------------------------------------------------- what is left out


def ghost_lab(tmp_path):
    """A firewall whose IPv6 neighbour cache holds two families of Ubiquiti MACs; one of those
    families has a sibling that a MAC table does see."""
    from snowth_my_net.collect.tables.arp import ArpEntry

    def link_local(mac):
        octets = [int(part, 16) for part in mac.split(":")]
        octets[0] ^= 0x02
        return "fe80::{:x}{:02x}:{:02x}ff:fe{:02x}:{:02x}{:02x}".format(*octets)

    heard = [f"1c:0b:8b:c0:eb:{i:02x}" for i in range(1, 4)] + ["1c:6a:1b:62:37:01"]
    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    run = repo.start_run("collect", NOW)
    repo.save_device(device("10.0.0.1", "FW", "00:00:5e:00:53:01", "firewall",
                            interfaces={1: Interface(1, "port1")},
                            arp=[ArpEntry(m, link_local(m), 6, 1, "physical") for m in heard]),
                     NOW, run)
    repo.save_device(device("10.0.0.2", "SW", "00:00:5e:00:53:02",
                            interfaces={1: Interface(1, "1")},
                            fdb=[fdb("1c:0b:8b:c0:eb:00", 1), fdb("01:00:5e:00:00:fb", 1)]),
                     NOW, run)
    repo.finish_run(run, "ok", NOW, {"devices": 2})
    repo.conn.close()
    return make_loaded(tmp_path)


def test_what_the_list_leaves_out_and_why(tmp_path):
    rows = view_of(ghost_lab(tmp_path)).left_out()
    reasons = {row["reason"] for row in rows}
    assert reasons == {"link_local_only", "multicast"}
    ghost = next(r for r in rows if r["mac"] == "1c:0b:8b:c0:eb:01")
    assert ghost["vendor"].startswith("Ubiquiti") or ghost["vendor"]
    assert ghost["seen_by"] == ["FW"]
    assert ghost["addresses"] == ["fe80::1e0b:8bff:fec0:eb01"]
    assert ghost["last_seen"] == NOW


def test_siblings_tell_a_second_interface_from_a_stranger(tmp_path):
    """The decisive question: is the same hardware known on a port, under another MAC?"""
    rows = {r["mac"]: r for r in view_of(ghost_lab(tmp_path)).left_out()}
    assert rows["1c:0b:8b:c0:eb:01"]["siblings"] == 1    # 1c:0b:8b:c0:eb:00 is on a port
    assert rows["1c:6a:1b:62:37:01"]["siblings"] == 0    # that family, never on a wire


def test_nothing_is_left_out_of_an_empty_state(tmp_path):
    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    repo.conn.close()
    assert view_of(make_loaded(tmp_path)).left_out() == []


def test_a_windows_laptop_heard_over_ipv6_is_not_a_row_either(tmp_path):
    """Its link-local has a random identifier, so it does not repeat the MAC — and it still
    says nothing but "an IPv6 stack spoke on that segment"."""
    from snowth_my_net.collect.tables.arp import ArpEntry

    intel = "34:fd:70:f0:71:20"
    random_iid = "fe80::10c2:5b7e:7947:5107"
    assert not derived_link_local(random_iid, intel)         # not the MAC rewritten
    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    run = repo.start_run("collect", NOW)
    repo.save_device(device("10.0.0.1", "FW", "00:00:5e:00:53:01", "firewall",
                            interfaces={1: Interface(1, "port1")},
                            arp=[ArpEntry(intel, random_iid, 6, 1, "physical")]), NOW, run)
    repo.finish_run(run, "ok", NOW, {"devices": 1})
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    assert [n.mac for n in view_of(loaded).nodes] == []
    left = view_of(loaded).left_out()
    assert [r["reason"] for r in left] == ["link_local_only"]
    loaded.cfg.nodes.include_link_local_only = True
    node = next(n for n in view_of(loaded).nodes if n.mac == intel)
    assert node.current_ip is None and [i.ip for i in node.ips] == [random_iid]


def test_the_tables_of_the_last_collect_are_listed_with_what_they_returned(tmp_path):
    """"Netdisco gives me a port and you do not" has two causes: a port held as an uplink, or a
    MAC table that was not read. This is how the second one is seen."""
    from snowth_my_net.collect.model import OK, TIMEOUT, Outcome

    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    run = repo.start_run("collect", NOW)
    switch = device("10.0.0.2", "SW", "00:00:5e:00:53:02",
                    interfaces={1: Interface(1, "1")}, fdb=[fdb(PHONE, 1)])
    switch.outcomes["fdb"] = Outcome("fdb", TIMEOUT, 0, detail="per-VLAN bridge instances failed")
    switch.outcomes["arp"] = Outcome("arp", OK, 12)
    repo.save_device(switch, NOW, run)
    repo.finish_run(run, "ok", NOW, {"devices": 1})
    statuses = {s["function"]: s for s in repo.statuses(run)}
    repo.conn.close()
    assert statuses["fdb"]["status"] == "timeout"
    assert "per-VLAN" in statuses["fdb"]["detail"]
    assert statuses["arp"]["rows"] == 12


# --------------------------------------------------------------------------- a VLAN not read


def test_a_vlan_with_ports_and_no_macs_is_reported_not_guessed():
    """Why another tool places a phone on VLAN 81 and this one does not: the bridge instance of
    that VLAN was never read. Said out loud, with the setting that reads it."""
    from snowth_my_net.collect.functions import silent_vlans

    # VLAN 81 is the native VLAN of port 30, and nothing was learned in it.
    said = silent_vlans([1, 30, 81], {30: 81, 2: 1}, {1})
    assert len(said) == 1
    assert "VLAN 81" in said[0] and "vlan_indexing: cisco" in said[0]
    assert "30" not in said[0].split(":")[1]          # VLAN 30 has no port: not suspicious

    # A VLAN nobody is in says nothing, and neither does one that answered.
    assert silent_vlans([1, 90], {2: 1}, {1}) == []
    assert silent_vlans([1, 81], {30: 81}, {1, 81}) == []


def test_many_silent_vlans_are_counted_not_listed_endlessly():
    from snowth_my_net.collect.functions import silent_vlans

    pvids = {port: 100 + port for port in range(12)}
    said = silent_vlans(sorted(pvids.values()), pvids, set())
    assert said[0].count(",") == 7 and "(+4)" in said[0]


def test_a_device_warning_is_printed_after_a_collect(tmp_path):
    """It was only in snapshot.json, where nobody looks after a collect."""
    from snowth_my_net.cli import _render_report
    from snowth_my_net.collect.engine import RunReport

    report = RunReport(command="collect", run_id=7, status="ok")
    result = device("10.0.0.2", "SW", "00:00:5e:00:53:02")
    result.warnings.append("VLAN 81: ports live there but the MAC table returned nothing")
    report.results.append(result)
    printed = _render_report(report, make_loaded(tmp_path))
    assert "note: 10.0.0.2: VLAN 81" in printed


# --------------------------------------------------------------------------- an unmanaged switch


def dumb_switch(tmp_path, how_many: int):
    """A switch nobody manages behind port 7, with that many devices behind it."""
    behind = [f"00:11:22:00:{i // 256:02x}:{i % 256:02x}" for i in range(how_many)]
    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    run = repo.start_run("collect", NOW)
    repo.save_device(device("10.0.0.2", "SW-OFFICE", "00:00:5e:00:53:02",
                            interfaces={7: Interface(7, "Gi1/0/7"), 8: Interface(8, "Gi1/0/8")},
                            fdb=[fdb(m, 7) for m in behind] + [fdb("00:aa:bb:cc:dd:ee", 8)]),
                     NOW, run)
    repo.finish_run(run, "ok", NOW, {"devices": 1})
    repo.conn.close()
    return make_loaded(tmp_path), behind


def test_a_small_unmanaged_switch_needs_no_setting_at_all(tmp_path):
    """Six devices behind a dumb switch: the port is an access port, every one is placed —
    the same answer another tool gives, with no configuration."""
    loaded, behind = dumb_switch(tmp_path, 6)
    view = view_of(loaded)
    placed = [n for n in view.nodes if n.mac in behind and n.positions]
    assert len(placed) == 6
    assert {n.position_kind for n in placed} == {"access"}
    assert {view.port_name(p.device_id, p.ifindex) for n in placed for p in n.positions} == {
        "Gi1/0/7"}


def test_a_crowded_unmanaged_switch_is_where_the_two_tools_differ(tmp_path):
    """Above the threshold the port is held as an uplink, so nothing is placed — and the count
    of what the fallback would recover is what the choice is made on."""
    loaded, behind = dumb_switch(tmp_path, 60)
    view = view_of(loaded)
    assert [n for n in view.nodes if n.mac in behind and n.positions] == []
    assert view.behind_soft_uplinks() == 60

    loaded.cfg.nodes.uplink_fallback = True
    with_fallback = view_of(loaded)
    placed = [n for n in with_fallback.nodes if n.mac in behind and n.positions]
    assert len(placed) == 60
    assert {n.position_kind for n in placed} == {"behind_uplink"}
    assert with_fallback.behind_soft_uplinks() == 0      # nothing left to recover


def test_what_sits_behind_a_switch_we_do_poll_is_not_recovered_that_way(tmp_path):
    """A hard uplink means the device is behind a switch we poll: its real port comes from
    there, and inventing one here would be the false positive to avoid."""
    loaded = lab(tmp_path)                               # LLDP on a member of the trunk
    view = view_of(loaded)
    assert view.behind_soft_uplinks() == 0

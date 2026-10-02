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
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        view = build_view(loaded, repo, NOW)
        node = next(n for n in view.nodes if n.mac == AP)
        assert node.current_ip is None                      # honestly: no address known
        assert [i.ip for i in node.ips] == ["fe80::1e0b:8bff:fec0:eb62"]   # still in the list
        loaded.cfg.nodes.elect_derived_link_local = True
        again = build_view(loaded, repo, NOW)
        assert next(n for n in again.nodes if n.mac == AP).current_ip is not None
    finally:
        repo.conn.close()


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


def test_the_rule_applies_to_the_mac_it_belongs_to(tmp_path):
    """Another MAC's link-local is a real sighting: it is elected when nothing better exists."""
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
    rw = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        node = next(n for n in build_view(loaded, rw, NOW).nodes if n.mac == other)
        assert node.current_ip.ip == "fe80::1e0b:8bff:fec0:eb62"
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
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        table = pages.nodes(loaded, repo, NOW, Translator("en"), 2000)
    finally:
        repo.conn.close()
    row = next(r for r in table.rows if any(AP in str(cell) for cell in r))
    address = row[4]
    assert address.text == "" and address.more == ()        # nothing, honestly
    loaded.cfg.nodes.elect_derived_link_local = True
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        again = pages.nodes(loaded, repo, NOW, Translator("en"), 2000)
    finally:
        repo.conn.close()
    shown = next(r for r in again.rows if any(AP in str(cell) for cell in r))[4]
    assert shown.text == "fe80::1e0b:8bff:fec0:eb62"        # for whoever wants it anyway

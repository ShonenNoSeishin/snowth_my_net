"""Three sources for one hostname: written by hand, held by a zone, stated by the host.

The order of trust is the subject: a name someone wrote down beats a zone, which beats what a
machine says about itself. What the three disagree about is shown rather than settled.
"""

from __future__ import annotations

import ipaddress

import pytest

from snowth_my_net.clock import FrozenClock
from snowth_my_net.collect.tables.arp import ArpEntry
from snowth_my_net.collect.tables.interfaces import Interface
from snowth_my_net.i18n import Translator
from snowth_my_net.merge.view import build_view
from snowth_my_net.names import store_for
from snowth_my_net.state.db import open_db
from snowth_my_net.state.repo import Repo
from snowth_my_net.web import pages
from tests.unit.test_cov_views import NOW, device, fdb, make_loaded

PC = "90:8d:6e:2e:48:33"
ADDRESS = "10.1.50.120"


def lab(tmp_path):
    """One node with an address, so every source has something to name."""
    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    run = repo.start_run("collect", NOW)
    switch = device("10.1.50.1", "SW", "00:00:5e:00:53:01",
                    interfaces={1: Interface(1, "Gi1/0/1")}, fdb=[fdb(PC, 1)],
                    arp=[ArpEntry(PC, ADDRESS, 4, 1, "physical")])
    repo.save_device(switch, NOW, run)
    repo.finish_run(run, "ok", NOW, {"devices": 1})
    repo.conn.close()
    return make_loaded(tmp_path)


def view_of(loaded):
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        view = build_view(loaded, repo, FrozenClock(NOW).now())
        assert view.nodes is not None
        return view
    finally:
        repo.conn.close()


def remember(loaded, name: str, mac: str = PC, source: str = "netbios") -> None:
    repo = Repo(open_db(loaded.paths.state_file))
    try:
        repo.save_probes(source, {ADDRESS: (name, mac, "ok")}, NOW, 3600, 600)
    finally:
        repo.conn.close()


def node_of(view):
    return next(n for n in view.nodes if n.mac == PC)


# --------------------------------------------------------------------------- the order


def test_with_nothing_known_there_is_no_hostname(tmp_path):
    view = view_of(lab(tmp_path))
    assert view.hostname(node_of(view)) == ("", "")


def test_what_the_host_says_is_used_when_nothing_else_names_it(tmp_path):
    loaded = lab(tmp_path)
    remember(loaded, "ACME-FRANK")
    view = view_of(loaded)
    assert view.probed_name(node_of(view)) == "ACME-FRANK"
    assert view.hostname(node_of(view)) == ("ACME-FRANK", "netbios")


def test_a_zone_beats_what_the_host_says(tmp_path):
    loaded = lab(tmp_path)
    remember(loaded, "ACME-FRANK")
    view = view_of(loaded)
    view.dns = {ADDRESS: "frank.example.net"}
    # dns.strip_domain is on in this configuration: the host part is what is shown and used.
    assert view.hostname(node_of(view)) == ("frank", "dns")


def test_a_hand_written_name_beats_both(tmp_path):
    loaded = lab(tmp_path)
    remember(loaded, "ACME-FRANK")
    store_for(loaded.paths).set(PC, "poste-de-frank")
    view = view_of(loaded)
    view.dns = {ADDRESS: "frank.example.net"}
    assert view.hostname(node_of(view)) == ("poste-de-frank", "manual")


# --------------------------------------------------------------------------- the guard


def test_a_name_whose_mac_contradicts_the_row_is_refused(tmp_path):
    """NetBIOS states the adapter's own address: when it is not this node's, the answer came
    from something else and naming this row with it would be the false positive to refuse."""
    loaded = lab(tmp_path)
    remember(loaded, "AUTRE-POSTE", mac="00:11:22:33:44:55")
    view = view_of(loaded)
    assert view.probed_name(node_of(view)) == ""
    assert view.hostname(node_of(view)) == ("", "")


def test_a_host_that_states_no_mac_is_still_believed(tmp_path):
    """mDNS and LLMNR state no address: there is nothing to contradict, so nothing is refused."""
    loaded = lab(tmp_path)
    remember(loaded, "imprimante.local", mac="", source="mdns")
    view = view_of(loaded)
    assert view.hostname(node_of(view)) == ("imprimante.local", "mdns")


def test_a_node_with_no_address_is_never_probed(tmp_path):
    loaded = lab(tmp_path)
    remember(loaded, "ACME-FRANK")
    view = view_of(loaded)
    node = node_of(view)
    node.current_ip = None
    assert view.probed_name(node) == "" and view.hostname(node) == ("", "")


# --------------------------------------------------------------------------- the disagreement


@pytest.mark.parametrize(("manual", "resolved", "clashes"), [
    ("poste-julie", "poste-julie.example.net", False),      # the same, with a domain
    ("POSTE-JULIE", "poste-julie.example.net", False),      # the same, shouted
    ("poste-julie", "poste-frank.example.net", True),       # two different machines
    ("", "poste-julie.example.net", False),                 # only one source: nothing to clash
    ("poste-julie", "", False),
])
def test_when_two_sources_name_the_same_row_differently(tmp_path, manual, resolved, clashes):
    loaded = lab(tmp_path)
    if manual:
        store_for(loaded.paths).set(PC, manual)
    view = view_of(loaded)
    view.dns = {ADDRESS: resolved} if resolved else {}
    assert view.hostnames_disagree(node_of(view)) is clashes


def test_the_table_says_it_above_the_rows_and_can_show_only_those(tmp_path):
    loaded = lab(tmp_path)
    store_for(loaded.paths).set(PC, "poste-julie")
    repo = Repo(open_db(loaded.paths.state_file))
    try:
        repo.save_dns({ADDRESS: ("poste-frank.example.net", "ok")}, NOW, 3600, 600)
    finally:
        repo.conn.close()
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        table = pages.nodes(loaded, repo, NOW, Translator("en"), 2000)
        only = pages.nodes(loaded, repo, NOW, Translator("en"), 2000, disagreeing_only=True)
    finally:
        repo.conn.close()
    assert table.disagreeing == 1
    assert [key for key in table.keys[:3]] == ["hostname_manual", "hostname_dns",
                                               "hostname_probe"]
    assert only.total == 1 and all(row[0].text == "poste-julie" for row in only.rows)
    assert only.rows[0][1].tone == "warn" and only.rows[0][0].text == "poste-julie"


# --------------------------------------------------------------------------- the export


def test_the_exported_name_is_the_best_of_the_three_unless_told_otherwise(tmp_path):
    from snowth_my_net.export.run import nodes_csv

    loaded = lab(tmp_path)
    remember(loaded, "ACME-FRANK")
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        merged = nodes_csv(loaded, repo, NOW).decode()
        loaded.cfg.export.nodes.merge_hostnames = False
        dns_only = nodes_csv(loaded, repo, NOW).decode()
    finally:
        repo.conn.close()
    assert "ACME-FRANK" in merged                          # nothing else names it
    assert "ACME-FRANK" not in dns_only                    # the column is the PTR alone


def test_what_the_snapshot_records_about_a_name(tmp_path):
    from snowth_my_net.merge.explain import node_json

    loaded = lab(tmp_path)
    remember(loaded, "ACME-FRANK")
    view = view_of(loaded)
    recorded = node_json(view, node_of(view))
    assert recorded["hostname"] == {"name": "ACME-FRANK", "source": "netbios"}
    assert recorded["probed_name"] == "ACME-FRANK"


def test_explain_names_every_source_and_the_one_it_kept(tmp_path):
    from snowth_my_net.merge.explain import explain

    loaded = lab(tmp_path)
    remember(loaded, "ACME-FRANK")
    store_for(loaded.paths).set(PC, "poste-de-frank")
    view = view_of(loaded)
    view.dns = {ADDRESS: "frank.example.net"}
    said = " ".join(text for text, _kind in explain(view, PC, Translator("en")))
    assert "ACME-FRANK (netbios)" in said                  # what the host says
    assert "DNS  frank" in said                              # what the zone says
    assert "Hostname used: poste-de-frank (written by hand)" in said
    assert "disagree" in said                                # and the two differ


# --------------------------------------------------------------------------- asking around


def test_only_the_networks_that_were_allowed_are_asked():
    from snowth_my_net.enrich.probe import in_networks

    allowed = [ipaddress.ip_network("10.1.50.0/24")]
    assert in_networks("10.1.50.120", allowed) and not in_networks("10.10.81.9", allowed)
    assert in_networks("10.10.81.9", []), "an empty list means anywhere"


def test_an_export_asks_nothing_unless_a_protocol_is_listed(tmp_path):
    from snowth_my_net.export.run import refresh_probes

    loaded = lab(tmp_path)
    repo = Repo(open_db(loaded.paths.state_file))
    try:
        assert refresh_probes(loaded, repo, [ADDRESS], NOW) == 0
        loaded.cfg.names.probe = ["netbios"]
        loaded.cfg.names.networks = [ipaddress.ip_network("192.0.2.0/24")]
        assert refresh_probes(loaded, repo, [ADDRESS], NOW) == 0    # outside the networks
    finally:
        repo.conn.close()


def test_an_export_asks_once_and_remembers(tmp_path, monkeypatch):
    from snowth_my_net.export import run as export_run

    loaded = lab(tmp_path)
    loaded.cfg.names.probe = ["netbios"]
    asked: list[list[str]] = []

    async def fake(source, ips, timeout, budget, concurrency=20):
        asked.append(list(ips))
        return {ip: ("ACME-FRANK", PC, "ok") for ip in ips}

    monkeypatch.setattr("snowth_my_net.enrich.probe.probe_many", fake)
    repo = Repo(open_db(loaded.paths.state_file))
    try:
        assert export_run.refresh_probes(loaded, repo, [ADDRESS], NOW) == 1
        assert export_run.refresh_probes(loaded, repo, [ADDRESS], NOW) == 0   # still fresh
        assert asked == [[ADDRESS]]
        assert repo.probe_names(NOW) == {ADDRESS: ("ACME-FRANK", "netbios")}
        assert repo.probe_claims(NOW) == {ADDRESS: PC}
        assert repo.forget_probes() == 1
    finally:
        repo.conn.close()


# --------------------------------------------------------------------------- SNMP sysName


def test_a_polled_device_is_named_by_its_sysname_before_what_it_volunteers(tmp_path):
    """A printer answers SNMP with 'IM C3000' and NetBIOS with noise: SNMP wins."""
    loaded = lab(tmp_path)
    remember(loaded, "RNP0026736A5C2B")
    view = view_of(loaded)
    node = node_of(view)
    view.polled = {ADDRESS: (7, "IM C3000")}
    assert view.hostname(node) == ("IM C3000", "snmp")
    view.dns = {ADDRESS: "printer.example.net"}         # a zone still comes first
    assert view.hostname(node)[1] == "dns"


def test_a_sysname_is_not_lent_to_a_node_that_is_not_the_device(tmp_path):
    loaded = lab(tmp_path)
    view = view_of(loaded)
    node = node_of(view)
    view.polled = {ADDRESS: (7, "IM C3000")}
    view.ctx.inputs.device_macs["aa:bb:cc:00:00:01"] = 7   # another MAC owns it
    assert view.snmp_name(node) == ""
    view.ctx.inputs.device_macs[node.mac] = 7
    assert view.snmp_name(node) == "IM C3000"
    view.polled = {ADDRESS: (7, "")}
    assert view.snmp_name(node) == ""                      # nothing reported, nothing claimed

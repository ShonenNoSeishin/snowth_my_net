"""The word "all", the names job (command, schedule, button) and the Unreachable page.

The page's rule is held to the collect's: what it says about a neighbour is what
``neighbor_targets`` decides, for the same input.
"""

from __future__ import annotations

import ipaddress
import re
from types import SimpleNamespace

import pytest

from snowth_my_net.collect.check import config_warnings
from snowth_my_net.collect.discovery import neighbor_targets, unpolled_reason
from snowth_my_net.config.loader import parse_config_text
from snowth_my_net.config.validate import ConfigError
from snowth_my_net.i18n import Translator
from snowth_my_net.schedule.planning import cron_lines
from snowth_my_net.state.db import open_db
from snowth_my_net.state.repo import Repo
from snowth_my_net.web import jobs, pages
from snowth_my_net.web.server import Site
from tests.unit.signed import SignedSite
from tests.unit.test_cov_views import NOW, build_state, make_loaded
from tests.unit.test_cov_web import FixedClock
from tests.unit.test_cov_web_jobs import FakeRunner, wait_for

EN = Translator("en")


# --------------------------------------------------------------------------- the word "all"


@pytest.mark.parametrize("text", [
    "discovery: {allowed: all}", "discovery: {allowed: [all]}", "discovery: {allowed: ALL}",
    "discovery: {allowed: [ All ]}",
])
def test_all_means_every_address_of_both_families(text):
    allowed = parse_config_text(text).discovery.allowed
    assert [str(net) for net in allowed] == ["0.0.0.0/0", "::/0"]


def test_all_sits_beside_other_networks_and_in_names():
    cfg = parse_config_text("discovery: {allowed: [10.0.0.0/8, all]}\n"
                            "names: {probe: [netbios], networks: all}")
    assert [str(n) for n in cfg.discovery.allowed] == ["10.0.0.0/8", "0.0.0.0/0", "::/0"]
    assert [str(n) for n in cfg.names.networks] == ["0.0.0.0/0", "::/0"]


@pytest.mark.parametrize("text", ["discovery: {allowed: everything}", "discovery: {allowed: 7}",
                                  "discovery: {allowed: {a: b}}"])
def test_anything_else_than_a_list_or_all_is_refused_with_the_way_out(text):
    with pytest.raises(ConfigError, match=r"a list of networks, or 'all'"):
        parse_config_text(text)


def test_all_leaves_the_exclusions_and_the_sweep_rule_working():
    """A sweep lies inside "everything", and an exclusion still holds something back."""
    cfg = parse_config_text("discovery: {allowed: all, exclude: [192.0.2.0/24],"
                            " sweep: [10.1.50.0/24]}")
    assert cfg.discovery.check() == []
    from snowth_my_net.collect.discovery import Scope

    scope = Scope(cfg.discovery.allowed, cfg.discovery.exclude, set())
    assert scope.check(ipaddress.ip_address("10.9.9.9")) is None
    assert scope.check(ipaddress.ip_address("2001:db8::1")) is None
    assert scope.check(ipaddress.ip_address("192.0.2.7")) == "excluded"


def test_all_is_warned_about_because_it_sends_credentials_where_a_neighbour_says(tmp_path):
    loaded = make_loaded(tmp_path)
    loaded.cfg.discovery.allowed = parse_config_text("discovery: {allowed: all}"
                                                     ).discovery.allowed
    said = " ".join(config_warnings(loaded))
    assert "discovery.allowed is 'all'" in said and "credentials" in said
    loaded.cfg.discovery.allowed = []
    assert "is 'all'" not in " ".join(config_warnings(loaded))


def test_probing_with_no_network_listed_asks_for_the_choice_to_be_written(tmp_path):
    loaded = make_loaded(tmp_path)
    loaded.cfg.names.probe = ["netbios"]
    assert "names.networks is empty" in " ".join(config_warnings(loaded))
    loaded.cfg.names.networks = parse_config_text("names: {networks: all}").names.networks
    assert "names.networks is empty" not in " ".join(config_warnings(loaded))


# --------------------------------------------------------------------------- the schedule


def test_the_names_job_is_scheduled_only_when_something_can_be_asked(tmp_path):
    loaded = make_loaded(tmp_path)
    loaded.cfg.schedule.names = "30 6 * * *"
    assert not [line for line in cron_lines(loaded) if "names" in line.command]
    assert "schedule.names is set but names.probe is empty" in " ".join(config_warnings(loaded))

    loaded.cfg.names.probe = ["netbios"]
    lines = [line for line in cron_lines(loaded) if "names" in line.command]
    assert len(lines) == 1 and lines[0].schedule == "30 6 * * *"
    assert lines[0].command[-2:] == ["names", "ask"]


def test_a_cron_expression_for_it_is_checked_like_the_others():
    with pytest.raises(ConfigError, match=r"schedule\.names"):
        parse_config_text("schedule: {names: 'not a cron'}")


# --------------------------------------------------------------------------- the command


def test_names_ask_says_what_it_needs_and_what_it_found(tmp_path, monkeypatch, capsys):
    from snowth_my_net import cli
    from snowth_my_net.config.manual import ManualError

    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    monkeypatch.setattr(cli, "load", lambda args: loaded)
    args = SimpleNamespace(json=False, force=False)
    with pytest.raises(ManualError, match=r"names\.probe is empty"):
        cli.cmd_names(args)

    loaded.cfg.names.probe = ["netbios"]
    asked: list[bool] = []

    def refresh(loaded, repo, ips, now, force=False):
        asked.append(force)
        repo.save_probes("netbios", {ips[0]: ("HOST-A", "", "ok")}, now, 3600, 600)
        return len(ips)

    monkeypatch.setattr("snowth_my_net.export.run.refresh_probes", refresh)
    monkeypatch.setattr(cli.Clock, "now", lambda self: NOW)
    assert cli.cmd_names(args) == 0
    said = capsys.readouterr().out
    assert "question(s) sent" in said and "Unreachable page" in said    # some stayed silent
    assert cli.cmd_names(SimpleNamespace(json=True, force=True)) == 0
    import json

    result = json.loads(capsys.readouterr().out)
    assert result["protocols"] == ["netbios"] and result["answered"] == 1
    assert result["silent"] == result["nodes"] - 1
    assert asked == [False, True]                      # --force reaches the questions


def test_an_export_can_leave_the_asking_to_the_names_job(tmp_path, monkeypatch):
    from snowth_my_net.export.run import ViewCache

    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    loaded.cfg.names.probe = ["netbios"]
    calls: list[str] = []
    monkeypatch.setattr("snowth_my_net.export.run.refresh_probes",
                        lambda *a, **k: calls.append("asked") or 0)
    rw = Repo(open_db(loaded.paths.state_file))
    try:
        ViewCache(loaded, rw, NOW).get()
        assert calls == ["asked"]                      # the default: an export still asks
        calls.clear()
        loaded.cfg.names.at_export = False
        ViewCache(loaded, rw, NOW).get()
        assert calls == []                             # now only 'names ask' does
    finally:
        rw.conn.close()


# --------------------------------------------------------------------------- the button


def site_with(tmp_path, probe: bool):
    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    loaded.cfg.names.probe = ["netbios"] if probe else []
    site = SignedSite(loaded)
    site.jobs = FakeRunner()
    return site


def test_the_button_exists_only_when_the_configuration_can_use_it(tmp_path):
    without = site_with(tmp_path / "a", probe=False)
    assert 'value="names"' not in without.respond("/runs", {}, lang="en")[2].decode()
    assert without.start_job("names", "")[0] == 404

    with_probe = site_with(tmp_path / "b", probe=True)
    page = with_probe.respond("/runs", {}, lang="en")[2].decode()
    assert 'value="names"' in page and "Ask names" in page


def test_pressing_it_asks_again_whatever_the_cache_says(tmp_path):
    site = site_with(tmp_path, probe=True)
    assert site.start_job("names", "alice")[:2] == (303, "/runs")
    wait_for(lambda: site.jobs.last is not None)
    assert site.jobs.last.extra == ("--force",)        # a button that does nothing is a mystery


def test_the_job_runs_the_names_command_and_summarises_it():
    runner = jobs.Runner("/c.yml", timeout=10)
    assert runner.argv("names", ("--force",))[-3:] == ["names", "ask", "--force"]
    assert runner.argv("collect")[-1] == "collect"
    done = SimpleNamespace(stdout='{"nodes": 10, "answered": 4}', stderr="", returncode=0)
    assert jobs.summarize("names", done) == "4/10 node(s) named by the host"


# --------------------------------------------------------------------------- the page


def unreachable(tmp_path, *, probe=False, kind=None, **settings):
    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    loaded.cfg.names.probe = ["netbios"] if probe else []
    for key, value in settings.items():
        setattr(loaded.cfg.names, key, value)
    ro = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        return pages.unreachable(loaded, ro, NOW, EN, 2000, kind), loaded
    finally:
        ro.conn.close()


def texts(table):
    return [[getattr(cell, "text", cell) for cell in row] for row in table.rows]


def test_an_address_that_does_not_answer_says_what_was_tried_and_why(tmp_path):
    table, _ = unreachable(tmp_path, kind="snmp")
    [row] = texts(table)
    assert row[:2] == ["SNMP", "192.0.2.200"]
    assert row[4] == "SNMP, every credential"
    assert "no answer" in row[5] and "attempt(s) failed in a row" in row[5]


def test_a_neighbour_that_is_not_polled_says_which_rule_stopped_it(tmp_path):
    table, _ = unreachable(tmp_path, kind="neighbor")
    why = {row[2]: row[5] for row in texts(table)}
    assert why["SEP00005E005377"] == "it announces no management address"
    assert why["core-rtr"] == "outside discovery.allowed"
    assert all(row[4] == "not attempted" for row in texts(table))


def test_a_device_that_is_polled_is_never_listed_as_out_of_reach(tmp_path):
    """sw2 hears itself in this data: a false positive if it ever showed up here."""
    table, _ = unreachable(tmp_path)
    assert "sw2" not in {row[2] for row in texts(table)}
    assert "sw1" not in {row[2] for row in texts(table)}


def test_nodes_are_listed_only_when_a_protocol_is_asked(tmp_path):
    off, _ = unreachable(tmp_path)
    assert not [r for r in texts(off) if r[0] == "Name probe"]
    assert "names.probe is empty" in off.note
    on, _ = unreachable(tmp_path / "x", probe=True)
    rows = [r for r in texts(on) if r[0] == "Name probe"]
    assert rows and all("not asked yet" in r[5] for r in rows)


def test_a_silent_host_an_outside_network_and_a_wrong_mac_are_three_different_reasons(tmp_path):
    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    loaded.cfg.names.probe = ["netbios"]
    loaded.cfg.names.networks = [ipaddress.ip_network("192.0.2.48/29")]    # .48 to .55
    rw = Repo(open_db(loaded.paths.state_file))
    try:
        rw.save_probes("netbios", {"192.0.2.50": ("", "", "none"),
                                   "192.0.2.51": ("POSTE", "00:11:22:33:44:55", "ok")},
                       NOW, 3600, 600)
    finally:
        rw.conn.close()
    ro = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        table = pages.unreachable(loaded, ro, NOW, EN, 2000, "names")
    finally:
        ro.conn.close()
    why = {row[1]: row[5] for row in texts(table)}
    assert why["192.0.2.50"] == "no answer"
    assert "states the MAC 00:11:22:33:44:55" in why["192.0.2.51"]       # dropped, and said
    # 192.0.2.60 lies outside 192.0.2.48/29: it is never asked, and the page says so
    assert "outside names.networks" in why["192.0.2.60"]


def test_the_pills_count_each_kind_and_isolate_it(tmp_path):
    table, _ = unreachable(tmp_path, probe=True)
    labels = [label for label, _href, _active in table.views]
    assert labels[0].startswith("Everything (") and "SNMP (1)" in labels[1]
    assert [href for _l, href, _a in table.views] == [
        "/unreachable", "/unreachable?kind=snmp", "/unreachable?kind=neighbor",
        "/unreachable?kind=names"]
    only, _ = unreachable(tmp_path / "x", probe=True, kind="snmp")
    assert only.total == 1 and [active for _l, _h, active in only.views] == [
        False, True, False, False]


def test_the_tab_is_in_the_navigation_and_renders(tmp_path):
    site = site_with(tmp_path, probe=True)
    status, _type, body = site.respond("/unreachable", {}, lang="en")
    page = body.decode()
    assert status == 200 and 'href="/unreachable"' in page
    assert re.search(r"address\(es\) that do not answer SNMP", page)
    assert "192.0.2.200" in page


# --------------------------------------------------------------------------- the same rule


@pytest.mark.parametrize("caps", [(), ("telephone",), ("station", "telephone"), ("bridge",),
                                  ("router", "telephone")])
@pytest.mark.parametrize("addresses", [(), ("203.0.113.9",), ("192.0.2.9",), ("fe80::1",)])
def test_the_page_and_a_collect_decide_a_neighbour_the_same_way(caps, addresses):
    """What the Unreachable page says is what ``neighbor_targets`` does, input for input."""
    cfg = parse_config_text("discovery: {allowed: [192.0.2.0/24], max_depth: 3}")
    neighbor = SimpleNamespace(sys_name="n", chassis_id="", mgmt_addresses=addresses,
                               caps=frozenset(caps))
    planned, notes = neighbor_targets(cfg, [neighbor], 0, set())
    reason = unpolled_reason(cfg, neighbor)
    if planned:
        assert reason == ""                              # it will be polled: nothing stops it
    elif addresses:
        assert reason, "a neighbour a collect skips must be explained"
        assert notes                                     # and the collect said so too
    else:
        assert reason == "it announces no management address"
        assert notes == []                               # a collect skips it silently


def test_a_neighbour_is_polled_when_following_is_on_and_explained_when_it_is_off():
    cfg = parse_config_text("discovery: {allowed: all}")
    neighbor = SimpleNamespace(sys_name="n", chassis_id="", mgmt_addresses=("198.51.100.1",),
                               caps=frozenset({"bridge"}))
    assert unpolled_reason(cfg, neighbor) == ""
    cfg.discovery.follow_neighbors = False
    assert unpolled_reason(cfg, neighbor) == "discovery.follow_neighbors is off"


def test_a_neighbour_that_is_disabled_by_hand_says_so():
    cfg = parse_config_text("discovery: {allowed: all}\n"
                            "devices: [{address: 198.51.100.1, disabled: true}]")
    neighbor = SimpleNamespace(sys_name="n", chassis_id="", mgmt_addresses=("198.51.100.1",),
                               caps=frozenset({"bridge"}))
    assert unpolled_reason(cfg, neighbor) == "disabled by the configuration"


def test_a_wrong_entry_is_named_by_its_index_even_beside_all():
    """Twenty networks must say which one is wrong; "all" in the middle keeps its place."""
    with pytest.raises(ConfigError) as caught:
        parse_config_text("discovery: {allowed: [10.0.0.0/8, banana, all, 300.1.1.1/8]}")
    problems = "\n".join(str(caught.value).splitlines())
    assert "discovery.allowed[1]: expected an IP address or CIDR, got 'banana'" in problems
    assert "discovery.allowed[3]: expected an IP address or CIDR" in problems
    assert "discovery.allowed[0]" not in problems and "discovery.allowed[2]" not in problems


# --------------------------------------------------------------------------- the corners


def test_an_address_with_a_chosen_credential_names_it_and_counts_its_failures(tmp_path):
    from snowth_my_net.config.schema import CredentialCfg

    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    loaded.cfg.credentials = [CredentialCfg("office", "2c", community_file="x")]
    rw = Repo(open_db(loaded.paths.state_file))
    try:
        rw.ensure_target("10.1.50.77", "manual", 0, NOW)
        rw.set_manual("10.1.50.77", {"credential": "office"}, NOW)
        rw.conn.execute("UPDATE targets SET consecutive_failures = 3 WHERE address = ?",
                        ("10.1.50.77",))
        rw.conn.commit()
    finally:
        rw.conn.close()
    ro = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        table = pages.unreachable(loaded, ro, NOW, EN, 2000, "snmp")
    finally:
        ro.conn.close()
    row = next(r for r in texts(table) if r[1] == "10.1.50.77")
    assert row[4] == "SNMP, office"                     # the credential chosen, by name
    assert row[5] == "never answered · 3 attempt(s) failed in a row"


def test_a_neighbour_heard_twice_or_already_a_target_is_listed_once_or_not_at_all(tmp_path):
    """The same neighbour announced by two ports is one row; one that is a polled address is the
    SNMP row above it, never a second row."""
    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    ro = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        rows = texts(pages.unreachable(loaded, ro, NOW, EN, 2000, "neighbor"))
    finally:
        ro.conn.close()
    names = [row[2] for row in rows]
    assert len(names) == len(set(names))                # no neighbour twice
    assert "192.0.2.200" not in {row[1] for row in rows}   # a polled address is not repeated here


def test_the_banner_offers_the_way_back_when_only_the_clashes_are_shown(tmp_path):
    from snowth_my_net.names import store_for

    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    from tests.unit.test_cov_views import D

    store_for(loaded.paths).set(D, "poste-julie")
    rw = Repo(open_db(loaded.paths.state_file))
    try:
        rw.save_dns({"2001:db8::60": ("poste-frank.example.net", "ok"),
                     "192.0.2.60": ("poste-frank.example.net", "ok")}, NOW, 3600, 600)
    finally:
        rw.conn.close()
    site = Site(loaded, FixedClock())
    page = site.respond("/nodes", {"disagree": ["1"]}, lang="en")[2].decode()
    assert "Show every row" in page and 'href="/nodes"' in page
    assert "Show only those" in site.respond("/nodes", {}, lang="en")[2].decode()


def test_an_export_that_got_answers_reloads_them_into_its_view(tmp_path, monkeypatch):
    from snowth_my_net.export.run import ViewCache

    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    loaded.cfg.names.probe = ["netbios"]
    rw = Repo(open_db(loaded.paths.state_file))
    try:
        def answered(loaded, repo, ips, now, force=False):
            repo.save_probes("netbios", {ips[0]: ("HOST-A", "", "ok")}, now, 3600, 600)
            return 1

        monkeypatch.setattr("snowth_my_net.export.run.refresh_probes", answered)
        view = ViewCache(loaded, rw, NOW).get()
        assert "HOST-A" in {name for name, _source in view.probed.values()}
    finally:
        rw.conn.close()

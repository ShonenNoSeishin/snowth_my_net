"""Port scans of one address: nmap without privilege, kept per address, asked from a page.

The XML below is what ``nmap --unprivileged -sT -sV`` really printed against a Python web server,
from a container with every capability dropped: the parser is held to a real report.
"""

from __future__ import annotations

import ipaddress
import subprocess
from types import SimpleNamespace

import pytest

from snowth_my_net import cli
from snowth_my_net.config.manual import ManualError
from snowth_my_net.config.schema import WebUserCfg
from snowth_my_net.enrich import scan
from snowth_my_net.i18n import Translator
from snowth_my_net.state.db import open_db
from snowth_my_net.state.repo import Repo
from snowth_my_net.web import jobs
from snowth_my_net.web import scan as scanpage
from snowth_my_net.web.server import Site
from tests.unit.test_cov_views import NOW, build_state, make_loaded
from tests.unit.test_cov_web import FixedClock
from tests.unit.test_cov_web_jobs import FakeRunner, wait_for
from tests.unit.test_cov_web_snmp import PASSWORD, signed_in

REPORT = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE nmaprun>
<nmaprun scanner="nmap" args="nmap" version="7.95">
<host starttime="1" endtime="2"><status state="up" reason="user-set" reason_ttl="0"/>
<address addr="192.0.2.21" addrtype="ipv4"/>
<ports><extraports state="closed" count="998"><extrareasons reason="conn-refused" count="998"/>
</extraports>
<port protocol="tcp" portid="80"><state state="open" reason="syn-ack" reason_ttl="0"/>
<service name="http" product="SimpleHTTPServer" version="0.6" extrainfo="Python 3.13.15"
method="probed" conf="10"><cpe>cpe:/a:python:simplehttpserver:0.6</cpe></service></port>
<port protocol="tcp" portid="9100"><state state="open" reason="syn-ack" reason_ttl="0"/>
<service name="jetdirect" method="table" conf="3"/></port>
<port protocol="tcp" portid="23"><state state="filtered" reason="no-response"/></port>
</ports></host>
<host><status state="up" reason="user-set"/><address addr="192.0.2.22" addrtype="ipv4"/>
<ports><extraports state="filtered" count="1000"/></ports></host>
<host><status state="down" reason="no-response"/><address addr="192.0.2.23" addrtype="ipv4"/></host>
<host><status state="up"/><address addr="00:00:5E:00:53:01" addrtype="mac"/></host>
</nmaprun>
"""


# --------------------------------------------------------------------------- the engine


def test_a_real_report_gives_the_open_ports_with_what_listens():
    hosts = {h["address"]: h for h in scan.parse(REPORT)}
    assert hosts["192.0.2.21"]["ports"] == [
        {"port": 80, "proto": "tcp", "state": "open", "service": "http",
         "product": "SimpleHTTPServer", "version": "0.6 Python 3.13.15"},
        {"port": 9100, "proto": "tcp", "state": "open", "service": "jetdirect", "product": "",
         "version": ""}]                                  # a filtered port is not an open one
    assert hosts["192.0.2.21"]["detail"] == ""


def test_a_host_with_nothing_open_says_what_the_rest_was():
    hosts = {h["address"]: h for h in scan.parse(REPORT)}
    assert hosts["192.0.2.22"]["status"] == "ok" and hosts["192.0.2.22"]["ports"] == []
    assert hosts["192.0.2.22"]["detail"] == "1000 filtered"      # silence is not "closed"
    assert hosts["192.0.2.23"]["status"] == "down"
    assert len(hosts) == 3                                        # a MAC-only entry is no address


@pytest.mark.parametrize("xml, message", [
    ('<!DOCTYPE x [<!ENTITY a "b">]><nmaprun/>', "defines entities"),
    ("<nmaprun><host>", "cannot be read"),
])
def test_a_report_that_is_not_safe_or_not_whole_is_refused(xml, message):
    with pytest.raises(scan.ScanError, match=message):
        scan.parse(xml)


def test_targets_are_addresses_and_networks_never_names_or_options():
    assert scan.addresses_of(["192.0.2.0/30", "192.0.2.1", "2001:db8::1"]) == [
        "192.0.2.1", "192.0.2.2", "2001:db8::1"]
    assert scan.addresses_of(["192.0.2.7/32"]) == ["192.0.2.7"]
    for bad in ("printer.example.net", "-iL", "--script=x", "192.0.2.1;ls", ""):
        with pytest.raises(scan.ScanError, match="not an IP address"):
            scan.addresses_of([bad])
    with pytest.raises(scan.ScanError, match="larger than 1024"):
        scan.addresses_of(["10.0.0.0/8"])
    with pytest.raises(scan.ScanError, match="more than 1024 hosts"):
        scan.addresses_of(["10.0.0.0/22", "10.1.0.0/24"])


def test_the_scope_of_discovery_bounds_the_scan_and_names_what_it_left():
    cfg = SimpleNamespace(discovery=SimpleNamespace(
        allowed=[ipaddress.ip_network("192.0.2.0/24")],
        exclude=[ipaddress.ip_network("192.0.2.128/25")], seeds=["198.51.100.9", "a-name"]))
    allowed, skipped = scan.in_scope(cfg, ["192.0.2.5", "192.0.2.200", "203.0.113.1",
                                           "198.51.100.9"])
    assert allowed == ["192.0.2.5", "198.51.100.9"]          # a seed is wanted by name
    assert {s.address: s.reason for s in skipped} == {
        "192.0.2.200": "excluded", "203.0.113.1": "outside discovery.allowed"}


def test_the_command_is_unprivileged_has_no_shell_and_skips_discovery_for_one_host():
    one, allowed = scan.command(["192.0.2.21"], "common")
    assert one[:3] == ["nmap", "--unprivileged", "-sT"] and "-Pn" in one
    assert one[-4:] == ["-oX", "-", "192.0.2.21"][-3:] or one[-3:] == ["-oX", "-", "192.0.2.21"]
    assert "-sV" in one and allowed == 300 + 60
    many, _ = scan.command([f"192.0.2.{n}" for n in range(1, 40)], "quick")
    assert "-Pn" not in many and "-sV" not in many and "100" in many


def fake_nmap(monkeypatch, stdout=REPORT, code=0, stderr="", boom=None):
    seen = []

    def run(argv, **kwargs):
        seen.append(argv)
        if boom:
            raise boom
        return subprocess.CompletedProcess(argv, code, stdout, stderr)

    monkeypatch.setattr(scan.subprocess, "run", run)
    monkeypatch.setattr(scan.shutil, "which", lambda name: "/usr/bin/nmap")
    return seen


def test_running_it_answers_for_every_address_asked(monkeypatch):
    seen = fake_nmap(monkeypatch)
    results = scan.run(["192.0.2.21", "192.0.2.99"], "quick")
    assert [r["address"] for r in results] == ["192.0.2.21", "192.0.2.99"]
    assert results[1]["status"] == "down"
    assert results[1]["detail"] == "no answer to the host discovery"
    assert results[0]["profile"] == "quick" and results[0]["seconds"] == 0.0   # a share is no time
    assert seen[0][0] == "/usr/bin/nmap"
    assert scan.run(["192.0.2.21"], "quick")[0]["seconds"] >= 0


@pytest.mark.parametrize("kwargs, message", [
    ({"code": 1, "stdout": "", "stderr": "x\nQUITTING!"}, "nmap failed: QUITTING!"),
    ({"code": 3, "stdout": ""}, "nmap failed: exit 3"),
    ({"boom": subprocess.TimeoutExpired("nmap", 1)}, "did not finish"),
    ({"boom": PermissionError("no")}, "cannot be started"),
])
def test_a_scan_that_fails_says_why_instead_of_reporting_a_quiet_host(monkeypatch, kwargs, message):
    fake_nmap(monkeypatch, **kwargs)
    with pytest.raises(scan.ScanError, match=message):
        scan.run(["192.0.2.21"], "quick")


def test_without_nmap_the_error_says_where_it_comes_from(monkeypatch):
    monkeypatch.setattr(scan.shutil, "which", lambda name: None)
    with pytest.raises(scan.ScanError, match="Docker image includes it"):
        scan.run(["192.0.2.21"], "quick")


# --------------------------------------------------------------------------- the state


def test_the_last_scan_of_an_address_replaces_the_one_before(tmp_path):
    repo = Repo(open_db(tmp_path / "state.sqlite"))
    ports = [{"port": 80, "proto": "tcp", "state": "open", "service": "http", "product": "",
              "version": ""}]
    repo.save_scans([{"address": "192.0.2.21", "profile": "quick", "status": "ok",
                      "ports": ports, "seconds": 3.5},
                     {"address": "192.0.2.22", "profile": "quick", "status": "down"}], NOW)
    repo.save_scans([{"address": "192.0.2.21", "profile": "all", "status": "ok", "ports": [],
                      "detail": "65535 closed", "seconds": 9.0}], NOW + 60)
    kept = repo.scans()
    assert kept["192.0.2.21"]["profile"] == "all" and kept["192.0.2.21"]["ports"] == []
    assert kept["192.0.2.21"]["scanned_at"] == NOW + 60 and kept["192.0.2.22"]["ports"] == []
    assert list(repo.scans("192.0.2.22")) == ["192.0.2.22"]
    repo.conn.close()


# --------------------------------------------------------------------------- the command


def loaded_for(tmp_path):
    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    loaded.cfg.discovery.allowed = [ipaddress.ip_network("192.0.2.0/24")]
    return loaded


def test_the_command_scans_what_discovery_permits_and_keeps_the_result(
        tmp_path, monkeypatch, capsys):
    loaded = loaded_for(tmp_path)
    monkeypatch.setattr(cli, "load", lambda args: loaded)
    monkeypatch.setattr(cli.Clock, "now", lambda self: NOW)
    fake_nmap(monkeypatch)
    args = SimpleNamespace(json=False, targets=["192.0.2.21", "203.0.113.5"], profile="common")
    assert cli.cmd_scan(args) == 0
    said = capsys.readouterr().out
    assert "192.0.2.21  ok  80/http (SimpleHTTPServer 0.6 Python 3.13.15), 9100/jetdirect" in said
    assert "1 address(es) scanned, 2 open port(s) found; 1 left alone (outside discovery" in said
    ro = Repo(open_db(loaded.paths.state_file, readonly=True))
    assert len(ro.scans()["192.0.2.21"]["ports"]) == 2 and "203.0.113.5" not in ro.scans()
    ro.conn.close()

    args.json = True
    assert cli.cmd_scan(args) == 0
    assert '"open_ports": 2' in capsys.readouterr().out

    assert cli.cmd_show(SimpleNamespace(json=False, what="scans", filter="jetdirect",
                                        limit=0)) == 0
    assert "192.0.2.21" in capsys.readouterr().out
    assert cli.cmd_show(SimpleNamespace(json=True, what="scans", filter="nothing-like-it",
                                        limit=0)) == 0
    assert capsys.readouterr().out.strip() == "[]"


def test_the_command_refuses_what_it_may_not_scan_and_says_why(tmp_path, monkeypatch):
    loaded = loaded_for(tmp_path)
    monkeypatch.setattr(cli, "load", lambda args: loaded)
    fake_nmap(monkeypatch)
    outside = r"203.0.113.5 is outside.*\(and 1 more\)"
    for targets, message in ((["203.0.113.5", "203.0.113.6"], outside),
                             (["printer"], "not an IP address")):
        with pytest.raises(ManualError, match=message):
            cli.cmd_scan(SimpleNamespace(json=False, targets=targets, profile="quick"))
    fake_nmap(monkeypatch, code=1, stdout="", stderr="boom")
    with pytest.raises(ManualError, match="nmap failed: boom"):
        cli.cmd_scan(SimpleNamespace(json=False, targets=["192.0.2.21"], profile="quick"))


# --------------------------------------------------------------------------- the job


def test_the_job_runs_the_scan_command_and_summarises_it():
    runner = jobs.Runner("/c.yml", timeout=10)
    assert runner.argv("scan", ("192.0.2.21", "--profile", "quick"))[-4:] == [
        "scan", "192.0.2.21", "--profile", "quick"]
    one = SimpleNamespace(stdout='{"open_ports": 3, "hosts": [{"address": "192.0.2.21"}]}',
                          stderr="", returncode=0)
    assert jobs.summarize("scan", one) == "3 open port(s) on 192.0.2.21"
    many = SimpleNamespace(stdout='{"open_ports": 9, "hosts": [{}, {}]}', stderr="", returncode=0)
    assert jobs.summarize("scan", many) == "9 open port(s) on 2 addresses"
    assert "scan" not in jobs.ACTIONS and "scan" in jobs.JOBS     # no button on the Runs page


# --------------------------------------------------------------------------- the page


def managed(tmp_path, nmap=True, actions=True, users=True):
    loaded = loaded_for(tmp_path)
    loaded.cfg.web.nmap, loaded.cfg.web.actions = nmap, actions
    if users:
        loaded.cfg.web.auth.users = [WebUserCfg("alice")]
    site = Site(loaded, FixedClock())
    if users:
        site.set_password("alice", PASSWORD)
    site.jobs = FakeRunner()
    return site


def test_the_page_exists_only_with_an_account_buttons_and_the_setting(tmp_path):
    for kwargs in ({"nmap": False}, {"actions": False}, {"users": False}):
        site = managed(tmp_path / str(kwargs), **kwargs)
        assert not site.scannable
        token = signed_in(site) if kwargs != {"users": False} else None
        assert site.respond("/scan", {"address": ["192.0.2.21"]}, token)[0] == 404
        assert site.start_scan({"address": ["192.0.2.21"], "profile": ["quick"]}, "alice")[0] == 404


def test_the_ip_of_a_device_opens_its_scan_page_only_when_scanning_is_on(tmp_path):
    on = managed(tmp_path / "on")
    page = on.respond("/", {}, signed_in(on), lang="en")[2].decode()
    assert 'href="/scan?address=192.0.2.200"' in page
    off = managed(tmp_path / "off", nmap=False)
    assert "/scan?address=" not in off.respond("/", {}, signed_in(off), lang="en")[2].decode()


def test_a_node_page_links_to_the_scan_of_its_address(tmp_path):
    from tests.unit.test_cov_hostnames import ADDRESS, PC, lab

    loaded = lab(tmp_path)
    loaded.cfg.discovery.allowed = [ipaddress.ip_network("10.1.50.0/24")]
    loaded.cfg.web.nmap, loaded.cfg.web.auth.users = True, [WebUserCfg("alice")]
    site = Site(loaded, FixedClock())
    site.set_password("alice", PASSWORD)
    page = site.respond("/node", {"mac": [PC]}, signed_in(site), lang="en")[2].decode()
    assert f'href="/scan?address={ADDRESS}"' in page and f"Scan {ADDRESS}" in page
    loaded.cfg.discovery.allowed = []                    # outside the scope: nothing to offer
    assert "/scan?address=" not in site.respond(
        "/node", {"mac": [PC]}, signed_in(site), lang="en")[2].decode()


def test_the_page_offers_the_profiles_the_result_and_the_command_for_a_network(
        tmp_path, monkeypatch):
    monkeypatch.setattr(scanpage.shutil, "which", lambda name: "/usr/bin/nmap")
    site = managed(tmp_path)
    token = signed_in(site)
    status, _type, body = site.respond("/scan", {"address": ["192.0.2.21"]}, token, lang="en")
    page = body.decode()
    assert status == 200 and "has not been scanned" in page
    for profile in ("quick", "common", "all"):
        assert f'<option value="{profile}"' in page
    assert 'value="common" selected' in page
    assert "snowth_my_net scan 192.0.2.0/24 --profile common" in page
    assert "nmap is not installed" not in page

    rw = Repo(open_db(site.loaded.paths.state_file))
    rw.save_scans([{"address": "192.0.2.21", "profile": "common", "status": "ok", "seconds": 4.2,
                    "ports": scan.parse(REPORT)[0]["ports"]}], NOW)
    rw.conn.close()
    page = site.respond("/scan", {"address": ["192.0.2.21"]}, token, lang="en")[2].decode()
    assert "SimpleHTTPServer" in page and "jetdirect" in page and "4.2 s" in page

    rw = Repo(open_db(site.loaded.paths.state_file))
    rw.save_scans([{"address": "192.0.2.22", "profile": "quick", "status": "ok",
                    "detail": "1000 filtered", "ports": []},
                   {"address": "192.0.2.23", "profile": "quick", "status": "down"}], NOW)
    rw.conn.close()
    assert "Nothing open was found (1000 filtered)" in site.respond(
        "/scan", {"address": ["192.0.2.22"]}, token, lang="en")[2].decode()
    assert "did not answer" in site.respond(
        "/scan", {"address": ["192.0.2.23"]}, token, lang="en")[2].decode()


def test_the_page_says_when_nmap_is_missing_and_when_the_address_is_not_scannable(
        tmp_path, monkeypatch):
    monkeypatch.setattr(scanpage.shutil, "which", lambda name: None)
    site = managed(tmp_path)
    token = signed_in(site)
    assert "nmap is not installed" in site.respond(
        "/scan", {"address": ["192.0.2.21"]}, token, lang="en")[2].decode()
    status, _t, body = site.respond("/scan", {"address": ["203.0.113.5"]}, token, lang="en")
    assert status == 200 and "outside discovery.allowed" in body.decode()
    assert "<form class=\"actions\"" not in body.decode()           # nothing to press
    status, _t, body = site.respond("/scan", {"address": ["printer; ls"]}, token, lang="en")
    assert status == 400 and "is not an IP address" in body.decode()


def test_pressing_the_button_starts_one_scan_and_shows_it_running_then_done(tmp_path):
    site = managed(tmp_path)
    site.jobs = FakeRunner(stdout='{"open_ports": 2, "hosts": [{"address": "192.0.2.21"}]}',
                           seconds=0.3)
    token = signed_in(site)
    form = {"address": ["192.0.2.21"], "profile": ["quick"]}
    assert site.start_scan(form, "alice")[:2] == (303, "/scan?address=192.0.2.21")
    page = site.respond("/scan", {"address": ["192.0.2.21"]}, token, lang="en")[2].decode()
    assert "Port scan running" in page and 'content="5"' in page and " disabled" in page
    assert site.start_scan(form, "alice")[0] == 409                  # one at a time
    wait_for(lambda: site.jobs.last is not None)
    assert site.jobs.last.extra == ("192.0.2.21", "--profile", "quick")
    page = site.respond("/scan", {"address": ["192.0.2.21"]}, token, lang="en")[2].decode()
    assert "Last: Port scan, done" in page and "2 open port(s) on 192.0.2.21" in page
    other = site.respond("/scan", {"address": ["192.0.2.22"]}, token, lang="en")[2].decode()
    assert "Last: Port scan" not in other                           # another address's job


@pytest.mark.parametrize("form", [
    {"address": ["192.0.2.21"], "profile": ["nuclear"]},
    {"address": ["not-an-ip"], "profile": ["quick"]},
    {"address": ["192.0.2.21"]},
])
def test_a_request_with_a_bad_address_or_profile_starts_nothing(tmp_path, form):
    site = managed(tmp_path)
    assert site.start_scan(form, "alice")[0] == 400
    assert site.jobs.current is None and site.jobs.last is None


def test_an_address_outside_the_scope_is_never_started_even_by_a_crafted_request(tmp_path):
    site = managed(tmp_path)
    status, _type, body = site.start_scan(
        {"address": ["203.0.113.5"], "profile": ["quick"]}, "alice")
    assert status == 200 and b"outside discovery.allowed" in body
    assert site.jobs.current is None and site.jobs.last is None


def test_the_post_goes_through_the_login_and_the_server(tmp_path):
    """The route itself: signed out it sends to the login, signed in it starts the job."""
    import threading
    import urllib.error
    import urllib.request

    from snowth_my_net.web.server import WebServer

    site = managed(tmp_path)
    site.jobs = FakeRunner(stdout='{"open_ports": 0, "hosts": []}')
    server = WebServer(("127.0.0.1", 0), site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    data = b"address=192.0.2.21&profile=quick"
    try:
        with pytest.raises(urllib.error.HTTPError) as signed_out:
            opener.open(urllib.request.Request(base + "/scan", data=data))
        assert signed_out.value.code == 303 and signed_out.value.headers["Location"] == "/login"
        token = signed_in(site)
        request = urllib.request.Request(base + "/scan", data=data,
                                         headers={"Cookie": f"snowth_session={token}"})
        with pytest.raises(urllib.error.HTTPError) as started:
            opener.open(request)
        assert started.value.code == 303
        assert started.value.headers["Location"] == "/scan?address=192.0.2.21"
        wait_for(lambda: site.jobs.last is not None)
    finally:
        server.shutdown()
        server.server_close()


def test_the_helper_of_the_page_builds_a_network_around_either_family():
    assert scanpage.network_of("192.0.2.77") == "192.0.2.0/24"
    assert scanpage.network_of("2001:db8::5") == "2001:db8::/64"
    assert scanpage.parse_address(" 2001:DB8::5 ") == "2001:db8::5"
    assert scanpage.parse_address("1.2.3") is None


def test_check_warns_when_the_setting_cannot_have_any_effect(tmp_path):
    from snowth_my_net.collect.check import config_warnings

    loaded = loaded_for(tmp_path)
    loaded.cfg.web.nmap = True
    assert any("web.nmap is on" in w for w in config_warnings(loaded))
    loaded.cfg.web.auth.users = [WebUserCfg("alice")]
    assert not any("web.nmap" in w for w in config_warnings(loaded))
    loaded.cfg.web.actions = False
    assert any("web.nmap is on" in w for w in config_warnings(loaded))


def host(address, ports, status="ok"):
    return {"address": address, "status": status, "detail": "",
            "ports": [{"port": p, "proto": "tcp", "state": "open", "service": "x",
                       "product": "", "version": ""} for p in ports]}


def test_the_same_answer_from_most_addresses_is_a_device_in_the_path_not_the_hosts():
    results = [host(f"10.0.0.{i}", [80, 443]) for i in range(1, 9)]
    results += [host("10.0.0.9", []), host("10.0.0.10", [], "down")]
    assert scan.flag_shared(results) == 8
    assert {r["status"] for r in results[:8]} == {"suspect"}
    assert "same open ports (80/tcp, 443/tcp)" in results[0]["detail"]
    assert results[8]["status"] == "ok" and results[9]["status"] == "down"


def test_a_real_fleet_and_a_small_scan_are_left_alone():
    varied = [host("10.0.0.1", [22]), host("10.0.0.2", [80, 443]), host("10.0.0.3", [80, 443]),
              host("10.0.0.4", [445]), host("10.0.0.5", [631]), host("10.0.0.6", [80])]
    assert scan.flag_shared(varied) == 0
    few = [host(f"10.0.0.{i}", [80, 443]) for i in range(1, 5)]       # four alike: not a pattern
    assert scan.flag_shared(few) == 0
    mixed = [host(f"10.0.0.{i}", [80, 443]) for i in range(1, 6)]     # five alike among a dozen
    mixed += [host(f"10.0.1.{i}", [i + 1000]) for i in range(1, 9)]
    assert scan.flag_shared(mixed) == 0


def test_a_suspect_host_is_shown_as_not_trusted(tmp_path):
    stored = {**host("10.0.0.1", [80]), "status": "suspect", "detail": "8 addresses answer",
              "profile": "quick", "seconds": 0.0, "scanned_at": 1_700_000_000}
    html = scanpage._result(Translator("en"), stored)
    assert "Not trusted" in html and "8 addresses answer" in html and "<table" not in html

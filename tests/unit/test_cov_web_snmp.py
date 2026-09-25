"""The SNMP connections page: what it shows, what it refuses, and what it never prints."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus

import pytest

from snowth_my_net.config.manual import ManualError
from snowth_my_net.config.schema import WebUserCfg
from snowth_my_net.i18n import Translator
from snowth_my_net.state.db import open_db
from snowth_my_net.state.repo import Repo
from snowth_my_net.web import snmp
from snowth_my_net.web.server import Site
from tests.unit.test_cov_views import build_state, make_loaded
from tests.unit.test_cov_web import FixedClock
from tests.unit.test_cov_web_jobs import FakeRunner, wait_for

PASSWORD = "un-mot-de-passe-qui-va-bien"
COMMUNITY = "la-communaute-tres-secrete"
NOW = 1_800_000_000


def managed(tmp_path, actions: bool = True, credentials: bool = True):
    """A site with an account, its password known, and something to manage."""
    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    loaded.cfg.web.auth.users = [WebUserCfg("alice")]
    loaded.cfg.web.actions = actions
    if credentials:
        from snowth_my_net.config.schema import CredentialCfg

        secrets = loaded.paths.secrets_dir
        secrets.mkdir(parents=True, exist_ok=True)
        (secrets / "community_office").write_text(COMMUNITY)
        loaded.cfg.credentials = [
            CredentialCfg("office", "2c", community_file="community_office"),
            CredentialCfg("legacy", "2c", community_file="community_office"),
        ]
    site = Site(loaded, FixedClock())
    site.set_password("alice", PASSWORD)
    return site


def signed_in(site):
    _status, _where, _body, token = site.sign_in(
        {"user": ["alice"], "password": [PASSWORD]}, "10.0.0.1")
    return token


def confirmed(site):
    token = signed_in(site)
    site.confirm("alice", PASSWORD, token, "10.0.0.1")
    return token


def writing(site) -> Repo:
    return Repo(open_db(site.loaded.paths.state_file))


# --------------------------------------------------------------------------- the data


def test_every_polled_address_is_listed_with_why_it_fails(tmp_path):
    site = managed(tmp_path)
    repo = writing(site)
    try:
        repo.ensure_target("10.1.50.77", "manual", 0, NOW)
        repo.ensure_target("192.0.2.222", "neighbor", 1, NOW)
        repo.conn.execute("UPDATE targets SET is_alias = 1 WHERE address = ?", ("192.0.2.222",))
        repo.conn.commit()
        rows = snmp.connections(site.loaded, repo)
    finally:
        repo.conn.close()
    by_host = {row.host: row for row in rows}
    assert "192.0.2.222" not in by_host                    # an alias is not a connection
    assert by_host["10.1.50.77"].status == "never" and by_host["10.1.50.77"].origin == "manual"
    failing = by_host["192.0.2.200"]
    assert failing.status == "failed" and failing.error and failing.failures >= 1


def test_an_address_is_added_and_removed_by_hand(tmp_path):
    site = managed(tmp_path)
    repo = writing(site)
    try:
        assert snmp.add_target(repo, "10.1.50.77:161", NOW) == "10.1.50.77"
        assert "10.1.50.77" in {row.host for row in snmp.connections(site.loaded, repo)}
        assert snmp.remove_target(repo, "10.1.50.77") == "10.1.50.77"
        assert "10.1.50.77" not in {row.host for row in snmp.connections(site.loaded, repo)}
        with pytest.raises(ManualError, match="not an IP address"):
            snmp.add_target(repo, "sw-office", NOW)
    finally:
        repo.conn.close()


def test_a_credential_is_chosen_by_name_and_only_a_known_one(tmp_path):
    site = managed(tmp_path)
    repo = writing(site)
    try:
        assert snmp.credential_names(site.loaded) == ["office", "legacy"]
        assert snmp.set_credential(site.loaded, repo, "192.0.2.200", "office", NOW) == "office"
        chosen = {row.host: row for row in snmp.connections(site.loaded, repo)}
        assert chosen["192.0.2.200"].credential == "office"
        assert chosen["192.0.2.200"].credential_source == "manual"
        with pytest.raises(ManualError, match="no credential named"):
            snmp.set_credential(site.loaded, repo, "192.0.2.200", "invented", NOW)
        assert snmp.set_credential(site.loaded, repo, "192.0.2.200", "", NOW) == ""
        again = {row.host: row for row in snmp.connections(site.loaded, repo)}
        assert again["192.0.2.200"].credential == ""       # back to "whichever answers"
    finally:
        repo.conn.close()


# --------------------------------------------------------------------------- the page


def test_the_page_never_prints_a_community(tmp_path):
    """The rule: names of credentials, never their value."""
    site = managed(tmp_path)
    token = confirmed(site)
    page = site.respond("/snmp", {}, token)[2].decode()
    assert COMMUNITY not in page
    assert "community_office" not in page                  # not even the file it lives in
    assert "office" in page and "legacy" in page           # the names, to choose from


def test_the_password_is_asked_again_before_the_page_opens(tmp_path):
    site = managed(tmp_path)
    token = signed_in(site)
    locked = site.respond("/snmp", {}, token, "en")[2].decode()
    assert 'name="password"' in locked and "Type your password again" in locked
    assert "192.0.2.200" not in locked                     # nothing of the page itself
    assert site.confirm("alice", PASSWORD, token, "10.0.0.1")[:2] == (HTTPStatus.SEE_OTHER,
                                                                     "/snmp")
    assert "192.0.2.200" in site.respond("/snmp", {}, token)[2].decode()


def test_a_wrong_confirmation_is_refused_and_counted(tmp_path):
    from snowth_my_net.web import auth

    site = managed(tmp_path)
    token = signed_in(site)
    status, _type, body = site.confirm("alice", "faux", token, "10.0.0.2", Translator("en"))
    assert status == HTTPStatus.UNAUTHORIZED and "Wrong" in body.decode()
    assert not site.sessions.confirmed(token)
    for _ in range(auth.MAX_FAILURES):
        site.confirm("alice", "faux", token, "10.0.0.2")
    status, _type, body = site.confirm("alice", PASSWORD, token, "10.0.0.2", Translator("en"))
    assert status == HTTPStatus.TOO_MANY_REQUESTS         # the good one waits too
    assert not site.sessions.confirmed(token)


def test_signing_out_forgets_the_confirmation(tmp_path):
    site = managed(tmp_path)
    token = confirmed(site)
    assert site.sessions.confirmed(token)
    site.sessions.close(token)
    assert not site.sessions.confirmed(token)


def test_the_confirmation_ages(tmp_path):
    site = managed(tmp_path)
    token = confirmed(site)
    assert site.sessions.confirmed(token, within=1)
    assert not site.sessions.confirmed(token, within=0)   # nothing lasts forever
    assert not site.sessions.confirmed("another-token")


def test_no_page_at_all_without_an_account_or_with_actions_off(tmp_path):
    bare = Site(make_loaded(tmp_path), FixedClock())      # no account: nothing to type again
    build_state(tmp_path).conn.close()
    assert bare.respond("/snmp", {})[0] == HTTPStatus.NOT_FOUND
    assert not bare.manageable
    off = managed(tmp_path, actions=False)
    assert off.respond("/snmp", {}, confirmed(off))[0] == HTTPStatus.NOT_FOUND
    assert "/snmp" not in off.shell("/", "x", "", t=Translator("en")).decode()


def test_the_tab_is_there_when_it_can_be_used(tmp_path):
    site = managed(tmp_path)
    assert 'href="/snmp"' in site.shell("/", "x", "", t=Translator("en")).decode()


# --------------------------------------------------------------------------- the changes


def test_adding_and_removing_from_the_page(tmp_path):
    site = managed(tmp_path)
    status, _type, body = site.manage_snmp({"do": ["add"], "address": ["10.1.50.77"]},
                                           "alice", Translator("en"))
    assert status == HTTPStatus.OK and "will be polled" in body.decode()
    assert "10.1.50.77" in body.decode().split("<tbody>")[1]
    status, _type, body = site.manage_snmp({"do": ["remove"], "address": ["10.1.50.77"]},
                                           "alice", Translator("en"))
    assert status == HTTPStatus.OK and "no longer polled" in body.decode()
    assert "10.1.50.77" not in body.decode().split("<tbody>")[1]   # gone from the table


def test_choosing_a_credential_from_the_page(tmp_path):
    site = managed(tmp_path)
    status, _type, body = site.manage_snmp(
        {"do": ["credential"], "address": ["192.0.2.200"], "credential": ["office"]},
        "alice", Translator("en"))
    assert status == HTTPStatus.OK and "192.0.2.200: office" in body.decode()
    assert 'value="office" selected' in body.decode()
    status, _type, body = site.manage_snmp(
        {"do": ["credential"], "address": ["192.0.2.200"], "credential": ["invented"]},
        "alice", Translator("en"))
    assert status == HTTPStatus.BAD_REQUEST and "no credential named" in body.decode()


def test_testing_one_address_starts_a_collect_for_it_alone(tmp_path):
    site = managed(tmp_path)
    site.jobs = FakeRunner()
    status, _type, body = site.manage_snmp({"do": ["test"], "address": ["192.0.2.200"]},
                                           "alice", Translator("en"))
    assert status == HTTPStatus.OK and "Testing 192.0.2.200" in body.decode()
    wait_for(lambda: site.jobs.last is not None)
    assert site.jobs.last.extra == ("--device", "192.0.2.200")
    assert site.jobs.last.what == "collect"


def test_a_test_waits_for_whatever_is_running(tmp_path):
    site = managed(tmp_path)
    site.jobs = FakeRunner(seconds=0.4)
    site.jobs.start("collect", "alice")
    status, _type, body = site.manage_snmp({"do": ["test"], "address": ["192.0.2.200"]},
                                           "alice", Translator("en"))
    assert status == HTTPStatus.BAD_REQUEST and "already running" in body.decode()
    wait_for(lambda: site.jobs.current is None)


def test_an_action_nobody_offers_changes_nothing(tmp_path):
    site = managed(tmp_path)
    assert site.manage_snmp({"do": ["drop-everything"], "address": ["1.2.3.4"]},
                            "alice")[0] == HTTPStatus.NOT_FOUND


# --------------------------------------------------------------------------- over HTTP


@pytest.fixture
def running(tmp_path):
    import threading

    from snowth_my_net.web.server import build

    site_config = managed(tmp_path).loaded
    server = build(site_config, "127.0.0.1", 0, FixedClock())
    server.site.set_password("alice", PASSWORD)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", server.site
    server.shutdown()
    server.server_close()


def browser():
    from http.cookiejar import CookieJar

    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def test_the_whole_walk_from_the_browser(running):
    base, site = running
    opener = browser()
    with opener.open(base + "/login", urllib.parse.urlencode(
            {"user": "alice", "password": PASSWORD, "next": "/snmp"}).encode()) as response:
        assert response.url.endswith("/snmp")
        assert 'name="password"' in response.read().decode()      # asked again, right away
    with opener.open(base + "/snmp", urllib.parse.urlencode(
            {"do": "add", "address": "10.1.50.77"}).encode()) as response:
        assert response.url.endswith("/snmp")                      # refused: not confirmed yet
    assert "10.1.50.77" not in {row.host for row in _rows(site)}
    with opener.open(base + "/confirm",
                     urllib.parse.urlencode({"password": PASSWORD}).encode()) as response:
        assert response.url.endswith("/snmp")
        assert "10.1.50.77" not in response.read().decode()
    with opener.open(base + "/snmp", urllib.parse.urlencode(
            {"do": "add", "address": "10.1.50.77"}).encode()) as response:
        assert "10.1.50.77" in response.read().decode()
    assert "10.1.50.77" in {row.host for row in _rows(site)}


def _rows(site):
    repo = Repo(open_db(site.loaded.paths.state_file, readonly=True))
    try:
        return snmp.connections(site.loaded, repo)
    finally:
        repo.conn.close()


def test_nobody_manages_anything_without_signing_in(running):
    base, site = running
    form = urllib.parse.urlencode({"do": "add", "address": "10.1.50.99"}).encode()
    with urllib.request.urlopen(base + "/snmp", form) as response:
        assert response.url.endswith("/login")
    assert "10.1.50.99" not in {row.host for row in _rows(site)}


def test_nothing_is_managed_when_the_tab_does_not_exist(tmp_path):
    """With web.actions off, the POST is not a hidden way in."""
    import threading

    from snowth_my_net.web.server import build

    loaded = managed(tmp_path, actions=False).loaded
    server = build(loaded, "127.0.0.1", 0, FixedClock())
    server.site.set_password("alice", PASSWORD)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        form = urllib.parse.urlencode({"do": "add", "address": "10.1.50.99"}).encode()
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(base + "/snmp", form)
        assert caught.value.code == HTTPStatus.NOT_FOUND
    finally:
        server.shutdown()
        server.server_close()

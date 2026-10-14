"""Login of the web interface: hashes, sessions, rate limit, and what stays open."""

from __future__ import annotations

import threading
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.cookiejar import CookieJar

import pytest

from snowth_my_net.config.validate import ConfigError
from snowth_my_net.web import auth
from snowth_my_net.web.server import Site, build, load_accounts, safe_target
from tests.unit.test_cov_views import build_state, make_loaded
from tests.unit.test_cov_web import FixedClock

PASSWORD = "un-mot-de-passe-qui-va-bien"


def test_hash_is_salted_and_verifies_in_both_directions():
    first, second = auth.hash_password(PASSWORD), auth.hash_password(PASSWORD)
    assert first != second                                   # salted
    assert first.startswith("scrypt$16384$8$1$")
    assert auth.verify_password(PASSWORD, first)
    assert not auth.verify_password(PASSWORD + " ", first)
    assert not auth.verify_password("", first)


@pytest.mark.parametrize("broken", [
    "", "pbkdf2$1$2$3$c2FsdA==$aGFzaA==", "scrypt$16384$8$1$not-base64$aGFzaA==",
    "scrypt$x$8$1$c2FsdA==$aGFzaA==", "scrypt$16384$8$1$c2FsdA==", "plain-text-password",
])
def test_an_unreadable_hash_never_lets_anyone_in(broken):
    assert not auth.verify_password(PASSWORD, broken)


def test_a_hash_with_impossible_parameters_is_refused_not_raised():
    """Well-formed, but scrypt itself rejects a cost that is not a power of two."""
    assert not auth.verify_password(PASSWORD, "scrypt$3$8$1$c2FsdA==$aGFzaA==")


def test_sessions_expire_and_can_be_closed():
    now = [0.0]
    sessions = auth.Sessions(lifetime=60, clock=lambda: now[0])
    token = sessions.open("alice")
    now[0] = 10
    assert sessions.user_of(token) == "alice"
    now[0] = 100
    assert sessions.user_of(token) is None                 # expired
    assert sessions.count == 0
    fresh = auth.Sessions(lifetime=60, clock=lambda: 0)
    other = fresh.open("alice")
    assert fresh.user_of(None) is None and fresh.user_of("nope") is None
    fresh.close(other)
    fresh.close(None)
    assert fresh.user_of(other) is None and fresh.count == 0


def test_use_renews_a_session_up_to_the_absolute_cap():
    now = [0.0]
    sessions = auth.Sessions(lifetime=60, max_lifetime=300, clock=lambda: now[0])
    token = sessions.open("alice")
    for moment in (50, 100, 150, 200, 250):                 # always used within the idle window
        now[0] = moment
        assert sessions.user_of(token) == "alice"
    now[0] = 300
    assert sessions.user_of(token) is None                  # active, but the cap is absolute
    assert sessions.refusal(token) == "cap"


def test_an_idle_session_says_why_it_was_refused():
    now = [0.0]
    sessions = auth.Sessions(lifetime=60, max_lifetime=300, clock=lambda: now[0])
    token, other = sessions.open("a"), sessions.open("b")
    assert sessions.refusal(None) == "none" and sessions.refusal("nope") == "unknown"
    sessions.close(other)
    assert sessions.refusal(other) == "closed"
    now[0] = 61
    assert sessions.user_of(token) is None and sessions.refusal(token) == "idle"


def test_sessions_survive_a_restart_without_the_token_on_disk(tmp_path):
    path = tmp_path / "sessions.json"
    now = [1000.0]
    first = auth.Sessions(lifetime=60, max_lifetime=300, clock=lambda: now[0], path=path)
    token = first.open("alice")
    assert token not in path.read_text() and path.stat().st_mode & 0o777 == 0o600
    now[0] = 1030
    second = auth.Sessions(lifetime=60, max_lifetime=300, clock=lambda: now[0], path=path)
    assert second.user_of(token) == "alice"                  # the restart did not sign out
    second.close(token)
    assert auth.Sessions(lifetime=60, clock=lambda: now[0], path=path).user_of(token) is None
    path.write_text("{ not json")
    assert auth.Sessions(lifetime=60, clock=lambda: now[0], path=path).count == 0


def test_purging_drops_every_expired_session():
    now = [0.0]
    sessions = auth.Sessions(lifetime=60, clock=lambda: now[0])
    sessions.open("a"), sessions.open("b")
    now[0] = 61
    sessions.purge()
    assert sessions._open == {}


def test_two_sessions_are_independent():
    sessions = auth.Sessions(lifetime=60, clock=lambda: 0)
    first, second = sessions.open("a"), sessions.open("b")
    assert first != second and sessions.count == 2
    sessions.close(first)
    assert sessions.user_of(second) == "b" and sessions.user_of(first) is None


def test_the_limiter_locks_then_forgets():
    now = [0.0]
    limiter = auth.LoginLimiter(max_failures=3, lockout=30, clock=lambda: now[0])
    for _ in range(2):
        limiter.failed("10.0.0.1")
    assert limiter.locked_for("10.0.0.1") == 0
    limiter.failed("10.0.0.1")
    assert limiter.locked_for("10.0.0.1") == 30
    assert limiter.locked_for("10.0.0.2") == 0             # per address
    now[0] = 31
    assert limiter.locked_for("10.0.0.1") == 0             # the window has passed
    limiter.failed("10.0.0.1")
    limiter.succeeded("10.0.0.1")
    assert limiter.locked_for("10.0.0.1") == 0


@pytest.mark.parametrize(("header", "expected"), [
    ("snowth_session=abc", "abc"), ("other=1; snowth_session=abc; x=2", "abc"),
    ("snowth_session=", None), ("other=1", None), (None, None), ("", None),
])
def test_cookie_parsing(header, expected):
    assert auth.parse_cookie(header) == expected


@pytest.mark.parametrize(("target", "expected"), [
    ("/nodes", "/nodes"), ("/node?mac=aa", "/node?mac=aa"),
    ("//evil.example.com", "/"), ("https://evil.example.com", "/"), ("", "/"),
    ("/\\evil.example.com", "/"),
])
def test_a_login_never_redirects_off_site(target, expected):
    assert safe_target(target) == expected


# --------------------------------------------------------------------------- with accounts


def guarded_config(tmp_path, password: str = PASSWORD, extra: str = ""):
    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    secrets = loaded.paths.secrets_dir
    secrets.mkdir(parents=True, exist_ok=True)
    (secrets / "web_alice").write_text(auth.hash_password(password))
    from snowth_my_net.config.schema import WebUserCfg

    loaded.cfg.web.auth.users = [WebUserCfg("alice", password_file="web_alice")]
    return loaded


def test_accounts_come_from_files_and_a_missing_one_is_an_error(tmp_path):
    loaded = guarded_config(tmp_path)
    accounts = load_accounts(loaded)
    assert list(accounts) == ["alice"] and accounts["alice"].startswith("scrypt$")
    loaded.cfg.web.auth.users[0].password_file = "absent"
    with pytest.raises(ConfigError, match="cannot read secret file"):
        load_accounts(loaded)


def test_without_accounts_nothing_is_guarded(tmp_path):
    repo = build_state(tmp_path)
    repo.conn.close()
    site = Site(make_loaded(tmp_path), FixedClock())
    assert not site.guarded
    assert site.respond("/", {})[0] == 200


@pytest.fixture
def guarded(tmp_path):
    running = build(guarded_config(tmp_path), "127.0.0.1", 0, FixedClock())
    thread = threading.Thread(target=running.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{running.server_address[1]}", running.site
    running.shutdown()
    running.server_close()


def browser():
    jar = CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), jar


def sign_in(opener, base, user="alice", password=PASSWORD, target="/"):
    data = urllib.parse.urlencode({"user": user, "password": password, "next": target})
    return opener.open(base + "/login", data.encode())


def test_a_page_asks_for_a_login_and_then_shows_itself(guarded):
    base, site = guarded
    opener, jar = browser()
    with opener.open(base + "/nodes") as response:
        assert response.url.endswith("/login?next=%2Fnodes")
        page = response.read().decode()                     # read once: the body is a stream
    assert "Utilisateur" in page or "User" in page
    assert 'name="password"' in page and "sw1" not in page
    assert [c.name for c in jar] == []                     # no cookie before signing in

    with sign_in(opener, base, target="/nodes") as response:
        assert response.status == 200 and response.url == base + "/nodes"
    cookie = next(iter(jar))
    assert cookie.name == auth.COOKIE and cookie.value
    assert "HttpOnly" in str(cookie._rest) and cookie._rest.get("SameSite") == "Strict"
    assert site.sessions.user_of(cookie.value) == "alice"
    assert cookie.expires is not None                      # a closed browser keeps the session

    with opener.open(base + "/") as response:
        assert response.status == 200 and "sw1" in response.read().decode()


def test_a_wrong_password_is_refused_and_counted(guarded):
    base, site = guarded
    opener, jar = browser()
    with pytest.raises(urllib.error.HTTPError) as caught:
        sign_in(opener, base, password="faux")
    assert caught.value.code == HTTPStatus.UNAUTHORIZED
    body = caught.value.read().decode()
    assert ("incorrect" in body or "Wrong" in body) and "faux" not in body
    assert [c.name for c in jar] == [] and site.sessions.count == 0
    with pytest.raises(urllib.error.HTTPError) as caught:
        sign_in(opener, base, user="inconnu")
    assert caught.value.code == HTTPStatus.UNAUTHORIZED     # same answer for an unknown user


def test_too_many_failures_are_slowed_down(guarded):
    base, _site = guarded
    opener, _jar = browser()
    codes = []
    for _ in range(auth.MAX_FAILURES + 1):
        with pytest.raises(urllib.error.HTTPError) as caught:
            sign_in(opener, base, password="faux")
        codes.append(caught.value.code)
    assert codes[-1] == HTTPStatus.TOO_MANY_REQUESTS
    with pytest.raises(urllib.error.HTTPError) as caught:
        sign_in(opener, base)                               # even the right password waits
    assert caught.value.code == HTTPStatus.TOO_MANY_REQUESTS


def test_signing_out_closes_the_session(guarded):
    base, site = guarded
    opener, jar = browser()
    sign_in(opener, base).close()
    token = next(iter(jar)).value
    with opener.open(base + "/logout", b"") as response:
        assert response.url.endswith("/login")
    assert site.sessions.user_of(token) is None
    assert site.sessions.count == 0
    with opener.open(base + "/nodes") as response:
        assert response.url.endswith("/login?next=%2Fnodes")


def test_downloads_and_files_need_a_session_too(guarded, tmp_path):
    base, _site = guarded
    output = tmp_path / "out"
    output.mkdir(parents=True, exist_ok=True)
    (output / "devices.csv").write_text("Device Name\nsw1\n")
    anonymous, _jar = browser()
    with anonymous.open(base + "/download/devices.csv") as response:
        assert response.url.endswith("/login?next=%2Fdownload%2Fdevices.csv")
        assert "sw1" not in response.read().decode()
    opener, _jar = browser()
    sign_in(opener, base).close()
    with opener.open(base + "/download/devices.csv") as response:
        assert "sw1" in response.read().decode()


def test_health_and_assets_stay_open(guarded):
    base, _site = guarded
    anonymous, _jar = browser()
    for path in ("/healthz", "/static/style.css", "/static/app.js"):
        with anonymous.open(base + path) as response:
            assert response.status == 200 and response.url.endswith(path)


def test_the_login_page_redirects_once_signed_in(guarded):
    base, _site = guarded
    opener, _jar = browser()
    sign_in(opener, base).close()
    with opener.open(base + "/login") as response:
        assert response.url == base + "/"


def test_post_is_only_for_the_two_forms(guarded):
    base, _site = guarded
    opener, _jar = browser()
    sign_in(opener, base).close()
    with pytest.raises(urllib.error.HTTPError) as caught:
        opener.open(base + "/nodes", b"x=1")
    assert caught.value.code == HTTPStatus.NOT_FOUND


def test_an_empty_form_is_a_failed_login(guarded):
    base, _site = guarded
    opener, _jar = browser()
    request = urllib.request.Request(base + "/login", data=b"", method="POST")
    with pytest.raises(urllib.error.HTTPError) as caught:
        opener.open(request)
    assert caught.value.code == HTTPStatus.UNAUTHORIZED


def test_the_cookie_is_marked_secure_behind_a_tls_proxy(guarded):
    from ipaddress import ip_network

    base, site = guarded
    site.proxies = [ip_network("127.0.0.1/32")]             # the front is trusted to say so
    data = urllib.parse.urlencode({"user": "alice", "password": PASSWORD}).encode()
    request = urllib.request.Request(base + "/login", data=data,
                                     headers={"X-Forwarded-Proto": "https"})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):                  # the 303 itself carries the cookie
            return None

    opener = urllib.request.build_opener(NoRedirect())
    with pytest.raises(urllib.error.HTTPError) as caught:
        opener.open(request)
    assert caught.value.code == HTTPStatus.SEE_OTHER
    cookie = caught.value.headers["Set-Cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    site.proxies = []                                        # an untrusted claim is ignored
    with pytest.raises(urllib.error.HTTPError) as caught:
        opener.open(urllib.request.Request(base + "/login", data=data,
                                           headers={"X-Forwarded-Proto": "https"}))
    assert "Secure" not in caught.value.headers["Set-Cookie"]


def test_check_warns_when_it_listens_wide_open_without_accounts(tmp_path):
    from snowth_my_net.collect.check import config_warnings

    loaded = make_loaded(tmp_path)
    loaded.cfg.web.bind = "0.0.0.0"
    assert any("no account in web.auth.users" in w for w in config_warnings(loaded))
    loaded.cfg.web.bind = "127.0.0.1"
    assert not any("web.auth.users" in w for w in config_warnings(loaded))


def test_configuration_of_the_accounts_is_validated():
    from snowth_my_net.config.loader import parse_config_text

    bare = parse_config_text("web: {auth: {users: [{name: a}]}}")
    assert bare.web.auth.users[0].name == "a"        # no password source: the store holds it
    with pytest.raises(ConfigError, match="password_file or password_env, not both"):
        parse_config_text("web: {auth: {users: [{name: a, password_file: f, "
                          "password_env: E}]}}")
    with pytest.raises(ConfigError, match="duplicate user name"):
        parse_config_text("web:\n  auth:\n    users:\n"
                          "      - {name: a, password_env: X}\n"
                          "      - {name: a, password_env: Y}\n")
    with pytest.raises(ConfigError, match="hash in a file"):
        parse_config_text("web: {auth: {users: [{name: a, password: secret}]}}")
    assert parse_context_hours() == 12


def parse_context_hours() -> int:
    from snowth_my_net.config.loader import parse_config_text

    return parse_config_text("").web.auth.session_hours


def test_parse_hash_reads_the_parts_and_refuses_anything_else():
    cost, block, parallel, salt, digest = auth.parse_hash(auth.hash_password(PASSWORD))
    assert (cost, block, parallel) == (auth.COST, auth.BLOCK, auth.PARALLEL)
    assert len(salt) == auth.SALT_BYTES and len(digest) == 64
    assert auth.parse_hash("Password: scrypt$16384$8$1$c2FsdA==$aGFzaA==") is None


def test_a_hash_broken_by_a_copy_from_a_terminal_stops_the_interface(tmp_path, caplog):
    """A line cut in two by the terminal used to read as 'wrong password' forever."""
    loaded = guarded_config(tmp_path)
    good = (loaded.paths.secrets_dir / "web_alice").read_text().strip()
    cut = good[:60] + "\n" + good[60:]
    (loaded.paths.secrets_dir / "web_alice").write_text(cut)
    with pytest.raises(ConfigError, match="--hash-password"):
        load_accounts(loaded)


def test_the_log_says_whether_the_account_or_the_password_is_wrong(tmp_path, caplog):
    site = Site(guarded_config(tmp_path), FixedClock())
    with caplog.at_level("WARNING"):
        site.sign_in({"user": ["alice"], "password": ["nope"]}, "10.0.0.1")
        site.sign_in({"user": ["nobody"], "password": [PASSWORD]}, "10.0.0.2")
    messages = [record.getMessage() for record in caplog.records]
    assert any("wrong password" in m and "10.0.0.1" in m for m in messages)
    assert any("no such account" in m and "10.0.0.2" in m for m in messages)


# --------------------------------------------------------------------------- behind a proxy


def proxied(tmp_path, *networks: str):
    from ipaddress import ip_network

    site = Site(guarded_config(tmp_path), FixedClock())
    site.proxies = [ip_network(value) for value in networks]
    return site


def test_without_a_trusted_proxy_the_header_is_ignored(tmp_path):
    site = proxied(tmp_path)
    assert site.caller("10.0.0.9", "203.0.113.7") == "10.0.0.9"


def test_a_trusted_proxy_states_the_readers_address(tmp_path):
    site = proxied(tmp_path, "172.16.0.0/12")
    assert site.caller("172.18.0.5", "10.1.50.121") == "10.1.50.121"
    assert site.caller("172.18.0.5", None) == "172.18.0.5"        # no header: the peer
    assert site.caller("172.18.0.5", "  ") == "172.18.0.5"        # an empty one too


def test_a_chain_of_proxies_yields_the_last_address_outside_them(tmp_path):
    site = proxied(tmp_path, "172.16.0.0/12", "10.0.0.0/8")
    assert site.caller("172.18.0.5", "203.0.113.7, 10.0.0.2, 172.18.0.5") == "203.0.113.7"
    assert site.caller("172.18.0.5", "10.0.0.2") == "172.18.0.5"  # nothing but proxies


def test_only_the_declared_proxy_is_believed(tmp_path):
    """Anyone else stating an address would dodge the failure limiter by inventing one."""
    site = proxied(tmp_path, "172.16.0.0/12")
    assert site.caller("10.1.50.121", "1.2.3.4") == "10.1.50.121"
    assert site.caller("not-an-address", "1.2.3.4") == "not-an-address"
    assert site.caller("172.18.0.5", "not-an-address") == "not-an-address"


def test_an_ipv6_proxy_does_not_match_an_ipv4_network(tmp_path):
    site = proxied(tmp_path, "172.16.0.0/12")
    assert site.caller("2001:db8::1", "1.2.3.4") == "2001:db8::1"


def test_the_failure_limiter_counts_the_reader_not_the_proxy(tmp_path):
    site = proxied(tmp_path, "172.16.0.0/12")
    for _ in range(auth.MAX_FAILURES):
        site.sign_in({"user": ["alice"], "password": ["faux"]},
                     site.caller("172.18.0.5", "10.1.50.121"))
    locked = site.sign_in({"user": ["alice"], "password": [PASSWORD]},
                          site.caller("172.18.0.5", "10.1.50.121"))
    assert locked[0] == HTTPStatus.TOO_MANY_REQUESTS
    other = site.sign_in({"user": ["alice"], "password": [PASSWORD]},
                         site.caller("172.18.0.5", "10.1.50.122"))
    assert other[0] == HTTPStatus.SEE_OTHER          # another reader is not locked out


def test_a_restarted_site_keeps_the_session_and_logs_why_one_is_refused(tmp_path, caplog):
    loaded = guarded_config(tmp_path)
    first = Site(loaded, FixedClock())
    token = first.sessions.open("alice")
    restarted = Site(loaded, FixedClock())                  # a redeploy, a Docker restart
    assert restarted.sessions.user_of(token) == "alice"
    with caplog.at_level("INFO"):
        status, _where, _body = restarted.respond("/nodes", {}, "never-issued")
    assert status == HTTPStatus.SEE_OTHER
    assert "session refused on /nodes: unknown" in caplog.text
    caplog.clear()
    with caplog.at_level("INFO"):
        restarted.respond("/nodes", {}, None)               # a plain visit says nothing
    assert "session refused" not in caplog.text

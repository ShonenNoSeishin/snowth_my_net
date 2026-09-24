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
    base, _site = guarded
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


def test_check_warns_when_it_listens_wide_open_without_accounts(tmp_path):
    from snowth_my_net.collect.check import config_warnings

    loaded = make_loaded(tmp_path)
    loaded.cfg.web.bind = "0.0.0.0"
    assert any("no account in web.auth.users" in w for w in config_warnings(loaded))
    loaded.cfg.web.bind = "127.0.0.1"
    assert not any("web.auth.users" in w for w in config_warnings(loaded))


def test_configuration_of_the_accounts_is_validated():
    from snowth_my_net.config.loader import parse_config_text

    with pytest.raises(ConfigError, match="exactly one of password_file or password_env"):
        parse_config_text("web: {auth: {users: [{name: a}]}}")
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

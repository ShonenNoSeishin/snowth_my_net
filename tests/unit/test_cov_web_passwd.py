"""Passwords the tool writes itself: first password, forced change, 'web passwd'.

Nothing here should ever require a reader to copy a hash: these tests walk the whole path a
reader takes, from a bare 'name:' in the configuration to a password of their own.
"""

from __future__ import annotations

import json
import stat
import threading
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.cookiejar import CookieJar

import pytest

from snowth_my_net.config.schema import WebUserCfg
from snowth_my_net.i18n import Translator
from snowth_my_net.web import accounts as acc
from snowth_my_net.web.auth import hash_password, verify_password
from snowth_my_net.web.server import Site, build
from tests.unit.test_cov_views import build_state, make_loaded
from tests.unit.test_cov_web import FixedClock

PASSWORD = "un-mot-de-passe-qui-va-bien"


def declared(tmp_path, *names: str, file_backed: str = ""):
    """A configuration with accounts and no password anywhere yet."""
    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    loaded.cfg.web.auth.users = [WebUserCfg(name) for name in names]
    if file_backed:
        secrets = loaded.paths.secrets_dir
        secrets.mkdir(parents=True, exist_ok=True)
        (secrets / "hash").write_text(hash_password(PASSWORD))
        loaded.cfg.web.auth.users.append(WebUserCfg(file_backed, password_file="hash"))
    return loaded


# --------------------------------------------------------------------------- the store


def test_the_store_survives_anything_it_is_handed(tmp_path):
    store = acc.Store(tmp_path / "state" / acc.STORE_NAME)
    assert store.read() == {}                                    # no file yet
    store.set("alice", hash_password(PASSWORD), must_change=True)
    assert store.read()["alice"].must_change
    store.set("other", hash_password(PASSWORD))
    assert sorted(store.read()) == ["alice", "other"]
    store.forget("other")
    assert sorted(store.read()) == ["alice"]
    assert not list(store.path.parent.glob("*.new"))             # no leftover temporary file
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


@pytest.mark.parametrize("content", [
    "not json", "[]", '{"users": "nope"}', '{"nothing": 1}',
    '{"users": {"alice": "a string"}}', '{"users": {"alice": {"no_hash": true}}}',
])
def test_a_damaged_store_reads_as_empty_never_as_an_open_door(tmp_path, content):
    path = tmp_path / acc.STORE_NAME
    path.write_text(content)
    assert acc.Store(path).read() == {}


def test_an_initial_password_can_be_read_from_a_log_and_typed_back():
    password = acc.initial_password()
    assert len(password) == acc.GROUPS * acc.GROUP_SIZE + (acc.GROUPS - 1)
    assert set(password) <= set(acc.ALPHABET + "-")
    assert not set(password) & set("l1o0")                       # nothing ambiguous
    assert acc.initial_password() != password


# --------------------------------------------------------------------------- first password


def test_a_declared_account_gets_a_first_password_printed_on_the_console(
        tmp_path, caplog, capsys):
    loaded = declared(tmp_path, "alice")
    with caplog.at_level("WARNING"):
        site = Site(loaded, FixedClock())
    message = capsys.readouterr().err
    assert "alice" in message and "no password yet" in message
    password = message.split("sign in once with: ")[1].split(" ")[0]
    # The log (a file, a shipper, a backup) never holds a password valid until first used.
    assert password not in "\n".join(record.getMessage() for record in caplog.records)
    assert site.guarded and site.must_change("alice")
    assert verify_password(password, site.account_of("alice").hash)


def test_the_first_password_is_kept_across_restarts(tmp_path, caplog):
    loaded = declared(tmp_path, "alice")
    Site(loaded, FixedClock())
    stored = (loaded.paths.state_dir / acc.STORE_NAME).read_text()
    caplog.clear()
    with caplog.at_level("WARNING"):
        Site(loaded, FixedClock())
    assert (loaded.paths.state_dir / acc.STORE_NAME).read_text() == stored
    assert "no password yet" not in "\n".join(r.getMessage() for r in caplog.records)


def test_signing_in_with_the_first_password_lands_on_the_password_page(tmp_path, capsys):
    loaded = declared(tmp_path, "alice")
    site = Site(loaded, FixedClock())
    password = capsys.readouterr().err.split("sign in once with: ")[1].split(" ")[0]
    status, where, _body, token = site.sign_in(
        {"user": ["alice"], "password": [password], "next": ["/nodes"]}, "10.0.0.1")
    assert (status, where) == (HTTPStatus.SEE_OTHER, "/password")   # not /nodes
    assert site.respond("/", {}, token)[:2] == (HTTPStatus.SEE_OTHER, "/password")
    assert site.respond("/nodes", {}, token)[:2] == (HTTPStatus.SEE_OTHER, "/password")
    body = site.respond("/password", {}, token)[2].decode()
    assert "web.password" not in body and "name=\"new\"" in body


# --------------------------------------------------------------------------- changing it


def signed_in(tmp_path, password: str = PASSWORD):
    """A site where 'alice' knows their password and nothing is pending."""
    loaded = declared(tmp_path, "alice")
    site = Site(loaded, FixedClock())
    site.set_password("alice", password)
    _status, _where, _body, token = site.sign_in(
        {"user": ["alice"], "password": [password]}, "10.0.0.1")
    return site, token


def test_a_reader_chooses_their_own_password_and_the_old_one_stops_working(tmp_path):
    site, token = signed_in(tmp_path)
    other = site.sessions.open("alice")                     # a session someone else holds
    status, where, _body = site.change_password("alice", {"current": [PASSWORD],
                                                         "new": ["a-new-one"],
                                                         "again": ["a-new-one"]},
                                                token=token)
    assert (status, where) == (HTTPStatus.SEE_OTHER, "/")
    assert not site.must_change("alice")
    assert site.respond("/", {}, token)[0] == HTTPStatus.OK
    assert site.sessions.user_of(other) is None            # and it is closed by the change
    assert verify_password("a-new-one", site.account_of("alice").hash)
    assert not verify_password(PASSWORD, site.account_of("alice").hash)


@pytest.mark.parametrize(("form", "expected"), [
    ({"current": [PASSWORD], "new": ["short"], "again": ["short"]}, "characters"),
    ({"current": [PASSWORD], "new": ["long-enough"], "again": ["other-one"]}, "differ"),
    ({"current": [PASSWORD]}, "characters"),
    ({"new": ["long-enough"], "again": ["long-enough"]}, "current password is wrong"),
    ({"current": ["not-it"], "new": ["long-enough"], "again": ["long-enough"]},
     "current password is wrong"),
])
def test_a_refused_password_says_why_and_changes_nothing(tmp_path, form, expected):
    site, _token = signed_in(tmp_path)
    status, _type, body = site.change_password("alice", form, Translator("en"))
    assert status == HTTPStatus.BAD_REQUEST and expected in body.decode()
    assert verify_password(PASSWORD, site.account_of("alice").hash)


def test_a_password_from_a_file_is_not_changed_from_the_browser(tmp_path):
    loaded = declared(tmp_path, file_backed="declarative")
    site = Site(loaded, FixedClock())
    _s, _w, _b, token = site.sign_in({"user": ["declarative"], "password": [PASSWORD]}, "10.0.0.1")
    page = site.respond("/password", {}, token, "en")[2].decode()
    assert "password_file" in page and 'name="new"' not in page
    status, _type, body = site.change_password("declarative", {"current": [PASSWORD],
                                                               "new": ["a-new-one"],
                                                               "again": ["a-new-one"]},
                                                              Translator("en"))
    assert status == HTTPStatus.OK and "password_file" in body.decode()
    assert verify_password(PASSWORD, site.account_of("declarative").hash)


def test_the_store_is_read_again_so_a_shell_reaches_a_running_interface(tmp_path):
    site, _token = signed_in(tmp_path)
    acc.Store(site.store.path).set("alice", hash_password("set-from-a-shell"))
    assert site.sign_in({"user": ["alice"], "password": ["set-from-a-shell"]},
                        "10.0.0.2")[0] == HTTPStatus.SEE_OTHER
    assert site.sign_in({"user": ["alice"], "password": [PASSWORD]},
                        "10.0.0.3")[0] == HTTPStatus.UNAUTHORIZED


def test_an_account_removed_from_the_configuration_cannot_sign_in(tmp_path):
    site, _token = signed_in(tmp_path)
    site.names = []                                     # as if the account was dropped
    assert site.account_of("alice") is None
    assert site.sign_in({"user": ["alice"], "password": [PASSWORD]},
                        "10.0.0.1")[0] == HTTPStatus.UNAUTHORIZED


def test_without_accounts_the_password_page_does_not_exist(tmp_path):
    repo = build_state(tmp_path)
    repo.conn.close()
    site = Site(make_loaded(tmp_path), FixedClock())
    assert site.respond("/password", {})[0] == HTTPStatus.NOT_FOUND


# --------------------------------------------------------------------------- the command


def run_passwd(loaded, name, monkeypatch, typed=("a-good-password", "a-good-password")):
    from snowth_my_net import cli

    answers = iter(typed)
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: next(answers))
    return cli._set_web_password(loaded, name)


def test_the_command_sets_a_password_without_any_file_to_edit(tmp_path, monkeypatch, capsys):
    loaded = declared(tmp_path, "alice")
    assert run_passwd(loaded, None, monkeypatch) == 0        # the only account: no name needed
    assert "password set for 'alice'" in capsys.readouterr().out
    store = acc.Store(loaded.paths.state_dir / acc.STORE_NAME)
    assert verify_password("a-good-password", store.read()["alice"].hash)
    assert not store.read()["alice"].must_change
    assert json.loads(store.path.read_text())["version"] == acc.FORMAT


def test_the_command_refuses_what_it_cannot_do(tmp_path, monkeypatch):
    from snowth_my_net.config.manual import ManualError

    none = make_loaded(tmp_path)
    with pytest.raises(ManualError, match="no account yet"):
        run_passwd(none, None, monkeypatch)

    two = declared(tmp_path, "alice", "other")
    with pytest.raises(ManualError, match="several accounts"):
        run_passwd(two, None, monkeypatch)
    with pytest.raises(ManualError, match="no account named 'ghost'"):
        run_passwd(two, "ghost", monkeypatch)

    declarative = declared(tmp_path, file_backed="declarative")
    with pytest.raises(ManualError, match="comes from hash"):
        run_passwd(declarative, "declarative", monkeypatch)
    declarative.cfg.web.auth.users[0] = WebUserCfg("declarative", password_env="SNOWTH_WEB")
    with pytest.raises(ManualError, match=r"comes from \$SNOWTH_WEB"):
        run_passwd(declarative, "declarative", monkeypatch)


@pytest.mark.parametrize(("typed", "message"), [
    (("short", "short"), "at least"),
    (("a-good-password", "another-one"), "differ"),
])
def test_the_command_checks_what_is_typed(tmp_path, monkeypatch, typed, message):
    from snowth_my_net.config.manual import ManualError

    loaded = declared(tmp_path, "alice")
    with pytest.raises(ManualError, match=message):
        run_passwd(loaded, "alice", monkeypatch, typed)


# --------------------------------------------------------------------------- over HTTP


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Show the 303 itself instead of following it."""

    def redirect_request(self, *args, **kwargs):
        return None


@pytest.fixture
def running(tmp_path, capsys):
    """A real server with one account and its invented first password."""
    server = build(declared(tmp_path, "alice"), "127.0.0.1", 0, FixedClock())
    password = capsys.readouterr().err.split("sign in once with: ")[1].split(" ")[0]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", server.site, password
    server.shutdown()
    server.server_close()


def test_the_whole_first_login_happens_in_the_browser(running):
    base, site, password = running
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    form = urllib.parse.urlencode({"user": "alice", "password": password, "next": "/nodes"})
    with opener.open(base + "/login", form.encode()) as response:
        assert response.url == base + "/password"          # not /nodes: it must be changed
        assert 'name="new"' in response.read().decode()
    with opener.open(base + "/nodes") as response:
        assert response.url == base + "/password"          # every page leads back to it
    chosen = urllib.parse.urlencode({"current": password, "new": "mon-mot-de-passe",
                                     "again": "mon-mot-de-passe"})
    with opener.open(base + "/password", chosen.encode()) as response:
        assert response.url == base + "/" and response.status == 200
    with opener.open(base + "/nodes") as response:
        assert response.status == 200 and "sw1" in response.read().decode()
    assert not site.must_change("alice")
    assert verify_password("mon-mot-de-passe", site.account_of("alice").hash)


def test_changing_a_password_needs_a_session(running):
    base, _site, _password = running
    form = urllib.parse.urlencode({"current": "whatever", "new": "mon-mot-de-passe",
                                   "again": "mon-mot-de-passe"})
    request = urllib.request.Request(base + "/password", form.encode())
    opener = urllib.request.build_opener(NoRedirect())
    with pytest.raises(urllib.error.HTTPError) as caught:
        opener.open(request)
    assert caught.value.code == HTTPStatus.SEE_OTHER
    assert caught.value.headers["Location"] == "/login"


def test_a_failed_write_leaves_the_previous_passwords_alone(tmp_path, monkeypatch):
    store = acc.Store(tmp_path / acc.STORE_NAME)
    store.set("alice", hash_password(PASSWORD))
    before = store.path.read_text()
    monkeypatch.setattr("os.replace", boom)
    with pytest.raises(OSError):
        store.set("alice", hash_password("something-else"))
    assert store.path.read_text() == before                      # nothing half-written
    assert not list(store.path.parent.glob("*.new"))             # and nothing left behind


def boom(*args, **kwargs):
    raise OSError("disk full")


def test_guessing_the_current_password_is_slowed_down_like_a_login(tmp_path):
    """A session left open on an unlocked screen must not become a free guessing machine."""
    from snowth_my_net.web import auth

    site, _token = signed_in(tmp_path)
    wrong = {"current": ["not-it"], "new": ["long-enough"], "again": ["long-enough"]}
    for _ in range(auth.MAX_FAILURES):
        assert site.change_password("alice", wrong, Translator("en"),
                                    "10.0.0.7")[0] == HTTPStatus.BAD_REQUEST
    status, _type, body = site.change_password(
        "alice", {"current": [PASSWORD], "new": ["long-enough"], "again": ["long-enough"]},
        Translator("en"), "10.0.0.7")
    assert status == HTTPStatus.TOO_MANY_REQUESTS and "Too many" in body.decode()
    assert verify_password(PASSWORD, site.account_of("alice").hash)      # unchanged
    status, _where, _body = site.change_password(
        "alice", {"current": [PASSWORD], "new": ["long-enough"], "again": ["long-enough"]},
        Translator("en"), "10.0.0.8")                                    # another address
    assert status == HTTPStatus.SEE_OTHER

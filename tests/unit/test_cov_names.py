"""Names given by hand to MAC addresses: they must survive everything a collect does."""

from __future__ import annotations

import stat
import urllib.parse
import urllib.request
from http import HTTPStatus

import pytest

from snowth_my_net import names as mod
from snowth_my_net.config.manual import ManualError
from snowth_my_net.i18n import Translator
from snowth_my_net.web.server import Site
from tests.unit.test_cov_views import D, build_state, make_loaded
from tests.unit.test_cov_web import FixedClock

MAC = "00:11:22:33:44:5a"


# --------------------------------------------------------------------------- the store


def test_a_name_is_kept_cleaned_and_forgotten_on_demand(tmp_path):
    store = mod.Names(tmp_path / mod.STORE_NAME)
    assert store.read() == {} and store.get(MAC) == ""
    assert store.set(MAC, "  imprimante   compta ") == "imprimante compta"   # one line, trimmed
    assert store.get(MAC) == "imprimante compta"
    assert store.set("0011.2233.445a", "poste de Julie") == "poste de Julie"  # any MAC spelling
    assert store.read() == {MAC: "poste de Julie"}                           # the same address
    assert store.set(MAC, "   ") == ""
    assert store.read() == {}
    assert not list(store.path.parent.glob("*.new"))
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o640


def test_what_a_name_may_not_be(tmp_path):
    store = mod.Names(tmp_path / mod.STORE_NAME)
    with pytest.raises(mod.NameError_, match="not a MAC address"):
        store.set("pas-une-mac", "x")
    with pytest.raises(mod.NameError_, match="at most 60"):
        store.set(MAC, "x" * (mod.MAX_LENGTH + 1))
    assert store.read() == {}


@pytest.mark.parametrize("content", [
    "not json", "[]", '{"names": "nope"}', '{"nothing": 1}',
    '{"names": {"aa": 3}}', '{"names": {"aa": ""}}',
])
def test_a_damaged_store_reads_as_no_names(tmp_path, content):
    path = tmp_path / mod.STORE_NAME
    path.write_text(content)
    assert mod.Names(path).read() == {}


def test_a_failed_write_keeps_the_names_it_had(tmp_path, monkeypatch):
    store = mod.Names(tmp_path / mod.STORE_NAME)
    store.set(MAC, "imprimante")
    before = store.path.read_text()

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", boom)
    with pytest.raises(OSError):
        store.set(MAC, "autre chose")
    assert store.path.read_text() == before
    assert not list(store.path.parent.glob("*.new"))


# --------------------------------------------------------------------------- in the views


def named(tmp_path, name: str = "imprimante compta"):
    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    mod.store_for(loaded.paths).set(D, name)
    return loaded


def test_the_name_shows_in_the_table_and_in_the_explanation(tmp_path):
    site = Site(named(tmp_path), FixedClock())
    page = site.respond("/nodes", {})[2].decode()
    assert "imprimante compta" in page
    assert page.index("imprimante compta") < page.index(D)      # the name comes first
    explanation = site.respond("/node", {"mac": [D]})[2].decode()
    assert "imprimante compta" in explanation


def test_a_name_survives_the_state_being_thrown_away(tmp_path):
    """The whole point: a collect, a schema upgrade, a lost database keep the names."""
    loaded = named(tmp_path)
    (loaded.paths.state_file).unlink()
    build_state(tmp_path).conn.close()                          # collected again from scratch
    site = Site(loaded, FixedClock())
    assert "imprimante compta" in site.respond("/nodes", {})[2].decode()


def test_the_exported_csv_keeps_its_columns_unless_asked(tmp_path):
    from snowth_my_net.export.run import nodes_csv
    from snowth_my_net.state.db import open_db
    from snowth_my_net.state.repo import Repo

    loaded = named(tmp_path)
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        plain = nodes_csv(loaded, repo, 1_800_000_000).decode()
        loaded.cfg.export.nodes.include_name = True
        named_csv = nodes_csv(loaded, repo, 1_800_000_000).decode()
    finally:
        repo.conn.close()
    assert plain.splitlines()[0].startswith('"MAC Address"')
    assert "imprimante compta" not in plain
    assert named_csv.splitlines()[0].startswith("Name,")
    assert "imprimante compta" in named_csv


# --------------------------------------------------------------------------- from the browser


def test_naming_a_mac_from_its_page_and_clearing_it(tmp_path):
    site = Site(named(tmp_path, ""), FixedClock())
    status, where, _body = site.set_name(D, "caméra hall")
    assert (status, where) == (HTTPStatus.SEE_OTHER, "/node?mac=" + D)
    assert mod.store_for(site.loaded.paths).get(D) == "caméra hall"
    assert "caméra hall" in site.respond("/nodes", {})[2].decode()
    site.set_name(D, "")
    assert mod.store_for(site.loaded.paths).get(D) == ""


def test_a_refused_name_says_why_and_changes_nothing(tmp_path):
    site = Site(named(tmp_path), FixedClock())
    status, _type, body = site.set_name(D, "x" * 200, Translator("en"))
    assert status == HTTPStatus.BAD_REQUEST and "at most 60" in body.decode()
    status, _type, body = site.set_name("pas-une-mac", "x", Translator("en"))
    assert status == HTTPStatus.BAD_REQUEST and "not a MAC address" in body.decode()
    assert mod.store_for(site.loaded.paths).get(D) == "imprimante compta"


def test_the_form_is_absent_when_the_page_is_not_about_a_mac(tmp_path):
    site = Site(named(tmp_path), FixedClock())
    assert "form class=\"rename\"" not in site.respond("/node", {"mac": ["nimporte"]})[2].decode()


# --------------------------------------------------------------------------- over HTTP


@pytest.fixture
def running(tmp_path):
    import threading

    from snowth_my_net.web.server import build

    server = build(named(tmp_path, ""), "127.0.0.1", 0, FixedClock())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", server.site
    server.shutdown()
    server.server_close()


def test_a_reader_names_a_mac_and_finds_it_in_the_table(running):
    base, site = running
    form = urllib.parse.urlencode({"mac": D, "name": "poste de Julie"}).encode()
    with urllib.request.urlopen(base + "/name", form) as response:
        assert response.url.endswith("/node?mac=" + D)
        assert "poste de Julie" in response.read().decode()
    with urllib.request.urlopen(base + "/nodes") as response:
        assert "poste de Julie" in response.read().decode()
    assert mod.store_for(site.loaded.paths).get(D) == "poste de Julie"


def test_naming_needs_a_session_when_there_are_accounts(tmp_path):
    import threading

    from snowth_my_net.config.schema import WebUserCfg
    from snowth_my_net.web.server import build

    loaded = named(tmp_path, "")
    loaded.cfg.web.auth.users = [WebUserCfg("alice")]
    server = build(loaded, "127.0.0.1", 0, FixedClock())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        form = urllib.parse.urlencode({"mac": D, "name": "poste de Julie"}).encode()
        with urllib.request.urlopen(base + "/name", form) as response:
            assert response.url.endswith("/login")          # sent to the login, not applied
        assert mod.store_for(loaded.paths).get(D) == ""
    finally:
        server.shutdown()
        server.server_close()


# --------------------------------------------------------------------------- from the shell


def run_node(loaded, *argv, json_out=False):
    import argparse

    from snowth_my_net import cli

    args = argparse.Namespace(json=json_out, action="name" if argv else None,
                              mac=argv[0] if argv else None, name=list(argv[1:]))
    original = cli.load
    cli.load = lambda _args: loaded
    try:
        return cli.cmd_node(args)
    finally:
        cli.load = original


def test_the_command_names_lists_and_forgets(tmp_path, capsys):
    loaded = named(tmp_path, "")
    assert run_node(loaded) == 0
    assert "no name given yet" in capsys.readouterr().out
    assert run_node(loaded, D, "imprimante", "compta") == 0
    assert capsys.readouterr().out.strip() == f"{D}: imprimante compta"
    assert run_node(loaded) == 0
    assert "imprimante compta" in capsys.readouterr().out
    assert run_node(loaded, D) == 0                                  # no text: forget it
    assert "forgotten" in capsys.readouterr().out
    assert mod.store_for(loaded.paths).read() == {}


def test_the_command_in_json_and_its_errors(tmp_path, capsys):
    import json

    loaded = named(tmp_path)
    assert run_node(loaded, json_out=True) == 0
    assert json.loads(capsys.readouterr().out) == {"names": {D: "imprimante compta"}}
    assert run_node(loaded, D, "autre", json_out=True) == 0
    assert json.loads(capsys.readouterr().out) == {"mac": D, "name": "autre"}
    with pytest.raises(ManualError, match="not a MAC address"):
        run_node(loaded, "pas-une-mac", "x")

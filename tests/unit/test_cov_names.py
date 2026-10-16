"""Names given by hand to MAC addresses: they must survive everything a collect does."""

from __future__ import annotations

import stat
import urllib.parse
import urllib.request
from http import HTTPStatus

import pytest

from snowth_my_net import names as mod
from snowth_my_net.config.manual import ManualError
from snowth_my_net.config.schema import WebUserCfg
from snowth_my_net.i18n import Translator
from snowth_my_net.web.server import Site
from tests.unit.signed import SignedSite, cookie_of
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
    assert store.read() == {MAC: {"name": "poste de Julie"}}                 # the same address
    assert store.set(MAC, "   ") == ""
    assert store.read() == {}
    assert not list(store.path.parent.glob("*.new"))
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o640


def test_what_a_name_may_not_be(tmp_path):
    store = mod.Names(tmp_path / mod.STORE_NAME)
    with pytest.raises(mod.NameError_, match="not a MAC address"):
        store.set("pas-une-mac", "x")
    with pytest.raises(mod.NameError_, match="at most 60"):
        store.set(MAC, "x" * (mod.MAX_LENGTH["name"] + 1))
    with pytest.raises(mod.NameError_, match="at most 200"):
        store.set(MAC, "x" * 201, "description")
    with pytest.raises(mod.NameError_, match="unknown field"):
        store.set(MAC, "x", "whatever")
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
    site = SignedSite(named(tmp_path))
    page = site.respond("/nodes", {})[2].decode()
    assert f'<input type="hidden" name="mac" value="{D}">' in page   # written in the table
    assert 'value="imprimante compta"' in page
    assert page.index("imprimante compta") < page.index(f'href="/node?mac={D}"')
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
    loaded.cfg.export.nodes.merge_hostnames = False      # the hostname column is another story
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


def test_the_description_is_a_column_of_its_own(tmp_path):
    from snowth_my_net.export.run import nodes_csv
    from snowth_my_net.state.db import open_db
    from snowth_my_net.state.repo import Repo

    loaded = named(tmp_path)
    mod.store_for(loaded.paths).set(D, "au fond du couloir", "description")
    loaded.cfg.export.nodes.merge_hostnames = False
    loaded.cfg.export.nodes.include_description = True
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        only_description = nodes_csv(loaded, repo, 1_800_000_000).decode()
        loaded.cfg.export.nodes.include_name = True
        both = nodes_csv(loaded, repo, 1_800_000_000).decode()
    finally:
        repo.conn.close()
    assert only_description.splitlines()[0].startswith('Description,"MAC Address"')
    assert "au fond du couloir" in only_description and "imprimante compta" not in only_description
    assert both.splitlines()[0].startswith('Name,Description,"MAC Address"')
    assert "imprimante compta" in both and "au fond du couloir" in both


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

    loaded = named(tmp_path, "")
    loaded.cfg.web.auth.users = [WebUserCfg("alice")]
    server = build(loaded, "127.0.0.1", 0, FixedClock())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = urllib.request.build_opener()
    opener.addheaders = [("Cookie", cookie_of(server))]
    urllib.request.install_opener(opener)
    yield f"http://127.0.0.1:{server.server_address[1]}", server.site
    urllib.request.install_opener(urllib.request.build_opener())
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


def run_node(loaded, *argv, json_out=False, action="name"):
    import argparse

    from snowth_my_net import cli

    args = argparse.Namespace(json=json_out, action=action if argv else None,
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
    assert capsys.readouterr().out.strip() == f"{D}: name = imprimante compta"
    assert run_node(loaded, D, "au", "fond", action="describe") == 0
    assert capsys.readouterr().out.strip() == f"{D}: description = au fond"
    assert run_node(loaded) == 0
    assert "imprimante compta" in capsys.readouterr().out
    assert run_node(loaded, D) == 0                                  # no text: forget it
    assert "forgotten" in capsys.readouterr().out
    assert mod.store_for(loaded.paths).read() == {D: {"description": "au fond"}}
    assert run_node(loaded, D, action="describe") == 0
    assert "forgotten" in capsys.readouterr().out
    assert mod.store_for(loaded.paths).read() == {}


def test_the_command_in_json_and_its_errors(tmp_path, capsys):
    import json

    loaded = named(tmp_path)
    assert run_node(loaded, json_out=True) == 0
    assert json.loads(capsys.readouterr().out) == {
        "names": {D: {"name": "imprimante compta"}}}
    assert run_node(loaded, D, "autre", json_out=True) == 0
    assert json.loads(capsys.readouterr().out) == {"mac": D, "field": "name", "value": "autre"}
    with pytest.raises(ManualError, match="not a MAC address"):
        run_node(loaded, "pas-une-mac", "x")


def test_the_table_saves_a_cell_without_reloading_the_page(running):
    """What the table's own script does: post one cell, read back what was stored."""
    import json

    base, site = running
    form = urllib.parse.urlencode({"mac": D, "name": "  caméra   hall "}).encode()
    request = urllib.request.Request(base + "/name", form,
                                     headers={"Accept": "application/json"})
    with urllib.request.urlopen(request) as response:
        assert response.headers["Content-Type"].startswith("application/json")
        assert json.loads(response.read()) == {"mac": D, "name": "caméra hall",
                                               "field": "name"}
    assert mod.store_for(site.loaded.paths).get(D) == "caméra hall"


def test_a_refused_cell_answers_the_script_in_its_own_language(running):
    import json
    import urllib.error

    base, _site = running
    form = urllib.parse.urlencode({"mac": D, "name": "x" * 200}).encode()
    request = urllib.request.Request(base + "/name", form,
                                     headers={"Accept": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request)
    assert caught.value.code == HTTPStatus.BAD_REQUEST
    assert "at most 60" in json.loads(caught.value.read())["error"]


def test_a_lost_session_is_said_plainly_instead_of_a_login_page(tmp_path):
    import json
    import threading
    import urllib.error

    from snowth_my_net.config.schema import WebUserCfg
    from snowth_my_net.web.server import build

    loaded = named(tmp_path, "")
    loaded.cfg.web.auth.users = [WebUserCfg("alice")]
    server = build(loaded, "127.0.0.1", 0, FixedClock())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        form = urllib.parse.urlencode({"mac": D, "name": "poste"}).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/name", form,
            headers={"Accept": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        assert caught.value.code == HTTPStatus.UNAUTHORIZED
        assert json.loads(caught.value.read())["error"]
    finally:
        server.shutdown()
        server.server_close()


# --------------------------------------------------------------------------- what did not answer


def test_an_address_that_never_answered_is_on_the_devices_page(tmp_path):
    """'11/12 reachable' must not leave the twelfth nowhere to be found."""
    from snowth_my_net.state.db import open_db
    from snowth_my_net.state.repo import Repo

    loaded = named(tmp_path, "")
    repo = Repo(open_db(loaded.paths.state_file))
    try:
        repo.ensure_target("192.0.2.77", "seed", 0, 1_800_000_000)
        repo.conn.execute("UPDATE targets SET last_error = ? WHERE address = ?",
                          ("timeout after 3 s", "192.0.2.77"))
        repo.conn.commit()
    finally:
        repo.conn.close()
    page = Site(loaded, FixedClock()).respond("/", {}, lang="en")[2].decode()
    assert "192.0.2.77" in page                       # the address itself
    assert "timeout after 3 s" in page                # why it is not there
    assert "col-status bad" in page                 # and it is coloured, not hidden


def test_a_device_that_stopped_answering_says_why(tmp_path):
    from snowth_my_net.state.db import open_db
    from snowth_my_net.state.repo import Repo

    loaded = named(tmp_path, "")
    repo = Repo(open_db(loaded.paths.state_file))
    try:
        address = repo.conn.execute(
            "SELECT mgmt_address FROM devices LIMIT 1").fetchone()[0]
        repo.conn.execute("UPDATE devices SET last_collect_status = 'failed' "
                          "WHERE mgmt_address = ?", (address,))
        repo.ensure_target(address, "seed", 0, 1_800_000_000)
        repo.conn.execute("UPDATE targets SET last_error = ? WHERE address = ?",
                          ("no answer to any credential", address))
        repo.conn.commit()
    finally:
        repo.conn.close()
    page = Site(loaded, FixedClock()).respond("/", {}, lang="en")[2].decode()
    assert "no answer to any credential" in page and "col-status bad" in page


def test_an_alias_address_is_not_listed_twice(tmp_path):
    """A device reachable through two addresses is one row, not one plus a ghost."""
    from snowth_my_net.state.db import open_db
    from snowth_my_net.state.repo import Repo

    loaded = named(tmp_path, "")
    repo = Repo(open_db(loaded.paths.state_file))
    try:
        repo.ensure_target("192.0.2.88", "neighbor", 1, 1_800_000_000)
        repo.conn.execute("UPDATE targets SET is_alias = 1 WHERE address = ?", ("192.0.2.88",))
        repo.conn.commit()
    finally:
        repo.conn.close()
    assert "192.0.2.88" not in Site(loaded, FixedClock()).respond("/", {})[2].decode()


def test_a_description_is_written_in_the_table_like_a_name(running):
    """The same cell mechanism, a second field, the same store."""
    import json

    base, site = running
    form = urllib.parse.urlencode({"mac": D, "field": "description",
                                   "name": "sous le bureau de la compta"}).encode()
    request = urllib.request.Request(base + "/name", form,
                                     headers={"Accept": "application/json"})
    with urllib.request.urlopen(request) as response:
        assert json.loads(response.read())["field"] == "description"
    names = mod.store_for(site.loaded.paths)
    assert names.get(D, "description") == "sous le bureau de la compta"
    assert names.get(D) == ""                                  # the name is untouched
    with urllib.request.urlopen(base + "/nodes") as response:
        assert "sous le bureau de la compta" in response.read().decode()


def test_the_old_store_of_names_is_read_and_carried_over(tmp_path):
    """A file written before descriptions existed keeps its names."""
    path = tmp_path / mod.STORE_NAME
    path.write_text(f'{{"version": 1, "names": {{"{MAC}": "imprimante"}}}}')
    store = mod.Names(path)
    assert store.get(MAC) == "imprimante"
    store.set(MAC, "au fond du couloir", "description")
    assert store.read() == {MAC: {"name": "imprimante",
                                  "description": "au fond du couloir"}}


def test_the_terminal_rows_start_with_the_mac_whatever_the_export_columns(tmp_path):
    from snowth_my_net.merge.view import build_view
    from snowth_my_net.state.db import open_db
    from snowth_my_net.state.repo import Repo

    loaded = named(tmp_path)
    loaded.cfg.export.nodes.include_name = True
    repo = Repo(open_db(loaded.paths.state_file, readonly=True))
    try:
        view = build_view(loaded, repo, 1_800_000_000)
        assert view.rows()[0][0] != view.rows(given_columns=False)[0][0]    # Name comes first
        assert all(row[0].count(":") == 5 for row in view.rows(given_columns=False))
    finally:
        repo.conn.close()


def test_the_rename_forms_carry_a_numeric_length_limit(tmp_path):
    import re

    site = SignedSite(named(tmp_path))
    for page in (site.respond("/nodes", {})[2].decode(),
                 site.respond("/node", {"mac": [D]})[2].decode()):
        limits = re.findall(r'maxlength="([^"]*)"', page)
        assert limits and all(value.isdigit() for value in limits)


def test_the_import_log_quotes_a_mac_cell_that_a_spreadsheet_would_run():
    line = mod.ImportLine(3, "=HYPERLINK(\"x\")", "x", "error", "not a MAC address")
    log = mod.import_log([line])
    assert "'=HYPERLINK" in log and ",=HYPERLINK" not in log

"""The web interface: routing, rendering, escaping, and what it refuses."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http import HTTPStatus

import pytest

from snowth_my_net.clock import Clock
from snowth_my_net.config.loader import parse_config_text
from snowth_my_net.web import pages
from snowth_my_net.web.server import Site, build
from tests.unit.test_cov_views import NOW, A, build_state, make_loaded


class FixedClock(Clock):
    def now(self) -> int:
        return NOW


@pytest.fixture
def site(tmp_path):
    repo = build_state(tmp_path)
    repo.conn.close()                        # the interface opens its own read-only connection
    return Site(make_loaded(tmp_path), FixedClock())


def get(site: Site, path: str, **query) -> tuple[int, str, str]:
    status, content_type, body = site.respond(path, {k: [v] for k, v in query.items()})
    return int(status), content_type, body.decode("utf-8", errors="replace")


def test_every_page_answers_and_shows_its_rows(site):
    status, content_type, body = get(site, "/")
    assert (status, content_type) == (200, "text/html; charset=utf-8")
    assert "sw1" in body and "<title>" in body
    assert 'class="on"' in body                                  # the current tab is marked
    assert "dernière collecte" in body or "last collect" in body  # the summary line
    for path, expected in (("/nodes", A), ("/links", "sw1"), ("/runs", "collect"),
                           ("/files", "")):
        status, _type, body = get(site, path)
        assert status == 200 and expected in body


def test_nodes_link_to_their_explanation(site):
    _status, _type, body = get(site, "/nodes")
    assert f'href="/node?mac={A}"' in body
    status, _type, page = get(site, "/node", mac=A)
    assert status == 200
    assert A in page and ("Position actuelle" in page or "Current position" in page)
    assert 'class="ok"' in page                                   # styled explanation lines


def test_unknown_page_and_unknown_node(site):
    status, _type, body = get(site, "/nope")
    assert status == HTTPStatus.NOT_FOUND and "snowth_my_net" in body
    status, _type, body = get(site, "/node", mac="02:00:00:00:00:99")
    assert status == 200 and ("vue dans aucune" in body or "not seen in any" in body)


def test_html_is_escaped(tmp_path):
    repo = build_state(tmp_path)
    repo.conn.execute("UPDATE devices SET sys_name = ? WHERE id = 1",
                      ("<script>alert(1)</script>",))
    repo.conn.commit()
    repo.conn.close()
    _status, _type, body = get(Site(make_loaded(tmp_path), FixedClock()), "/")
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


def test_downloads_are_limited_to_the_exported_files(site, tmp_path):
    output = site.loaded.paths.output_dir
    output.mkdir(parents=True, exist_ok=True)
    (output / "devices.csv").write_text("Device Name\nsw1\n")
    (tmp_path / "secret.txt").write_text("not for the browser")
    status, content_type, body = get(site, "/download/devices.csv")
    assert (status, content_type) == (200, "text/csv; charset=utf-8") and "sw1" in body
    for refused in ("/download/secret.txt", "/download/../secret.txt",
                    "/download/..%2Fsecret.txt", "/download/state.sqlite"):
        assert get(site, refused)[0] == HTTPStatus.NOT_FOUND
    _status, _type, listing = get(site, "/files")
    assert "devices.csv" in listing and 'href="/download/devices.csv"' in listing


def test_missing_exported_file_is_not_found(site):
    assert get(site, "/download/map.html")[0] == HTTPStatus.NOT_FOUND


def test_static_assets_and_health(site):
    for name, expected in (("style.css", "text/css"), ("app.js", "text/javascript")):
        status, content_type, body = get(site, f"/static/{name}")
        assert status == 200 and expected in content_type and body
    assert get(site, "/static/../server.py")[0] == HTTPStatus.NOT_FOUND
    assert get(site, "/healthz") == (200, "text/plain; charset=utf-8", "ok\n")


def test_node_limit_truncates_and_says_so(tmp_path):
    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    loaded.cfg.web.node_limit = 2
    _status, _type, body = get(Site(loaded, FixedClock()), "/nodes")
    assert body.count("<tr>") == 3                         # the header row plus two nodes
    assert "2" in body and ("premières" in body or "first" in body)


def test_empty_state_explains_what_to_do(tmp_path):
    from snowth_my_net.state.db import open_db
    from snowth_my_net.state.repo import Repo

    Repo(open_db(tmp_path / "state" / "state.sqlite")).conn.close()   # an empty but valid state
    site = Site(make_loaded(tmp_path), FixedClock())
    for path in ("/", "/nodes", "/links", "/runs", "/files"):
        status, _type, body = get(site, path)
        assert status == 200 and 'class="empty"' in body
    assert ("Aucun équipement" in get(site, "/")[2] or "No device" in get(site, "/")[2])


def test_no_state_yet_is_a_service_unavailable(tmp_path):
    site = Site(make_loaded(tmp_path), FixedClock())
    with pytest.raises(Exception, match="no state yet"):
        site.respond("/", {})


def test_pages_use_the_configured_language(tmp_path, monkeypatch):
    monkeypatch.delenv("LANG", raising=False)
    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    loaded.cfg.general.language = "fr"
    assert "Équipements" in get(Site(loaded, FixedClock()), "/")[2]
    loaded.cfg.general.language = "en"
    assert "Devices" in get(Site(loaded, FixedClock()), "/")[2]


# --------------------------------------------------------------------------- over a socket


@pytest.fixture
def server(tmp_path):
    repo = build_state(tmp_path)
    repo.conn.close()
    running = build(make_loaded(tmp_path), "127.0.0.1", 0, FixedClock())
    thread = threading.Thread(target=running.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{running.server_address[1]}"
    running.shutdown()
    running.server_close()


def test_served_over_http_with_safe_headers(server):
    with urllib.request.urlopen(server + "/") as response:
        body = response.read().decode()
        headers = dict(response.headers.items())
    assert response.status == 200 and "snowth_my_net" in body
    assert headers["X-Content-Type-Options"] == "nosniff"
    policy = headers["Content-Security-Policy"]
    assert "default-src 'none'" in policy                   # only our own style and script
    assert "form-action 'self'" in policy                   # the login form, nothing else
    assert "connect-src 'self'" in policy                   # saving a name in the table
    assert headers["Cache-Control"] == "no-store"
    assert "Python" not in headers.get("Server", "")


def test_no_page_accepts_a_post(server):
    """Without accounts there is no form at all: every POST is refused."""
    for path in ("/", "/nodes", "/login", "/logout"):
        request = urllib.request.Request(server + path, data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        assert caught.value.code in (404, 405, 501), path


def test_a_broken_page_answers_500_without_details(server, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(pages, "devices", boom)
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(server + "/")
    assert caught.value.code == 500 and b"secret detail" not in caught.value.read()


def test_cli_web_command_serves(tmp_path, monkeypatch, capsys):
    from snowth_my_net import cli

    cfg = tmp_path / "c.yml"
    cfg.write_text(f"general: {{state_dir: {tmp_path / 'state'}}}\nweb: {{port: 8123}}\n")
    seen = {}

    def fake_serve(loaded, bind, port):
        seen.update(bind=bind, port=port, cfg_port=loaded.cfg.web.port)
        return 0

    monkeypatch.setattr("snowth_my_net.web.server.serve", fake_serve)
    assert cli.main(["--config", str(cfg), "web", "--bind", "0.0.0.0", "--port", "9"]) == 0
    assert seen == {"bind": "0.0.0.0", "port": 9, "cfg_port": 8123}


def test_web_configuration_is_validated():
    assert parse_config_text("web: {bind: 0.0.0.0, port: 9000}").web.port == 9000
    problems = parse_config_text("").web.check()
    assert problems == []
    from snowth_my_net.config.validate import ConfigError

    with pytest.raises(ConfigError, match="not a port number"):
        parse_config_text("web: {port: 70000}")
    with pytest.raises(ConfigError, match="node_limit"):
        parse_config_text("web: {node_limit: 0}")


def test_summary_without_a_successful_collect(tmp_path):
    from snowth_my_net.i18n import Translator
    from snowth_my_net.state.db import open_db
    from snowth_my_net.state.repo import Repo

    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    try:
        text = pages.summary(make_loaded(tmp_path), repo, NOW, Translator("en"))
    finally:
        repo.conn.close()
    assert "no collect yet" in text


def test_files_page_lists_what_exists(tmp_path):
    from snowth_my_net.i18n import Translator

    output = tmp_path / "out"
    output.mkdir()
    (output / "snapshot.json").write_text(json.dumps({"devices": []}))
    table = pages.files(output, Translator("en"))
    assert [row[0] for row in table.rows] == ["snapshot.json"]
    assert pages.files(tmp_path / "nowhere", Translator("en")).rows == []


def test_before_the_first_collect_the_page_says_so_over_http(tmp_path):
    """No state file yet: a browser gets 503 and the reason, not a stack trace."""
    running = build(make_loaded(tmp_path), "127.0.0.1", 0, FixedClock())
    thread = threading.Thread(target=running.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"http://127.0.0.1:{running.server_address[1]}/")
        assert caught.value.code == 503
        assert b"no state yet" in caught.value.read()
    finally:
        running.shutdown()
        running.server_close()


def test_serve_stops_cleanly_on_interrupt(tmp_path, monkeypatch):
    from snowth_my_net.web import server as server_module

    closed = []

    class FakeSite:
        guarded = False

    class FakeServer:
        server_address = ("127.0.0.1", 8080)
        site = FakeSite()

        def serve_forever(self):        # pragma: no cover - the fake thread never runs it
            raise AssertionError("not reached")

        def shutdown(self):
            closed.append("shutdown")

        def server_close(self):
            closed.append("close")

    class FakeThread:
        def __init__(self, target, daemon):
            self.target, self.daemon = target, daemon

        def start(self):
            pass

        def join(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(server_module, "build", lambda *a, **k: FakeServer())
    monkeypatch.setattr(server_module.threading, "Thread", FakeThread)
    assert server_module.serve(make_loaded(tmp_path)) == 0
    assert closed == ["shutdown", "close"]


def test_listening_wide_open_without_accounts_is_said_out_loud(tmp_path, monkeypatch, caplog):
    from snowth_my_net.web import server as server_module

    class FakeSite:
        guarded = False

    class FakeServer:
        server_address = ("0.0.0.0", 8080)
        site = FakeSite()

        def serve_forever(self):        # pragma: no cover - the fake thread never runs it
            raise AssertionError("not reached")

        def shutdown(self):
            pass

        def server_close(self):
            pass

    class FakeThread:
        def __init__(self, target, daemon):
            pass

        def start(self):
            pass

        def join(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(server_module, "build", lambda *a, **k: FakeServer())
    monkeypatch.setattr(server_module.threading, "Thread", FakeThread)
    with caplog.at_level("WARNING"):
        assert server_module.serve(make_loaded(tmp_path)) == 0
    assert "no account" in "\n".join(r.getMessage() for r in caplog.records)


def test_each_page_explains_where_its_columns_come_from(site):
    """The 'how to read this table' panel: one line per column, none left as a raw key."""
    from snowth_my_net.i18n import STRINGS

    for path in ("/", "/nodes", "/links", "/runs"):
        _status, _type, body = get(site, path)
        assert "Comment lire ce tableau" in body or "How to read this table" in body
        assert "<dt>" in body and "<dd>" in body
        assert "hint." not in body                       # every key was translated
    assert [k for k in STRINGS if k.startswith("hint.") and not STRINGS[k][0]] == []


def test_the_columns_of_a_page_match_its_explanations(tmp_path):
    from snowth_my_net.i18n import Translator
    from snowth_my_net.state.db import open_db
    from snowth_my_net.state.repo import Repo

    t = Translator("en")
    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    loaded = make_loaded(tmp_path)
    try:
        tables = {"devices": pages.devices(loaded, repo, NOW, t),
                  "nodes": pages.nodes(loaded, repo, NOW, t, 10),
                  "links": pages.links(loaded, repo, NOW, t),
                  "runs": pages.runs(repo, t),
                  "files": pages.files(tmp_path, t)}
    finally:
        repo.conn.close()
    for name, table in tables.items():
        labels = [label for label, _kind in table.columns]
        explained = [label for label, _text in table.help if label]
        assert explained, name
        assert explained == [label for label in labels if label in explained], name
        assert all(text.strip() for _label, text in table.help), name


def test_the_nodes_help_answers_the_ipv6_and_empty_switch_questions(site):
    _status, _type, body = get(site, "/nodes")
    assert "IPv4" in body                                 # how the shown address is elected
    assert ("cache ARP" in body or "ARP cache" in body)   # why Switch can be empty
    assert "uplinks" in body


def test_a_node_shows_its_other_addresses_next_to_the_elected_one(site):
    """D's IPv4 was claimed by another MAC, so an IPv6 is elected: the rest stays visible."""
    from tests.unit.test_cov_views import D

    _status, _type, body = get(site, "/nodes")
    row = next(line for line in body.split("<tr>") if D in line)
    assert "2001:db8::60" in row                           # the elected address
    assert '<span class="note">' in row and "192.0.2.60" in row   # the ones it hides


def test_a_roaming_mac_says_so_on_every_one_of_its_rows(site):
    from tests.unit.test_cov_views import D

    _status, _type, body = get(site, "/nodes")
    rows = [line for line in body.split("<tr>") if D in line]
    assert len(rows) > 1                                   # D moved from sw2 to sw1
    assert all("positions" in row for row in rows)


def test_a_device_known_by_several_macs_says_how_many(site):
    _status, _type, body = get(site, "/")
    assert "+" in body and "MAC" in body


def test_the_reader_can_switch_language_and_it_is_remembered(server):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None

    opener = urllib.request.build_opener(NoRedirect())
    with pytest.raises(urllib.error.HTTPError) as caught:
        opener.open(server + "/nodes?lang=en")
    assert caught.value.code == 303
    assert caught.value.headers["Location"] == "/nodes"
    assert "snowth_lang=en" in caught.value.headers["Set-Cookie"]

    request = urllib.request.Request(server + "/", headers={"Cookie": "snowth_lang=en"})
    with urllib.request.urlopen(request) as response:
        assert "Devices" in response.read().decode()
    request = urllib.request.Request(server + "/", headers={"Cookie": "snowth_lang=fr"})
    with urllib.request.urlopen(request) as response:
        page = response.read().decode()
    assert "Équipements" in page and 'href="?lang=en"' in page


def test_an_unknown_language_is_ignored(server):
    request = urllib.request.Request(server + "/", headers={"Cookie": "snowth_lang=xx"})
    with urllib.request.urlopen(request) as response:
        assert response.status == 200                     # falls back to the configured one


def test_the_theme_button_is_there_for_the_browser_to_use(server):
    with urllib.request.urlopen(server + "/") as response:
        page = response.read().decode()
    assert 'id="theme"' in page
    with urllib.request.urlopen(server + "/static/app.js") as response:
        script = response.read().decode()
    assert "snowth_theme" in script and "prefers-color-scheme" in script


def test_the_pages_show_the_hours_of_the_reader_not_utc(tmp_path, monkeypatch):
    """The exports stay in UTC; a page is read by someone who counts in their own hours."""
    import time as time_module

    from snowth_my_net.clock import local_time, local_zone
    from snowth_my_net.web.server import Site

    monkeypatch.setenv("TZ", "Europe/Brussels")
    time_module.tzset()
    try:
        repo = build_state(tmp_path)
        repo.conn.close()
        site = Site(make_loaded(tmp_path), FixedClock())
        assert local_time(1768467640) == "2026-01-15 10:00"         # winter: +01:00
        assert local_time(1789200040) == "2026-09-12 10:00"         # summer: +02:00
        page = site.respond("/runs", {})[2].decode()
        assert "Europe/Brussels" in page                            # said once, in the footer
        assert 'title="' in page and "Z\">" in page                 # the UTC value on hover
        assert local_zone() == "Europe/Brussels"
    finally:
        monkeypatch.undo()
        time_module.tzset()


def test_without_a_configured_zone_the_offset_is_spelled_out(monkeypatch):
    import time as time_module

    from snowth_my_net.clock import local_zone

    monkeypatch.setenv("TZ", "UTC")
    time_module.tzset()
    monkeypatch.delenv("TZ")
    try:
        assert local_zone(1789200040) in ("UTC (+00:00)", "UTC")
    finally:
        monkeypatch.undo()
        time_module.tzset()


def test_the_addresses_a_row_hides_fold_instead_of_widening_it(site):
    """A list of addresses in the cell pushed the end of the table off the screen."""
    from tests.unit.test_cov_views import D

    _status, _type, body = get(site, "/nodes")
    row = next(line for line in body.split("<tr>") if D in line)
    assert '<details class="more"><summary>+1</summary>' in row
    assert "<li>192.0.2.60</li>" in row                     # there when opened, not before
    assert "fe80::60" not in row                            # nothing can be reached by it


def test_the_table_carries_what_a_browser_needs_to_let_the_reader_arrange_it(site):
    """The chooser and the drag handles are the browser's work; the page names the columns and
    stays whole without a script."""
    _status, _type, body = get(site, "/nodes")
    assert 'class="cols" id="cols" hidden' in body        # revealed by the script, not before
    assert 'class="pick"' in body and 'class="reset"' in body
    for key in ("col-hostname_manual", "col-hostname_dns", "col-hostname_probe",
                "col-mac", "col-vendor", "col-ip", "col-seen"):
        assert f'<th class="text {key}"' in body or f'class="text {key}"' in body
    script = (site.asset("app.js")[2]).decode()
    assert "scrollWidth > cell.clientWidth" in script    # a tooltip only when really cut
    assert "localStorage" in script and "col-" in script


def test_a_report_of_an_unexpected_shape_does_not_hide_the_exit_code():
    import subprocess

    from snowth_my_net.web.jobs import summarize

    done = subprocess.CompletedProcess([], 1, stdout='{"hosts": [{"nope": 1}], "open_ports": 1}')
    assert "unexpected" in summarize("scan", done)
    assert "unexpected" in summarize("collect", subprocess.CompletedProcess([], 1, stdout="[]"))

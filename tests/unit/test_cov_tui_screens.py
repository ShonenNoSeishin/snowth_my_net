"""Terminal interface screens driven with Textual's pilot, on a state built without SNMP."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from textual.widgets import Button, DataTable, Input, Select, Static, Switch, TabbedContent

from snowth_my_net.config.loader import load_config
from snowth_my_net.lock import StateLock
from snowth_my_net.state.db import open_db
from snowth_my_net.state.repo import Repo
from snowth_my_net.tui import app as tui_app
from snowth_my_net.tui.app import (
    AddDeviceModal,
    CollectModal,
    CollectorModal,
    ConfirmModal,
    DeviceScreen,
    ExplainModal,
    HelpModal,
    SnowthApp,
    TuiContext,
)
from snowth_my_net.tui.reports import FilterRow, ReportScreen

NOW = 1_790_000_000
EXTENSION = """
collectors:
  - name: file-collector
    description: from a file
    applies_to: {types: [switch]}
    get: {firmware: 1.3.6.1.4.1.99999.1.0}
reports:
  - name: file-report
    title: From a file
    dataset: devices
"""


def write_cfg(tmp_path: Path, extra: str = "", language: str = "en") -> Path:
    (tmp_path / "extensions").mkdir(exist_ok=True)
    (tmp_path / "extensions" / "ext.yml").write_text(EXTENSION)
    cfg = tmp_path / "snowth_my_net.yml"
    cfg.write_text(f"""
general:
  state_dir: {tmp_path / 'state'}
  output_dir: {tmp_path / 'out'}
  secrets_dir: {tmp_path / 'secrets'}
  language: {language}
discovery:
  exclude: [198.51.100.0/24]
dns:
  enabled: false
{extra}""")
    return cfg


def seed_state(loaded) -> None:
    """Two polled devices (a switch with a run, custom values and a MAC table) and a target."""
    conn = open_db(loaded.paths.state_file)
    repo = Repo(conn)
    with conn:
        run = repo.start_run("collect", NOW - 60)
        repo.finish_run(run, "ok", NOW, {"devices": 2, "reachable": 2})
        conn.execute("INSERT INTO runs(command, started_at) VALUES ('collect', ?)", (NOW,))
        conn.executemany(
            "INSERT INTO devices(id, mgmt_address, sys_name, sys_descr, vendor, model, serial, "
            "os_name, os_version, base_mac, device_type, type_rule, type_reason, credential, "
            "first_seen, last_seen, last_collect_status, driver) "
            "VALUES (?, ?, ?, 'descr', ?, ?, 'SN1', 'OS', '1.0', ?, ?, ?, ?, 'v2', ?, ?, ?, ?)",
            [(1, "192.0.2.1", "sw1", "Acme", "X1", "00:00:5e:00:53:01", "switch", "catalog",
              "sysObjectID", NOW, NOW, "ok", "fortinet"),
             (2, "192.0.2.2", "fw1", "", "", None, "", "", "", NOW, NOW, "partial", None)])
        conn.executemany("INSERT INTO targets(address, origin, depth, device_id, first_seen) "
                         "VALUES (?, 'seed', 0, ?, ?)",
                         [("192.0.2.1", 1, NOW), ("192.0.2.2", 2, NOW)])
        conn.execute("INSERT INTO interfaces(device_id, ifindex, name, descr, if_type, "
                     "last_seen) VALUES (1, 3, 'Gi1/0/3', 'Gi1/0/3', 6, ?)", (NOW,))
        conn.executemany(
            "INSERT INTO fdb_obs(mac, device_id, ifindex, vlan, vlan_source, method, first_seen, "
            "last_seen, last_run_id) VALUES (?, 1, 3, 10, 'fdb', 'qbridge', ?, ?, ?)",
            [(f"00:00:5e:00:54:{n:02x}", NOW, NOW, run) for n in range(3)])
        conn.executemany(
            "INSERT INTO collect_status(run_id, device_id, function, status, rows, duration_ms, "
            "detail) VALUES (?, 1, ?, ?, ?, 12, ?)",
            [(run, "fdb", "ok", 3, ""), (run, "arp", "timeout", 0, "no answer")])
        conn.execute("INSERT INTO custom_runs(device_id, collector, run_at, status, rows) "
                     "VALUES (1, 'poe', ?, 'ok', 2)", (NOW,))
        conn.executemany(
            "INSERT INTO custom_values(device_id, collector, idx, column, value, first_seen, "
            "last_seen) VALUES (1, 'poe', ?, ?, ?, ?, ?)",
            [("", "firmware", "2.1", NOW, NOW), ("1.1", "status", "delivering", NOW, NOW)])
    repo.ensure_target("192.0.2.30", "manual", 0, NOW)
    repo.target_failed("192.0.2.30", NOW, "no answer (v2: timeout)")
    repo.save_custom_collector("tui-collector", {
        "name": "tui-collector", "walk": {"columns": {"a": "1.3.6.1.2.1.2.2.1.2"}}}, NOW)
    conn.close()


class Clock:
    def now(self) -> int:
        return NOW


@pytest.fixture
def make_app(tmp_path):
    contexts = []

    def make(extra: str = "", language: str = "en", seed: bool = True):
        loaded = load_config(write_cfg(tmp_path, extra, language))
        if seed:
            seed_state(loaded)
        ctx = TuiContext(loaded, Clock())
        contexts.append(ctx)
        app = SnowthApp(ctx)
        notes: list[tuple[str, str]] = []
        original = app.notify

        def notify(message, *args, severity="information", **kwargs):
            notes.append((str(message), severity))
            return original(message, *args, severity=severity, **kwargs)

        app.notify = notify
        app.notes = notes
        return app

    yield make
    for ctx in contexts:
        ctx.close()


async def settle(app, pilot, rounds: int = 3):
    for _ in range(rounds):
        await pilot.pause()
        await app.workers.wait_for_complete()
    await pilot.pause()


def tab(app, name: str) -> None:
    app.screen.query_one("#main-tabs", TabbedContent).active = f"tab-{name}"


def plain(widget: Static) -> str:
    """Text of a Static whose content is a Rich renderable (tables)."""
    import io

    from rich.console import Console

    console = Console(width=220, file=io.StringIO(), record=True)
    console.print(widget.content)
    return console.export_text()


def cells(table: DataTable) -> list[list[str]]:
    return [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)]


# --------------------------------------------------------------------------- main screen


async def test_devices_list_filter_help_and_refresh(make_app):
    app = make_app()
    async with app.run_test(size=(160, 45)) as pilot:
        await settle(app, pilot)
        screen = app.screen
        table = screen.query_one("#devices", DataTable)
        rows = cells(table)
        assert [r[0] for r in rows] == ["192.0.2.30", "fw1", "sw1"]
        assert rows[2][2] == "switch" and rows[2][5].startswith("●")
        assert rows[0][5].startswith("✖") and rows[1][5].startswith("◐")
        assert "last collect" in str(screen.query_one("#runstatus").render())
        await pilot.press("slash")
        await settle(app, pilot)
        assert isinstance(app.focused, Input) and app.focused.id == "filter"
        await pilot.press("f", "w")
        await settle(app, pilot)
        assert [r[0] for r in cells(table)] == ["fw1"]
        await pilot.press("enter")                         # filter submitted: back to the table
        await settle(app, pilot)
        assert app.focused is table
        screen.query_one("#filter", Input).value = ""
        await settle(app, pilot)
        await pilot.press("question_mark")
        await settle(app, pilot)
        assert isinstance(app.screen, HelpModal)
        await pilot.press("escape")
        await settle(app, pilot)
        await pilot.press("question_mark")
        await settle(app, pilot)
        await pilot.click("#ok")
        await settle(app, pilot)
        assert app.screen is screen
        runs = screen.query_one("#runs", DataTable)
        assert [r[4] for r in cells(runs)] == ["running", "ok"]
        assert cells(runs)[0][3] == "…" and cells(runs)[1][5] == "2/2"
        for name in ("nodes", "links"):
            tab(app, name)
            await settle(app, pilot)
            screen.action_refresh()
            await settle(app, pilot)
        assert "3" in str(screen.query_one("#nodes-count", Static).render())


async def test_nodes_truncation_and_explain(make_app, monkeypatch):
    monkeypatch.setattr(tui_app.MainScreen, "NODE_LIMIT", 2)
    app = make_app()
    async with app.run_test(size=(160, 45)) as pilot:
        await settle(app, pilot)
        tab(app, "nodes")
        await settle(app, pilot)
        screen = app.screen
        nodes = screen.query_one("#nodes", DataTable)
        assert nodes.row_count == 2
        assert "2" in str(screen.query_one("#nodes-count", Static).render())
        nodes.focus()
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, ExplainModal)
        await pilot.press("escape")
        await settle(app, pilot)
        assert app.screen is screen


async def test_add_device_modal(make_app):
    app = make_app()
    async with app.run_test(size=(160, 45)) as pilot:
        await settle(app, pilot)
        await pilot.press("a")
        await settle(app, pilot)
        modal = app.screen
        assert isinstance(modal, AddDeviceModal)
        modal.query_one("#address", Input).value = "not an address"
        modal.submit()
        await settle(app, pilot)
        assert "Not a valid address" in str(modal.query_one("#add-message", Static).render())
        modal.query_one("#address", Input).value = "198.51.100.7"
        modal.submit()
        await settle(app, pilot)
        assert "discovery.exclude" in str(modal.query_one("#add-message", Static).render())
        await pilot.click("#cancel")
        await settle(app, pilot)
        assert not isinstance(app.screen, AddDeviceModal)
        await pilot.press("a")
        await settle(app, pilot)
        await pilot.press("escape")
        await settle(app, pilot)
        await pilot.press("a")
        await settle(app, pilot)
        app.screen.query_one("#address", Input).value = "192.0.2.99"
        await pilot.press("enter")
        await settle(app, pilot)
        assert ("192.0.2.99 added", "information") in app.notes
        assert "192.0.2.99" in [r[0] for r in cells(app.screen.query_one("#devices", DataTable))]


async def test_remove_device_seed_warning_and_cancel(make_app):
    app = make_app(extra="discovery:\n  seeds: [192.0.2.1]\n")
    async with app.run_test(size=(160, 45)) as pilot:
        await settle(app, pilot)
        screen = app.screen
        table = screen.query_one("#devices", DataTable)
        table.focus()
        table.move_cursor(row=2)                                  # sw1, a seed
        await pilot.press("delete")
        for _ in range(8):
            await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        assert "seed" in app.screen.message
        await pilot.press("escape")                               # cancelled
        await settle(app, pilot)
        assert ctx_repo(app).device(1) is not None
        table.move_cursor(row=1)                                  # fw1
        await pilot.press("delete")
        for _ in range(8):
            await pilot.pause()
        assert "seed" not in app.screen.message
        await pilot.click("#yes")
        await settle(app, pilot)
        assert ctx_repo(app).device(2) is None
        assert ("fw1 forgotten", "information") in app.notes


def ctx_repo(app) -> Repo:
    return app.ctx.repo


async def test_remove_with_nothing_selected_does_nothing(make_app):
    app = make_app(seed=False)
    app.ctx.loaded.collectors, app.ctx.loaded.reports = [], []
    async with app.run_test(size=(160, 45)) as pilot:
        await settle(app, pilot)
        screen = app.screen
        assert screen.query_one("#devices-empty", Static).display
        assert screen.selected_row() is None
        assert "no collect yet" in str(screen.query_one("#runstatus").render())
        for name in ("devices", "reports", "extensions"):
            tab(app, name)
            await settle(app, pilot)
            screen.action_remove()
            await settle(app, pilot)
            assert app.screen is screen
        assert screen.selected_collector() is None and screen.selected_report() is None
        tab(app, "reports")
        await settle(app, pilot)
        screen.action_export_report()                             # no report selected
        screen.action_open()                                      # no device selected
        await settle(app, pilot)
        assert app.screen is screen and app.notes == []


async def test_selected_row_survives_a_broken_cursor(make_app, monkeypatch):
    app = make_app()
    async with app.run_test(size=(160, 45)) as pilot:
        await settle(app, pilot)
        screen = app.screen
        table = screen.query_one("#devices", DataTable)

        def broken(*_args):
            raise RuntimeError("cursor outside the table")

        monkeypatch.setattr(table, "coordinate_to_cell_key", broken)
        assert screen.selected_row() is None


async def test_open_device_with_action_and_row_selected(make_app):
    app = make_app()
    async with app.run_test(size=(160, 45)) as pilot:
        await settle(app, pilot)
        screen = app.screen
        screen.query_one("#devices", DataTable).move_cursor(row=2)
        screen.action_open()
        await settle(app, pilot)
        assert isinstance(app.screen, DeviceScreen) and app.screen.row.name == "sw1"
        await pilot.press("escape")
        await settle(app, pilot)

        class Event:
            class row_key:
                value = "nowhere"

        screen.row_selected(Event())
        await settle(app, pilot)
        assert app.screen is screen


async def test_extensions_tab_detail_and_delete_rules(make_app):
    app = make_app()
    async with app.run_test(size=(160, 45)) as pilot:
        await settle(app, pilot)
        tab(app, "extensions")
        await settle(app, pilot)
        screen = app.screen
        table = screen.query_one("#extensions", DataTable)
        rows = cells(table)
        assert [r[0] for r in rows] == ["file-collector", "tui-collector"]
        assert rows[0][2] == "switch" and rows[1][3] == "created in the interface"
        table.focus()
        table.move_cursor(row=0)
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, CollectorModal)
        text = str(app.screen.query_one("#collector-yaml", Static).render())
        assert "firmware: 1.3.6.1.4.1.99999.1.0" in text and "types:" in text
        await pilot.click("#close")
        await settle(app, pilot)
        await pilot.press("delete")                               # file collector: refused
        await settle(app, pilot)
        assert any("comes from" in n for n, _s in app.notes)
        table.move_cursor(row=1)
        await pilot.press("delete")
        for _ in range(8):
            await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        await pilot.press("escape")
        await settle(app, pilot)
        assert "tui-collector" in app.ctx.repo.custom_stored()


async def test_collect_refused_without_credentials(make_app):
    app = make_app(extra="credentials:\n  - name: broken\n    version: 2c\n"
                         "    community_file: missing\n")
    async with app.run_test(size=(160, 45)) as pilot:
        await settle(app, pilot)
        screen = app.screen
        banners = [str(w.render()) for w in screen.query(".banner-error")]
        assert banners and "missing" in banners[0]
        await pilot.press("c")
        await settle(app, pilot)
        assert not isinstance(app.screen, CollectModal)
        assert app.notes[-1][1] == "error"
        screen.query_one("#devices", DataTable).move_cursor(row=2)
        screen.action_open()
        await settle(app, pilot)
        device = app.screen
        await pilot.press("c")
        await settle(app, pilot)
        assert not isinstance(app.screen, CollectModal) and app.notes[-1][1] == "error"
        device.run_probe("system")
        await settle(app, pilot)
        assert "credential" in str(device.query_one("#tester-status", Static).render()).lower()


async def test_collect_modal_busy_lock_errors_and_failures(make_app, monkeypatch):
    app = make_app()
    async with app.run_test(size=(160, 45)) as pilot:
        await settle(app, pilot)
        lock = StateLock(app.ctx.loaded.paths.lock_file, "someone else")
        lock.acquire(0)
        try:
            await pilot.press("c")
            await settle(app, pilot)
            modal = app.screen
            assert isinstance(modal, CollectModal) and modal.finished
            assert "someone else" in str(modal.query_one("#collect-status", Static).render())
        finally:
            lock.release()
        await pilot.press("escape")
        await settle(app, pilot)
        assert not isinstance(app.screen, CollectModal)

        # No seed and no known address to poll: the run reports it as an error line.
        conn = app.ctx.conn
        with conn:
            conn.execute("DELETE FROM targets")
        await pilot.press("c")
        await settle(app, pilot, rounds=5)
        modal = app.screen
        assert "failed" in str(modal.query_one("#collect-status", Static).render())
        await pilot.click("#close")
        await settle(app, pilot)

        async def explode(self, only=None):
            raise RuntimeError("state is gone")

        monkeypatch.setattr(tui_app.Collector, "run", explode)
        await pilot.press("c")
        await settle(app, pilot)
        modal = app.screen
        assert "state is gone" in str(modal.query_one("#collect-status", Static).render())
        modal.finished = False
        modal.action_close()                                      # still running: stays open
        assert app.screen is modal
        modal.finished = True
        modal.action_close()
        await settle(app, pilot)
        assert not isinstance(app.screen, CollectModal)


async def test_theme_is_restored_and_saved_on_quit(make_app):
    app = make_app()
    app.ctx.repo.set_meta("tui_theme", "gruvbox")
    async with app.run_test(size=(160, 45)) as pilot:
        await settle(app, pilot)
        assert app.theme == "gruvbox"
        app.theme = "dracula"
        await pilot.press("q")
        await settle(app, pilot)
    assert app.ctx.repo.get_meta("tui_theme") == "dracula"
    assert app.report_screen(None).__class__ is app.report_screen(None).__class__


async def test_french_interface(make_app):
    app = make_app(language="fr")
    async with app.run_test(size=(160, 45)) as pilot:
        await settle(app, pilot)
        labels = [str(t.label) for t in app.screen.query_one("#main-tabs", TabbedContent)
                  .query("ContentTab")]
        assert "Équipements" in labels and "Rapports" in labels
        assert any(b.description == "Tout collecter" for b in app.screen.BINDINGS)


# --------------------------------------------------------------------------- reports tab


async def test_reports_tab_keys_export_and_delete(make_app):
    app = make_app()
    app.ctx.repo.save_report("tui-report", {"name": "tui-report", "dataset": "devices",
                                            "filters": [{"field": "vendor", "op": "eq",
                                                         "value": "nobody"}]}, NOW)
    app.ctx.repo.save_report("all-devices", {"name": "all-devices", "dataset": "devices",
                                             "format": "json", "schedule": "0 7 * * 1"}, NOW)
    async with app.run_test(size=(160, 45)) as pilot:
        await settle(app, pilot)
        screen = app.screen
        assert screen.check_action("new_report", ()) is False
        tab(app, "reports")
        await settle(app, pilot)
        assert screen.check_action("new_report", ()) is True
        table = screen.query_one("#reports", DataTable)
        rows = cells(table)
        assert [r[0] for r in rows] == ["file-report", "all-devices", "tui-report"]
        assert rows[1][3] == "0 7 * * 1" and rows[0][6] == "From a file"
        assert not screen.query_one("#reports-empty", Static).display

        table.move_cursor(row=1)
        await pilot.press("x")
        await settle(app, pilot)
        written = Path(app.ctx.loaded.paths.output_dir / "reports" / "all-devices.json")
        assert json.loads(written.read_text())["row_count"] == 2
        assert any("all-devices.json" in n for n, _s in app.notes)

        table.move_cursor(row=2)
        await pilot.press("x")                                     # no row: not written
        await settle(app, pilot)
        assert app.notes[-1][1] == "warning"
        assert not (written.parent / "tui-report.csv").exists()

        output = Path(app.ctx.loaded.paths.output_dir)
        output.parent.mkdir(parents=True, exist_ok=True)
        (output / "reports").mkdir(parents=True, exist_ok=True)
        (output / "reports" / "file-report.csv").mkdir()           # cannot be replaced
        table.move_cursor(row=0)
        await pilot.press("x")
        await settle(app, pilot)
        assert app.notes[-1][1] == "error"

        await pilot.press("delete")                                # file report: refused
        await settle(app, pilot)
        assert "comes from" in app.notes[-1][0]
        table.move_cursor(row=2)
        await pilot.press("delete")
        for _ in range(8):
            await pilot.pause()
        await pilot.click("#yes")
        await settle(app, pilot)
        assert "tui-report" not in app.ctx.repo.reports_stored()
        assert table.row_count == 2

        table.move_cursor(row=0)
        await pilot.press("enter")
        await settle(app, pilot)
        builder = app.screen
        assert isinstance(builder, ReportScreen)
        assert "Defined in" in str(builder.query_one(".intro", Static).render())
        await pilot.press("escape")
        await settle(app, pilot)
        await pilot.press("n")
        await settle(app, pilot)
        assert isinstance(app.screen, ReportScreen) and app.screen.report is None


async def test_reports_empty_state(make_app):
    app = make_app()
    (Path(app.ctx.loaded.paths.config_file).parent / "extensions" / "ext.yml").write_text("")
    app.ctx.loaded.reports = []
    async with app.run_test(size=(160, 45)) as pilot:
        await settle(app, pilot)
        tab(app, "reports")
        await settle(app, pilot)
        empty = app.screen.query_one("#reports-empty", Static)
        assert empty.display and "No report yet" in str(empty.render())
        app.screen.action_export_report()
        assert app.notes == []


# --------------------------------------------------------------------------- report builder


async def open_builder(app, pilot, report=None):
    app.push_screen(app.report_screen(report))
    await settle(app, pilot)
    return app.screen


async def test_builder_sql_mode_columns_limit_and_invalid_definitions(make_app):
    app = make_app()
    async with app.run_test(size=(170, 48)) as pilot:
        await settle(app, pilot)
        builder = await open_builder(app, pilot)
        status = builder.query_one("#b-status", Static)
        assert "2 of 2" in str(status.render())

        builder.query_one("#b-limit", Input).value = "1"
        builder.refresh_preview()
        assert "keeps the first 1" in str(status.render())
        builder.query_one("#b-limit", Input).value = ""

        builder.query_one("#b-source", Select).value = "__sql__"
        await settle(app, pilot)
        assert builder.query_one("#b-sql-part").display
        assert not builder.query_one("#b-dataset-part").display
        builder.query_one("#b-sql").text = "select name, 'x' || repeat from devices"
        builder.refresh_preview()
        assert "sql:" in str(status.render())
        assert builder.query_one("#b-preview", DataTable).row_count == 0
        builder.query_one("#b-sql").text = (
            "select name, printf('%060d', 7) as wide, count(*) as n from devices group by name")
        builder.refresh_preview()
        preview = builder.query_one("#b-preview", DataTable)
        assert preview.row_count == 2 and str(preview.get_row_at(0)[1]).endswith("…")
        assert str(preview.get_row_at(0)[2]) == "1"

        builder.query_one("#b-sql").text = "delete from devices"
        builder.refresh_preview()
        assert "fix the definition" in str(status.render())
        assert "SELECT" in str(builder.query_one("#b-message", Static).render())

        builder.query_one("#b-name", Input).value = ""
        builder.action_save()
        assert "Give the report a name" in str(builder.query_one("#b-message", Static).render())
        builder.action_export()
        await settle(app, pilot)
        builder.query_one("#b-name", Input).value = "Bad Name"
        builder.action_save()
        assert "lowercase" in str(builder.query_one("#b-message", Static).render())

        builder.query_one("#b-source", Select).value = "devices"
        await settle(app, pilot)
        builder.query_one("#b-name", Input).value = ""
        builder.action_export()                                    # valid but unnamed
        await settle(app, pilot)
        assert "Give the report a name" in str(builder.query_one("#b-message", Static).render())


async def test_builder_filters_columns_labels_and_save_rules(make_app):
    app = make_app()
    stored = {"name": "edited", "title": "Edited", "description": "kept",
              "output": "custom/edited.csv", "dataset": "devices",
              "columns": [{"field": "name", "label": "Device Name"}, "vendor"],
              "filters": [{"field": "vendor", "op": "in", "value": ["Acme", "Other"]}],
              "sort": ["-name"], "limit": 5, "allow_empty": True}
    app.ctx.repo.save_report("edited", stored, NOW)
    app.ctx.repo.save_report("taken", {"name": "taken", "dataset": "runs"}, NOW)
    async with app.run_test(size=(170, 48)) as pilot:
        await settle(app, pilot)
        loaded = next(r for r in tui_reports_catalog(app) if r.cfg.name == "edited")
        builder = await open_builder(app, pilot, loaded)
        rows = list(builder.query(FilterRow))
        assert len(rows) == 1
        assert rows[0].query_one(".f-value", Input).value == "Acme, Other"
        assert builder.definition() == {
            "name": "edited", "title": "Edited", "description": "kept",
            "output": "custom/edited.csv", "dataset": "devices",
            "columns": [{"field": "name", "label": "Device Name"}, "vendor"],
            "filters": [{"field": "vendor", "op": "in", "value": ["Acme", "Other"]}],
            "sort": ["-name"], "limit": 5, "format": "csv", "allow_empty": True}
        preview = builder.query_one("#b-preview", DataTable)
        assert [str(c.label) for c in preview.columns.values()] == ["Device Name", "vendor"]

        await pilot.click("#b-add-filter")
        await settle(app, pilot)
        rows = list(builder.query(FilterRow))
        assert len(rows) == 2 and rows[1].definition() is None     # no field chosen yet
        rows[1].query_one(".f-field", Select).value = "device_type"
        rows[1].query_one(".f-op", Select).value = "empty"
        assert rows[1].definition() == {"field": "device_type", "op": "empty"}
        await settle(app, pilot)
        rows[0].query_one(".f-remove", Button).press()
        await settle(app, pilot)
        await pilot.pause(0.7)                                     # debounced preview
        await settle(app, pilot)
        assert [r.definition() for r in builder.query(FilterRow)] == [
            {"field": "device_type", "op": "empty"}]
        assert builder.query_one("#b-preview", DataTable).row_count == 1

        builder.query_one("#b-name", Input).value = "file-report"
        builder.action_save()
        assert "extension file" in str(builder.query_one("#b-message", Static).render())
        builder.query_one("#b-name", Input).value = "taken"
        builder.action_save()
        assert "already exists" in str(builder.query_one("#b-message", Static).render())

        builder.query_one("#b-name", Input).value = "renamed"
        builder.query_one("#b-schedule", Input).value = "0 6 * * *"
        builder.action_save()
        stored_now = app.ctx.repo.reports_stored()
        assert "renamed" in stored_now and "edited" not in stored_now
        assert stored_now["renamed"]["schedule"] == "0 6 * * *"
        assert "crontab" in app.notes[-1][0]
        builder.action_save()                                      # saving again: same name
        assert "renamed" in app.ctx.repo.reports_stored()

        builder.query_one("#b-allow-empty", Switch).value = False
        builder.query_one("#b-filters").mount(FilterRow(app.ctx.t, ["vendor"], {
            "field": "vendor", "op": "eq", "value": "nobody"}))
        await settle(app, pilot)
        await builder.run_action("export")
        await settle(app, pilot)
        assert app.notes[-1][1] == "warning"                        # empty: not written

        builder.action_reload()
        await pilot.press("escape")
        await settle(app, pilot)
        assert not isinstance(app.screen, ReportScreen)


def tui_reports_catalog(app):
    from snowth_my_net.tui.reports import catalog

    return catalog(app.ctx)


async def test_builder_unknown_dataset_and_export_errors(make_app, monkeypatch):
    from snowth_my_net.config.reports import LoadedReport, ReportCfg

    app = make_app()
    async with app.run_test(size=(170, 48)) as pilot:
        await settle(app, pilot)
        ghost = LoadedReport(ReportCfg(name="ghost", dataset="custom:gone"), "tui")
        builder = await open_builder(app, pilot, ghost)
        source = builder.query_one("#b-source", Select)
        assert source.value == "custom:gone"
        assert "unknown" in str(builder.query_one("#b-status", Static).render()).lower()
        assert builder.query_one("#b-columns").option_count == 0
        builder.add_filter()
        await settle(app, pilot)
        assert builder.query_one(FilterRow).fields == []

        builder.query_one("#b-name", Input).value = "ghost"
        await builder.run_action("export")
        await settle(app, pilot)
        assert app.notes[-1][1] == "error"

        source.value = "devices"
        await settle(app, pilot)
        monkeypatch.setattr("snowth_my_net.tui.reports.generate",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
        await builder.run_action("export")
        await settle(app, pilot)
        assert app.notes[-1] == ("disk full", "error")


async def test_builder_export_then_push(make_app, tmp_path):
    from tests.support.fake_push import FakeImportServer

    token = "tok-tui-push-1234"
    secrets = tmp_path / "secrets"
    secrets.mkdir(exist_ok=True)
    (secrets / "token").write_text(token)
    (secrets / "token").chmod(0o600)
    with FakeImportServer(token=token) as server:
        extra = f"""push:
  targets:
    - name: cmdb
      url: {server.base_url}/ok
      auth: {{bearer_token_file: token}}
      timeout: 5
    - name: broken
      url: {server.base_url}/error
      auth: {{bearer_token_file: token}}
      timeout: 5
"""
        app = make_app(extra=extra)
        async with app.run_test(size=(170, 48)) as pilot:
            await settle(app, pilot)
            builder = await open_builder(app, pilot)
            builder.query_one("#b-name", Input).value = "pushed"
            push = builder.query_one("#b-push")
            push.select("cmdb")
            push.select("broken")
            await settle(app, pilot)
            assert builder.definition()["push"] == ["cmdb", "broken"]
            await builder.run_action("export")
            for _ in range(8):
                await pilot.pause()
            assert isinstance(app.screen, ConfirmModal)
            await pilot.click("#yes")
            await settle(app, pilot, rounds=6)
            texts = [n for n, _s in app.notes]
            assert any(n.startswith("cmdb: OK") for n in texts)
            assert any(n.startswith("broken: FAILED") for n in texts)
            received = [r.path for r in server.received]
            assert "/ok" in received and "/error" in received

            await builder.run_action("export")
            for _ in range(8):
                await pilot.pause()
            await pilot.press("escape")                            # no push this time
            await settle(app, pilot)
            assert len([r for r in server.received if r.path == "/ok"]) == 1


async def test_builder_push_warnings_are_notified(make_app, tmp_path, monkeypatch):
    from snowth_my_net.push.http import PushOutcome

    app = make_app()
    monkeypatch.setattr("snowth_my_net.tui.reports.push_report",
                        lambda loaded, generated: ([PushOutcome("t", "report:x", True)],
                                                   ["TLS verification disabled"]))
    async with app.run_test(size=(170, 48)) as pilot:
        await settle(app, pilot)
        builder = await open_builder(app, pilot)
        builder.push(object())
        await settle(app, pilot)
        assert ("TLS verification disabled", "warning") in app.notes
        assert ("t: OK", "information") in app.notes


# --------------------------------------------------------------------------- device screen


async def open_device(app, pilot, name: str):
    screen = app.screen
    row = next(r for r in screen.rows if r.name == name)
    app.push_screen(app.device_screen(row))
    await settle(app, pilot)
    return app.screen


async def test_device_sheet_identity_last_collect_and_custom_values(make_app):
    app = make_app()
    async with app.run_test(size=(170, 48)) as pilot:
        await settle(app, pilot)
        device = await open_device(app, pilot, "sw1")
        identity = plain(device.query_one("#identity", Static))
        assert "fortinet" in identity and "catalog — sysObjectID" in identity
        last = cells(device.query_one("#last", DataTable))
        assert ["arp", "timeout", "0", "12 ms", "no answer"] in last
        custom = cells(device.query_one("#custom", DataTable))
        assert custom[1][:4] == ["", "", "firmware", "2.1"]
        assert custom[2][:4] == ["", "1.1", "status", "delivering"]
        assert str(device.query_one("#neighbors-empty", Static).render()) == \
            app.ctx.t("neighbors.none")
        await pilot.press("question_mark")
        await settle(app, pilot)
        assert isinstance(app.screen, HelpModal)
        await pilot.press("escape")
        await settle(app, pilot)

        # The detected type changes behind the sheet: the "automatic" label follows.
        with app.ctx.conn:
            app.ctx.conn.execute("UPDATE devices SET device_type = 'router' WHERE id = 1")
        device.refresh_all()
        await settle(app, pilot)
        options = [str(o[0]) for o in device.query_one("#f-type", Select)._options]
        assert any("router" in o.lower() for o in options[:2])


async def test_device_sheet_of_a_device_without_collect_status(make_app):
    app = make_app()
    async with app.run_test(size=(170, 48)) as pilot:
        await settle(app, pilot)
        device = await open_device(app, pilot, "fw1")
        assert str(device.query_one("#last-when", Static).render()) == app.ctx.t("last.none")
        assert device.query_one("#last", DataTable).row_count == 0
        assert device.query_one("#custom-empty", Static).display
        await pilot.press("escape")
        await settle(app, pilot)
        pending = await open_device(app, pilot, "192.0.2.30")
        identity = plain(pending.query_one("#identity", Static))
        assert "no answer (v2: timeout)" in identity
        assert pending.device() is None
        assert pending.query_one("#last", DataTable).row_count == 0


async def test_device_settings_save_paths(make_app):
    app = make_app(extra="devices:\n  - address: 192.0.2.1\n    type: firewall\n")
    async with app.run_test(size=(170, 48)) as pilot:
        await settle(app, pilot)
        device = await open_device(app, pilot, "sw1")
        options = [str(o[0]) for o in device.query_one("#f-type", Select)._options]
        assert "config.yml" in options[0]

        await device.run_action("save")
        await settle(app, pilot)
        assert app.notes[-1][0] == app.ctx.t("set.nothing")

        device.query_one("#f-snmp-max_repetitions", Input).value = "-5"
        device.save_pressed()
        await settle(app, pilot)
        assert app.notes[-1][1] == "error"

        device.query_one("#f-snmp-max_repetitions", Input).value = "7"
        device.query_one("#f-disabled", Switch).value = True
        device.save_pressed()
        for _ in range(8):
            await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        await pilot.press("escape")                                   # disabling cancelled
        await settle(app, pilot)
        assert app.ctx.repo.manual_settings() == {}

        device.query_one("#f-disabled", Switch).value = False
        device.query_one("#f-name", Input).value = "core"
        device.save_pressed()
        await settle(app, pilot)
        assert app.ctx.repo.manual_settings() == {
            "192.0.2.1": {"snmp.max_repetitions": 7, "name": "core"}}
        assert device.query_one("#s-name", Static).render().plain == app.ctx.t("src.manual")

        device.query_one("#f-name", Input).value = ""
        device.save_pressed()
        await settle(app, pilot)
        assert app.ctx.repo.manual_settings() == {"192.0.2.1": {"snmp.max_repetitions": 7}}

        device.query_one("#reset", Button).press()
        await settle(app, pilot)
        assert app.ctx.repo.manual_settings() == {}
        assert app.notes[-1][0] == app.ctx.t("set.reset_done")


async def test_tester_input_errors_and_unreachable_device(tmp_path):
    """Nothing listens on UDP port 9 of 127.0.0.19: every probe times out quickly."""
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "community").write_text("lab-ro-community")
    (secrets / "community").chmod(0o600)
    cfg = write_cfg(tmp_path, "credentials:\n  - name: v2\n    version: 2c\n"
                              "    community_file: community\n")
    cfg.write_text(cfg.read_text().replace(
        "  language: en\n", "  language: en\n  snmp:\n    port: 9\n    probe_timeout: 0.2\n"
        "    timeout: 0.2\n    retries: 0\n"))
    loaded = load_config(cfg)
    seed_state(loaded)
    ctx = TuiContext(loaded, Clock())
    app = SnowthApp(ctx)
    try:
        async with app.run_test(size=(170, 48)) as pilot:
            await settle(app, pilot)
            device = await open_device(app, pilot, "192.0.2.30")
            status = device.query_one("#tester-status", Static)
            device.oid_submitted()                                    # empty input: nothing
            await settle(app, pilot)
            assert str(status.render()) == app.ctx.t("tester.hint")
            device.query_one("#oid", Input).value = "not-an-oid"
            device.oid_submitted()
            await settle(app, pilot)
            assert "not-an-oid" in str(status.render())
            device.query_one("#limit", Input).value = ""
            assert device.limit() == 50
            device.query_one("#limit", Input).value = "999999"
            assert device.limit() == 10_000

            device.row.target = "127.0.0.19"
            device.run_probe("system")
            await settle(app, pilot, rounds=6)
            assert str(status.render()).startswith("Unreachable: ")
            device.run_probe("system")                                # pool reused
            await settle(app, pilot, rounds=6)
            assert device.pool is not None

            device.connection = None
            device.row.target = "not a target"
            device.run_probe("system")
            await settle(app, pilot)
            assert "address" in str(status.render()).lower()

            device.save_oid_pressed()                                 # nothing tested yet
            assert app.screen is device
            await pilot.press("escape")
            await settle(app, pilot)
    finally:
        ctx.close()


async def test_stale_selections_and_cancelled_report_deletion(make_app):
    app = make_app()
    app.ctx.repo.save_report("kept", {"name": "kept", "dataset": "devices"}, NOW)
    app.ctx.repo.ensure_target("192.0.2.77", "manual", 0, NOW)          # never polled, no error
    async with app.run_test(size=(160, 45)) as pilot:
        await settle(app, pilot)
        screen = app.screen
        tab(app, "links")
        screen.query_one("#links", DataTable).focus()          # keep the tab when it settles
        await settle(app, pilot)
        assert screen.query_one("#main-tabs", TabbedContent).active == "tab-links"
        screen.action_refresh()
        await settle(app, pilot)
        assert "0" in str(screen.query_one("#links-count", Static).render())

        tab(app, "reports")
        await settle(app, pilot)
        reports = screen.query_one("#reports", DataTable)
        reports.move_cursor(row=reports.get_row_index("kept"))
        await pilot.press("delete")
        for _ in range(8):
            await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        app.screen.query_one("#no", Button).press()
        await settle(app, pilot)
        assert app.screen is screen and "kept" in app.ctx.repo.reports_stored()
        reports.move_cursor(row=reports.get_row_index("kept"))
        app.ctx.repo.delete_report("kept")                          # deleted behind the table
        screen.report_selected()
        await settle(app, pilot)
        assert app.screen is screen

        tab(app, "extensions")
        await settle(app, pilot)
        extensions = screen.query_one("#extensions", DataTable)
        extensions.move_cursor(row=extensions.get_row_index("tui-collector"))
        app.ctx.repo.delete_custom_collector("tui-collector")
        screen.extension_selected()
        await settle(app, pilot)
        assert app.screen is screen

        pending = await open_device(app, pilot, "192.0.2.77")
        identity = plain(pending.query_one("#identity", Static))
        assert app.ctx.t("id.never") in identity and app.ctx.t("id.last_error") not in identity


async def test_save_collector_modal_rules(make_app):
    from snowth_my_net.tui.app import SaveCollectorModal

    app = make_app()
    async with app.run_test(size=(170, 48)) as pilot:
        await settle(app, pilot)
        row = next(r for r in app.screen.rows if r.name == "fw1")
        results = []
        columns = {"sysName": "1.3.6.1.2.1.1.5.0", "sysLocation": "1.3.6.1.2.1.1.6.0"}
        app.push_screen(SaveCollectorModal(app.ctx, row, columns, "get", "system", "", ""),
                        results.append)
        await settle(app, pilot)
        modal = app.screen
        scopes = [value for _label, value in modal.query_one("#c-scope", Select)._options]
        assert scopes == ["device", "all"]                          # no vendor, no type
        assert not modal.query("#c-column")                         # several columns
        modal.query_one("#c-name", Input).value = "Bad Name"
        modal.save()
        await settle(app, pilot)
        assert "lowercase" in str(modal.query_one("#c-message", Static).render())
        modal.query_one("#c-name", Input).value = "file-collector"
        modal.save()
        await settle(app, pilot)
        assert "already exists" in str(modal.query_one("#c-message", Static).render())
        modal.query_one("#c-name", Input).value = "system-all"
        modal.query_one("#c-description", Input).value = "identity everywhere"
        modal.query_one("#c-scope", Select).value = "all"
        assert modal.definition() == {"name": "system-all", "description": "identity everywhere",
                                      "get": columns}
        modal.save()
        await settle(app, pilot)
        assert results == ["system-all"]
        assert app.ctx.repo.custom_stored()["system-all"]["get"] == columns

        sw = next(r for r in app.screen.rows if r.name == "sw1")
        app.push_screen(SaveCollectorModal(app.ctx, sw, {"value": "1.3.6.1.2.1.2.2.1.2"}, "walk",
                                           "oid-x", "Acme", "switch"), results.append)
        await settle(app, pilot)
        modal = app.screen
        scopes = [value for _label, value in modal.query_one("#c-scope", Select)._options]
        assert scopes == ["device", "vendor", "type", "all"]
        modal.query_one("#c-column", Input).value = ""
        modal.query_one("#c-type", Select).value = "text"
        modal.query_one("#c-scope", Select).value = "type"
        assert modal.definition() == {"name": "oid-x", "applies_to": {"types": ["switch"]},
                                      "walk": {"columns": {"value": {
                                          "oid": "1.3.6.1.2.1.2.2.1.2", "type": "text"}}}}
        await pilot.click("#cancel")
        await settle(app, pilot)
        assert results == ["system-all", None]


async def test_filter_row_outside_the_builder_just_removes_itself():
    from textual.app import App

    from snowth_my_net.tui.i18n import Translator

    class Host(App):
        def compose(self):
            yield FilterRow(Translator("en"), ["name"], {"field": "name", "op": "not_in",
                                                         "value": ["a", "b"]})

    app = Host()
    async with app.run_test() as pilot:
        row = app.query_one(FilterRow)
        row.query_one(".f-value", Input).value = " a , ,b "
        assert row.definition() == {"field": "name", "op": "not_in", "value": ["a", "b"]}
        row.query_one(".f-remove", Button).press()
        await pilot.pause()
        assert not app.query(FilterRow)

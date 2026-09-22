"""Manual settings, OID tester (CLI and TUI) and the terminal interface against snmpsim."""

from __future__ import annotations

import json

import pytest
from textual.widgets import DataTable, Input, Select, TabbedContent

from snowth_my_net.cli import main
from snowth_my_net.config.loader import load_config
from snowth_my_net.state.db import open_db
from snowth_my_net.state.repo import Repo
from snowth_my_net.tui.app import AddDeviceModal, CollectModal, DeviceScreen, SnowthApp, TuiContext
from tests.support.lab import write_config


def run_json(capsys, *argv: str) -> tuple[int, object]:
    code = main(["--json", *argv])
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def collected(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=lab.all_seeds())
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    capsys.readouterr()
    return cfg


def device_types(capsys, cfg) -> dict[str, tuple[str, str]]:
    _code, devices = run_json(capsys, "--config", str(cfg), "show", "devices")
    return {d["name"]: (d["device_type"], d["type_rule"]) for d in devices}


def test_manual_type_applies_at_once_and_can_be_removed(collected, capsys, tmp_path):
    cfg = collected
    assert device_types(capsys, cfg)["sw-generic-02"] == ("", "")
    assert main(["--config", str(cfg), "device", "set", "127.0.0.12", "type=switch"]) == 0
    capsys.readouterr()
    assert device_types(capsys, cfg)["sw-generic-02"] == ("switch", "manual")
    assert main(["--config", str(cfg), "-q", "export"]) == 0
    capsys.readouterr()
    csv_line = next(line for line in (tmp_path / "out" / "devices.csv").read_text().splitlines()
                    if line.startswith("sw-generic-02"))
    assert csv_line.endswith(",switch")
    # a new collect keeps the manual type, and the detected type stays visible
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    capsys.readouterr()
    assert device_types(capsys, cfg)["sw-generic-02"] == ("switch", "manual")
    assert main(["--config", str(cfg), "device", "unset", "127.0.0.12", "--all"]) == 0
    capsys.readouterr()
    assert device_types(capsys, cfg)["sw-generic-02"] == ("", "")


def test_device_show_reports_sources(collected, capsys):
    code, result = run_json(capsys, "--config", str(collected), "device", "show", "127.0.0.13")
    assert code == 0
    settings = {s["key"]: s for s in result["settings"]}
    assert settings["features.arp"] == {"key": "features.arp", "value": "auto",
                                        "source": "default"}
    assert result["detected_type"] == "firewall"


def test_disabled_device_is_not_polled(collected, capsys):
    cfg = collected
    assert main(["--config", str(cfg), "device", "set", "127.0.0.16", "disabled=true"]) == 0
    capsys.readouterr()
    _code, report = run_json(capsys, "--config", str(cfg), "collect")
    assert any("disabled" in note for note in report["notes"])
    assert all(not d["address"].startswith("127.0.0.16:") for d in report["devices"])


def test_invalid_manual_value_is_a_usage_error(collected, capsys):
    assert main(["--config", str(collected), "device", "set", "127.0.0.12", "type=l3"]) == 2


def test_probe_preset_on_the_firewall(lab, collected, capsys):
    code, result = run_json(capsys, "--config", str(collected), "probe", lab.agent("fw"),
                            "arp-media")
    assert code == 0
    table = result["results"][0]
    assert table["status"] == "ok"
    assert table["headers"] == ["index", "ipNetToMediaPhysAddress", "ipNetToMediaType"]
    assert ["1.192.0.2.50", "00:00:5e:00:53:a0", "dynamic(3)"] in table["rows"]


def test_probe_lists_suggestions_for_the_type(lab, collected, capsys):
    code, result = run_json(capsys, "--config", str(collected), "probe", lab.agent("fw"))
    assert code == 0 and result["device_type"] == "firewall"
    presets = {p["name"]: p for p in result["presets"]}
    assert presets["arp-media"]["status"] == "ok"
    assert presets["arp-physical"]["status"] == "absent"
    assert "fdb-qbridge" not in presets        # not suggested for a firewall, see --all


def test_probe_raw_oid_get_and_walk(lab, collected, capsys):
    code, result = run_json(capsys, "--config", str(collected), "probe", lab.agent("fw"),
                            "1.3.6.1.2.1.1.5.0", "1.3.6.1.2.1.2.2.1.2", "--limit", "2")
    assert code == 0
    get, walk = result["results"]
    assert get["rows"] == [["1.3.6.1.2.1.1.5.0", "fw-edge.example.net"]]
    assert len(walk["rows"]) == 2 and walk["truncated"] is True


def test_probe_unreachable_device(lab, collected, capsys):
    from tests.support.lab import DEAD

    assert main(["--config", str(collected), "probe", lab.address(DEAD), "system"]) == 1


# --------------------------------------------------------------------------- TUI


async def wait(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def devices_table(app) -> DataTable:
    return app.screen.query_one("#devices", DataTable)


def select_row(table: DataTable, name: str) -> None:
    for i in range(table.row_count):
        if name in str(table.get_row_at(i)[0]):
            table.move_cursor(row=i)
            return
    raise AssertionError(name)


async def test_tui_lists_filters_and_sets_a_type_by_hand(lab, collected, monkeypatch):
    monkeypatch.setenv("LANG", "fr_BE.UTF-8")
    ctx = TuiContext(load_config(collected))
    app = SnowthApp(ctx)
    async with app.run_test(size=(150, 45)) as pilot:
        await wait(app, pilot)
        table = devices_table(app)
        assert table.row_count == 10                          # 9 devices + the silent one
        app.screen.query_one("#filter", Input).value = "sophos"
        await pilot.pause()
        assert table.row_count == 1
        app.screen.query_one("#filter", Input).value = ""
        await pilot.pause()

        select_row(table, "sw-generic-02")
        await pilot.press("enter")
        await wait(app, pilot)
        assert isinstance(app.screen, DeviceScreen)
        app.screen.query_one("#device-tabs", TabbedContent).active = "tab-settings"
        await pilot.pause()
        app.screen.query_one("#f-type", Select).value = "switch"
        app.screen.query_one("#f-features-arp", Select).value = "force"
        await pilot.press("ctrl+s")
        await wait(app, pilot)
        assert ctx.repo.manual_settings()["127.0.0.12"] == {"type": "switch",
                                                             "features.arp": "force"}
        await pilot.press("escape")
        await wait(app, pilot)
        table = devices_table(app)
        select_row(table, "sw-generic-02")
        type_cell = str(table.get_row_at(table.cursor_row)[2])
        assert "switch" in type_cell and "✎" in type_cell
    ctx.close()


async def test_tui_oid_tester_and_collect(lab, collected):
    ctx = TuiContext(load_config(collected))
    app = SnowthApp(ctx)
    async with app.run_test(size=(150, 45)) as pilot:
        await wait(app, pilot)
        select_row(devices_table(app), "fw-edge")
        await pilot.press("enter")
        await wait(app, pilot)
        screen = app.screen
        screen.query_one("#device-tabs", TabbedContent).active = "tab-tester"
        await pilot.pause()
        screen.run_probe("arp-media")
        await wait(app, pilot)
        assert screen.query_one("#results", DataTable).row_count == 5
        screen.query_one("#oid", Input).value = "1.3.6.1.2.1.1.5.0"
        screen.oid_submitted()
        await wait(app, pilot)
        results = screen.query_one("#results", DataTable)
        assert str(results.get_row_at(0)[1]) == "fw-edge.example.net"

        runs_before = len(ctx.repo.recent_runs(100))
        await pilot.press("c")
        await wait(app, pilot)
        assert isinstance(app.screen, CollectModal) and app.screen.finished
        await pilot.press("escape")
        await wait(app, pilot)
        assert len(ctx.repo.recent_runs(100)) == runs_before + 1
    ctx.close()


async def test_tui_adds_a_device(lab, collected):
    ctx = TuiContext(load_config(collected))
    app = SnowthApp(ctx)
    async with app.run_test(size=(150, 45)) as pilot:
        await wait(app, pilot)
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, AddDeviceModal)
        app.screen.query_one("#address", Input).value = "192.0.2.77"
        await pilot.press("enter")
        await wait(app, pilot)
        assert any("192.0.2.77" in str(devices_table(app).get_row_at(i)[1])
                   for i in range(devices_table(app).row_count))
    loaded = load_config(collected)
    repo = Repo(open_db(loaded.paths.state_file))
    # the address was typed without a port: it gets general.snmp.port, like the seeds
    stored = f"192.0.2.77:{loaded.cfg.general.snmp.port}"
    origin = repo.conn.execute("SELECT origin FROM targets WHERE address = ?",
                               (stored,)).fetchone()
    assert origin[0] == "manual"
    repo.conn.close()
    ctx.close()


async def test_tui_nodes_tab_search_and_explain(lab, collected):
    from snowth_my_net.tui.app import ExplainModal

    ctx = TuiContext(load_config(collected))
    app = SnowthApp(ctx)
    async with app.run_test(size=(160, 45)) as pilot:
        await wait(app, pilot)
        app.screen.query_one("#main-tabs", TabbedContent).active = "tab-nodes"
        await wait(app, pilot)
        nodes = app.screen.query_one("#nodes", DataTable)
        assert nodes.row_count == 19
        app.screen.query_one("#node-filter", Input).value = "192.0.2.50"
        await pilot.pause()
        assert nodes.row_count == 1
        nodes.focus()
        await pilot.press("enter")
        await wait(app, pilot)
        assert isinstance(app.screen, ExplainModal)
        body = str(app.screen.query_one("#explain-text").render())
        assert "sw-access-01 1/1/3" in body and "transit" in body
    ctx.close()


async def test_tui_links_tab_and_device_neighbors(lab, collected):
    ctx = TuiContext(load_config(collected))
    app = SnowthApp(ctx)
    async with app.run_test(size=(160, 45)) as pilot:
        await wait(app, pilot)
        app.screen.query_one("#main-tabs", TabbedContent).active = "tab-links"
        await wait(app, pilot)
        links = app.screen.query_one("#links", DataTable)
        assert links.row_count == 3
        app.screen.query_one("#main-tabs", TabbedContent).active = "tab-devices"
        await wait(app, pilot)
        select_row(devices_table(app), "sw-access-01")
        devices_table(app).focus()
        await pilot.press("enter")
        await wait(app, pilot)
        neighbors = app.screen.query_one("#neighbors", DataTable)
        assert neighbors.row_count == 2
        rows = [[str(c) for c in neighbors.get_row_at(i)] for i in range(neighbors.row_count)]
        trunk = next(r for r in rows if r[0] == "1/1/12")
        assert "sw-cisco-03" in trunk[1] and trunk[5] in ("uplink",)
        phone = next(r for r in rows if r[0] == "1/1/7")
        assert "telephone" in phone[4] and phone[5] in ("access", "accès")
    ctx.close()


async def test_tui_save_tested_oid_as_custom_collector(lab, collected):
    from snowth_my_net.tui.app import SaveCollectorModal

    ctx = TuiContext(load_config(collected))
    app = SnowthApp(ctx)
    async with app.run_test(size=(160, 45)) as pilot:
        await wait(app, pilot)
        select_row(devices_table(app), "fw-edge")
        devices_table(app).focus()
        await pilot.press("enter")
        await wait(app, pilot)
        screen = app.screen
        screen.query_one("#device-tabs", TabbedContent).active = "tab-tester"
        await pilot.pause()
        screen.query_one("#oid", Input).value = "1.3.6.1.2.1.1.6.0"
        screen.oid_submitted()
        await wait(app, pilot)
        screen.save_oid_pressed()
        await wait(app, pilot)
        assert isinstance(app.screen, SaveCollectorModal)
        modal = app.screen
        modal.query_one("#c-name", Input).value = "fw-location"
        modal.query_one("#c-column", Input).value = "location"
        modal.query_one("#c-scope", Select).value = "vendor"
        await pilot.pause()
        modal.save()
        await wait(app, pilot)
        stored = ctx.repo.custom_stored()["fw-location"]
        assert stored == {"name": "fw-location", "applies_to": {"vendors": ["Sophos"]},
                          "get": {"location": "1.3.6.1.2.1.1.6.0"}}

        await pilot.press("c")                          # collect this device now
        await wait(app, pilot)
        await pilot.press("escape")
        await wait(app, pilot)
        screen.query_one("#device-tabs", TabbedContent).active = "tab-custom"
        await wait(app, pilot)
        rows = [[str(c) for c in screen.query_one("#custom", DataTable).get_row_at(i)]
                for i in range(screen.query_one("#custom", DataTable).row_count)]
        assert rows[1][:4] == ["", "", "location", "Server room"]

        await pilot.press("escape")
        await wait(app, pilot)
        app.screen.query_one("#main-tabs", TabbedContent).active = "tab-extensions"
        await wait(app, pilot)
        extensions = app.screen.query_one("#extensions", DataTable)
        assert extensions.row_count == 1
        extensions.focus()
        await pilot.press("delete")
        for _ in range(5):                              # the confirmation is awaited by a worker
            await pilot.pause()
        from snowth_my_net.tui.app import ConfirmModal

        assert isinstance(app.screen, ConfirmModal)
        await pilot.click("#yes")
        await wait(app, pilot)
        assert "fw-location" not in ctx.repo.custom_stored()
    ctx.close()

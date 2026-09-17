"""Custom reports (E2) against snmpsim: files, CLI, SQL, push, cron and the TUI builder."""

from __future__ import annotations

import json

import pytest
from textual.widgets import DataTable, Input, Select, TabbedContent

from snowth_my_net.cli import main
from snowth_my_net.config.loader import load_config
from tests.support.fake_push import FakeImportServer
from tests.support.lab import write_config

TOKEN = "tok-report-9a8b7c6d"
REPORTS = """
reports:
  - name: switch-inventory
    title: Switch inventory
    dataset: devices
    columns: [name, {field: ip, label: IP Address}, vendor, model, os_version]
    filters:
      - {field: device_type, op: eq, value: switch}
    sort: [name]
    format: csv
    schedule: "0 7 * * 1"
  - name: untyped
    dataset: devices
    columns: [name, sys_object_id]
    filters:
      - {field: device_type, op: empty}
    format: markdown
  - name: nodes-per-switch
    sql: >
      SELECT device, count(*) AS nodes, count(DISTINCT vlan) AS vlans FROM nodes
      WHERE device <> '' GROUP BY device ORDER BY nodes DESC, device
    format: json
    push: [cmdb]
  - name: phones
    dataset: neighbors
    filters:
      - {field: remote_caps, op: contains, value: telephone}
    format: html
  - name: never-empty
    dataset: devices
    filters:
      - {field: vendor, op: eq, value: NoSuchVendor}
"""


def run_json(capsys, *argv):
    code = main(["--json", *argv])
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def reported(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=lab.all_seeds())
    token = tmp_path / "secrets" / "cmdb_token"
    token.write_text(TOKEN + "\n")
    token.chmod(0o600)
    (tmp_path / "extensions").mkdir()
    (tmp_path / "extensions" / "reports.yml").write_text(REPORTS)
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    capsys.readouterr()
    return cfg


def add_push(cfg, url):
    cfg.write_text(cfg.read_text() + f"""
push:
  targets:
    - name: cmdb
      url: {url}
      files: [devices]
      auth: {{bearer_token_file: cmdb_token}}
      timeout: 10
""")


def test_list_fields_show(reported, capsys):
    code, listed = run_json(capsys, "--config", str(reported), "report", "list")
    assert code == 0
    assert [(r["name"], r["source"], r["format"]) for r in listed] == [
        ("switch-inventory", "devices", "csv"), ("untyped", "devices", "markdown"),
        ("nodes-per-switch", "sql", "json"), ("phones", "neighbors", "html"),
        ("never-empty", "devices", "csv")]
    code, fields = run_json(capsys, "--config", str(reported), "report", "fields", "nodes")
    assert {"name": "last_seen", "type": "time", "default": True,
            "description": ""} in fields["fields"]
    assert main(["--config", str(reported), "report", "show", "untyped"]) == 0
    text = capsys.readouterr().out
    assert "dataset: devices" in text and "op: empty" in text


def test_run_writes_every_format(reported, tmp_path, capsys):
    code, result = run_json(capsys, "--config", str(reported), "report", "run", "--all",
                            "--no-push")
    assert code == 1                                   # never-empty has no row
    assert result["failed"] == [{"report": "never-empty", "reason":
                                 "report 'never-empty' has no row (allow_empty: true to write "
                                 "it anyway)"}]
    out = tmp_path / "out" / "reports"
    assert not (out / "never-empty.csv").exists()
    assert (out / "switch-inventory.csv").read_bytes() == (
        b"name,IP Address,vendor,model,os_version\r\n"
        b"sw-access-01,127.0.0.11,HPE Aruba,JL679A,PL.10.13.1005\r\n"
        b"sw-core-01,127.0.0.17,Juniper,EX2300-24P,21.4R3-S5.4\r\n")
    untyped = (out / "untyped.md").read_text()
    assert "| backup01 |" in untyped and "| sw-cisco-03 |" in untyped
    assert "sw-access-01" not in untyped
    document = json.loads((out / "nodes-per-switch.json").read_text())
    assert document["rows"][0] == {"device": "sw-generic-02", "nodes": 5, "vlans": 1}
    page = (out / "phones.html").read_text()
    assert "SEP00005E0053F0" in page and "sw-cisco-03" not in page


def test_adhoc_reports_on_stdout(reported, capsys):
    code = main(["--config", str(reported), "report", "run", "--dataset", "interfaces",
                 "--columns", "device,port,neighbors", "--filter", "neighbors not_empty",
                 "--sort=device,port", "--format", "csv"])
    assert code == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "device,port,neighbors"
    assert "sw-access-01,1/1/12,sw-cisco-03" in lines
    code = main(["--config", str(reported), "report", "preview", "--sql",
                 "select name from devices where name like 'sw-%' order by name"])
    assert code == 0
    assert "sw-access-01" in capsys.readouterr().out
    assert main(["--config", str(reported), "report", "preview", "--sql",
                 "select 1 from devices; delete from devices"]) == 2
    assert main(["--config", str(reported), "report", "preview", "--dataset", "nodes",
                 "--filter", "vendor bogus x"]) == 2


def test_push_cron_and_check(reported, tmp_path, capsys):
    with FakeImportServer(token=TOKEN) as server:
        add_push(reported, server.base_url + "/ok")
        code, result = run_json(capsys, "--config", str(reported), "report", "run",
                                "nodes-per-switch")
        received = [(r.path, [p["filename"] for p in r.parts if p["filename"]],
                     r.headers.get("Authorization")) for r in server.received]
    assert code == 0, result
    assert [(p["file"], p["ok"]) for p in result["push"]] == [("report:nodes-per-switch", True)]
    assert received == [("/ok", ["nodes-per-switch.json"], f"Bearer {TOKEN}")]

    assert main(["--config", str(reported), "cron", "print"]) == 0
    crontab = capsys.readouterr().out
    assert "\n0 7 * * 1 " in crontab and crontab.rstrip().endswith("report run switch-inventory")

    (tmp_path / "extensions" / "more.yml").write_text(
        "reports:\n  - {name: lost, dataset: devices, push: [nowhere]}\n")
    main(["--config", str(reported), "check", "--quick", "127.0.0.13"])
    assert "report 'lost': unknown push target 'nowhere'" in capsys.readouterr().out


def test_import_export_delete(reported, tmp_path, capsys):
    source = tmp_path / "mine.yml"
    source.write_text("reports:\n  - {name: stale, dataset: devices, filters: "
                      "[{field: last_seen, op: older_than, value: 7d}], allow_empty: true}\n")
    assert main(["--config", str(reported), "report", "import", str(source)]) == 0
    assert main(["--config", str(reported), "report", "export"]) == 0
    exported = capsys.readouterr().out
    assert "name: stale" in exported and "switch-inventory" not in exported
    code, result = run_json(capsys, "--config", str(reported), "report", "run", "stale")
    assert code == 0 and result["written"][0]["rows"] == 0
    assert main(["--config", str(reported), "report", "delete", "untyped"]) == 2
    assert main(["--config", str(reported), "report", "delete", "stale"]) == 0
    source.write_text("reports:\n  - {name: untyped, dataset: devices}\n")
    assert main(["--config", str(reported), "report", "import", str(source)]) == 2


async def wait(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def test_tui_report_builder(reported, tmp_path):
    from snowth_my_net.tui.app import ConfirmModal, SnowthApp, TuiContext
    from snowth_my_net.tui.reports import ReportScreen

    ctx = TuiContext(load_config(reported))
    app = SnowthApp(ctx)
    async with app.run_test(size=(170, 48)) as pilot:
        await wait(app, pilot)
        app.screen.query_one("#main-tabs", TabbedContent).active = "tab-reports"
        await wait(app, pilot)
        reports = app.screen.query_one("#reports", DataTable)
        assert reports.row_count == 5
        await pilot.press("n")
        await wait(app, pilot)
        screen = app.screen
        assert isinstance(screen, ReportScreen)
        screen.query_one("#b-name", Input).value = "vlan-10"
        screen.query_one("#b-source", Select).value = "nodes"
        await wait(app, pilot)
        screen.add_filter({"field": "vlan", "op": "eq", "value": "10"})
        screen.query_one("#b-sort", Input).value = "mac"
        screen.query_one("#b-format", Select).value = "html"
        await wait(app, pilot)
        screen.refresh_preview()
        preview = screen.query_one("#b-preview", DataTable)
        assert preview.row_count == 4
        assert str(preview.get_row_at(0)[0]) == "00:00:5e:00:53:a0"
        screen.action_save()
        stored = ctx.repo.reports_stored()["vlan-10"]
        assert stored == {"name": "vlan-10", "dataset": "nodes", "format": "html",
                          "filters": [{"field": "vlan", "op": "eq", "value": "10"}],
                          "sort": ["mac"]}
        screen.action_export()
        await wait(app, pilot)
        assert (tmp_path / "out" / "reports" / "vlan-10.html").exists()

        await pilot.press("escape")
        await wait(app, pilot)
        main_screen = app.screen
        main_screen.fill_reports()
        reports = main_screen.query_one("#reports", DataTable)
        assert reports.row_count == 6
        reports.focus()
        reports.move_cursor(row=reports.get_row_index("vlan-10"))
        await pilot.press("delete")
        for _ in range(5):
            await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        await pilot.click("#yes")
        await wait(app, pilot)
        assert "vlan-10" not in ctx.repo.reports_stored()
    ctx.close()

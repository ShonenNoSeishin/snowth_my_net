"""``report`` commands without SNMP: argument errors, outputs, failures, push and hooks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from snowth_my_net import cli
from snowth_my_net.push.http import PushError, PushOutcome
from tests.unit.cov_cli_support import NOW, add_device, read_json, state
from tests.unit.cov_cli_support import write_config as base_config

REPORTS = """
reports:
  - name: inventory
    dataset: devices
    columns: [name, vendor]
    push: [cmdb]
  - name: nothing
    dataset: devices
    filters: [{field: vendor, op: eq, value: NoSuchVendor}]
  - name: bad-sql
    sql: select no_such_column from devices
"""


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("SNOWTH_COV_COMMUNITY", "cov-community")
    config = base_config(tmp_path, extra="""
push:
  targets:
    - name: cmdb
      url: https://cmdb.example.net/import
      auth: {bearer_token_file: token}
""")
    (tmp_path / "extensions").mkdir()
    (tmp_path / "extensions" / "reports.yml").write_text(REPORTS)
    return config


def run(cfg: Path, *argv: str) -> int:
    return cli.main(["--config", str(cfg), *argv])


def with_device(tmp_path, name="sw-cov"):
    repo = state(tmp_path)
    add_device(repo, name=name, last_seen=NOW)
    repo.conn.close()


def test_commands_without_a_state(cfg, capsys):
    assert run(cfg, "report", "list") == 0
    assert "inventory  devices" in capsys.readouterr().out
    assert run(cfg, "report", "show", "inventory") == 0
    assert "# origin:" in capsys.readouterr().out
    assert run(cfg, "report", "fields", "vlans") == 0
    out = capsys.readouterr().out
    assert out.startswith("vlans — VLANs declared") and "(SQL table: vlans)" in out
    assert run(cfg, "report", "export", "inventory") == 0
    assert "name: inventory" in capsys.readouterr().out
    assert run(cfg, "report", "preview", "inventory") == 1
    assert "no state yet (run collect first)" in capsys.readouterr().err


def test_list_fields_show_json(cfg, capsys):
    assert run(cfg, "--json", "report", "fields") == 0
    datasets = read_json(capsys)
    assert {"dataset": "devices", "sql_table": "devices"}.items() <= datasets[0].items()
    assert run(cfg, "report", "fields") == 0
    assert capsys.readouterr().out.startswith("DATASET")
    assert run(cfg, "report", "fields", "nope") == 2
    assert "unknown dataset 'nope'" in capsys.readouterr().err
    assert run(cfg, "--json", "report", "show", "inventory") == 0
    assert read_json(capsys)["definition"]["columns"] == ["name", "vendor"]
    assert run(cfg, "report", "show", "missing") == 2
    assert "unknown report 'missing' (inventory, nothing, bad-sql; see 'report list')" in \
        capsys.readouterr().err


def test_list_empty(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("SNOWTH_COV_COMMUNITY", "x")
    config = base_config(tmp_path)
    assert run(config, "report", "list") == 0
    assert "no report defined" in capsys.readouterr().out
    state(tmp_path).conn.close()
    assert run(config, "report", "show", "x") == 2
    assert "none defined" in capsys.readouterr().err


@pytest.mark.parametrize(("argv", "message"), [
    (["--columns", "name"], "--columns, --filter and --sort need --dataset"),
    (["--dataset", "devices", "--filter", "vendor"], "expected 'FIELD OP [VALUE]'"),
    (["--dataset", "devices", "--filter", "vendor like x"], "--filter 'vendor like x'"),
    (["--dataset", "nope"], "unknown dataset 'nope'"),
    (["--sql", "select 1 from devices", "--filter", "vendor empty"], "do not apply to sql"),
    ([], "give a report name, or --dataset / --sql"),
    (["inventory", "--dataset", "devices"], "not both"),
    (["bad-sql"], "no such column"),
])
def test_preview_usage_errors(cfg, capsys, tmp_path, argv, message):
    state(tmp_path).conn.close()
    assert run(cfg, "report", "preview", *argv) == 2
    assert message in capsys.readouterr().err


def test_preview_outputs(cfg, capsys, tmp_path):
    state(tmp_path).conn.close()
    assert run(cfg, "report", "preview", "nothing") == 0
    assert capsys.readouterr().out == "no row\n"
    with_device(tmp_path, name="a" * 70)
    with_device(tmp_path, name="sw-2")
    assert run(cfg, "report", "preview", "--dataset", "devices", "--columns", "name",
               "--filter", "vendor in Acme, Other", "--sort=name", "--limit", "1") == 0
    out = capsys.readouterr().out
    assert "a" * 59 + "…" in out and "2 row(s), first 1 shown (--limit)" in out
    assert run(cfg, "--json", "report", "preview", "inventory") == 0
    payload = read_json(capsys)
    assert payload["columns"] == ["name", "vendor"] and payload["row_count"] == 2


def test_run_errors(cfg, capsys, tmp_path):
    state(tmp_path).conn.close()
    assert run(cfg, "report", "run") == 2
    assert "give report names, --all, or --dataset / --sql" in capsys.readouterr().err
    assert run(cfg, "report", "run", "inventory", "--dataset", "devices") == 2
    assert "not both" in capsys.readouterr().err
    assert run(cfg, "report", "run", "--all", "--output", "x.csv") == 2
    assert "--output needs exactly one report" in capsys.readouterr().err


def test_run_to_a_file_stdout_and_failures(cfg, capsys, tmp_path):
    with_device(tmp_path)
    target = tmp_path / "adhoc.csv"
    assert run(cfg, "report", "run", "--dataset", "devices", "--columns", "name",
               "--output", str(target)) == 0
    assert target.read_bytes() == b"name\r\nsw-cov\r\n"
    assert "wrote" in capsys.readouterr().out
    assert run(cfg, "report", "run", "--sql", "select nope from devices") == 1
    assert "no such column" in capsys.readouterr().err
    (tmp_path / "dir.csv").mkdir()
    assert run(cfg, "--json", "report", "run", "inventory", "--no-push", "--output",
               str(tmp_path / "dir.csv")) == 1
    payload = read_json(capsys)
    assert payload["failed"][0]["reason"].startswith("cannot write:")


def test_run_all_with_push_warnings_and_hooks(cfg, capsys, tmp_path, monkeypatch):
    import snowth_my_net.reports.service as service

    with_device(tmp_path)
    cfg.write_text(cfg.read_text() + "hooks:\n  after_report:\n    - name: h\n"
                   "      command: [/bin/true]\n")
    pushed = []

    def push_report(loaded, generated, targets, wait, dry_run):
        pushed.append((generated.cfg.name, targets))
        return [PushOutcome("cmdb", f"report:{generated.cfg.name}", False, 500,
                            detail="HTTP 500")], ["TLS verification disabled"]

    monkeypatch.setattr(service, "push_report", push_report)
    assert run(cfg, "report", "run", "--all") == 1
    captured = capsys.readouterr()
    assert pushed == [("inventory", None)]
    assert "FAILED nothing: report 'nothing' has no row" in captured.out
    assert "FAILED bad-sql:" in captured.out and "HTTP 500" in captured.out
    assert captured.out.count("hook after_report/h: ok") == 3
    assert "TLS verification disabled" in captured.err

    assert run(cfg, "--json", "report", "run", "inventory", "--target", "other") == 1
    payload = read_json(capsys)
    assert pushed[-1] == ("inventory", ["other"])
    assert payload["hooks"][0]["ok"] is True and payload["push"][0]["ok"] is False

    def broken(*args):
        raise PushError("the report was not written")

    monkeypatch.setattr(service, "push_report", broken)
    assert run(cfg, "report", "run", "inventory") == 2
    assert "the report was not written" in capsys.readouterr().err


def test_export_import_errors(cfg, capsys, tmp_path):
    assert run(cfg, "report", "export", "ghost") == 2
    assert "unknown report(s): ghost" in capsys.readouterr().err
    source = tmp_path / "r.yml"
    source.write_text("reports: {name: x}\n")
    assert run(cfg, "report", "import", str(source)) == 2
    assert "expected a reports: list" in capsys.readouterr().err
    assert run(cfg, "report", "import", str(tmp_path / "missing.yml")) == 2
    assert "cannot read" in capsys.readouterr().err
    source.write_text(json.dumps([{"name": "mine", "dataset": "vlans"}]))
    assert run(cfg, "report", "import", str(source)) == 0
    assert run(cfg, "report", "export") == 0
    out = capsys.readouterr().out
    assert "name: mine" in out and "name: inventory" not in out

"""CLI commands exercised without SNMP: collectors, pushes and connections are faked, the state
is built through the repository API. Every test checks outputs and exit codes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from snowth_my_net import cli
from snowth_my_net.collect.check import DeviceCheck
from snowth_my_net.collect.engine import RunReport
from snowth_my_net.collect.model import DeviceResult, Identification, Outcome
from snowth_my_net.collect.probe import Connection, ProbeTable
from snowth_my_net.collect.tables.system import SystemInfo
from snowth_my_net.config.effective import settings_for
from snowth_my_net.export.run import ExportResult
from snowth_my_net.hooks import HookResult
from snowth_my_net.lock import StateLock
from snowth_my_net.push.http import PushError, PushOutcome
from snowth_my_net.snmp.client import SnmpError
from snowth_my_net.snmp.target import parse_target
from tests.unit.cov_cli_support import NOW, add_custom, add_device, add_run, read_json, state
from tests.unit.cov_cli_support import write_config as base_config

TRUE = "/bin/true"
FALSE = "/bin/false"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("SNOWTH_COV_COMMUNITY", "cov-community")
    return base_config(tmp_path)


def run(cfg: Path, *argv: str) -> int:
    return cli.main(["--config", str(cfg), *argv])


def hooks_yaml(event: str, command: str = FALSE) -> str:
    return f"hooks:\n  {event}:\n    - name: h1\n      command: [{command}]\n"


# --------------------------------------------------------------------------- collect / discover


def fake_report(loaded, command="collect"):
    target = parse_target("192.0.2.1")
    settings = settings_for(loaded.cfg, target.host)
    ok = DeviceResult(target, "seed", 0, settings, credential="v2c",
                      system=SystemInfo(name="sw-cov.example.net"),
                      ident=Identification(vendor="Acme", model="X1", device_type="switch"))
    ok.outcomes = {"fdb": Outcome("fdb", "timeout", detail="slow"),
                   "arp": Outcome("arp", "ok", rows=2)}
    dead = DeviceResult(parse_target("192.0.2.9"), "seed", 0, settings, error="no answer")
    report = RunReport(7, command, "partial", [ok, dead], notes=["n1"], errors=["e1"],
                       stats={"devices": 2, "reachable": 1})
    return report


class FakeCollector:
    def __init__(self, loaded, repo, creds, clock, mode="collect"):
        self.loaded, self.mode = loaded, mode

    async def run(self, only=None):
        return fake_report(self.loaded, self.mode)


def test_collect_text_json_and_hooks(cfg, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Collector", FakeCollector)
    monkeypatch.setattr(cli.LoadedConfig, "resolve_credentials",
                        lambda self: ([], ["secret file is group readable"]))
    assert run(cfg, "collect") == 1
    captured = capsys.readouterr()
    assert "secret file is group readable" in captured.err
    assert "partial (fdb:timeout)" in captured.out and "192.0.2.9: no answer" in captured.out
    assert "note: n1" in captured.out and "error: e1" in captured.out

    cfg.write_text(cfg.read_text() + hooks_yaml("after_collect"))
    assert run(cfg, "--json", "collect") == 1
    payload = read_json(capsys)
    assert payload["hooks"][0]["name"] == "h1" and payload["exit_code"] == 1
    assert payload["devices"][0]["functions"]["fdb"]["status"] == "timeout"

    assert run(cfg, "collect") == 1
    assert "hook after_collect/h1: FAILED — exit code 1" in capsys.readouterr().out
    assert run(cfg, "discover", "--dry-run") == 1                  # no hooks for discover
    assert "hook" not in capsys.readouterr().out


# --------------------------------------------------------------------------- export / push / run


def test_export_text_with_failure_and_hooks(cfg, monkeypatch, capsys, tmp_path):
    result = ExportResult(written=[tmp_path / "out" / "devices.csv"],
                          failed=[("nodes", "no data row")])
    monkeypatch.setattr(cli, "export", lambda *a, **k: result)
    cfg.write_text(cfg.read_text() + hooks_yaml("after_export", TRUE))
    assert run(cfg, "export") == 1
    out = capsys.readouterr().out
    assert "FAILED nodes: no data row" in out and "hook after_export/h1: ok" in out


def test_push_errors_warnings_and_json(cfg, monkeypatch, capsys):
    import snowth_my_net.push.http as http

    def broken(loaded, **kwargs):
        raise PushError("unknown push target 'x'")

    monkeypatch.setattr(http, "push_all", broken)
    assert run(cfg, "push", "--target", "x") == 2
    assert "unknown push target 'x'" in capsys.readouterr().err

    outcomes = [PushOutcome("cmdb", "devices", True, 201), PushOutcome("cmdb", "nodes", False,
                                                                       500, detail="HTTP 500")]
    monkeypatch.setattr(http, "push_all", lambda loaded, **kw: (outcomes, ["TLS disabled"]))
    cfg.write_text(cfg.read_text() + hooks_yaml("after_push", TRUE))
    assert run(cfg, "push") == 1
    captured = capsys.readouterr()
    assert "warning  TLS disabled" in captured.out and "FAILED" in captured.out
    assert "hook after_push/h1: ok" in captured.out and "TLS disabled" in captured.err
    assert run(cfg, "--json", "push") == 1
    payload = read_json(capsys)
    assert payload["warnings"] == ["TLS disabled"] and payload["hooks"][0]["ok"] is True
    assert [r["ok"] for r in payload["results"]] == [True, False]

    monkeypatch.setattr(http, "push_all", lambda loaded, **kw: ([], []))
    assert run(cfg, "push") == 0
    assert "no push target configured" in capsys.readouterr().out


def test_run_collect_export_push_with_hooks(cfg, monkeypatch, capsys, tmp_path):
    import snowth_my_net.push.http as http

    monkeypatch.setattr(cli, "Collector", FakeCollector)
    monkeypatch.setattr(cli, "export", lambda *a, **k: ExportResult(
        written=[tmp_path / "out" / "devices.csv"], failed=[("links", "empty")]))
    seen = {}

    def push_all(loaded, wait=None, available=None):
        seen["available"] = available
        return [PushOutcome("cmdb", "devices", True, 201),
                PushOutcome("cmdb", "links", False, detail="export failed")], ["proxy set"]

    monkeypatch.setattr(http, "push_all", push_all)
    cfg.write_text(cfg.read_text() + """
push:
  targets:
    - name: cmdb
      url: https://cmdb.example.net/import
      auth: {bearer_token_file: token}
""" + "hooks:\n" + "".join(f"  {e}:\n    - name: {e}\n      command: [{TRUE}]\n"
                           for e in ("after_collect", "after_export", "after_push")))
    assert run(cfg, "run") == 1
    captured = capsys.readouterr()
    assert seen["available"] == {"links": "export failed in this run: empty"}
    assert "FAILED links: empty" in captured.out and "proxy set" in captured.err
    for event in ("after_collect", "after_export", "after_push"):
        assert f"hook {event}/{event}: ok" in captured.out

    assert run(cfg, "--json", "run", "--no-collect") == 1
    payload = read_json(capsys)
    assert "collect" not in payload and [h["event"] for h in payload["hooks"]] == [
        "after_export", "after_push"]
    assert payload["push"][1]["ok"] is False


def test_lock_busy_exits_3(cfg, capsys, tmp_path):
    lock = StateLock(tmp_path / "state" / "state.lock", "collect")
    lock.acquire(0)
    try:
        assert run(cfg, "export") == 3
    finally:
        lock.release()
    assert "state is locked by pid" in capsys.readouterr().err


# --------------------------------------------------------------------------- cron / health / show


def test_cron_print_with_a_state_and_a_broken_stored_report(cfg, capsys, tmp_path):
    repo = state(tmp_path)
    repo.save_report("broken", {"name": "broken", "dataset": "nope"}, NOW)
    repo.save_report("weekly", {"name": "weekly", "dataset": "devices",
                                "schedule": "0 6 * * 1"}, NOW)
    repo.conn.close()
    assert run(cfg, "cron", "print") == 0
    captured = capsys.readouterr()
    assert "report run weekly" in captured.out
    assert "report 'broken' from the state is invalid" in captured.err


def test_health_states(cfg, monkeypatch, capsys, tmp_path):
    assert run(cfg, "health", "--max-age", "soon") == 2
    assert "expected a duration" in capsys.readouterr().err
    assert run(cfg, "health") == 1
    assert "UNHEALTHY: no successful collect yet" in capsys.readouterr().out
    repo = state(tmp_path)
    add_run(repo, NOW - 600)
    repo.conn.close()
    monkeypatch.setattr(cli.Clock, "now", lambda self: NOW)
    assert run(cfg, "health", "--max-age", "30m") == 0
    assert capsys.readouterr().out.startswith("OK: last successful collect")
    assert run(cfg, "health", "--max-age", "5m") == 1
    assert "UNHEALTHY: last successful collect" in capsys.readouterr().out
    assert run(cfg, "--json", "health", "--max-age", "5m") == 1
    payload = read_json(capsys)
    assert payload["age_s"] == 600 and payload["max_age_from"] == "--max-age"


def test_show_text_outputs(cfg, monkeypatch, capsys, tmp_path):
    repo = state(tmp_path)
    add_device(repo, os_name="AOS", os_version="10")
    add_run(repo, NOW)
    repo.conn.close()
    monkeypatch.setattr(cli.Clock, "now", lambda self: NOW)
    assert run(cfg, "show", "devices") == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("NAME") and "sw-cov" in out and "AOS 10" in out
    assert run(cfg, "show", "links", "--filter", "nothing") == 0
    assert capsys.readouterr().out.rstrip().endswith("0 link(s)")
    assert run(cfg, "--json", "show", "links", "--filter", "x") == 0
    assert read_json(capsys) == []
    assert run(cfg, "show", "nodes", "--filter", "aa:bb", "--limit", "5") == 0
    assert capsys.readouterr().out.rstrip().endswith("0 row(s)")
    assert run(cfg, "show", "runs") == 0
    assert "collect" in capsys.readouterr().out
    assert run(cfg, "show", "uplinks") == 0
    assert "uplink port(s)" in capsys.readouterr().out
    assert run(cfg, "show", "uplinks", "--filter", "nothing") == 0
    assert "0 uplink port(s)" in capsys.readouterr().out
    assert run(cfg, "--json", "show", "uplinks") == 0
    assert read_json(capsys) == []


# --------------------------------------------------------------------------- check


def test_check_state_output_and_save(cfg, monkeypatch, capsys, tmp_path):
    import snowth_my_net.collect.discovery as discovery

    repo = state(tmp_path)
    add_run(repo, NOW)
    repo.conn.close()

    async def fake_check(loaded, creds, planned, quick, manual=None, collectors=None):
        assert {str(p.target) for p in planned} >= {"192.0.2.1", "192.0.2.77"}
        good = DeviceCheck("192.0.2.1", reachable=True, credential="v2c", rtt_ms=3,
                           sys_name="sw-cov", ident=Identification(vendor="Acme"),
                           mibs={"lldp": "ok"}, warnings=["factory sysName"])
        bare = DeviceCheck("192.0.2.2", reachable=True, credential="v2c", rtt_ms=1)
        dead = DeviceCheck("192.0.2.77", error="no answer", tolerated=True)
        return [good, bare, dead]

    class Seeds:
        def __init__(self):
            self.targets = [(parse_target("192.0.2.1"), 0)]
            self.errors = ["cannot resolve core.example.net"]

    async def seeds(cfg):
        return Seeds()

    monkeypatch.setattr(cli, "check_devices", fake_check)
    monkeypatch.setattr(cli, "resolve_seeds", seeds)
    monkeypatch.setattr(cli, "plan_targets", lambda *a, **k: (
        discovery.plan_targets(*a, **k)[0], ["192.0.2.250 skipped (outside discovery.allowed)"]))
    assert run(cfg, "check", "--save", "192.0.2.1", "192.0.2.77") == 1   # seed error
    out = capsys.readouterr().out
    assert "last successful collect" in out
    assert "error    cannot resolve core.example.net" in out
    assert "note     192.0.2.250 skipped" in out
    assert "  identity  Acme ?" in out and "  type      (empty: no sure evidence)" in out
    assert "  warning   factory sysName" in out
    assert "192.0.2.77  UNREACHABLE — no answer  (tolerate_failure)" in out
    assert "192.0.2.2  (no sysName)" in out
    repo = state(tmp_path)
    assert {r["address"]: r["credential"] for r in repo.targets()}["192.0.2.2"] == "v2c"
    repo.conn.close()


def test_check_unreadable_state_and_output(cfg, monkeypatch, capsys, tmp_path):
    repo = state(tmp_path)
    repo.conn.execute("PRAGMA user_version = 999")
    repo.conn.close()

    async def nothing(*a, **k):
        return []

    def not_writable(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(cli, "check_devices", nothing)
    monkeypatch.setattr(cli.tempfile, "NamedTemporaryFile", not_writable)
    assert run(cfg, "check") == 0
    captured = capsys.readouterr()
    assert "is newer than this version" in captured.out
    assert "NOT writable (Permission denied)" in captured.out
    assert "warning  output directory" in captured.out
    assert "state: state schema v999" in captured.err       # _state_readonly warning


# --------------------------------------------------------------------------- probe


def fake_connection(loaded, reachable=True):
    target = parse_target("192.0.2.1")
    conn = Connection(target, settings_for(loaded.cfg, target.host), attempts=[("v2c", "timeout")])
    if reachable:
        conn.client, conn.credential, conn.rtt_ms = object(), "v2c", 4
        conn.system = SystemInfo(name="", object_id="1.3.6.1.4.1.99999.1")
    else:
        conn.error = "no answer (v2c: timeout)"
    return conn


def patch_probe(monkeypatch, reachable=True, status="ok"):
    import snowth_my_net.collect.probe as probe

    async def connect(loaded, creds, target, pool, manual=None, remembered=None):
        return fake_connection(loaded, reachable)

    async def run_preset(client, preset, lang, limit, pen, timeout):
        return ProbeTable(preset.title_en, ["A"], [["1"]], status=status, detail="d",
                          truncated=True, requests=2)

    async def run_oid(client, oid, mode, limit, timeout):
        return ProbeTable("oid", ["OID", "VALUE"], [], status="absent")

    monkeypatch.setattr(probe, "connect", connect)
    monkeypatch.setattr(probe, "run_preset", run_preset)
    monkeypatch.setattr(probe, "run_oid", run_oid)


def test_probe_paths(cfg, monkeypatch, capsys, tmp_path):
    assert run(cfg, "probe", "192.0.2.1", "--limit", "0") == 2
    assert "--limit must be at least 1" in capsys.readouterr().err

    patch_probe(monkeypatch, reachable=False)
    assert run(cfg, "probe", "192.0.2.1") == 1
    assert "UNREACHABLE — no answer" in capsys.readouterr().out
    assert run(cfg, "--json", "probe", "192.0.2.1") == 1
    assert read_json(capsys) == {"address": "192.0.2.1", "reachable": False,
                                 "error": "no answer (v2c: timeout)",
                                 "attempts": [["v2c", "timeout"]]}

    repo = state(tmp_path)
    add_device(repo, device_type="firewall", type_rule="manual")
    repo.conn.close()
    patch_probe(monkeypatch)
    assert run(cfg, "probe", "192.0.2.1") == 0
    out = capsys.readouterr().out
    assert "type firewall (manual)" in out and "(no sysName)" in out
    assert "--all also tries" in out
    assert run(cfg, "probe", "192.0.2.1", "--all") == 0
    assert "--all also tries" not in capsys.readouterr().out

    assert run(cfg, "probe", "192.0.2.1", "system", "1.3.6.1.2.1.1.5.0", "--limit", "3") == 0
    out = capsys.readouterr().out
    assert "System group — ok, 1 row(s), 2 request(s), 0 ms — d" in out
    assert "(stopped at 3 rows per column; use --limit)" in out and "oid — absent" in out

    patch_probe(monkeypatch, status="timeout")
    assert run(cfg, "--json", "probe", "192.0.2.1", "system") == 1
    assert read_json(capsys)["results"][0]["status"] == "timeout"


# --------------------------------------------------------------------------- device


def test_device_show_set_unset_add_remove(cfg, capsys, tmp_path, monkeypatch):
    assert run(cfg, "device", "show", "192.0.2.5") == 0
    out = capsys.readouterr().out
    assert "192.0.2.5  (never collected)" in out and "Sources: manual" in out

    repo = state(tmp_path)
    add_device(repo, address="192.0.2.5", name="fw-cov", device_type="firewall",
               type_rule="catalog")
    repo.conn.close()
    assert run(cfg, "device", "show", "192.0.2.5") == 0
    assert "fw-cov — detected type firewall (catalog)" in capsys.readouterr().out
    assert run(cfg, "--json", "device", "set", "192.0.2.5", "type=router") == 0
    assert read_json(capsys) == {"address": "192.0.2.5", "set": {"type": "router"}}
    assert run(cfg, "device", "unset", "192.0.2.5") == 2
    assert "give the keys to remove, or --all" in capsys.readouterr().err
    assert run(cfg, "device", "unset", "192.0.2.5", "--all") == 0
    assert "1 manual value(s) removed" in capsys.readouterr().out

    assert run(cfg, "device", "add", "192.0.2.200") == 2
    assert "inside discovery.exclude" in capsys.readouterr().err
    assert run(cfg, "device", "add", "192.0.2.6") == 0
    assert "192.0.2.6 added" in capsys.readouterr().out
    assert run(cfg, "device", "remove", "192.0.2.1") == 0
    out = capsys.readouterr().out
    assert "forgotten" in out and "it is a seed in config.yml" in out
    assert run(cfg, "device", "remove", "192.0.2.6") == 0
    assert "seed" not in capsys.readouterr().out


def test_device_export_and_import(cfg, capsys, tmp_path):
    assert run(cfg, "--json", "device", "export-settings") == 0
    assert read_json(capsys) == {"devices": []}
    assert run(cfg, "device", "set", "192.0.2.5", "type=router", "name=edge") == 0
    capsys.readouterr()
    assert run(cfg, "device", "export-settings") == 0
    exported = capsys.readouterr().out
    assert exported.startswith("# Manual settings exported") and "name: edge" in exported

    source = tmp_path / "settings.yml"
    source.write_text("devices:\n  - address: 192.0.2.5\n    type: switch\n")
    assert run(cfg, "device", "import-settings", str(source), "--replace") == 0
    assert "for 1 address(es)" in capsys.readouterr().out
    repo = state(tmp_path)
    assert repo.manual_settings() == {"192.0.2.5": {"type": "switch"}}
    repo.conn.close()
    source.write_text("devices: [\n")
    assert run(cfg, "device", "import-settings", str(source)) == 2
    assert "cannot read" in capsys.readouterr().err
    assert run(cfg, "device", "import-settings", str(tmp_path / "missing.yml")) == 2


# --------------------------------------------------------------------------- explain / oui


def test_explain_unknown_mac_and_oui_update(cfg, capsys, tmp_path, monkeypatch):
    state(tmp_path).conn.close()
    assert run(cfg, "explain", "00:00:5e:00:53:99") == 1
    assert "00:00:5e:00:53:99" in capsys.readouterr().out

    assert run(cfg, "oui-update", "--from-file", str(tmp_path / "nothing")) == 1
    assert "oui-update failed" in capsys.readouterr().err
    monkeypatch.setattr("snowth_my_net.enrich.oui.update_database", lambda dest, urls, src: 3)
    assert run(cfg, "oui-update") == 0
    assert capsys.readouterr().out.rstrip().endswith("oui.tsv.gz: 3 vendor prefixes")


# --------------------------------------------------------------------------- custom collectors


def test_custom_list_show_export_import_delete(cfg, capsys, tmp_path):
    assert run(cfg, "custom", "show", "192.0.2.1") == 1
    assert "no state yet" in capsys.readouterr().err

    repo = state(tmp_path)
    device_id = add_device(repo)
    bare = add_device(repo, address="192.0.2.3", name="bare")
    add_custom(repo, device_id)
    repo.save_custom_collector("fw-info", {"name": "fw-info", "applies_to": {
        "vendors": ["Acme"], "types": ["switch"], "addresses": ["192.0.2.0/24"],
        "sys_object_ids": ["1.3.6.1.4.1.9"]}, "get": {"version": "1.3.6.1.4.1.9.1.0"}}, NOW)
    repo.conn.close()
    assert bare
    assert run(cfg, "custom", "list") == 0
    assert "vendors=Acme types=switch addresses=192.0.2.0/24 sys_object_ids=1.3.6.1.4.1.9" in \
        capsys.readouterr().out
    assert run(cfg, "custom", "show", "192.0.2.99") == 2
    assert "192.0.2.99: unknown device" in capsys.readouterr().err
    assert run(cfg, "custom", "show", "192.0.2.3") == 0
    assert "192.0.2.3: no custom value yet" in capsys.readouterr().out
    assert run(cfg, "custom", "show", "192.0.2.1") == 0
    out = capsys.readouterr().out
    assert "fw-info — ok at" in out and "— slow agent" in out and "version  7.2" in out

    assert run(cfg, "custom", "export") == 0
    exported = capsys.readouterr().out
    assert "collectors:" in exported and "name: fw-info" in exported

    source = tmp_path / "c.yml"
    source.write_text("collectors: {name: x}\n")
    assert run(cfg, "custom", "import", str(source)) == 2
    assert "expected a collectors: list" in capsys.readouterr().err
    source.write_text("collectors: [\n")
    assert run(cfg, "custom", "import", str(source)) == 2
    assert "cannot read" in capsys.readouterr().err
    assert run(cfg, "custom", "delete", "fw-info") == 0
    assert run(cfg, "custom", "delete", "fw-info") == 1
    assert "fw-info: not found" in capsys.readouterr().out.splitlines()[-1]


def test_custom_list_empty_and_file_collector_delete(cfg, capsys, tmp_path):
    assert run(cfg, "custom", "list") == 0
    assert "no custom collector" in capsys.readouterr().out
    (tmp_path / "extensions").mkdir()
    (tmp_path / "extensions" / "c.yml").write_text(
        "collectors:\n  - {name: from-file, get: {v: 1.3.6.1.2.1.1.5.0}}\n")
    assert run(cfg, "custom", "delete", "from-file") == 2
    assert "comes from an extension file" in capsys.readouterr().err


def test_custom_test_paths(cfg, capsys, tmp_path, monkeypatch):
    import snowth_my_net.collect.custom as custom
    import snowth_my_net.collect.probe as probe

    (tmp_path / "extensions").mkdir()
    (tmp_path / "extensions" / "c.yml").write_text(
        "collectors:\n  - {name: sysname, get: {v: 1.3.6.1.2.1.1.5.0}}\n")
    assert run(cfg, "custom", "test", "nope", "192.0.2.1") == 2
    assert "unknown collector 'nope' (sysname)" in capsys.readouterr().err

    reachable = {"ok": False}

    async def connect(loaded, creds, target, pool, manual=None, remembered=None):
        return fake_connection(loaded, reachable["ok"])

    monkeypatch.setattr(probe, "connect", connect)
    assert run(cfg, "custom", "test", "sysname", "192.0.2.1") == 1
    assert "UNREACHABLE" in capsys.readouterr().out

    reachable["ok"] = True
    repo = state(tmp_path)
    add_device(repo)
    repo.conn.close()
    behaviour = {}

    async def run_collector(client, collector, result, facts):
        behaviour["facts"] = facts
        if behaviour.get("fail"):
            result.rows.append(("", "v", "partial", None))
            raise SnmpError("timeout after 1 row")
        result.rows.append(("", "v", "sw-cov", None))
        result.truncated = True

    monkeypatch.setattr(custom, "run_collector", run_collector)
    assert run(cfg, "custom", "test", "sysname", "192.0.2.1") == 0
    out = capsys.readouterr().out
    assert "sysname on 192.0.2.1: 1 value(s) (truncated)" in out and "sw-cov" in out
    assert behaviour["facts"].vendor == "Acme" and behaviour["facts"].model == "X1"
    behaviour["fail"] = True
    assert run(cfg, "custom", "test", "sysname", "192.0.2.1") == 1
    assert "1 value(s) — timeout after 1 row" in capsys.readouterr().out


# --------------------------------------------------------------------------- hooks


def test_hooks_list_and_test(cfg, capsys, tmp_path):
    assert run(cfg, "hooks", "list") == 0
    assert "no hook configured" in capsys.readouterr().out
    assert run(cfg, "hooks", "test", "after_report") == 0
    assert "no hook in hooks.after_report" in capsys.readouterr().out
    cfg.write_text(cfg.read_text() + hooks_yaml("after_report", TRUE))
    assert run(cfg, "--json", "hooks", "list") == 0
    assert read_json(capsys) == [{"event": "after_report", "name": "h1", "command": TRUE,
                                  "timeout": "60s", "when": "always"}]
    assert run(cfg, "hooks", "test", "after_report", "nope") == 2
    assert "no hook 'nope' in hooks.after_report (h1)" in capsys.readouterr().err
    assert run(cfg, "--json", "hooks", "test", "after_report", "h1") == 0
    assert read_json(capsys)[0]["ok"] is True


def test_print_hooks_formats(capsys):
    cli.print_hooks([HookResult("after_export", "a", True, skipped=True, detail="skipped"),
                     HookResult("after_export", "b", False, detail="exit code 2")])
    assert capsys.readouterr().out == ("hook after_export/a: skipped\n"
                                       "hook after_export/b: FAILED — exit code 2\n")


def test_init_refuses_overwrite(tmp_path, capsys, monkeypatch):
    target = tmp_path / "x.yml"
    target.write_text("keep")
    assert cli.main(["init", "--output", str(target)]) == 2
    assert target.read_text() == "keep"
    monkeypatch.setattr(sys, "argv", ["snowth_my_net"])


def test_remaining_branches(cfg, capsys, tmp_path, monkeypatch):
    import snowth_my_net.collect.custom as custom
    import snowth_my_net.collect.probe as probe

    # cron print and custom export without any state
    assert run(cfg, "cron", "print") == 0
    assert "collect" in capsys.readouterr().out
    assert run(cfg, "custom", "export") == 0
    assert "collectors: []" in capsys.readouterr().out

    repo = state(tmp_path)
    device_id = add_device(repo)
    add_run(repo, NOW)
    with repo.conn:
        repo.conn.execute("INSERT INTO custom_runs(device_id, collector, run_at, status, rows) "
                          "VALUES (?, 'empty', ?, 'absent', 0)", (device_id, NOW))
    repo.save_custom_collector("broken", {"name": "broken"}, NOW)       # invalid definition
    repo.conn.close()
    assert run(cfg, "--json", "show", "runs") == 0
    assert read_json(capsys)[0]["command"] == "collect"
    assert run(cfg, "show", "links") == 0 and run(cfg, "show", "nodes") == 0
    capsys.readouterr()
    assert run(cfg, "custom", "show", "192.0.2.1") == 0
    out = capsys.readouterr().out
    assert "empty — absent at" in out and "INDEX" not in out
    assert run(cfg, "custom", "list") == 0
    assert "collector 'broken' from the state is invalid" in capsys.readouterr().err

    # import: a bare list, without --replace, and an address with no values
    source = tmp_path / "s.yml"
    source.write_text("- address: 192.0.2.5\n  type: switch\n- address: 192.0.2.6\n")
    assert run(cfg, "device", "import-settings", str(source)) == 0
    assert "for 2 address(es)" in capsys.readouterr().out

    (tmp_path / "extensions").mkdir()
    (tmp_path / "extensions" / "c.yml").write_text(
        "collectors:\n  - {name: sysname, get: {v: 1.3.6.1.2.1.1.5.0}}\n")

    async def connect(loaded, creds, target, pool, manual=None, remembered=None):
        return fake_connection(loaded)

    async def nothing(client, collector, result, facts):
        return None

    monkeypatch.setattr(probe, "connect", connect)
    monkeypatch.setattr(custom, "run_collector", nothing)
    assert run(cfg, "custom", "test", "sysname", "192.0.2.77") == 1
    assert capsys.readouterr().out == "sysname on 192.0.2.77: 0 value(s)\n"


def test_cli_addresses_use_the_configured_snmp_port(tmp_path, capsys, monkeypatch):
    """An address typed without a port reaches the same port as the seeds."""
    assert (parse_target("192.0.2.1").port, parse_target("192.0.2.1", 1161).port) == (161, 1161)
    assert parse_target("192.0.2.1:2161", 1161).port == 2161        # an explicit port wins
    assert parse_target("[2001:db8::1]", 1161).port == 1161

    monkeypatch.setenv("SNOWTH_COV_COMMUNITY", "cov-community")
    cfg = base_config(tmp_path)
    cfg.write_text(cfg.read_text().replace("  lock_wait:", "  snmp: {port: 1161}\n  lock_wait:"))
    assert run(cfg, "device", "add", "192.0.2.42") == 0
    capsys.readouterr()
    repo = state(tmp_path)
    try:
        assert [row["address"] for row in repo.targets()] == ["192.0.2.42:1161"]
    finally:
        repo.conn.close()


def test_node_reset_asks_before_forgetting(cfg, capsys, tmp_path):
    repo = state(tmp_path)
    add_device(repo)
    repo.conn.execute("INSERT INTO fdb_obs(mac, device_id, ifindex, vlan, vlan_source, "
                      "first_seen, last_seen, last_run_id) VALUES "
                      "('aa:bb:cc:dd:ee:ff', 1, 1, 10, 'fdb', ?, ?, 1)", (NOW, NOW))
    repo.conn.commit()
    repo.conn.close()
    assert run(cfg, "node", "reset") == 2            # refused: it must be confirmed
    assert run(cfg, "node", "reset", "--yes") == 0
    assert "1 MAC observation(s)" in capsys.readouterr().out
    assert run(cfg, "--json", "node", "reset", "--yes") == 0
    assert read_json(capsys) == {"fdb": 0, "arp": 0}

"""``check``: per-device diagnosis with fake agents, and configuration/secret warnings."""

from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest

from snowth_my_net.collect import check
from snowth_my_net.collect.check import check_devices, config_warnings, secret_warnings
from snowth_my_net.collect.discovery import PlannedTarget
from snowth_my_net.config.extensions import LoadedCollector, parse_collector
from snowth_my_net.config.loader import LoadedConfig, Paths, ResolvedCredential
from snowth_my_net.config.reports import LoadedReport, ReportCfg
from snowth_my_net.config.schema import CredentialCfg
from snowth_my_net.config.secrets import Secret
from snowth_my_net.config.validate import build
from snowth_my_net.drivers.base import Driver
from snowth_my_net.snmp import oids
from snowth_my_net.snmp.client import SnmpError, SnmpTimeout
from snowth_my_net.snmp.target import Target
from snowth_my_net.snmp.values import parse_oid
from tests.unit.test_cov_collect_engine import (
    FakeClient,
    Lab,
    credential,
    loaded_config,
    system_values,
)

PRIVATE = "1.3.6.1.4.1.99999.9"


@pytest.fixture
def lab(monkeypatch):
    original = check.settings_for

    def short_tables(cfg, host, manual=None):
        settings = original(cfg, host, manual)
        settings.snmp.table_timeout = 0.2     # the schema only accepts whole seconds
        return settings

    monkeypatch.setattr(check, "settings_for", short_tables)
    return Lab(monkeypatch, module=check)


def planned(*hosts):
    return [PlannedTarget(Target(h), "seed") for h in hosts]


async def test_check_full_and_quick(tmp_path, lab, monkeypatch):
    values = {**system_values("Switch", descr="Generic switch"),
              oids.IF_DESCR + (1,): b"eth0", oids.IF_DESCR + (2,): b"eth1",
              parse_oid(f"{PRIVATE}.1.0"): b"fine"}
    lab.add("192.0.2.1", FakeClient(values, fail={oids.CDP_CACHE_ENTRY: SnmpTimeout("slow"),
                                                  oids.UPS_IDENT: SnmpError("genErr")},
                                    delay={oids.PRT_GENERAL_ENTRY: 1}))
    lab.add("192.0.2.2", FakeClient(system_values("Switch")))
    loaded = loaded_config(tmp_path, """devices:
  - {address: 192.0.2.1, features: {lldp: force, fdb: force, interfaces: force}}
""")
    collectors = [
        LoadedCollector(parse_collector({"name": "ok-one", "get": {"v": f"{PRIVATE}.1.0"}}), "t"),
        LoadedCollector(parse_collector({"name": "forced", "mode": "force",
                                         "get": {"v": f"{PRIVATE}.2.0"}}), "t"),
        LoadedCollector(parse_collector({"name": "slow", "walk": {"columns": {
            "v": f"{PRIVATE}.3"}}}), "t"),
        LoadedCollector(parse_collector({"name": "broken", "walk": {"columns": {
            "v": f"{PRIVATE}.4"}}}), "t"),
        LoadedCollector(parse_collector({"name": "elsewhere", "applies_to": {
            "vendors": ["Nobody"]}, "get": {"v": f"{PRIVATE}.1.0"}}), "t"),
    ]
    lab.devices["192.0.2.1"].delay[parse_oid(f"{PRIVATE}.3")] = 1
    lab.devices["192.0.2.1"].fail[parse_oid(f"{PRIVATE}.4")] = SnmpError("noAccess")
    manual = {"192.0.2.1": {"tolerate_failure": True}}
    creds = [credential(), credential("other", scope=["198.51.100.0/24"])]
    results = await check_devices(loaded, creds, planned("192.0.2.1", "192.0.2.2"), quick=False,
                                  manual=manual, collectors=collectors)
    first, _second = results
    assert first.reachable and first.credential == "lab" and first.tolerated
    assert first.mibs["ifTable"] == "ok(2)" and first.mibs["dot1qTpFdb"] == "absent"
    assert first.mibs["cdpCache"] == "timeout" and first.mibs["upsMib"] == "error: genErr"
    assert first.mibs["printerMib"] == "timeout"
    assert first.mibs["custom:ok-one"] == "ok(1)" and first.mibs["custom:forced"] == "absent"
    assert first.mibs["custom:slow"] == "timeout"
    assert first.mibs["custom:broken"] == "error: noAccess"
    assert "custom:elsewhere" not in first.mibs
    assert "forced function 'lldp' has no data" in first.warnings
    assert "forced function 'fdb' has no data" in first.warnings
    assert not any("'interfaces'" in w for w in first.warnings)
    assert "forced collector 'forced' has no data" in first.warnings
    assert any("sysName 'Switch' is also used by 192.0.2.2" in w for w in first.warnings)
    assert any("set a real hostname" in w for w in first.warnings)
    assert first.failed

    quick = await check_devices(loaded, [credential()], planned("192.0.2.2"), quick=True)
    assert quick[0].mibs["ifTable"] == "absent" and not quick[0].failed


async def test_check_unreachable_no_credential_and_manual_override(tmp_path, lab):
    lab.add("192.0.2.3", FakeClient(system_values("fw3")))
    loaded = loaded_config(tmp_path, "devices:\n  - {address: 192.0.2.3, type: firewall}\n")
    scoped = credential(scope=["192.0.2.0/30"])
    results = await check_devices(loaded, [scoped], planned("192.0.2.1", "192.0.2.3",
                                                            "192.0.2.9"), quick=True,
                                  manual={"192.0.2.3": {"type": "router"}})
    silent, manual, out_of_scope = results
    assert silent.error == "no answer (lab: timeout)" and silent.failed
    assert manual.ident.device_type == "router"
    assert "manual setting 'type' overrides config.yml" in manual.warnings
    assert out_of_scope.error == "no credential in scope for this address"


async def test_check_runs_the_driver_identity(tmp_path, lab, monkeypatch):
    class Filling(Driver):
        name = "fill"

        async def identify(self, client, r):
            return {"serial": "SN-1"}

    class Nothing(Driver):
        name = "nothing"
        identity_oids: ClassVar[dict[str, str]] = {"x": "1.3.6.1.4.1.1.0"}

        async def identify(self, client, r):
            return {}

    class Quiet(Driver):
        name = "quiet"

    class Slow(Driver):
        name = "slow"

        async def identify(self, client, r):
            await asyncio.sleep(5)

    class Failing(Driver):
        name = "failing"

        def __init__(self, exc):
            self.exc = exc

        async def identify(self, client, r):
            raise self.exc

    for host in ("192.0.2.1", "192.0.2.2"):
        lab.add(host, FakeClient(system_values(f"dev{host[-1]}")))
    loaded = loaded_config(tmp_path)
    expectations = [(Filling(), "ok(serial)"), (Nothing(), "absent"), (Quiet(), "ok"),
                    (Slow(), "timeout"), (Failing(SnmpTimeout("t")), "timeout"),
                    (Failing(SnmpError("bad")), "error: bad")]
    for driver, expected in expectations:
        monkeypatch.setattr(check.drivers, "select", lambda *a, d=driver: d)
        (dc,) = await check_devices(loaded, [credential()], planned("192.0.2.1"), quick=True)
        assert dc.mibs[f"driver:{driver.name}"] == expected
        if expected == "ok(serial)":
            assert dc.ident.serial == "SN-1"


def resolved_v3(name, auth_key, priv_key=None):
    cfg = build(CredentialCfg, {"name": name, "version": "3", "username": "u",
                                "auth_protocol": "sha", "auth_key_file": "a",
                                **({"priv_protocol": "aes128", "priv_key_file": "p"}
                                   if priv_key else {})})
    return ResolvedCredential(cfg, auth_key=Secret(auth_key, "t"),
                              priv_key=Secret(priv_key, "t") if priv_key else None)


def test_secret_warnings():
    weak = ResolvedCredential(build(CredentialCfg, {"name": "ro", "version": "2c",
                                                    "community_file": "x"}),
                              community=Secret("public", "t"))
    named = resolved_v3("key-authkey-secret-x", "authkey-secret")
    fine = resolved_v3("v3", "authkey-other-1", "privkey-other-1")
    warnings = secret_warnings([weak, named, fine])
    assert warnings == [
        "credential 'ro': the community is a well-known default or shorter than 8 characters",
        "credential 'key-authkey-secret-x': its name contains its own secret; the name will "
        "appear masked in logs and outputs"]


def test_config_warnings_and_hooks(tmp_path, monkeypatch):
    from snowth_my_net.config.loader import parse_config_text

    tool = tmp_path / "tool.sh"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o644)                                   # not executable
    cfg = parse_config_text(f"""
credentials:
  - {{name: noauth, version: "3", username: u}}
  - {{name: authonly, version: "3", username: u, auth_protocol: sha, auth_key_env: AUTH_ENV}}
  - {{name: v2, version: 2c, community_env: COMMUNITY_ENV}}
push:
  targets:
    - name: insecure
      url: http://cmdb.example.net/import
      tls_verify: false
      auth: {{bearer_token_env: TOKEN_ENV}}
      headers: {{X-Key: {{env: HEADER_ENV}}}}
    - name: basic
      url: https://cmdb.example.net/import
      auth: {{basic: {{username: u, password_env: PASSWORD_ENV}}}}
hooks:
  after_export:
    - {{name: templated, command: ["{{output_dir}}/run"]}}
    - {{name: not-exec, command: [{tool}], pass_env: [TOKEN_ENV, HOME]}}
    - {{name: relative, command: [surely-missing-tool-xyz]}}
    - {{name: found, command: [sh], pass_env: [COMMUNITY_ENV]}}
""")
    paths = Paths(tmp_path / "c.yml", tmp_path, tmp_path, tmp_path, tmp_path)
    loaded = LoadedConfig(cfg, paths)
    loaded.collectors = [LoadedCollector(parse_collector({"name": "poe", "get": {
        "v": "1.3.6.1.4.1.1.0"}}), "t")]
    loaded.reports = [LoadedReport(build(ReportCfg, {"name": "r1", "dataset": "custom:poe",
                                                     "push": ["insecure", "nowhere"]}), "f"),
                      LoadedReport(build(ReportCfg, {"name": "r2", "dataset": "custom:gone"}),
                                   "f")]
    warnings = config_warnings(loaded)
    assert "credential 'noauth' is noAuthNoPriv; authPriv is recommended" in warnings
    assert "credential 'authonly' is authNoPriv; authPriv is recommended" in warnings
    assert any(w.startswith("credential 'v2' uses SNMPv2c") for w in warnings)
    assert "push target 'insecure': TLS verification is disabled" in warnings
    assert any("plain HTTP" in w for w in warnings)
    assert "discovery.allowed is empty: only the seeds will ever be polled" in warnings
    assert "hook after_export/templated: the program itself should not be a placeholder" \
        in warnings
    assert f"hook after_export/not-exec: {tool} is not an executable file" in warnings
    assert any(w.startswith("hook after_export/relative: surely-missing-tool-xyz is not found")
               for w in warnings)
    assert "hook after_export/not-exec: pass_env hands a secret to the hook (TOKEN_ENV)" \
        in warnings
    assert "hook after_export/found: pass_env hands a secret to the hook (COMMUNITY_ENV)" \
        in warnings
    assert "report 'r1': unknown push target 'nowhere'" in warnings
    assert not any("'r1': dataset" in w for w in warnings)
    assert any(w.startswith("report 'r2': dataset custom:gone needs the collector 'gone'")
               for w in warnings)
    assert check.secret_env_names(loaded) == {"AUTH_ENV", "COMMUNITY_ENV", "TOKEN_ENV",
                                              "HEADER_ENV", "PASSWORD_ENV"}


def test_quiet_configuration_has_no_warning(tmp_path):
    from snowth_my_net.config.loader import parse_config_text

    cfg = parse_config_text("""
discovery: {allowed: [192.0.2.0/24]}
credentials:
  - {name: v3, version: "3", username: u, auth_protocol: sha, auth_key_env: A,
     priv_protocol: aes128, priv_key_env: P}
hooks:
  after_collect:
    - {name: ok, command: [/bin/true]}
""")
    loaded = LoadedConfig(cfg, Paths(tmp_path / "c.yml", tmp_path, tmp_path, tmp_path, tmp_path))
    assert config_warnings(loaded) == []
    strong = ResolvedCredential(build(CredentialCfg, {"name": "ro", "version": "2c",
                                                      "community_file": "x"}),
                                community=Secret("a-long-community-9", "t"))
    assert secret_warnings([strong]) == []

"""Secrets, configuration loading, effective settings, manual settings and extension files."""

from __future__ import annotations

import os
import pickle
from pathlib import Path

import pytest

from snowth_my_net.config import loader as loader_module
from snowth_my_net.config.effective import settings_for
from snowth_my_net.config.extensions import load_extensions, parse_collector
from snowth_my_net.config.loader import (
    find_config,
    load_config,
    parse_config_text,
)
from snowth_my_net.config.manual import (
    ManualError,
    coerce,
    from_override_entries,
    parse_assignment,
    validate,
)
from snowth_my_net.config.reports import FilterCfg
from snowth_my_net.config.secrets import Secret, SecretError, read_secret_file, resolve_secret
from snowth_my_net.config.validate import ConfigError

# --------------------------------------------------------------------------- secrets


def test_secret_value_is_hidden_and_not_picklable():
    secret = Secret("s3cr3t-value", "env X")
    assert secret.reveal() == "s3cr3t-value" and "s3cr3t" not in repr(secret) + str(secret)
    with pytest.raises(TypeError, match="cannot be pickled"):
        pickle.dumps(secret)
    with pytest.raises(SecretError, match="empty"):
        Secret("", "env X")


def test_secret_files(tmp_path):
    good = tmp_path / "good"
    good.write_bytes("﻿token-1\r\n".encode())
    good.chmod(0o600)
    assert read_secret_file(good) == ("token-1", [])
    good.chmod(0o640)
    assert "readable by group/others (mode 0640)" in read_secret_file(good)[1][0]
    with pytest.raises(SecretError, match="cannot read secret file"):
        read_secret_file(tmp_path / "missing")
    bad = tmp_path / "bad"
    bad.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(SecretError, match="not valid UTF-8"):
        read_secret_file(bad)
    empty = tmp_path / "empty"
    empty.write_text(" \n")
    with pytest.raises(SecretError, match="is empty"):
        read_secret_file(empty)


def test_resolve_secret_forms(tmp_path, monkeypatch):
    (tmp_path / "rel").write_text("from-file")
    (tmp_path / "rel").chmod(0o600)
    secret, _warnings = resolve_secret("rel", None, tmp_path, "thing")
    assert secret.reveal() == "from-file" and secret.source == f"file {tmp_path / 'rel'}"
    assert resolve_secret(str(tmp_path / "rel"), None, Path("/nowhere"), "t")[0].reveal() == \
        "from-file"
    monkeypatch.setenv("SNOWTH_TEST_SECRET", "  from-env \n")
    assert resolve_secret(None, "SNOWTH_TEST_SECRET", tmp_path, "t")[0].reveal() == "from-env"
    monkeypatch.setenv("SNOWTH_TEST_EMPTY", "  ")
    for args, message in (((("f", "E")), "not both"), (((None, "SNOWTH_UNSET_X")), "is not set"),
                          (((None, "SNOWTH_TEST_EMPTY")), "is empty"),
                          (((None, None)), "missing")):
        with pytest.raises(SecretError, match=message):
            resolve_secret(*args, tmp_path, "thing")


# --------------------------------------------------------------------------- loader


def test_find_config_order(tmp_path, monkeypatch):
    assert find_config("given.yml") == Path("given.yml")
    monkeypatch.setenv("SNOWTH_CONFIG", "/etc/from-env.yml")
    assert find_config(None) == Path("/etc/from-env.yml")
    monkeypatch.delenv("SNOWTH_CONFIG")
    local = tmp_path / "snowth_my_net.yml"
    monkeypatch.setattr(loader_module, "DEFAULT_CONFIG_CANDIDATES", (local,))
    with pytest.raises(ConfigError, match="no configuration file found"):
        find_config(None)
    local.write_text("")
    assert find_config(None) == local


def test_parse_errors():
    with pytest.raises(ConfigError, match="invalid YAML"):
        parse_config_text("general: [unclosed")
    with pytest.raises(ConfigError, match="the top level must be a mapping"):
        parse_config_text("- a\n- b\n")
    assert parse_config_text("﻿").version == 1


def test_load_config_paths_and_errors(tmp_path, monkeypatch):
    with pytest.raises(ConfigError, match="cannot read configuration"):
        load_config(tmp_path / "missing.yml")
    cfg = tmp_path / "c.yml"
    cfg.write_text("general:\n  state_dir: rel-state\n  output_dir: ~/out\n")
    for name in ("SNOWTH_STATE_DIR", "SNOWTH_OUTPUT_DIR", "SNOWTH_SECRETS_DIR",
                 "SNOWTH_EXTENSIONS_DIR"):
        monkeypatch.delenv(name, raising=False)
    paths = load_config(cfg).paths
    assert paths.state_dir == tmp_path / "rel-state"
    assert paths.output_dir == Path("~/out").expanduser()
    assert paths.extensions_dir == tmp_path.resolve() / "extensions"
    assert paths.state_file.name == "state.sqlite" and paths.lock_file.name == "state.lock"
    assert paths.oui_file.name == "oui.tsv.gz"
    monkeypatch.setenv("SNOWTH_STATE_DIR", "env-state")
    monkeypatch.chdir(tmp_path)
    paths = load_config(cfg, output_dir="cli-out").paths
    assert paths.state_dir == tmp_path / "env-state" and paths.output_dir == tmp_path / "cli-out"


def test_resolve_credentials_collects_every_problem(tmp_path, monkeypatch):
    cfg = tmp_path / "c.yml"
    cfg.write_text(f"""
general: {{state_dir: {tmp_path}, secrets_dir: {tmp_path}}}
credentials:
  - {{name: v2, version: 2c, community_file: missing}}
  - {{name: short, version: 3, username: u, auth_protocol: sha, auth_key_env: SHORT_KEY,
      priv_protocol: aes128, priv_key_env: GOOD_KEY}}
  - {{name: noauth, version: 3, username: u}}
""")
    monkeypatch.setenv("SHORT_KEY", "abc")
    monkeypatch.setenv("GOOD_KEY", "long-enough-key")
    loaded = load_config(cfg)
    with pytest.raises(ConfigError) as caught:
        loaded.resolve_credentials()
    text = "\n".join(caught.value.errors)
    assert "cannot read secret file" in text
    assert "SNMPv3 keys must be at least 8 characters (env SHORT_KEY)" in text
    monkeypatch.setenv("SHORT_KEY", "now-long-enough")
    cfg.write_text(cfg.read_text().replace("community_file: missing", "community_env: GOOD_KEY"))
    resolved, warnings = load_config(cfg).resolve_credentials()
    assert [c.name for c in resolved] == ["v2", "short", "noauth"] and warnings == []
    assert resolved[2].auth_key is None and resolved[0].community.reveal() == "long-enough-key"


def test_unknown_driver_is_reported_after_loading(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text(f"general: {{state_dir: {tmp_path}}}\n"
                   "devices:\n  - {address: 192.0.2.1, driver: nothing-like-it}\n")
    with pytest.raises(ConfigError, match="unknown driver 'nothing-like-it'"):
        load_config(cfg)


# --------------------------------------------------------------------------- effective / manual


def test_effective_settings_get_set_and_sources():
    cfg = parse_config_text("""
devices:
  - {address: 192.0.2.0/24, snmp: {pace_ms: 5}, features: {arp: force}}
  - {address: 192.0.2.7, type: firewall}
""")
    s = settings_for(cfg, "192.0.2.7", {"192.0.2.7": {"features.cdp": "off"}})
    assert s.get("type") == "firewall" and s.get("snmp.pace_ms") == 5
    assert s.get("features.arp") == "force" and s.get("features.cdp") == "off"
    assert s.source("features.cdp") == "manual" and s.source("type") == "config"
    assert s.source("name") == "default"
    other = settings_for(cfg, "not-an-ip", {"not-an-ip": {"type": "router"}})
    assert other.get("type") == "router" and other.get("snmp.pace_ms") == 0
    assert settings_for(cfg, "2001:db8::1").get("features.arp") == "auto"


def test_manual_values():
    assert coerce("uplinks", "Gi1/0/1, Gi1/0/2,") == ["Gi1/0/1", "Gi1/0/2"]
    assert coerce("uplink_mac_threshold", "20") == 20
    assert coerce("name", "a: [b") == "a: [b"
    with pytest.raises(ManualError, match="empty value"):
        coerce("name", " ")
    with pytest.raises(ManualError, match="did you mean 'type'"):
        coerce("typ", "x")
    with pytest.raises(ManualError, match="expected one of"):
        validate("features.arp", "maybe")
    with pytest.raises(ManualError, match="a value is required"):
        validate("type", None)
    cfg = parse_config_text("credentials: [{name: main, version: 2c, community_env: C}]")
    with pytest.raises(ManualError, match=r"unknown credential 'other' \(configured: main\)"):
        validate("credential", "other", cfg)
    assert validate("credential", "main", cfg) == "main"
    with pytest.raises(ManualError, match="unknown credential 'x' \\(configured: none\\)"):
        validate("credential", "x", parse_config_text(""))
    with pytest.raises(ManualError, match="expected key=value"):
        parse_assignment("type")
    assert parse_assignment(" snmp.pace_ms =20") == ("snmp.pace_ms", 20)


def test_manual_import_errors():
    for entries, message in (({}, "expected a list"), ([{"type": "x"}], "with an address"),
                             ([{"address": "nope"}], "invalid address"),
                             ([{"address": "10.0.0.0/24"}], "is a range")):
        with pytest.raises(ManualError, match=message):
            from_override_entries(entries)
    assert from_override_entries([{"address": "192.0.2.1/32", "features": {"arp": "off"},
                                   "snmp": {"retries": 2}, "type": "switch"}]) == {
        "192.0.2.1": {"features.arp": "off", "snmp.retries": 2, "type": "switch"}}


# --------------------------------------------------------------------------- extension files


def test_extension_files_errors(tmp_path):
    assert load_extensions(None) == ([], [])
    assert load_extensions(tmp_path / "missing") == ([], [])
    (tmp_path / "a.yaml").write_text("collectors: [unclosed\n")
    (tmp_path / "b.yml").write_text(
        "collectors:\n"
        "  - {name: c1, get: {v: {oid: 'not.an.oid', type: enum}}}\n"
        "  - {name: c2, get: {v: 1.3.6.1.2.1.1.5.0}, fills: {model: w}, limit: 0}\n"
        "  - {name: c3}\n"
        "  - {name: c4, get: {v: 1.3.6.1.2.1.1.5.0}, walk: {columns: {x: 1.3.6.1.2.1.2}}}\n"
        "  - {name: c5, walk: {columns: {}}}\n"
        "  - {name: c6, get: {v: {oid: 1.3.6.1.2.1.1.5.0, type: bits, values: {x: y}}}}\n"
        "  - {name: c7, get: {v: 1.3.6.1.2.1.1.5.0}, applies_to: {sys_object_ids: [nope]}}\n")
    with pytest.raises(ConfigError) as caught:
        load_extensions(tmp_path)
    text = "\n".join(caught.value.errors)
    for expected in ("a.yaml: invalid YAML", "is not a numeric OID", "type enum needs values",
                     "fills.model: 'w' is not a get: value", "limit must be > 0",
                     "collector 'c3': needs get: or walk:", "use either get: or walk:",
                     "walk needs at least one column", "values keys must be numbers, got x",
                     "sys_object_ids: 'nope' is not a numeric OID"):
        assert expected in text, expected
    assert parse_collector({"name": "ok", "get": {"v": "1.3.6.1.2.1.1.5.0"}}).kind == "get"


@pytest.mark.parametrize(("flt", "message"), [
    (FilterCfg("f", "empty", "x"), "takes no value"),
    (FilterCfg("f", "eq"), "needs a value"),
    (FilterCfg("f", "in", "a"), "needs a list"),
    (FilterCfg("f", "older_than", "soon"), "expected a duration"),
    (FilterCfg("f", "regex", "("), "invalid regex"),
])
def test_filter_checks(flt, message):
    assert message in flt.check()[0]


def test_filter_checks_accept_valid_values():
    assert FilterCfg("f", None).check() == []
    assert FilterCfg("f", "newer_than", "7d").check() == []
    assert FilterCfg("f", "regex", "^a").check() == []


def test_report_definition_checks():
    from snowth_my_net.config.reports import ReportCfg

    r = ReportCfg("r", sql="select 1", columns=["a"], limit=0)
    errors = "\n".join(r.check())
    assert "do not apply to sql reports" in errors and "limit must be > 0" in errors
    assert ReportCfg("r", dataset="py:x").check() == []
    assert "unknown dataset 'py:'" in "\n".join(ReportCfg("r", dataset="py:").check())
    assert ReportCfg("r", dataset="devices", output="x/").check() == []
    assert "relative path" in "\n".join(ReportCfg("r", dataset="devices", output="/abs").check())
    assert os.sep == "/"


def test_python_extensions_are_loaded_with_the_configuration(tmp_path):
    (tmp_path / "extensions").mkdir()
    (tmp_path / "extensions" / "demo.py").write_text(
        "from snowth_my_net.api import Extension, Field\n"
        "extension = Extension('demo')\n"
        "drv = extension.driver('demo-drv', object_ids=['1.3.6.1.4.1.1'])\n"
        "@drv.identity\n"
        "async def identity(device, snmp):\n"
        "    return {}\n"
        "@extension.report_dataset('rows', fields=[Field('a')])\n"
        "def rows(ctx):\n"
        "    return [{'a': 1}]\n"
        "@extension.exporter('x.txt')\n"
        "def export(snapshot):\n"
        "    return b''\n")
    cfg = tmp_path / "c.yml"
    cfg.write_text(f"general: {{state_dir: {tmp_path}, python_extensions: [demo]}}\n"
                   "devices:\n  - {address: 192.0.2.1, driver: demo-drv}\n")
    loaded = load_config(cfg)
    assert [d.name for d in loaded.drivers] == ["demo-drv"]
    assert [d.name for d in loaded.datasets] == ["py:rows"]
    assert loaded.datasets[0].build(None) == [{"a": 1}]
    assert [e.filename for _n, e in loaded.exporters] == ["x.txt"]
    assert [p.name for p in loaded.python] == ["demo"]

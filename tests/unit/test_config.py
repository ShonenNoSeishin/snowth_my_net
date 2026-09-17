from importlib import resources

import pytest

from snowth_my_net.config.effective import settings_for
from snowth_my_net.config.loader import load_config, parse_config_text
from snowth_my_net.config.validate import ConfigError


def errors_of(text: str) -> list[str]:
    with pytest.raises(ConfigError) as exc:
        parse_config_text(text)
    return exc.value.errors


def test_empty_config_uses_generic_defaults():
    cfg = parse_config_text("")
    assert cfg.nodes.uplink_mac_threshold == 50
    assert cfg.nodes.lag_is_uplink is False
    assert cfg.general.snmp.per_device_concurrency == 1
    assert cfg.export.csv.line_terminator == "crlf"
    assert cfg.export.devices.include_type is True


def test_example_config_is_valid():
    text = resources.files("snowth_my_net.config").joinpath("example.yml").read_text("utf-8")
    cfg = parse_config_text(text)
    assert cfg.credentials[0].security_level == "authPriv"
    assert cfg.schedule.collect == "*/10 * * * *"


def test_unknown_key_suggests_the_closest_name():
    assert errors_of("genral: {}") == ["genral: unknown key (did you mean 'general'?)"]


def test_plain_text_secrets_are_refused():
    errs = errors_of("credentials:\n  - {name: a, version: 2c, community: public}\n")
    assert any(e.startswith("credentials[0].community: secrets are never written") for e in errs)
    errs = errors_of("push:\n  targets:\n    - {name: t, url: 'https://x', auth: {token: abc}}\n")
    assert any("push.targets[0].auth.token: secrets are never written" in e for e in errs)


def test_errors_carry_their_path_and_are_all_reported():
    errs = errors_of(
        "devices:\n  - {address: 10.0.0.1, features: {arp: yes}}\n"
        "discovery: {allowed: [10.0.0.0/33]}\n"
        "general: {snmp: {max_repetitions: 0}}\n"
    )
    expected = "devices[0].features.arp: expected one of auto|force|off"
    assert any(e.startswith(expected) for e in errs)
    assert any(e.startswith("discovery.allowed[0]: expected an IP address or CIDR") for e in errs)
    assert any("max_repetitions must be between 1 and 200" in e for e in errs)


def test_snmpv3_version_may_be_written_as_a_number():
    cfg = parse_config_text(
        "credentials:\n"
        "  - {name: v3, version: 3, username: u, auth_protocol: sha256, auth_key_file: a,\n"
        "     priv_protocol: aes128, priv_key_file: p}\n"
    )
    assert cfg.credentials[0].version == "3"


@pytest.mark.parametrize(
    "credential, message",
    [
        ("{name: c, version: 2c}", "v2c needs community_file or community_env"),
        ("{name: c, version: 3}", "SNMPv3 needs a username"),
        ("{name: c, version: 3, username: u, priv_protocol: aes128, priv_key_file: p}",
         "privacy (priv_protocol) requires authentication"),
        ("{name: c, version: 3, username: u, auth_protocol: sha}",
         "auth_protocol needs auth_key_file or auth_key_env"),
    ],
)
def test_credential_consistency(credential, message):
    errs = errors_of(f"credentials:\n  - {credential}\n")
    assert any(message in e for e in errs), errs


def test_unknown_credential_reference():
    errs = errors_of("devices:\n  - {address: 10.0.0.1, credential: nope}\n")
    assert "<config>: devices[0].credential: unknown credential 'nope'" in errs


def test_durations_and_networks():
    cfg = parse_config_text(
        "general: {run_timeout: 10m}\nnodes: {current_ip_window: 2h}\n"
        "discovery: {allowed: [10.0.0.0/8, 192.0.2.7], exclude: ['2001:db8::/32']}\n"
    )
    assert cfg.general.run_timeout == 600
    assert cfg.nodes.current_ip_window == 7200
    assert [str(n) for n in cfg.discovery.allowed] == ["10.0.0.0/8", "192.0.2.7/32"]


def test_sweep_must_stay_inside_allowed():
    errs = errors_of("discovery: {allowed: [10.0.0.0/24], sweep: [10.0.1.0/24]}\n")
    assert any("sweep range 10.0.1.0/24 is not inside discovery.allowed" in e for e in errs)


def test_device_overrides_merge_by_specificity():
    cfg = parse_config_text(
        "devices:\n"
        "  - {address: 10.0.0.1, snmp: {pace_ms: 50}, features: {arp: force}, ha_mode: vip}\n"
        "  - {address: 10.0.0.0/8, snmp: {pace_ms: 10, timeout: 5}, uplink_mac_threshold: 100}\n"
    )
    s = settings_for(cfg, "10.0.0.1")
    assert (s.snmp.pace_ms, s.snmp.timeout, s.uplink_mac_threshold) == (50, 5.0, 100)
    assert s.feature("arp") == "force" and s.feature("fdb") == "auto"
    assert s.ha_mode == "vip"
    other = settings_for(cfg, "10.1.0.1")
    assert (other.snmp.pace_ms, other.ha_mode) == (10, None)
    outside = settings_for(cfg, "192.0.2.1")
    assert (outside.snmp.pace_ms, outside.uplink_mac_threshold) == (0, 50)


def test_path_precedence(tmp_path, monkeypatch):
    for var in ("SNOWTH_STATE_DIR", "SNOWTH_OUTPUT_DIR", "SNOWTH_SECRETS_DIR"):
        monkeypatch.delenv(var, raising=False)
    cfg_file = tmp_path / "snowth.yml"
    cfg_file.write_text("general: {state_dir: st, output_dir: out}\n")
    base = tmp_path.resolve()

    paths = load_config(cfg_file).paths
    assert (paths.state_dir, paths.output_dir) == (base / "st", base / "out")

    monkeypatch.setenv("SNOWTH_STATE_DIR", str(tmp_path / "from_env"))
    assert load_config(cfg_file).paths.state_dir == tmp_path / "from_env"
    assert load_config(cfg_file, state_dir=str(tmp_path / "cli")).paths.state_dir == (
        tmp_path / "cli")

    bare = tmp_path / "bare.yml"
    bare.write_text("")
    monkeypatch.delenv("SNOWTH_STATE_DIR")
    paths = load_config(bare).paths
    assert str(paths.state_dir) == "/var/lib/snowth_my_net"
    assert paths.output_dir == paths.state_dir / "output"


def test_credentials_are_resolved_from_files_and_env(tmp_path, monkeypatch):
    (tmp_path / "auth").write_text("authkey-123\n")
    (tmp_path / "priv").write_bytes(b"\xef\xbb\xbfprivkey-456\r\n")
    monkeypatch.setenv("SNOWTH_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("V2C", "community-x")
    cfg_file = tmp_path / "c.yml"
    cfg_file.write_text(
        "credentials:\n"
        "  - {name: v3, version: 3, username: u, auth_protocol: sha, auth_key_file: auth,\n"
        "     priv_protocol: aes128, priv_key_file: priv}\n"
        "  - {name: v2, version: 2c, community_env: V2C}\n"
    )
    creds, _warnings = load_config(cfg_file).resolve_credentials()
    assert creds[0].auth_key.reveal() == "authkey-123"
    assert creds[0].priv_key.reveal() == "privkey-456"
    assert creds[1].community.reveal() == "community-x"
    assert "community-x" not in repr(creds[1])


def test_missing_secrets_are_all_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("SNOWTH_SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("NOPE", raising=False)
    cfg_file = tmp_path / "c.yml"
    cfg_file.write_text(
        "credentials:\n"
        "  - {name: a, version: 2c, community_file: missing}\n"
        "  - {name: b, version: 2c, community_env: NOPE}\n"
    )
    with pytest.raises(ConfigError) as exc:
        load_config(cfg_file).resolve_credentials()
    assert len(exc.value.errors) == 2
    assert "cannot read secret file" in exc.value.errors[0]
    assert "environment variable NOPE is not set" in exc.value.errors[1]


def test_short_v3_keys_are_refused(tmp_path, monkeypatch):
    (tmp_path / "k").write_text("short")
    monkeypatch.setenv("SNOWTH_SECRETS_DIR", str(tmp_path))
    cfg_file = tmp_path / "c.yml"
    cfg_file.write_text(
        "credentials:\n  - {name: a, version: 3, username: u, auth_protocol: sha,"
        " auth_key_file: k}\n")
    with pytest.raises(ConfigError, match="at least 8 characters"):
        load_config(cfg_file).resolve_credentials()


def test_yaml_off_is_understood_as_the_word_off():
    cfg = parse_config_text("devices:\n  - {address: 10.0.0.1, features: {arp: off, fdb: force}}\n")
    assert cfg.devices[0].features.arp == "off"
    errs = errors_of("devices:\n  - {address: 10.0.0.1, features: {arp: yes}}\n")
    assert any("expected one of auto|force|off" in e for e in errs)

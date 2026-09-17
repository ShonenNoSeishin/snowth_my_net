"""Configuration schema checks: one assertion per documented rule."""

from __future__ import annotations

import pytest
import yaml

from snowth_my_net.config.loader import parse_config_text
from snowth_my_net.config.schema import CredentialCfg, hook_placeholders
from snowth_my_net.config.validate import ConfigError


def errors(data: dict) -> str:
    with pytest.raises(ConfigError) as caught:
        parse_config_text(yaml.safe_dump(data))
    return "\n".join(caught.value.errors)


def test_snmp_limits():
    text = errors({"general": {"snmp": {"max_repetitions": 0, "port": 70000, "timeout": 0}},
                   "devices": [{"address": "192.0.2.1", "snmp": {"max_repetitions": 500,
                                                                  "retries": -1}}]})
    assert "max_repetitions must be between 1 and 200, got 0" in text
    assert "port must be between 1 and 65535, got 70000" in text
    assert "max_repetitions must be between 1 and 200, got 500" in text
    assert "retries" in text and "timeout" in text


@pytest.mark.parametrize(("cred", "message"), [
    ({"version": "2c", "community_file": "c", "username": "u"}, "v2c does not use username"),
    ({"version": "2c"}, "v2c needs community_file or community_env"),
    ({"version": "3", "username": "u", "community_env": "C"}, "SNMPv3 does not use a community"),
    ({"version": "3"}, "SNMPv3 needs a username"),
    ({"version": "3", "username": "u", "auth_protocol": "sha"},
     "auth_protocol needs auth_key_file or auth_key_env"),
    ({"version": "3", "username": "u", "auth_key_file": "a"},
     "an auth key is set but auth_protocol is missing"),
    ({"version": "3", "username": "u", "priv_protocol": "aes128", "priv_key_file": "p"},
     "privacy (priv_protocol) requires authentication"),
    ({"version": "3", "username": "u", "auth_protocol": "sha", "auth_key_file": "a",
      "priv_protocol": "aes128"}, "priv_protocol needs priv_key_file or priv_key_env"),
    ({"version": "3", "username": "u", "auth_protocol": "sha", "auth_key_file": "a",
      "priv_key_env": "P"}, "a privacy key is set but priv_protocol is missing"),
])
def test_credential_rules(cred, message):
    assert message in errors({"credentials": [{"name": "c", **cred}]})


def test_security_levels_and_forbidden_secrets():
    assert CredentialCfg("a", "2c").security_level == "v2c"
    assert CredentialCfg("a", "3", auth_protocol="sha").security_level == "authNoPriv"
    assert CredentialCfg("a", "3", auth_protocol="sha",
                         priv_protocol="aes128").security_level == "authPriv"
    assert CredentialCfg("a", "3").security_level == "noAuthNoPriv"
    text = errors({"credentials": [{"name": "c", "version": "2c", "community": "public"}]})
    assert "secrets are never written in the YAML" in text


def test_discovery_sweep_rules():
    text = errors({"discovery": {"allowed": ["10.0.0.0/8"],
                                 "sweep": ["192.0.2.0/24", "10.0.0.0/15", "bad"]}})
    assert "sweep range 192.0.2.0/24 is not inside discovery.allowed" in text
    assert "sweep covers 131328 addresses; the limit is 65536 per run" in text
    assert "expected an IP address or CIDR" in text


def test_dns_resolvers_must_be_addresses():
    assert "resolvers: 'dns.example' is not an IP address" in errors(
        {"dns": {"resolvers": ["192.0.2.53", "dns.example"]}})


def test_push_rules():
    text = errors({"push": {"targets": [
        {"name": "a", "url": "ftp://x", "files": []},
        {"name": "a", "url": "https://x", "files": ["devices", "devices"],
         "headers": {"X-Key": {"file": "k", "env": "K"}},
         "auth": {"bearer_token_file": "t", "bearer_token_env": "T"}},
        {"name": "b", "url": "https://x", "headers": {"X-Key": {}},
         "auth": {"bearer_token_env": "T", "basic": {"username": "u", "password_env": "P"}}},
        {"name": "c", "url": "https://x", "auth": {"basic": {"username": "u"}},
         "poll": {"url": "https://x/jobs"}},
        {"name": "d", "url": "https://x", "headers": {"X-Ok": {"env": "OK"}},
         "poll": {"url": "https://x/jobs/{id}"}},
    ]}})
    for expected in ("url must start with https:// or http://", "files must not be empty",
                     "files contains duplicates", "set exactly one of file or env",
                     "set either bearer_token_file or bearer_token_env, not both",
                     "choose bearer or basic authentication, not both",
                     "basic auth needs exactly one of password_file or password_env",
                     "duplicate push target name(s): a",
                     "poll.url must contain the {id} placeholder"):
        assert expected in text, expected


def test_schedule_rules():
    text = errors({"schedule": {"timezone": "Mars/Olympus", "collect": "every minute",
                                "export_push": "61 * * * *"}})
    assert "unknown time zone 'Mars/Olympus'" in text
    assert "schedule.collect:" in text and "schedule.export_push:" in text
    parse_config_text("schedule: {timezone: Europe/Brussels, collect: null, export_push: '@daily'}")


def test_hook_rules():
    text = errors({"hooks": {
        "after_collect": [
            {"name": "empty", "command": [" "]},
            {"name": "line", "command": ["notify-send done"]},
            {"name": "env", "command": ["/bin/true"],
             "env": {"1BAD": "x", "SNOWTH_X": "y", "GOOD": "z"},
             "pass_env": ["snowth_path"], "timeout": 0},
            {"name": "env", "command": ["/bin/true", "{devices}"]},
            {"command": ["/bin/true"]},
        ],
        "after_report": [{"name": "ok", "command": ["/bin/echo", "{report_file}", "{{x}}"]}],
    }})
    for expected in ("hook 'empty': command must be a non-empty list",
                     "command is a list of arguments, not a shell line (write ['notify-send', "
                     "'done'])",
                     "'1BAD' is not a variable name", "SNOWTH_X is reserved",
                     "snowth_path is reserved", "hook 'env' timeout",
                     "hooks.after_collect: duplicate hook name 'env'",
                     "hooks.after_collect.env: unknown placeholder {devices}",
                     "name: required"):
        assert expected in text, expected
    assert "after_report" not in text
    assert hook_placeholders("a{x}b{{literal}}{y}") == ["x", "y"]


def test_devices_credentials_and_duplicates():
    text = errors({"credentials": [
        {"name": "c", "version": "2c", "community_env": "C"},
        {"name": "c", "version": "2c", "community_env": "D"}],
        "devices": [{"address": "192.0.2.1", "credential": "missing", "driver": "Bad Name",
                     "uplink_mac_threshold": 0}]})
    assert "duplicate credential name(s): c" in text
    assert "devices[0].credential: unknown credential 'missing'" in text
    assert "driver: 'Bad Name' is not a driver name" in text
    assert "uplink_mac_threshold" in text


def test_nodes_rules():
    text = errors({"nodes": {"ignore_macs": ["zz"], "ignore_mac_prefixes": ["q"],
                             "retention_days": 0}})
    assert "ignore_macs: invalid MAC 'zz'" in text
    assert "ignore_mac_prefixes: invalid prefix 'q'" in text
    assert "retention_days" in text

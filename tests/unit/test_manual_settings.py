import sqlite3
from importlib import resources

import pytest

from snowth_my_net.collect.presets import PRESETS, suggestions
from snowth_my_net.collect.probe import ProbeInputError, format_value, parse_oid_input
from snowth_my_net.config.effective import settings_for
from snowth_my_net.config.loader import LoadedConfig, Paths, parse_config_text
from snowth_my_net.config.manual import (
    ManualError,
    coerce,
    from_override_entries,
    normalize_address,
    parse_assignment,
    to_override_entries,
    validate,
)
from snowth_my_net.state.db import SCHEMA_VERSION, open_db
from snowth_my_net.state.repo import Repo
from snowth_my_net.tui.data import plan_form_change

CFG = parse_config_text(
    "credentials:\n"
    "  - {name: v2, version: 2c, community_env: X}\n"
    "devices:\n"
    "  - {address: 10.0.0.0/24, type: switch, features: {arp: force}, snmp: {pace_ms: 20}}\n"
)


def test_assignments_are_typed_and_validated():
    assert parse_assignment("type=firewall") == ("type", "firewall")
    assert parse_assignment("features.arp=off") == ("features.arp", "off")
    assert parse_assignment("snmp.pace_ms=50") == ("snmp.pace_ms", 50)
    assert parse_assignment("tolerate_failure=true") == ("tolerate_failure", True)
    assert parse_assignment("uplinks=Te1/1/1, Te1/1/2") == ("uplinks", ["Te1/1/1", "Te1/1/2"])
    assert parse_assignment("credential=v2", CFG) == ("credential", "v2")


@pytest.mark.parametrize("text, message", [
    ("type=l3", "expected one of switch|router"),
    ("features.arp=yes", "expected one of auto|force|off"),
    ("snmp.pace_ms=-1", "must be >= 0"),
    ("typ=switch", "did you mean 'type'"),
    ("type", "expected key=value"),
    ("type=", "empty value"),
    ("community=public", "unknown setting"),
])
def test_invalid_assignments(text, message):
    with pytest.raises(ManualError, match=message):
        parse_assignment(text)


def test_unknown_credential_is_refused():
    with pytest.raises(ManualError, match="unknown credential 'nope'"):
        validate("credential", "nope", CFG)


def test_addresses_lose_their_port():
    assert normalize_address("10.0.0.1:1161") == "10.0.0.1"
    assert normalize_address("[2001:db8::1]:161") == "2001:db8::1"
    with pytest.raises(ManualError):
        normalize_address("host.example.com")


def test_manual_wins_over_config_field_by_field_with_sources():
    manual = {"10.0.0.5": {"type": "firewall", "features.fdb": "off"}}
    s = settings_for(CFG, "10.0.0.5", manual)
    assert (s.type, s.source("type")) == ("firewall", "manual")
    assert (s.feature("arp"), s.source("features.arp")) == ("force", "config")
    assert (s.feature("fdb"), s.source("features.fdb")) == ("off", "manual")
    assert (s.snmp.pace_ms, s.source("snmp.pace_ms")) == (20, "config")
    assert s.source("name") == "default"
    other = settings_for(CFG, "10.0.0.6", manual)
    assert (other.type, other.source("type")) == ("switch", "config")


def test_settings_round_trip_through_yaml_entries():
    manual = {"10.0.0.5": {"type": "firewall", "features.arp": "force", "snmp.pace_ms": 50}}
    entries = to_override_entries(manual)
    assert entries == [{"address": "10.0.0.5", "type": "firewall",
                        "features": {"arp": "force"}, "snmp": {"pace_ms": 50}}]
    assert from_override_entries(entries) == manual
    with pytest.raises(ManualError, match="is a range"):
        from_override_entries([{"address": "10.0.0.0/24", "type": "switch"}])


def test_coerce():
    assert coerce("name", "core-01") == "core-01"
    assert coerce("snmp.use_bulk", "false") is False


def test_form_changes_only_store_differences(tmp_path):
    loaded = LoadedConfig(CFG, Paths(tmp_path / "c.yml", tmp_path, tmp_path / "out", tmp_path))
    manual = {"10.0.0.5": {"features.fdb": "off"}}
    change = plan_form_change(loaded, "10.0.0.5", manual, {
        "type": None,                 # automatic: config.yml type applies
        "features.arp": "force",      # equal to config.yml: nothing to store
        "features.fdb": "auto",       # back to the default: remove the manual value
        "features.lldp": "off",       # new manual value
        "snmp.pace_ms": 20,
    })
    assert change.to_set == {"features.lldp": "off"}
    assert change.to_unset == ["features.fdb"]
    with pytest.raises(ManualError):
        plan_form_change(loaded, "10.0.0.5", {}, {"snmp.pace_ms": -5})


def test_state_migrates_from_v1_and_stores_manual_settings(tmp_path):
    db = tmp_path / "state.sqlite"
    conn = sqlite3.connect(db)
    v1 = resources.files("snowth_my_net.state").joinpath("schema_v1.sql").read_text()
    conn.executescript(v1)
    conn.execute("PRAGMA user_version = 1")
    conn.close()

    repo = Repo(open_db(db))
    assert repo.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    repo.set_manual("10.0.0.5", {"type": "firewall", "uplinks": ["Te1/1/1"]}, 100)
    repo.set_manual("10.0.0.5", {"type": "router"}, 200)
    assert repo.manual_settings() == {"10.0.0.5": {"type": "router", "uplinks": ["Te1/1/1"]}}
    assert repo.unset_manual("10.0.0.5", ["type"]) == 1
    repo.ensure_target("10.0.0.5:1161", "manual", 0, 100)
    repo.ensure_target("10.0.0.5:1161", "neighbor", 1, 100)
    origin = repo.conn.execute("SELECT origin FROM targets").fetchone()[0]
    assert origin == "manual"
    repo.remove_target("10.0.0.5:1161")
    assert repo.manual_settings() == {}
    assert repo.targets() == []


def test_format_value():
    assert format_value(None) == "∅ (no such object)"
    assert format_value(b"\x00\x00\x5e\x00\x53\x01") == "00:00:5e:00:53:01"
    assert format_value(b"abcdef") == "abcdef"
    arp_type = next(p for p in PRESETS if p.name == "arp-media").columns[1]
    mac_column = next(p for p in PRESETS if p.name == "arp-media").columns[0]
    assert format_value(b"abcdef", mac_column) == "61:62:63:64:65:66"
    assert format_value(3, arp_type) == "dynamic(3)"
    assert format_value((1, 3, 6, 1)) == "1.3.6.1"
    assert format_value(b"\xff\x01") == "0xff01"
    assert format_value(b"line1\r\nline2") == "line1 ⏎ line2"


def test_suggestions_put_the_type_presets_first_and_never_hide_others():
    firewall = suggestions("firewall")
    assert len(firewall) == len(PRESETS)
    suggested = [p.name for p, s in firewall if s]
    assert "arp-media" in suggested and "fdb-qbridge" not in suggested
    assert all(s for _p, s in suggestions(""))


def test_oid_input():
    assert parse_oid_input(".1.3.6.1.2.1.1.5.0") == (1, 3, 6, 1, 2, 1, 1, 5, 0)
    for bad in ("sysName", "1", "1.3.x", ""):
        with pytest.raises(ProbeInputError):
            parse_oid_input(bad)

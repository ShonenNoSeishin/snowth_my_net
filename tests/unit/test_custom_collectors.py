import pytest

from snowth_my_net.collect.custom import DeviceFacts, all_collectors, applies, convert, fills_for
from snowth_my_net.config.extensions import ValueSpec, load_extension_dir, parse_collector
from snowth_my_net.config.validate import ConfigError


def spec(**kw):
    return ValueSpec(oid="1.3.6.1.4.1.99999.1", **kw)


@pytest.mark.parametrize("value, kw, expected", [
    (b"2.4.1\x00", {"type": "text"}, "2.4.1"),
    (452, {"type": "integer", "scale": 0.1, "unit": "°C"}, "45.2 °C"),
    (3, {"type": "enum", "values": {"3": "delivering"}}, "delivering"),
    (4, {"type": "enum", "values": {"3": "delivering"}}, "4"),
    (8640123, {"type": "timeticks"}, "1d 00:00:01"),
    (bytes.fromhex("00005e005301"), {"type": "mac"}, "00:00:5e:00:53:01"),
    (bytes([192, 0, 2, 1]), {"type": "ip"}, "192.0.2.1"),
    (b"\xa0", {"type": "bits", "values": {"0": "a", "2": "c"}}, "a, c"),
    (b"\x01\x02", {"type": "hex"}, "01:02"),
    ((1, 3, 6), {"type": "oid"}, "1.3.6"),
    (b"hello", {}, "hello"),
])
def test_conversions(value, kw, expected):
    assert convert(value, spec(**kw))[0] == expected


def test_missing_objects_convert_to_nothing():
    assert convert(None, spec()) == (None, None)


def facts(**kw):
    base = {"address": "10.0.0.5", "vendor": "Fortinet", "device_type": "firewall",
            "object_id": "1.3.6.1.4.1.12356.101.1.644"}
    base.update(kw)
    return DeviceFacts(**base)


def collector(**kw):
    data = {"name": "c1", "get": {"v": "1.3.6.1.4.1.1.0"}}
    data.update(kw)
    return parse_collector(data)


def test_applies_to_combines_every_criterion():
    assert applies(collector(), facts())
    assert applies(collector(applies_to={"vendors": ["fortinet"]}), facts())
    assert not applies(collector(applies_to={"vendors": ["Cisco"]}), facts())
    both = collector(applies_to={"types": ["firewall"], "addresses": ["10.0.0.0/24"],
                                 "sys_object_ids": [".1.3.6.1.4.1.12356"]})
    assert applies(both, facts())
    assert not applies(both, facts(address="192.0.2.1"))
    assert not applies(collector(applies_to={"sys_object_ids": ["1.3.6.1.4.1.1235"]}), facts())


@pytest.mark.parametrize("data, message", [
    ({"name": "Bad Name", "get": {"v": "1.3.6.1"}}, "use lowercase"),
    ({"name": "c", "get": {"v": "sysName"}}, "is not a numeric OID"),
    ({"name": "c"}, "needs get: or walk:"),
    ({"name": "c", "get": {"v": "1.3.6"}, "walk": {"columns": {"x": "1.3.6"}}}, "not both"),
    ({"name": "c", "get": {"v": "1.3.6"}, "fills": {"os_version": "nope"}}, "not a get: value"),
    ({"name": "c", "get": {"v": {"oid": "1.3.6", "type": "enum"}}}, "needs values"),
    ({"name": "c", "get": {"v": "1.3.6"}, "fills": {"colour": "v"}}, "expected one of"),
])
def test_invalid_collectors(data, message):
    with pytest.raises(ConfigError) as exc:
        parse_collector(data)
    assert any(message in e for e in exc.value.errors), exc.value.errors


def test_fills_only_use_present_values():
    c = collector(fills={"os_version": "v", "model": "v"})
    assert fills_for(c, {"v": "7.2"}) == {"os_version": "7.2", "model": "7.2"}
    assert fills_for(c, {}) == {}


def test_extension_directory_loading(tmp_path):
    (tmp_path / "a.yml").write_text("collectors:\n  - {name: one, get: {v: 1.3.6.1.2.1.1.5.0}}\n")
    (tmp_path / "b.yaml").write_text("collectors:\n  - {name: two, walk: {columns: {x: 1.3.6}}}\n")
    loaded = load_extension_dir(tmp_path)
    assert [(c.cfg.name, c.cfg.kind) for c in loaded] == [("one", "get"), ("two", "walk")]
    (tmp_path / "c.yml").write_text("collectors:\n  - {name: one, get: {v: 1.3.6.1}}\n")
    with pytest.raises(ConfigError, match="more than once"):
        load_extension_dir(tmp_path)
    (tmp_path / "c.yml").write_text("collectors: [{name: x, get: {v: nope}}]\n")
    with pytest.raises(ConfigError) as exc:
        load_extension_dir(tmp_path)
    assert str(tmp_path / "c.yml") in exc.value.errors[0]
    assert load_extension_dir(tmp_path / "absent") == []


def test_stored_collectors_never_shadow_files(tmp_path):
    (tmp_path / "a.yml").write_text("collectors:\n  - {name: one, get: {v: 1.3.6.1.2.1.1.5.0}}\n")
    files = load_extension_dir(tmp_path)
    merged, warnings = all_collectors(files, {
        "one": {"name": "one", "get": {"v": "1.3.6.1"}},
        "two": {"name": "two", "get": {"v": "1.3.6.1"}},
        "bad": {"name": "bad"}})
    assert [(c.cfg.name, c.origin) for c in merged] == [("one", str(tmp_path / "a.yml")),
                                                        ("two", "tui")]
    assert len(warnings) == 2


def test_shipped_examples_are_valid():
    from pathlib import Path

    examples = Path(__file__).resolve().parents[2] / "examples" / "extensions"
    names = [c.cfg.name for c in load_extension_dir(examples)]
    assert names == ["ups-battery", "poe-ports", "fortigate-version"]
    from snowth_my_net.config.extensions import load_extensions

    reports = [r.cfg.name for r in load_extensions(examples)[1]]
    assert reports == ["untyped-devices", "stale-nodes", "crowded-access-ports",
                       "vendors-per-switch"]

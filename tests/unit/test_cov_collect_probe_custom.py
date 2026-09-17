"""OID tester (probe) and custom collectors against a fake client (no network)."""

from __future__ import annotations

import asyncio

import pytest

from snowth_my_net.api import Extension
from snowth_my_net.collect import custom, probe
from snowth_my_net.collect.custom import (
    ClientSnmp,
    CustomResult,
    DeviceFacts,
    ExtensionError,
    applies,
    convert,
    python_collector_cfg,
    run_collector,
    run_python_collector,
)
from snowth_my_net.collect.presets import Preset, _c, get_preset
from snowth_my_net.collect.probe import (
    ProbeInputError,
    ProbeTable,
    connect,
    format_value,
    parse_oid_input,
    run_oid,
    run_preset,
)
from snowth_my_net.config.extensions import AppliesTo, ValueSpec, parse_collector
from snowth_my_net.config.validate import build
from snowth_my_net.snmp import oids
from snowth_my_net.snmp.client import EnginePool, SnmpError, SnmpTimeout
from snowth_my_net.snmp.target import Target
from snowth_my_net.snmp.values import parse_oid
from tests.unit.test_cov_collect_engine import FakeClient, Lab, credential, loaded_config
from tests.unit.test_cov_collect_engine import system_values as sysvals

PRIVATE = "1.3.6.1.4.1.99999.9"


# --------------------------------------------------------------------------- values


def test_format_value_forms():
    enum = _c("s", "1.3", "enum", {1: "up"})
    caps = _c("c", "1.3", "caps")
    mac = _c("m", "1.3", "mac")
    assert format_value(None) == "∅ (no such object)"
    assert format_value((1, 3, 6)) == "1.3.6"
    assert format_value(True) == "True"
    assert format_value(1, enum) == "up(1)" and format_value(7, enum) == "7"
    assert format_value("192.0.2.1") == "192.0.2.1"
    assert format_value(b"\x28\x00", caps) == "bridge, router"
    assert format_value(b"\x00\x00", caps) == "0x0000"
    assert format_value(b"abcdef", mac) == "61:62:63:64:65:66"
    assert format_value(b"\x00\x11\x22\x33\x44\x55") == "00:11:22:33:44:55"
    assert format_value(b"") == '""'
    assert format_value(b"line1\r\nline2\x00") == "line1 ⏎ line2"
    assert format_value(b"\xff\xfe\x01") == "0xfffe01"
    assert format_value(b"a\x07b") == "0x610762"


def test_parse_oid_input():
    assert parse_oid_input(" .1.3.6.1 ") == (1, 3, 6, 1)
    for bad, message in (("sysName", "neither"), ("", "neither"), ("1", "too short")):
        with pytest.raises(ProbeInputError, match=message):
            parse_oid_input(bad)


# --------------------------------------------------------------------------- presets and OIDs


async def test_run_preset_walk_get_enterprise_and_errors():
    values = {oids.IF_DESCR + (1,): b"eth0", oids.IF_DESCR + (2,): b"eth1",
              oids.IF_NAME + (2,): b"e1", oids.IF_NAME + (3,): b"e3",
              oids.SYS_NAME: b"sw1", parse_oid("1.3.6.1.4.1.9.1.1"): 5}
    client = FakeClient(values)
    interfaces = Preset("if", "Interfaces", "Interfaces", (_c("ifDescr", oids.IF_DESCR),
                                                           _c("ifName", oids.IF_NAME)))
    table = await run_preset(client, interfaces, "en")
    assert table.rows == [["1", "eth0", ""], ["2", "eth1", "e1"], ["3", "", "e3"]]
    assert table.status == "ok" and table.requests == 2 and not table.truncated
    cut = await run_preset(client, interfaces, "fr", limit=1)
    assert cut.truncated and len(cut.rows) == 1
    empty = await run_preset(FakeClient({}), interfaces, "en")
    assert empty.status == "absent"

    system = get_preset("system")
    got = await run_preset(client, system, "fr")
    assert got.title == system.title_fr and ["sysName", "sw1", "1.3.6.1.2.1.1.5.0"] in got.rows
    assert (await run_preset(FakeClient({}), system, "en")).status == "absent"

    enterprise = get_preset("enterprise")
    none = await run_preset(client, enterprise, "en")
    assert none.status == "error" and "no sysObjectID" in none.detail
    tree = await run_preset(client, enterprise, "en", pen=9)
    assert tree.title.endswith("1.3.6.1.4.1.9") and tree.rows == [["1.3.6.1.4.1.9.1.1", "5"]]

    failing = FakeClient(values, fail={oids.IF_DESCR: SnmpTimeout("late")})
    timed_out = await run_preset(failing, interfaces, "en")
    assert (timed_out.status, timed_out.detail) == ("timeout", "late")
    broken = FakeClient(values, fail={oids.IF_DESCR: SnmpError("noAccess")})
    assert (await run_preset(broken, interfaces, "en")).status == "error"
    slow = FakeClient(values, delay={oids.IF_DESCR: 2})
    late = await run_preset(slow, interfaces, "en", timeout=0.05)
    assert late.status == "timeout" and "no complete answer" in late.detail
    assert ProbeTable("t", []).as_dict()["status"] == "ok"


async def test_run_oid_modes():
    scalar = oids.SYS_NAME
    client = FakeClient({scalar: b"sw1", oids.IF_DESCR + (1,): b"eth0",
                         oids.IF_DESCR + (2,): b"eth1"})
    assert (await run_oid(client, scalar)).rows == [["1.3.6.1.2.1.1.5.0", "sw1"]]
    walked = await run_oid(client, oids.IF_DESCR)
    assert [r[1] for r in walked.rows] == ["eth0", "eth1"]
    missing = await run_oid(client, oids.SYS_CONTACT, "get")
    assert missing.status == "absent" and missing.rows[0][1] == "∅ (no such object)"
    assert (await run_oid(client, oids.IF_DESCR, "walk", limit=1)).truncated
    assert (await run_oid(client, (1, 3, 6, 1, 99), "walk")).status == "absent"


async def test_connect_paths(tmp_path, monkeypatch):
    lab = Lab(monkeypatch, module=probe)
    lab.add("192.0.2.1", FakeClient(sysvals("sw1")))
    loaded = loaded_config(tmp_path)
    pool = EnginePool()
    conn = await connect(loaded, [credential()], Target("192.0.2.1"), pool)
    assert conn.ok and conn.credential == "lab" and conn.system.name == "sw1"
    assert conn.rtt_ms is not None
    silent = await connect(loaded, [credential()], Target("192.0.2.2"), pool)
    assert not silent.ok and silent.error == "no answer (lab: timeout)"
    scoped = await connect(loaded, [credential(scope=["198.51.100.0/24"])], Target("192.0.2.1"),
                           pool)
    assert scoped.error == "no credential in scope for this address"
    named = await connect(loaded, [credential()], Target("sw1.example.net"), pool)
    assert named.error == "'sw1.example.net' is not an IP address"


# --------------------------------------------------------------------------- custom collectors


def facts(**kw):
    base = {"address": "192.0.2.1", "vendor": "Acme", "device_type": "switch",
            "object_id": "1.3.6.1.4.1.99999.1.7"}
    return DeviceFacts(**(base | kw))


def test_applies_scopes():
    def collector(scope):
        return parse_collector({"name": "c", "applies_to": scope, "get": {"v": "1.3.6.1.1.0"}})

    assert applies(collector({}), facts())
    assert applies(collector({"vendors": ["ACME"], "types": ["switch"]}), facts())
    assert not applies(collector({"types": ["router"]}), facts())
    assert applies(collector({"addresses": ["192.0.2.0/24", "2001:db8::/32"]}), facts())
    assert not applies(collector({"addresses": ["192.0.2.0/24"]}), facts(address="not-ip"))
    assert applies(collector({"sys_object_ids": [".1.3.6.1.4.1.99999"]}), facts())
    assert not applies(collector({"sys_object_ids": ["1.3.6.1.4.1.9999"]}), facts())


@pytest.mark.parametrize(("value", "spec", "expected"), [
    (None, {"oid": "1.3"}, (None, None)),
    (3, {"oid": "1.3", "type": "enum", "values": {3: "delivering"}}, ("delivering", "3")),
    (9, {"oid": "1.3", "type": "enum", "values": {3: "x"}}, ("9", "9")),
    (8_640_123, {"oid": "1.3", "type": "timeticks"}, ("1d 00:00:01", "8640123")),
    (452, {"oid": "1.3", "type": "integer", "scale": 0.1, "unit": "°C"}, ("45.2 °C", "452")),
    (5, {"oid": "1.3", "type": "integer"}, ("5", "5")),
    (b"\x00\x00\x5e\x00\x53\x01", {"oid": "1.3", "type": "mac"},
     ("00:00:5e:00:53:01", "00005e005301")),
    (b"zz", {"oid": "1.3", "type": "mac"}, ("7a7a", "7a7a")),
    (b"\x01\xff", {"oid": "1.3", "type": "hex"}, ("01:ff", "01ff")),
    (b"\xc0\x00\x02\x01", {"oid": "1.3", "type": "ip"}, ("192.0.2.1", "c0000201")),
    ((1, 3, 6), {"oid": "1.3", "type": "oid"}, ("1.3.6", "1.3.6")),
    (b"\x28", {"oid": "1.3", "type": "lldp_caps"}, ("bridge, router", "28")),
    (b"\xa0", {"oid": "1.3", "type": "bits", "values": {0: "a", 2: "c"}}, ("a, c", "a0")),
    (b" name\x00", {"oid": "1.3", "type": "text"}, ("name", "206e616d6500")),
    (7, {"oid": "1.3", "unit": "W"}, ("7 W", "7")),
    ("text", {"oid": "1.3", "type": "hex"}, ("text", "text")),
])
def test_convert(value, spec, expected):
    assert convert(value, build(ValueSpec, spec)) == expected


async def test_run_collector_get_walk_and_truncation():
    client = FakeClient({parse_oid(f"{PRIVATE}.1.0"): b"v1",
                         parse_oid(f"{PRIVATE}.5.1"): 1, parse_oid(f"{PRIVATE}.5.2"): 2,
                         parse_oid(f"{PRIVATE}.5.3"): 3})
    scalar = parse_collector({"name": "s", "get": {"a": f"{PRIVATE}.1.0",
                                                   "b": f"{PRIVATE}.2.0"}})
    result = CustomResult()
    await run_collector(client, scalar, result)
    assert result.values() == {"a": "v1"} and result.rows == [("", "a", "v1", "7631")]
    table = parse_collector({"name": "t", "walk": {"columns": {"n": f"{PRIVATE}.5"}},
                             "limit": 2})
    result = CustomResult()
    await run_collector(client, table, result)
    assert [r[:3] for r in result.rows] == [("1", "n", "1"), ("2", "n", "2")]
    assert result.truncated and result.values() == {}


def python_cfg(ext: Extension, name: str):
    declared = next(c for c in ext.collectors if c.name == name)
    return python_collector_cfg(declared, build(AppliesTo, declared.applies_to), 0, ext.name)


async def test_python_collectors_through_the_client():
    ext = Extension("demo")

    @ext.collector("scalar", columns=["name", "oid", "ratio", "missing"])
    async def scalar(device, snmp):
        got = await snmp.get("1.3.6.1.2.1.1.5.0", "1.3.6.1.2.1.1.2.0")
        rows = await snmp.walk("1.3.6.1.2.1.2.2.1.2", limit=1)
        return {"name": got["1.3.6.1.2.1.1.5.0"], "oid": got["1.3.6.1.2.1.1.2.0"],
                "ratio": len(rows) / 4, "missing": None, "ignored": device.address}

    @ext.collector("table", columns=["v"], table=True, limit=2)
    async def table(device, snmp):
        return [{"v": b"a"}, {"index": "9", "v": 2}, {"v": 3}]

    @ext.collector("nothing", columns=["v"])
    async def nothing(device, snmp):
        return None

    @ext.collector("wrong", columns=["v"])
    async def wrong(device, snmp):
        return ["not", "a", "dict"]

    @ext.collector("timeout", columns=["v"])
    async def timeout(device, snmp):
        raise SnmpTimeout("device slow")

    client = FakeClient({**sysvals("sw9", object_id="1.3.6.1.4.1.9.1.5"),
                         oids.IF_DESCR + (1,): b"eth0", oids.IF_DESCR + (2,): b"eth1"})
    client.target = Target("192.0.2.9")
    result = CustomResult()
    await run_collector(client, python_cfg(ext, "scalar"), result)
    assert result.values() == {"name": "sw9", "oid": "1.3.6.1.4.1.9.1.5", "ratio": "0.25"}

    result = CustomResult()
    await run_collector(client, python_cfg(ext, "table"), result, facts())
    assert [r[:3] for r in result.rows] == [("0", "v", "a"), ("9", "v", "2")]
    assert result.truncated

    result = CustomResult()
    await run_python_collector(client, python_cfg(ext, "nothing"), result, None)
    assert result.rows == []
    with pytest.raises(ExtensionError, match="returns a dict of its columns"):
        await run_python_collector(client, python_cfg(ext, "wrong"), CustomResult(), None)
    with pytest.raises(SnmpTimeout):
        await run_python_collector(client, python_cfg(ext, "timeout"), CustomResult(), None)

    snmp = ClientSnmp(client, limit=1)
    assert await snmp.walk("1.3.6.1.2.1.2.2.1.2") == [("1", b"eth0")]
    assert custom._cell(1.0) == "1" and custom._cell(b"\x00\x11\x22\x33\x44\x55") == \
        "00:11:22:33:44:55"


async def test_python_collector_cancellation_is_not_wrapped():
    ext = Extension("demo")

    @ext.collector("cancel", columns=["v"])
    async def cancel(device, snmp):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_python_collector(FakeClient(), python_cfg(ext, "cancel"), CustomResult(),
                                   facts())


def test_all_collectors_merges_and_reports_problems():
    from snowth_my_net.config.extensions import LoadedCollector

    file = LoadedCollector(parse_collector({"name": "one", "get": {"v": "1.3.6.1.1.0"}}), "f.yml")
    merged, warnings = custom.all_collectors([file], {
        "one": {"name": "one", "get": {"v": "1.3.6.1.2.0"}},
        "two": {"name": "two", "get": {"v": "1.3.6.1.2.0"}},
        "bad": {"name": "bad"}})
    assert [(c.cfg.name, c.origin) for c in merged] == [("one", "f.yml"), ("two", "tui")]
    assert warnings[0] == "collector 'bad' from the state is invalid: " + warnings[0].split(
        "invalid: ", 1)[1]
    assert warnings[1] == "collector 'one' from the state is shadowed by an extension file"


async def test_python_collector_errors_specs_and_fills():
    ext = Extension("demo")

    @ext.collector("boom", columns=["v"])
    async def boom(device, snmp):
        raise KeyError("nope")

    @ext.collector("not-rows", columns=["v"], table=True)
    async def not_rows(device, snmp):
        return {"v": 1}

    @ext.collector("sparse", columns=["a", "b"], table=True)
    async def sparse(device, snmp):
        return [{"index": "1", "a": None, "b": "x"}]

    @ext.collector("filled", columns=["fw"], fills={"os_version": "fw"})
    async def filled(device, snmp):
        return {"fw": "1.0"}

    with pytest.raises(ExtensionError, match=r"demo\.boom raised KeyError"):
        await run_python_collector(FakeClient(), python_cfg(ext, "boom"), CustomResult(), None)
    with pytest.raises(ExtensionError, match="list of dicts"):
        await run_python_collector(FakeClient(), python_cfg(ext, "not-rows"), CustomResult(),
                                   None)
    result = CustomResult()
    await run_python_collector(FakeClient(), python_cfg(ext, "sparse"), result, None)
    assert result.rows == [("1", "b", "x", None)] and not result.truncated
    cfg = python_cfg(ext, "filled")
    assert cfg.kind == "python" and set(cfg.value_specs()) == {"fw"}
    assert python_cfg(ext, "sparse").walk.index == "raw"
    result = CustomResult()
    await run_python_collector(FakeClient(), cfg, result, None)
    assert custom.fills_for(cfg, result.values()) == {"os_version": "1.0"}
    assert custom.fills_for(cfg, {"fw": ""}) == {}

    snmp = ClientSnmp(FakeClient({(1, 3, 6, 1, 5): 1}), limit=5)
    assert await snmp.walk("1.3.6.1") == [("5", 1)]


async def test_walk_collector_columns_end_naturally():
    client = FakeClient({parse_oid(f"{PRIVATE}.5.1"): 1, parse_oid(f"{PRIVATE}.6.1"): 2})
    table = parse_collector({"name": "t", "walk": {"columns": {"n": f"{PRIVATE}.5",
                                                               "m": f"{PRIVATE}.6"}}})
    result = CustomResult()
    await run_collector(client, table, result)
    assert [r[:3] for r in result.rows] == [("1", "n", "1"), ("1", "m", "2")]
    assert not result.truncated

"""Python extensions: API validation, loading, the test harness and the shipped example."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from snowth_my_net import testing
from snowth_my_net.api import Extension, ExtensionDefinitionError, Field, ip, mac, number, text
from snowth_my_net.config.python_ext import load_python_extensions
from snowth_my_net.config.validate import ConfigError

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "extensions" / "host_storage.py"
ST = "1.3.6.1.2.1.25.2.3.1"


def test_value_helpers():
    assert text(b"abc\x00\x00 ") == "abc" and text(None) == "" and text(7) == "7"
    assert number(b"42") == 42 and number(b"x") is None and number(3) == 3
    assert mac(b"\x00\x00\x5e\x00\x53\x01") == "00:00:5e:00:53:01"
    assert ip(b"\xc0\x00\x02\x01") == "192.0.2.1" and ip("nope") is None


def test_declarations_are_validated():
    ext = Extension("demo")
    with pytest.raises(ExtensionDefinitionError, match="lowercase"):
        Extension("Demo Ext")
    with pytest.raises(ExtensionDefinitionError, match="'index' is reserved"):
        ext.collector("x", columns=["index"])
    with pytest.raises(ExtensionDefinitionError, match="fills use unknown columns"):
        ext.collector("x", columns=["a"], fills={"os_version": "b"})
    with pytest.raises(ExtensionDefinitionError, match="scalar collector"):
        ext.collector("x", columns=["a"], table=True, fills={"os_version": "a"})
    with pytest.raises(ExtensionDefinitionError, match="Field"):
        ext.report_dataset("d", fields=["name"])
    with pytest.raises(ExtensionDefinitionError, match="relative path"):
        ext.exporter("../x.txt")


def write(directory: Path, name: str, body: str) -> None:
    (directory / f"{name}.py").write_text(textwrap.dedent(body))


def test_loading_by_name_only_and_errors(tmp_path):
    write(tmp_path, "good", """
        from snowth_my_net.api import Extension, Field
        extension = Extension("good")

        @extension.collector("good-one", columns=["v"], applies_to={"vendors": ["Acme"]},
                             every="2h")
        async def one(device, snmp):
            return {"v": 1}

        @extension.report_dataset("things", fields=[Field("name")])
        def things(ctx):
            return [{"name": "a"}]
    """)
    write(tmp_path, "unused", "raise RuntimeError('must never be imported')\n")
    write(tmp_path, "broken", "import nothing_here\n")
    write(tmp_path, "empty", "x = 1\n")
    write(tmp_path, "clash", """
        from snowth_my_net.api import Extension
        extension = Extension("clash")

        @extension.collector("yaml-one", columns=["v"])
        async def one(device, snmp):
            return {}

        @extension.collector("bad-scope", columns=["v"], applies_to={"typos": ["x"]})
        async def two(device, snmp):
            return {}
    """)
    parts = load_python_extensions(["good"], tmp_path, set())
    assert [(c.cfg.name, c.cfg.kind, c.origin, c.cfg.every) for c in parts.collectors] == [
        ("good-one", "python", "python:good", 7200)]
    assert [d.name for d in parts.datasets] == ["py:things"]
    with pytest.raises(ConfigError) as caught:
        load_python_extensions(["broken", "empty", "missing", "clash"], tmp_path, {"yaml-one"})
    errors = "\n".join(caught.value.errors)
    assert "'broken': import failed: ModuleNotFoundError" in errors
    assert "'empty'" in errors and "extension = Extension(...)" in errors
    assert "'missing': not found" in errors
    assert "collector name 'yaml-one' is already used" in errors
    assert "collector 'bad-scope'" in errors and "typos" in errors


def test_example_extension_with_the_harness():
    ext = testing.load(EXAMPLE)
    snmp = testing.FakeSnmp({
        f"{ST}.2.1": "1.3.6.1.2.1.25.2.1.2", f"{ST}.3.1": b"Physical memory",
        f"{ST}.4.1": 1024, f"{ST}.5.1": 8_000_000, f"{ST}.6.1": 3_000_000,
        f"{ST}.2.31": "1.3.6.1.2.1.25.2.1.4", f"{ST}.3.31": b"/", f"{ST}.4.31": 4096,
        f"{ST}.5.31": 5_000_000, f"{ST}.6.31": 4_500_000,
        f"{ST}.2.40": "1.3.6.1.2.1.25.2.1.7", f"{ST}.3.40": b"/media/cdrom",   # skipped
        f"{ST}.4.40": 2048, f"{ST}.5.40": 0, f"{ST}.6.40": 0,
    })
    rows = testing.run_collector(ext, "host-storage", snmp, name="backup01")
    assert rows == [
        {"index": "1", "kind": "ram", "description": "Physical memory", "size_gb": "8.2",
         "used_gb": "3.1", "used_pct": "38"},
        {"index": "31", "kind": "disk", "description": "/", "size_gb": "20.5",
         "used_gb": "18.4", "used_pct": "90"}]
    usage = testing.run_dataset(ext, "disk-usage", {"custom:host-storage": [
        {"device": "backup01", "kind": "disk", "description": "/", "size_gb": "20.5",
         "used_pct": "90", "collected": 1}]})
    assert usage == [{"device": "backup01", "kind": "disk", "description": "/", "size_gb": 20,
                      "used_pct": 90, "collected": 1}]
    prom = testing.export(ext, "metrics/snowth_my_net.prom", {
        "devices": [{"name": 'sw "1"', "last_collect_status": "ok"}], "nodes": [{}, {}]})
    assert b'snowth_device_ok{device="sw \\"1\\""} 1' in prom and b"snowth_nodes 2" in prom


def test_collector_errors_are_contained():
    from snowth_my_net.collect.custom import ExtensionError

    ext = Extension("bad")

    @ext.collector("boom", columns=["v"])
    async def boom(device, snmp):
        raise ZeroDivisionError("oops")

    @ext.collector("wrong", columns=["v"], table=True)
    async def wrong(device, snmp):
        return {"v": 1}

    with pytest.raises(ExtensionError, match=r"bad\.boom raised ZeroDivisionError: oops"):
        testing.run_collector(ext, "boom")
    with pytest.raises(ExtensionError, match="returns a list of dicts"):
        testing.run_collector(ext, "wrong")


def test_dataset_field_names_come_from_the_api():
    assert Field("x", "integer").type == "integer"

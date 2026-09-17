"""Public extension API, test harness and Python extension loading: edge cases."""

from __future__ import annotations

import textwrap
from types import SimpleNamespace

import pytest

from snowth_my_net import testing
from snowth_my_net.api import (
    Extension,
    ExtensionDefinitionError,
    Field,
    Observations,
    Station,
    ip,
    number,
)
from snowth_my_net.config import python_ext
from snowth_my_net.config.python_ext import _short_error, load_python_extensions
from snowth_my_net.config.validate import ConfigError


def test_value_helpers_edge_cases():
    assert number(True) is None and number(None) is None
    assert ip(b"\x20\x01\x0d\xb8" + b"\x00" * 11 + b"\x01") == "2001:db8::1"
    assert ip("192.0.2.1") == "192.0.2.1" and ip(7) is None and ip(b"\x01\x02") is None


def test_every_declaration_error():
    ext = Extension("demo")
    cases = [
        (lambda: ext.driver("Bad Name", object_ids=["1.3.6"]), "driver name"),
        (lambda: ext.collector("Bad Name", columns=["a"]), "collector name"),
        (lambda: ext.collector("x", columns=[]), "columns must be non-empty"),
        (lambda: ext.collector("x", columns=["a"], index="ifindex"), "index is 'raw' or 'port'"),
        (lambda: ext.collector("x", columns=["a"], mode="off"), "mode is 'auto' or 'force'"),
        (lambda: ext.report_dataset("Bad Name", fields=[Field("a")]), "dataset name"),
        (lambda: ext.report_dataset("d", fields=[]), "Field"),
        (lambda: ext.exporter(""), "relative path"),
        (lambda: ext.exporter("a\\b"), "relative path"),
        (lambda: ext.exporter(".hidden"), "relative path"),
        (lambda: ext.exporter("a/../b"), "relative path"),
    ]
    for make, message in cases:
        with pytest.raises(ExtensionDefinitionError, match=message):
            make()


def test_collector_description_defaults_to_the_docstring():
    ext = Extension("demo")

    @ext.collector("doc", columns=["a"])
    async def documented(device, snmp):
        """First line.

        More text."""

    @ext.collector("nodoc", columns=["a"], description="given")
    async def undocumented(device, snmp):
        return None

    assert [c.description for c in ext.collectors] == ["First line.", "given"]
    assert testing.run_collector(ext, "nodoc") == {}


def test_harness_errors_and_defaults(tmp_path):
    ext = Extension("demo")
    for call in (lambda: testing.run_collector(ext, "x"), lambda: testing.run_dataset(ext, "x"),
                 lambda: testing.run_driver(ext, "x"), lambda: testing.export(ext, "x", {})):
        with pytest.raises(KeyError, match="no "):
            call()
    (tmp_path / "plain.py").write_text("x = 1\n")
    with pytest.raises(TypeError, match="must define 'extension"):
        testing.load(tmp_path / "plain.py")

    @ext.report_dataset("reads", fields=[Field("n", "integer")])
    def reads(ctx):
        return [{"n": len(ctx.dataset_rows("devices")), "now": ctx.now}]

    assert testing.run_dataset(ext, "reads", {"devices": [{}, {}]}, now=5) == [{"n": 2, "now": 5}]
    with pytest.raises(KeyError, match="not provided"):
        testing.run_dataset(ext, "reads")

    @ext.exporter("text.txt")
    def as_text(snapshot):
        return "hello"

    assert testing.export(ext, "text.txt", {}) == b"hello"

    only_obs = ext.driver("obs", object_ids=["1.3.6.1.4.1.1"])

    @only_obs.observations
    async def observations(device, snmp):
        return Observations(stations=[Station("00:00:5e:00:53:01", 1)])

    identity, observed = testing.run_driver(ext, "obs", name="dev")
    assert identity == {} and observed.stations[0].port == 1

    only_id = ext.driver("ident", object_ids=["1.3.6.1.4.1.1"])

    @only_id.identity
    async def identity_func(device, snmp):
        return {"model": device.name}

    assert testing.run_driver(ext, "ident", view=testing.device("192.0.2.9", name="m")) == (
        {"model": "m"}, None)


def test_fake_snmp_walk_and_limits():
    snmp = testing.FakeSnmp({"1.3.6.1.4.1.9.1.1": 1, "1.3.6.1.4.1.9.1.2": 2,
                             "1.3.6.1.4.1.9.2.1": 3, "1.3.6.1.4.1.9": 0})
    import asyncio

    assert asyncio.run(snmp.walk("1.3.6.1.4.1.9.1")) == [("1", 1), ("2", 2)]
    assert asyncio.run(snmp.walk(".1.3.6.1.4.1.9", limit=1)) == [("1.1", 1)]
    assert asyncio.run(snmp.get("1.3.6.1.4.1.9.9")) == {"1.3.6.1.4.1.9.9": None}
    assert snmp.requests[0] == ("walk", "1.3.6.1.4.1.9.1")


def _write(directory, name, body):
    (directory / f"{name}.py").write_text(textwrap.dedent(body))


def test_python_extension_loading_errors(tmp_path, monkeypatch):
    _write(tmp_path, "old", """
        from snowth_my_net.api import Extension
        extension = Extension("old", api_version=0)
    """)
    _write(tmp_path, "twice", """
        from snowth_my_net.api import Extension, Field
        extension = Extension("twice")

        @extension.report_dataset("same", fields=[Field("a")])
        def one(ctx):
            return "not a list"

        @extension.report_dataset("same", fields=[Field("a")])
        def two(ctx):
            return []

        @extension.exporter("out.txt")
        def e1(snapshot):
            return b""

        @extension.exporter("out.txt")
        def e2(snapshot):
            return b""

        @extension.collector("col", columns=["a"], every="sometimes")
        async def c(device, snmp):
            return {}

        drv = extension.driver("dup", object_ids=["1.3.6.1.4.1.1"])
        drv2 = extension.driver("dup", object_ids=["1.3.6.1.4.1.1"])

        @drv.identity
        async def i1(device, snmp):
            return {}

        @drv2.identity
        async def i2(device, snmp):
            return {}
    """)
    with pytest.raises(ConfigError) as caught:
        load_python_extensions(["old", "twice"], tmp_path, set())
    text = "\n".join(caught.value.errors)
    for expected in ("written for API 0", "dataset 'py:same' is already used",
                     "file 'out.txt' is already written", "collector 'col': expected a duration",
                     "driver name 'dup' is already used"):
        assert expected in text, expected
    assert "'twice'" in text

    _write(tmp_path, "badrows", """
        from snowth_my_net.api import Extension, Field
        extension = Extension("badrows")

        @extension.report_dataset("rows", fields=[Field("a")])
        def rows(ctx):
            return "not a list"
    """)
    parts = load_python_extensions(["badrows"], tmp_path, set())
    with pytest.raises(TypeError, match="list of dicts"):
        parts.datasets[0].build(None)


def test_entry_points_and_missing_directory(monkeypatch, tmp_path):
    ext = Extension("from-ep")
    entry = SimpleNamespace(name="from-ep", value="pkg.mod:extension", load=lambda: ext)
    monkeypatch.setattr(python_ext.importlib.metadata, "entry_points",
                        lambda group: [SimpleNamespace(name="other"), entry])
    parts = load_python_extensions(["from-ep"], None, set())
    assert parts.extensions[0].origin == "entry point pkg.mod:extension"
    with pytest.raises(ConfigError, match=r"no the extensions directory|not found"):
        load_python_extensions(["absent"], None, set())


def test_import_file_failures(tmp_path, monkeypatch):
    import sys

    (tmp_path / "raises.py").write_text("raise RuntimeError('at import')\n")
    with pytest.raises(RuntimeError):
        python_ext._import_file("raises", tmp_path / "raises.py")
    assert "snowth_my_net_ext_raises" not in sys.modules
    monkeypatch.setattr(python_ext.importlib.util, "spec_from_file_location", lambda *a: None)
    with pytest.raises(ImportError, match="cannot load"):
        python_ext._import_file("x", tmp_path / "raises.py")
    assert _short_error(ValueError("plain")) == "ValueError: plain"

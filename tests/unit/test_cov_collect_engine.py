"""Collection engine with fake SNMP agents: outcomes, identity de-duplication, sweep, BFS,
time budgets, internal errors, custom collectors and fills (no network)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from snowth_my_net.clock import FrozenClock
from snowth_my_net.collect import engine
from snowth_my_net.collect.engine import (
    Collector,
    IdentityRegistry,
    driver_identity,
    final_owner,
    preference,
    run_function,
    same_device,
)
from snowth_my_net.collect.functions import Rows
from snowth_my_net.collect.model import DeviceResult, Identification, Outcome
from snowth_my_net.collect.tables.system import SystemInfo
from snowth_my_net.config.effective import settings_for
from snowth_my_net.config.extensions import LoadedCollector, parse_collector
from snowth_my_net.config.loader import LoadedConfig, Paths, ResolvedCredential, parse_config_text
from snowth_my_net.config.schema import CredentialCfg
from snowth_my_net.config.secrets import Secret
from snowth_my_net.config.validate import build
from snowth_my_net.drivers.base import Driver
from snowth_my_net.snmp import oids
from snowth_my_net.snmp.client import SnmpError, SnmpTimeout
from snowth_my_net.snmp.credentials import ProbeResult
from snowth_my_net.snmp.target import Target
from snowth_my_net.snmp.values import has_prefix, parse_oid
from snowth_my_net.state.db import open_db
from snowth_my_net.state.repo import Repo

NOW = 1_800_000_000


# --------------------------------------------------------------------------- fakes


class FakeClient:
    """A device served from a dict ``{oid tuple: value}``; ``fail`` maps an OID prefix to an
    exception raised when walking it, ``delay`` to seconds to wait first."""

    def __init__(self, values=None, fail=None, delay=None, after_rows=None):
        self.values = dict(sorted((values or {}).items()))
        self.fail = fail or {}
        self.delay = delay or {}
        self.after_rows = after_rows or {}
        self.requests = 0

    def for_vlan(self, vlan):
        return self

    async def get(self, requested):
        self.requests += 1
        for prefix, exc in self.fail.items():
            if any(has_prefix(o, prefix) for o in requested):
                raise exc
        return {o: self.values.get(o) for o in requested}

    async def walk(self, base):
        self.requests += 1
        for prefix, seconds in self.delay.items():
            if has_prefix(base, prefix):
                await asyncio.sleep(seconds)
        sent = 0
        for oid, value in self.values.items():
            if has_prefix(oid, base):
                if base in self.after_rows and sent >= self.after_rows[base][0]:
                    raise self.after_rows[base][1]
                sent += 1
                yield oid, value
        for prefix, exc in self.fail.items():
            if has_prefix(base, prefix):
                raise exc


def system_values(name, object_id="1.3.6.1.4.1.99999.1", mac=None, uptime=100, descr="box"):
    values = {oids.SYS_DESCR: descr.encode(), oids.SYS_OBJECT_ID: parse_oid(object_id),
              oids.SYS_UPTIME: uptime, oids.SYS_NAME: name.encode(), oids.SYS_LOCATION: b""}
    if mac:
        values[oids.DOT1D_BASE_BRIDGE_ADDRESS] = bytes.fromhex(mac.replace(":", ""))
    return values


def credential(name="lab", scope=None):
    cfg = build(CredentialCfg, {"name": name, "version": "2c", "community_file": "x",
                                **({"scope": scope} if scope else {})})
    return ResolvedCredential(cfg, community=Secret("engine-test-community", "test"))


def loaded_config(tmp_path: Path, text: str = "") -> LoadedConfig:
    cfg = parse_config_text("discovery:\n  allowed: [192.0.2.0/24]\n" + text)
    paths = Paths(tmp_path / "c.yml", tmp_path / "state", tmp_path / "out", tmp_path / "s",
                  tmp_path / "ext")
    return LoadedConfig(cfg, paths)


class Lab:
    """Patches probe/SnmpClient of the engine to serve FakeClients by host."""

    def __init__(self, monkeypatch, module=engine):
        self.devices: dict[str, FakeClient] = {}
        self.probe_delay: dict[str, float] = {}
        monkeypatch.setattr(module, "probe", self.probe)
        monkeypatch.setattr(module, "SnmpClient", self.client)

    def add(self, host, client):
        self.devices[host] = client
        return client

    async def probe(self, pool, target, candidates, params, timeout, requested):
        await asyncio.sleep(self.probe_delay.get(target.host, 0))
        result = ProbeResult()
        device = self.devices.get(target.host)
        for cred in candidates:
            if device is None:
                result.attempts.append((cred.name, "timeout"))
                continue
            result.attempts.append((cred.name, "ok"))
            result.credential = cred
            result.values = await device.get(list(requested))
            return result
        return result

    def client(self, engine_, cred, target, params):
        return self.devices[target.host]


@pytest.fixture
def lab(monkeypatch):
    return Lab(monkeypatch)


def result_for(host="192.0.2.1", cfg_text="", manual=None, **fields):
    cfg = parse_config_text(cfg_text)
    return DeviceResult(Target(host), "seed", 0, settings_for(cfg, host, manual), **fields)


# --------------------------------------------------------------------------- run_function


async def test_run_function_statuses():
    loop = asyncio.get_running_loop()
    r = result_for(cfg_text="devices:\n  - {address: 192.0.2.1, features: {arp: off, lldp: force}}")
    far = loop.time() + 60

    async def rows_then(exc, count=1):
        async def func(client, r, rows):
            for i in range(count):
                rows.column("x")[(i,)] = i
            if exc:
                raise exc
        return func

    await run_function(r, "arp", None, far, await rows_then(None))
    await run_function(r, "fdb", None, loop.time() - 1, await rows_then(None))
    await run_function(r, "ipaddr", None, far, await rows_then(SnmpTimeout("slow")))
    await run_function(r, "lldp", None, far, await rows_then(None, count=0))
    await run_function(r, "cdp", None, far, await rows_then(SnmpError("boom"), count=0))
    await run_function(r, "interfaces", None, far, await rows_then(None, count=0))

    async def hangs(client, r, rows):
        rows.column("x")[(1,)] = 1
        await asyncio.sleep(5)

    await run_function(r, "entity", None, loop.time() + 0.05, hangs)
    got = {name: (o.status, o.rows, o.detail) for name, o in r.outcomes.items()}
    assert got["arp"] == ("skipped", 0, "off in configuration")
    assert got["fdb"] == ("timeout", 0, "device_timeout exhausted")
    assert got["ipaddr"] == ("partial", 1, "slow")
    assert got["lldp"] == ("forced_absent", 0, "no data although the function is forced")
    assert got["cdp"] == ("error", 0, "boom")
    assert got["interfaces"][0] == "absent"
    assert got["entity"][0] == "partial" and "no complete answer" in got["entity"][2]
    r.system = SystemInfo()
    assert r.status == "partial"


# --------------------------------------------------------------------------- identity


def test_same_device_rules_and_preferences():
    a = result_for(system=SystemInfo(name="sw", object_id="1.3.6.1.4.1.9", uptime=100))
    b = result_for("192.0.2.2", system=SystemInfo(name="sw", object_id="1.3.6.1.4.1.9",
                                                  uptime=5000))
    assert same_device(a, b)                                     # sysName + uptime within 60 s
    b.system.uptime = 9000
    assert not same_device(a, b)
    b.system.uptime = None
    assert not same_device(a, b)
    assert not same_device(a, result_for("192.0.2.3"))          # no system
    a.device_id = b.device_id = 7
    assert same_device(a, b)
    c = result_for(ident=Identification(serial="S1", pen=9))
    d = result_for("192.0.2.4", ident=Identification(serial="S1", pen=9))
    assert same_device(c, d)
    e = result_for(system=SystemInfo(bridge_mac="00:00:5e:00:53:01"))
    f = result_for("192.0.2.5", system=SystemInfo(bridge_mac="00:00:5e:00:53:01"))
    assert same_device(e, f)

    vip = result_for("192.0.2.9", "devices:\n  - {address: 192.0.2.9, ha_mode: vip}")
    member = result_for("192.0.2.8")
    members = result_for("192.0.2.7", "devices:\n  - {address: 192.0.2.7, ha_mode: members}")
    assert preference(vip) < preference(member) < preference(members)


def test_registry_supersedes_and_keeps_the_device_id():
    registry = IdentityRegistry()
    mac = "00:00:5e:00:53:01"
    first = result_for("192.0.2.20", system=SystemInfo(bridge_mac=mac), device_id=12)
    assert registry.claim(first) is first
    better = result_for("192.0.2.10", system=SystemInfo(bridge_mac=mac), is_current_mgmt=True)
    assert registry.claim(better) is better
    assert first.superseded and first.alias_of is better and better.device_id == 12
    worse = result_for("192.0.2.30", system=SystemInfo(bridge_mac=mac))
    assert registry.claim(worse) is better and final_owner(worse) is better
    other = result_for("192.0.2.40", system=SystemInfo(bridge_mac="00:00:5e:00:53:02"))
    assert registry.claim(other) is other


async def test_driver_identity_function_fills_and_types():
    class ModelDriver(Driver):
        name = "model-only"

        async def identify(self, client, r):
            return {"model": "EX4300-48T", "serial": ""}

    class Silent(Driver):
        name = "silent"

    r = result_for(system=SystemInfo(descr="Juniper Networks", object_id="1.3.6.1.4.1.2636.1"),
                   ident=Identification(vendor="Juniper"))
    rows = Rows()
    await driver_identity(ModelDriver())(None, r, rows)
    assert r.ident.model == "EX4300-48T"
    assert rows.column("values") == {(0,): "model"}
    assert r.ident.device_type == "switch" and r.ident.type_rule == "catalog"

    r2 = result_for(system=SystemInfo(), ident=Identification(device_type="router"))
    rows2 = Rows()
    await driver_identity(Silent())(None, r2, rows2)
    assert rows2.column("values") == {(0,): "silent"} and r2.ident.device_type == "router"


# --------------------------------------------------------------------------- whole runs


def make_collector(tmp_path, text="", repo=True, mode="collect", collectors=(), clock=None):
    loaded = loaded_config(tmp_path, text)
    loaded.collectors = list(collectors)
    state = Repo(open_db(tmp_path / "state.sqlite")) if repo else None
    return Collector(loaded, state, [credential()], clock or FrozenClock(NOW), mode), state


async def test_aliases_failures_and_statistics(tmp_path, lab):
    mac = "00:00:5e:00:53:01"
    lab.add("192.0.2.1", FakeClient(system_values("core", mac=mac)))
    lab.add("192.0.2.2", FakeClient(system_values("core", mac=mac)))
    collector, repo = make_collector(tmp_path, """  seeds: [192.0.2.1, 192.0.2.2, 192.0.2.3]
devices:
  - {address: 192.0.2.3, tolerate_failure: true}
""")
    report = await collector.run()
    assert report.status == "ok"
    assert report.stats | {"duration_s": 0} == {
        "purged": report.stats["purged"], "targets": 3, "devices": 2, "reachable": 1,
        "failing": 0, "aliases": 1, "duration_s": 0}
    failed = next(r for r in report.results if r.target.host == "192.0.2.3")
    assert failed.error == "no answer (lab: timeout)"
    alias = repo.conn.execute("SELECT address, is_alias FROM targets WHERE address = ?",
                              ("192.0.2.2",)).fetchone()
    assert alias["is_alias"] == 1
    assert repo.conn.execute("SELECT status FROM runs").fetchone()[0] == "ok"


async def test_nothing_to_poll_and_all_failed(tmp_path, lab):
    collector, _ = make_collector(tmp_path, repo=False)
    report = await collector.run()
    assert report.status == "failed" and report.run_id is None
    assert report.errors == ["nothing to poll: no seed and no known device in scope"]

    collector, _ = make_collector(tmp_path / "x", "  seeds: [192.0.2.1]\n", repo=False)
    (tmp_path / "x").mkdir(exist_ok=True)
    report = await collector.run(only={"192.0.2.1"})
    assert report.status == "failed" and report.stats["only"] == ["192.0.2.1"]


async def test_no_credential_in_scope_run_timeout_and_internal_errors(tmp_path, lab,
                                                                      monkeypatch):
    lab.add("192.0.2.1", FakeClient(system_values("a")))
    lab.add("192.0.2.2", FakeClient(system_values("b")))
    collector, _ = make_collector(tmp_path, "  seeds: [192.0.2.1, 192.0.2.2, 192.0.2.4]\n",
                                  repo=False)
    collector.credentials = [credential(scope=["192.0.2.0/30"])]

    async def explode(client, r, rows):
        raise RuntimeError("bug in a parser")

    monkeypatch.setattr(engine.functions, "interfaces", explode)
    original_guarded = engine.identify.identify

    def identify_or_crash(system, *args, **kwargs):
        if system.name == "b":
            raise ValueError("crash before reachable")
        return original_guarded(system, *args, **kwargs)

    monkeypatch.setattr(engine.identify, "identify", identify_or_crash)
    report = await collector.run()
    by_host = {r.target.host: r for r in report.results}
    assert by_host["192.0.2.4"].error == "no credential in scope for this address"
    assert by_host["192.0.2.1"].outcomes["internal"].detail == "RuntimeError('bug in a parser')"
    # b has a system (reachable) when it crashes, so the error is an outcome too
    assert by_host["192.0.2.2"].outcomes["internal"].status == "error"
    assert report.status == "partial"

    unreachable = result_for("192.0.2.5")

    async def crash_device(r, planned, deadline):
        raise KeyError("before probe")

    monkeypatch.setattr(collector, "_collect_device", crash_device)
    collector._run_deadline = asyncio.get_running_loop().time() + 100
    r = await collector._guarded(engine.PlannedTarget(Target("192.0.2.5"), "seed"),
                                 asyncio.Semaphore(1))
    assert r.error == "internal error: KeyError('before probe')" and not unreachable.reachable
    collector._run_deadline = asyncio.get_running_loop().time()
    r = await collector._guarded(engine.PlannedTarget(Target("192.0.2.5"), "seed"),
                                 asyncio.Semaphore(1))
    assert r.error == "run_timeout reached before this device could be polled"


async def test_sweep_is_scheduled_and_finds_devices(tmp_path, lab):
    lab.add("192.0.2.2", FakeClient(system_values("found-by-sweep")))
    text = """  sweep: [192.0.2.0/30]
  sweep_rate: 1000
  sweep_interval: 3600
"""
    clock = FrozenClock(NOW)
    collector, repo = make_collector(tmp_path, text, clock=clock)
    report = await collector.run()
    assert [r.target.host for r in report.results] == ["192.0.2.2"]
    assert repo.get_meta("last_sweep") == str(NOW)
    assert repo.conn.execute("SELECT origin FROM targets WHERE address = '192.0.2.2'"
                             ).fetchone()[0] == "sweep"
    assert collector._sweep_due(NOW + 60) is False
    assert collector._sweep_due(NOW + 3600) is True
    discover, _ = make_collector(tmp_path / "d", text, repo=False, mode="discover")
    assert discover._sweep_due(NOW) is True
    dry = await discover.run()
    assert [r.target.host for r in dry.results] == ["192.0.2.2"] and dry.exit_code == 0
    assert dry.run_id is None
    plain, _ = make_collector(tmp_path / "p", "", repo=False)
    assert plain._sweep_due(NOW) is False


@pytest.fixture(autouse=True)
def _dirs(tmp_path):
    for name in ("d", "p", "x", "n"):
        (tmp_path / name).mkdir(exist_ok=True)


async def test_neighbors_are_explored_and_notes_kept(tmp_path, lab):
    lldp = "1.0.8802.1.1.2.1.4.1.1"
    remote = {parse_oid(f"{lldp}.5.0.1.1"): bytes.fromhex("00005e005399"),
              parse_oid(f"{lldp}.4.0.1.1"): 4, parse_oid(f"{lldp}.6.0.1.1"): 5,
              parse_oid(f"{lldp}.7.0.1.1"): b"xe-0/0/1", parse_oid(f"{lldp}.9.0.1.1"): b"dist",
              parse_oid(f"{lldp}.12.0.1.1"): b"\x20",
              parse_oid("1.0.8802.1.1.2.1.4.2.1.3.0.1.1.1.4.192.0.2.9"): 2}
    lab.add("192.0.2.1", FakeClient({**system_values("edge"), **remote}))
    lab.add("192.0.2.9", FakeClient(system_values("dist", mac="00:00:5e:00:53:99")))
    collector, repo = make_collector(tmp_path, "  seeds: [192.0.2.1]\n")
    report = await collector.run()
    assert sorted(r.target.host for r in report.results) == ["192.0.2.1", "192.0.2.9"]
    assert repo.conn.execute("SELECT origin, depth FROM targets WHERE address = '192.0.2.9'"
                             ).fetchone()[:] == ("neighbor", 1)

    lab2 = FakeClient({**system_values("edge"), **remote})
    lab.add("192.0.2.1", lab2)
    lone, _ = make_collector(tmp_path / "n", "  seeds: [192.0.2.1]\n", repo=False)
    lone._run_deadline = asyncio.get_running_loop().time() + 100
    results = await lone._collect_all([engine.PlannedTarget(Target("192.0.2.1"), "seed")], None,
                                      NOW, notes=None)
    assert sorted(r.target.host for r in results) == ["192.0.2.1", "192.0.2.9"]


async def test_discover_mode_skips_tables_and_custom(tmp_path, lab):
    lab.add("192.0.2.1", FakeClient(system_values("sw")))
    collector, _ = make_collector(tmp_path, "  seeds: [192.0.2.1]\n", repo=False,
                                  mode="discover")
    report = await collector.run()
    outcomes = set(report.results[0].outcomes)
    assert {"interfaces", "lldp", "cdp"} <= outcomes and not {"fdb", "arp"} & outcomes


async def test_superseded_while_running_stops_the_slower_address(tmp_path, lab):
    mac = "00:00:5e:00:53:01"
    slow = FakeClient(system_values("core", mac=mac), delay={oids.IF_DESCR: 0.2})
    lab.add("192.0.2.20", slow)
    lab.add("192.0.2.1", FakeClient(system_values("core", mac=mac)))
    lab.probe_delay["192.0.2.1"] = 0.05
    collector, _ = make_collector(tmp_path, "  seeds: [192.0.2.1, 192.0.2.20]\n", repo=False)
    report = await collector.run()
    loser = next(r for r in report.results if r.target.host == "192.0.2.20")
    assert loser.superseded and loser.alias_of.target.host == "192.0.2.1"
    assert "fdb" not in loser.outcomes
    assert report.stats["aliases"] == 1


async def test_match_warnings_are_kept(tmp_path, lab, monkeypatch):
    lab.add("192.0.2.1", FakeClient(system_values("sw")))
    collector, repo = make_collector(tmp_path, "  seeds: [192.0.2.1]\n")
    monkeypatch.setattr(repo, "match_device", lambda **kw: (None, ["serial number changed"]))
    report = await collector.run()
    assert report.results[0].warnings == ["serial number changed"]


# --------------------------------------------------------------------------- custom collectors


def loaded_collector(data):
    return LoadedCollector(parse_collector(data), "test")


async def test_custom_collectors_every_fills_and_invalid_stored(tmp_path, lab):
    private = "1.3.6.1.4.1.99999.9"
    lab.add("192.0.2.1", FakeClient({**system_values("sw"),
                                     parse_oid(f"{private}.1.0"): b"Room 12",
                                     parse_oid(f"{private}.2.0"): b"firewall",
                                     parse_oid(f"{private}.3.0"): b"toaster",
                                     parse_oid(f"{private}.4.0"): b"MODEL-9"}))
    collectors = [
        loaded_collector({"name": "where", "get": {"loc": f"{private}.1.0"},
                          "fills": {"location": "loc"}, "every": "1h"}),
        loaded_collector({"name": "kind", "get": {"t": f"{private}.2.0"},
                          "fills": {"device_type": "t"}}),
        loaded_collector({"name": "bad-kind", "get": {"t": f"{private}.3.0"},
                          "fills": {"device_type": "t"}}),
        loaded_collector({"name": "model", "get": {"m": f"{private}.4.0"},
                          "fills": {"model": "m"}, "fill_override": True}),
        loaded_collector({"name": "elsewhere", "applies_to": {"vendors": ["Nobody"]},
                          "get": {"x": f"{private}.1.0"}}),
    ]
    clock = FrozenClock(NOW)
    collector, repo = make_collector(tmp_path, "  seeds: [192.0.2.1]\n", collectors=collectors,
                                     clock=clock)
    repo.save_custom_collector("broken", {"name": "Broken Name"}, NOW)
    first = (await collector.run()).results[0]
    assert first.system.location == "Room 12"
    assert (first.ident.device_type, first.ident.type_rule) == ("firewall", "custom")
    assert first.ident.type_reason == "custom collector kind"
    assert first.ident.model == "MODEL-9"
    assert "collector bad-kind: 'toaster' is not a device type" in first.warnings
    assert set(first.custom) == {"where", "kind", "bad-kind", "model"}

    clock.advance(60)
    again, _ = make_collector(tmp_path, "  seeds: [192.0.2.1]\n", collectors=collectors,
                              clock=clock)
    again.repo = repo
    second = (await again.run()).results[0]
    assert "where" not in second.custom                  # every: 1h, not due
    assert second.system.location == "Room 12"           # filled from the stored values


def test_apply_fills_respects_existing_values():
    r = result_for(system=SystemInfo(location="Rack 1"), ident=Identification(model="A"))
    keep = parse_collector({"name": "k", "get": {"l": "1.3.6.1.4.1.1.0", "m": "1.3.6.1.4.1.2.0"},
                            "fills": {"location": "l", "model": "m"}})
    Collector._apply_fills(r, keep, {"l": "Rack 2", "m": "B"})
    assert (r.system.location, r.ident.model) == ("Rack 1", "A")
    over = parse_collector({"name": "o", "get": {"l": "1.3.6.1.4.1.1.0"},
                            "fills": {"location": "l"}, "fill_override": True})
    Collector._apply_fills(r, over, {"l": "Rack 2"})
    assert r.system.location == "Rack 2"


def test_outcome_status_helper():
    r = result_for()
    r.outcomes["x"] = Outcome("x", "ok")
    assert r.outcome_status("x") == "ok" and r.outcome_status("y") is None

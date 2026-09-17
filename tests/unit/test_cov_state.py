"""State database and repository, without devices: migrations and every repository method."""

from __future__ import annotations

import sqlite3

import pytest

from snowth_my_net.collect.custom import CustomResult
from snowth_my_net.collect.model import (
    ABSENT,
    OK,
    TIMEOUT,
    DeviceResult,
    Identification,
    Outcome,
)
from snowth_my_net.collect.tables.arp import ArpEntry
from snowth_my_net.collect.tables.bridge import FdbEntry
from snowth_my_net.collect.tables.entity import Chassis
from snowth_my_net.collect.tables.interfaces import Interface
from snowth_my_net.collect.tables.ipaddr import DeviceAddress
from snowth_my_net.collect.tables.neighbors import Neighbor
from snowth_my_net.collect.tables.system import SystemInfo
from snowth_my_net.config.effective import DeviceSettings
from snowth_my_net.drivers.base import SyntheticDevice
from snowth_my_net.snmp.target import parse_target
from snowth_my_net.state.db import SCHEMA_VERSION, StateError, migrate, open_db
from snowth_my_net.state.repo import DAY, Repo

NOW = 1_800_000_000


@pytest.fixture
def repo(tmp_path):
    conn = open_db(tmp_path / "state.sqlite")
    yield Repo(conn)
    conn.close()


def result(address="192.0.2.1", name="sw1", serial="SN1", mac="00:00:5e:00:53:01",
           entity=OK, **kwargs) -> DeviceResult:
    r = DeviceResult(parse_target(address), "seed", 0, DeviceSettings(), credential="v3")
    r.system = SystemInfo(descr="d", object_id="1.3.6.1.4.1.9.1.1", name=name, bridge_mac=mac)
    r.ident = Identification(vendor="Cisco", pen=9, model="M", serial=serial, os_name="IOS",
                             os_version="15", device_type="switch", type_rule="catalog",
                             type_reason="r")
    r.outcomes = {"entity": Outcome("entity", entity), "ipaddr": Outcome("ipaddr", OK),
                  "interfaces": Outcome("interfaces", OK), "fdb": Outcome("fdb", OK),
                  "arp": Outcome("arp", OK), "lldp": Outcome("lldp", OK)}
    for key, value in kwargs.items():
        setattr(r, key, value)
    return r


# --------------------------------------------------------------------------- db


def test_open_readonly_and_schema_versions(tmp_path):
    path = tmp_path / "s.sqlite"
    with pytest.raises(StateError, match="no state yet"):
        open_db(path, readonly=True)
    raw = sqlite3.connect(path)
    raw.execute("PRAGMA user_version = 1")
    raw.close()
    with pytest.raises(StateError, match="is older than this version"):
        open_db(path, readonly=True)
    raw = sqlite3.connect(path)
    raw.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    raw.close()
    with pytest.raises(StateError, match="is newer than this version"):
        open_db(path, readonly=True)
    with pytest.raises(StateError, match="upgrade the tool"):
        open_db(path)
    fresh = tmp_path / "fresh" / "s.sqlite"
    open_db(fresh).close()
    conn = open_db(fresh, readonly=True)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO meta(key, value) VALUES ('a', 'b')")
    conn.close()


def test_migrations_are_incremental(tmp_path):
    conn = sqlite3.connect(tmp_path / "m.sqlite")
    migrate(conn, 0)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    migrate(conn, SCHEMA_VERSION)          # nothing to do
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"devices", "manual_settings", "custom_values", "reports"} <= tables


# --------------------------------------------------------------------------- repo


def test_meta_runs_and_dns(repo):
    assert repo.get_meta("x") is None
    repo.set_meta("x", "1")
    repo.set_meta("x", "2")
    assert repo.get_meta("x") == "2"
    a = repo.start_run("collect", NOW)
    repo.finish_run(a, "ok", NOW + 5, {"only": ["x"]})
    b = repo.start_run("run", NOW + 10)
    repo.finish_run(b, "partial", NOW + 20, {})
    repo.start_run("collect", NOW + 30)                  # unfinished
    assert repo.last_successful_collect()["id"] == b      # --device runs are not full collects
    assert [r["id"] for r in repo.recent_runs(2)] == [3, 2]
    repo.save_dns({"192.0.2.1": ("host", "ok"), "192.0.2.2": (None, "nxdomain")}, NOW, 100, 10)
    assert repo.dns_names(NOW + 50) == {"192.0.2.1": "host"}
    assert repo.dns_fresh(NOW + 50) == {"192.0.2.1"}
    assert repo.dns_fresh(NOW + 5) == {"192.0.2.1", "192.0.2.2"}


def test_targets_origin_precedence_and_removal(repo):
    repo.ensure_target("192.0.2.1", "neighbor", 2, NOW)
    repo.ensure_target("192.0.2.1", "manual", 3, NOW)
    repo.ensure_target("192.0.2.2", "seed", 0, NOW)
    repo.ensure_target("192.0.2.2", "manual", 0, NOW)
    rows = {r["address"]: r for r in repo.targets()}
    assert (rows["192.0.2.1"]["origin"], rows["192.0.2.1"]["depth"]) == ("manual", 2)
    assert rows["192.0.2.2"]["origin"] == "seed"
    repo.demote_seeds({"192.0.2.9"})
    assert {r["address"]: r["origin"] for r in repo.targets()}["192.0.2.2"] == "state"
    repo.demote_seeds(set())                              # nothing left to demote
    repo.remember_credential("192.0.2.3:1161", "v2", NOW)
    repo.target_failed("192.0.2.3:1161", NOW, "timeout")
    row = {r["address"]: r for r in repo.targets()}["192.0.2.3:1161"]
    assert (row["credential"], row["consecutive_failures"], row["last_error"]) == (
        "v2", 1, "timeout")

    device_id = repo.save_device(result(), NOW, repo.start_run("collect", NOW))
    repo.ensure_target("192.0.2.1", "seed", 0, NOW)
    repo._target_ok("192.0.2.1", NOW, device_id, "v3", is_alias=False)
    repo.set_manual("192.0.2.1", {"type": "router"}, NOW)
    repo.remove_target("192.0.2.1")
    assert repo.device(device_id) is None and repo.manual_settings() == {}
    repo.remove_target("192.0.2.3:1161")                  # no device: only the target goes
    assert "192.0.2.3:1161" not in {r["address"] for r in repo.targets()}


def test_manual_settings(repo):
    repo.set_manual("192.0.2.1", {"type": "firewall", "uplinks": ["a"]}, NOW)
    repo.set_manual("192.0.2.1", {"type": "router"}, NOW)
    assert repo.manual_settings() == {"192.0.2.1": {"type": "router", "uplinks": ["a"]}}
    assert repo.unset_manual("192.0.2.1", ["uplinks", "missing"]) == 1
    assert repo.unset_manual("192.0.2.1") == 1


def test_save_device_details_observations_and_matching(repo):
    run = repo.start_run("collect", NOW)
    r = result(
        chassis=[Chassis(1, "M", "SN1", "15", "chassis")],
        addresses=[DeviceAddress("192.0.2.1", 5, 24), DeviceAddress("10.0.0.1", 6, 8)],
        interfaces={5: Interface(5, "Gi1/0/1", phys_mac="00:00:5e:00:53:05"), 6: Interface(6)},
        fdb=[FdbEntry("00:00:5e:00:53:a0", 5, 10, "fdb", "qbridge")],
        arp=[ArpEntry("00:00:5e:00:53:a0", "192.0.2.50", 4, 5, "physical")],
        vlans={10: "USERS"}, pvid={5: 10}, bridge_ports={1: 5},
        neighbors=[Neighbor("lldp", 1, 5, "name", chassis_id="00:00:5e:00:53:99",
                            port_id="Gi0/1", sys_name="core", caps=frozenset({"bridge"}),
                            mgmt_addresses=["192.0.2.99"])])
    r.system.chassis_mac = "00:00:5e:00:53:02"
    r.outcomes["system"] = Outcome("system", OK)
    device_id = repo.save_device(r, NOW, run)
    assert repo.find_device("192.0.2.1:161")["id"] == device_id
    assert repo.find_device("10.0.0.1")["id"] == device_id
    assert {"00:00:5e:00:53:01", "00:00:5e:00:53:02", "00:00:5e:00:53:05"} <= repo.device_macs()
    assert [s["function"] for s in repo.statuses(run)][:2] == ["arp", "entity"]
    assert repo.last_outcomes(device_id)[0]["function"] == "arp"

    # ENTITY-MIB not observed this run: the stored model, serial and type are kept.
    r2 = result(serial="", entity=TIMEOUT)
    r2.ident.model, r2.ident.device_type = "", ""
    r2.device_id = device_id
    repo.save_device(r2, NOW + 60, repo.start_run("collect", NOW + 60))
    row = repo.device(device_id)
    assert (row["model"], row["serial"], row["device_type"]) == ("M", "SN1", "switch")
    assert repo.devices(since=NOW + 30)[0]["id"] == device_id
    assert repo.devices(since=NOW + 120) == [] and len(repo.devices()) == 1

    assert repo.match_device(serial="SN1", pen=9, base_mac=None, sys_name="x",
                             address="x") == (device_id, [])
    other = repo.save_device(result("192.0.2.2", "sw2", "SN2", "00:00:5e:00:53:10"), NOW, run)
    matched, warnings = repo.match_device(serial="SN1", pen=9, base_mac="00:00:5e:00:53:10",
                                          sys_name="x", address="x")
    assert matched == device_id and "already known on another device" in warnings[0]
    assert repo.match_device(serial="", pen=None, base_mac="00:00:5e:00:53:10", sys_name="",
                             address="")[0] == other
    matched, warnings = repo.match_device(serial="NEW", pen=9, base_mac=None, sys_name="sw2",
                                          address="192.0.2.2")
    assert matched == other and "serial number changed from SN2 to NEW" in warnings[0]
    assert repo.match_device(serial="", pen=None, base_mac=None, sys_name="nobody",
                             address="192.0.2.77") == (None, [])


def test_alias_and_failure(repo):
    run = repo.start_run("collect", NOW)
    device_id = repo.save_device(result(), NOW, run)
    alias = result("192.0.2.9")
    repo.ensure_target("192.0.2.9", "seed", 0, NOW)
    repo.save_alias(alias, device_id, NOW)
    assert repo.find_device("192.0.2.9")["id"] == device_id
    failed = result()
    failed.error = "no answer (v3: timeout)"
    repo.save_failure(failed, NOW + 1, run, device_id)
    assert repo.device(device_id)["last_collect_status"] == "failed"
    assert [(s["function"], s["status"]) for s in repo.statuses(run)
            if s["function"] == "system"] == [("system", "timeout")]
    failed.error = "internal error"
    run2 = repo.start_run("collect", NOW + 2)
    repo.save_failure(failed, NOW + 2, run2, device_id)
    assert repo.statuses(run2)[0]["status"] == "error"
    repo.save_failure(failed, NOW + 3, run2, None)        # unknown device: target only


def test_custom_collectors_reports_and_values(repo):
    repo.save_custom_collector("c", {"name": "c", "get": {"v": "1.3"}}, NOW)
    repo.save_custom_collector("c", {"name": "c", "get": {"v": "1.4"}}, NOW + 1)
    assert repo.custom_stored() == {"c": {"name": "c", "get": {"v": "1.4"}}}
    repo.save_report("r", {"name": "r", "dataset": "devices"}, NOW)
    assert repo.reports_stored() == {"r": {"name": "r", "dataset": "devices"}}
    assert repo.delete_report("r") and not repo.delete_report("r")

    r = result()
    ok = CustomResult(rows=[("", "v", "1", "01"), ("2", "col", "x", None)])
    r.custom = {"c": (Outcome("custom:c", OK, 2), ok),
                "gone": (Outcome("custom:gone", ABSENT), CustomResult())}
    device_id = repo.save_device(r, NOW, repo.start_run("collect", NOW))
    current = repo.custom_current(device_id)
    assert current["c"]["values"] == {"v": "1"} and current["c"]["table"] == [("2", "col", "x")]
    assert current["gone"]["status"] == ABSENT and current["gone"]["values"] == {}
    assert repo.delete_custom_collector("c") and not repo.delete_custom_collector("c")
    assert "c" not in repo.custom_current(device_id)


def test_synthetic_devices(repo):
    controller = result("192.0.2.40", "wlc", "WLC1", "00:00:5e:00:53:40")
    controller.driver = "cisco-wlc"
    controller.outcomes["driver:cisco-wlc"] = Outcome("driver:cisco-wlc", OK, 1)
    ap = SyntheticDevice("00:00:5e:00:53:70", "ap-1", "192.0.2.70", "AIR", "FGL1", "8.10",
                         "hall", ports={1: "radio1"},
                         stations=[("00:00:5e:00:56:01", 1, 0)])
    no_address = SyntheticDevice("00:00:5e:00:53:71", "ap-2")
    controller.synthetic = [ap, no_address]
    run = repo.start_run("collect", NOW)
    controller.device_id = repo.save_device(controller, NOW, run)
    by_name = {d["sys_name"]: d for d in repo.devices()}
    assert set(by_name) == {"wlc", "ap-1"}
    assert (by_name["ap-1"]["driver"], by_name["ap-1"]["type_rule"]) == (
        "synthetic:cisco-wlc", "driver")
    assert "reported by wlc" in by_name["ap-1"]["sys_descr"]

    ap.name, ap.model = "ap-1-renamed", "AIR2"
    repo.save_device(controller, NOW + 60, repo.start_run("collect", NOW + 60))
    assert repo.device(by_name["ap-1"]["id"])["sys_name"] == "ap-1-renamed"

    # The same AP polled directly keeps its polled identity; only last_seen moves.
    polled = result("192.0.2.70", "ap-polled", "FGL1", "00:00:5e:00:53:70")
    repo.conn.execute("DELETE FROM devices WHERE driver LIKE 'synthetic:%'")
    polled_id = repo.save_device(polled, NOW, run)
    repo.save_device(controller, NOW + 120, repo.start_run("collect", NOW + 120))
    row = repo.device(polled_id)
    assert (row["sys_name"], row["last_seen"]) == ("ap-polled", NOW + 120)
    assert repo.conn.execute("SELECT COUNT(*) FROM fdb_obs WHERE device_id = ?",
                             (polled_id,)).fetchone()[0] == 1

    controller.outcomes["driver:cisco-wlc"] = Outcome("driver:cisco-wlc", "error")
    before = repo.conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    ap.key_mac = "00:00:5e:00:53:7e"
    repo.save_device(controller, NOW + 180, repo.start_run("collect", NOW + 180))
    assert repo.conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == before
    controller.synthetic = []
    repo.save_device(controller, NOW + 200, repo.start_run("collect", NOW + 200))


def test_purge(repo):
    run = repo.start_run("collect", NOW - 200 * DAY)
    old = result("192.0.2.5", "old", "OLD", "00:00:5e:00:53:55",
                 fdb=[FdbEntry("00:00:5e:00:53:b1", 1, 0, "none", "bridge")],
                 arp=[ArpEntry("00:00:5e:00:53:b1", "192.0.2.51", 4, None, "media")],
                 neighbors=[Neighbor("cdp", 1, 1, "n", sys_name="x", port_id="p")])
    old.outcomes["cdp"] = Outcome("cdp", OK)
    repo.save_device(old, NOW - 200 * DAY, run)
    repo.save_dns({"192.0.2.51": ("n", "ok")}, NOW - 200 * DAY, 1, 1)
    repo.ensure_target("192.0.2.6", "neighbor", 1, NOW - 200 * DAY)
    repo.ensure_target("192.0.2.7", "seed", 0, NOW - 200 * DAY)
    for i in range(60):
        rid = repo.start_run("collect", NOW - i)
        repo._save_outcomes(rid, 1, [Outcome("x", OK)])
    counts = repo.purge(NOW, retention_days=90, forget_after_days=90, nodes_retention_days=30)
    assert counts["fdb"] == 1 and counts["arp"] == 1 and counts["neighbors"] == 1
    assert counts["devices"] == 1 and counts["targets"] == 1      # the seed stays
    assert {r["address"] for r in repo.targets()} == {"192.0.2.7"}
    assert repo.conn.execute("SELECT COUNT(DISTINCT run_id) FROM collect_status"
                             ).fetchone()[0] == 50
    assert repo.dns_fresh(0) == set()


def test_a_refused_state_closes_its_connection(tmp_path, monkeypatch):
    import sqlite3 as sqlite3_module

    from snowth_my_net.state import db as db_module

    path = tmp_path / "state.sqlite"
    raw = sqlite3_module.connect(path)
    raw.execute("PRAGMA user_version = 999")
    raw.close()
    opened = []
    real_connect = sqlite3_module.connect

    def spy(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(db_module.sqlite3, "connect", spy)
    for readonly in (True, False):
        with pytest.raises(db_module.StateError, match="newer"):
            db_module.open_db(path, readonly=readonly)
    assert len(opened) == 2
    for conn in opened:
        with pytest.raises(sqlite3_module.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")

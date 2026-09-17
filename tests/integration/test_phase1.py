"""Phase 1 end to end: check, discover, collect, export devices.csv against snmpsim."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from snowth_my_net.cli import main
from snowth_my_net.lock import StateLock
from tests.support.lab import DEAD, write_config
from tests.support.udp_proxy import GET, GET_BULK, GET_NEXT, SET, RecordingProxy

GOLDEN = Path(__file__).resolve().parents[1] / "golden"


def all_seeds(lab) -> list[str]:
    return lab.all_seeds()


def run_json(capsys, *argv: str) -> tuple[int, dict]:
    code = main(["--json", *argv])
    captured = capsys.readouterr().out
    return code, json.loads(captured)


def golden_bytes(name: str) -> bytes:
    # The golden file is stored with LF in git; the contract is CRLF (RFC 4180).
    return (GOLDEN / name).read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


@pytest.fixture
def collected(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=all_seeds(lab))
    code, report = run_json(capsys, "--config", str(cfg), "collect")
    return cfg, code, report


def by_address(report: dict) -> dict[str, dict]:
    return {d["address"]: d for d in report["devices"]}


def test_collect_polls_everything_and_tolerates_the_dead_device(lab, collected):
    _cfg, code, report = collected
    assert code == 0, report
    devices = by_address(report)
    assert devices[lab.address(DEAD)]["status"] == "failed"
    assert report["stats"]["reachable"] == 9
    fw = devices[lab.agent("fw")]
    assert fw["credential"] == "v2c-lab"               # v3 refused, then v2c accepted
    assert fw["attempts"][0][0] == "v3-main" and fw["attempts"][-1] == ["v2c-lab", "ok"]
    sw = devices[lab.agent("sw-access")]
    assert sw["credential"] == "v3-main", sw["attempts"]
    assert fw["functions"]["entity"]["status"] == "absent"  # not an error in auto mode
    assert fw["device_type"] == "firewall" and fw["type_rule"] == "catalog"


def test_types_are_only_set_on_sure_evidence(lab, collected):
    _cfg, _code, report = collected
    devices = by_address(report)
    expected = {
        "sw-access": ("switch", "catalog"), "sw-generic": ("", ""), "fw": ("firewall", "catalog"),
        "printer": ("printer", "function_mib"), "ups": ("facility", "function_mib"),
        "linux": ("", ""), "dual": ("switch", "catalog"), "ap": ("wireless", "lldp_caps"),
        "sw-cisco": ("", ""),
    }
    for agent, (device_type, rule) in expected.items():
        d = devices[lab.agent(agent)]
        assert (d["device_type"], d["type_rule"]) == (device_type, rule), agent


def test_devices_csv_matches_the_golden_file(collected, tmp_path, capsys):
    cfg, _code, _report = collected
    assert main(["--config", str(cfg), "export"]) == 0
    capsys.readouterr()
    produced = (tmp_path / "out" / "devices.csv").read_bytes()
    assert produced == golden_bytes("devices.csv")


def test_a_device_with_two_addresses_is_polled_once(lab, collected, tmp_path):
    _cfg, _code, report = collected
    devices = by_address(report)
    primary, secondary = devices[lab.agent("dual", 0)], devices[lab.agent("dual", 1)]
    assert primary["alias_of"] is None
    assert secondary["alias_of"] == lab.agent("dual", 0)
    db = sqlite3.connect(tmp_path / "state" / "state.sqlite")
    rows = db.execute("SELECT address, is_alias FROM targets WHERE address IN (?, ?)",
                      (lab.agent("dual", 0), lab.agent("dual", 1))).fetchall()
    assert sorted(rows) == [(lab.agent("dual", 0), 0), (lab.agent("dual", 1), 1)]
    count = db.execute("SELECT COUNT(*) FROM devices WHERE sys_name = 'sw-core-01'").fetchone()
    assert count[0] == 1


def test_second_collect_reuses_the_remembered_credential(lab, collected, capsys):
    cfg, _code, _report = collected
    code, report = run_json(capsys, "--config", str(cfg), "collect")
    assert code == 0
    fw = by_address(report)[lab.agent("fw")]
    assert fw["attempts"] == [["v2c-lab", "ok"]]


def test_show_devices_explains_the_type(collected, capsys):
    cfg, _code, _report = collected
    code, devices = run_json(capsys, "--config", str(cfg), "show", "devices")
    assert code == 0
    printer = next(d for d in devices if d["name"] == "PRN-2F-01")
    assert printer["type_rule"] == "function_mib"
    assert "Printer-MIB" in printer["type_reason"]


def test_check_diagnoses_each_device(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=all_seeds(lab), tolerate_dead=False)
    code, result = run_json(capsys, "--config", str(cfg), "check", "--quick")
    assert code == 1  # the dead device is not tolerated here
    devices = {d["address"]: d for d in result["devices"]}
    assert devices[lab.address(DEAD)]["reachable"] is False
    sw = devices[lab.agent("sw-access")]
    assert sw["mibs"]["entity"] == "ok" and sw["mibs"]["ifXTable"] == "ok"
    fw = devices[lab.agent("fw")]
    assert fw["mibs"]["ipNetToMedia"] == "ok" and fw["mibs"]["ipNetToPhysical"] == "absent"
    assert any("SNMPv2c" in w for w in result["warnings"])


def test_only_get_getnext_getbulk_are_sent(lab, tmp_path, capsys):
    host, port = lab.agent("sw-generic").split(":")
    proxy = RecordingProxy(("127.0.0.40", 0), (host, int(port)))
    proxy.start()
    try:
        proxied = f"127.0.0.40:{proxy.address[1]}"
        cfg = write_config(tmp_path, lab, seeds=[proxied],
                           extra_devices="  - address: 127.0.0.40\n    credential: v2c-lab\n")
        assert main(["--config", str(cfg), "collect"]) == 0
        capsys.readouterr()
    finally:
        proxy.stop()
    assert proxy.tags, "no request went through the proxy"
    assert SET not in proxy.tags
    assert set(proxy.tags) <= {GET, GET_NEXT, GET_BULK}


def test_a_running_command_holds_the_lock(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("sw-generic")])
    text = cfg.read_text().replace("general:\n", "general:\n  lock_wait: {collect: 0}\n", 1)
    cfg.write_text(text)
    holder = StateLock(tmp_path / "state" / "state.lock", "export")
    holder.acquire(0)
    try:
        assert main(["--config", str(cfg), "collect"]) == 3
    finally:
        holder.release()


def test_invalid_configuration_exits_2(tmp_path, capsys):
    cfg = tmp_path / "bad.yml"
    cfg.write_text("credentials:\n  - {name: x, version: 2c, community: public}\n")
    assert main(["--config", str(cfg), "collect"]) == 2


def test_discover_dry_run_identifies_without_writing_state(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("sw-access"), lab.agent("printer")])
    code, report = run_json(capsys, "--config", str(cfg), "discover", "--dry-run")
    assert code == 0
    assert report["run_id"] is None
    types = {d["address"]: d["device_type"] for d in report["devices"]}
    assert types == {lab.agent("sw-access"): "switch", lab.agent("printer"): "printer"}
    assert "interfaces" not in by_address(report)[lab.agent("sw-access")]["functions"]
    assert not (tmp_path / "state").exists()

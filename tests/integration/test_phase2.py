"""Phase 2 end to end: MAC tables, ARP, merge, nodes.csv, explain, DNS cache."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from snowth_my_net.cli import main
from snowth_my_net.clock import Clock
from snowth_my_net.config.loader import load_config
from snowth_my_net.export.run import export
from snowth_my_net.state.db import open_db
from snowth_my_net.state.repo import Repo
from tests.support.lab import write_config

GOLDEN = Path(__file__).resolve().parents[1] / "golden"
TS = re.compile(rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
A0, B0, D0, D1 = "00:00:5e:00:53:a0", "00:00:5e:00:53:b0", "00:00:5e:00:53:d0", "00:00:5e:00:53:d1"


def run_json(capsys, *argv):
    code = main(["--json", *argv])
    return code, json.loads(capsys.readouterr().out)


def collect(capsys, cfg) -> int:
    code = main(["--config", str(cfg), "-q", "collect"])
    capsys.readouterr()
    return code


@pytest.fixture
def lab_cfg(lab, tmp_path):
    return write_config(tmp_path, lab, seeds=lab.all_seeds(), files="[devices, nodes]")


def explain(capsys, cfg, query):
    return run_json(capsys, "--config", str(cfg), "explain", query)


def test_nodes_csv_matches_the_golden_file_and_uses_the_dns_cache(lab_cfg, tmp_path, capsys):
    assert collect(capsys, lab_cfg) == 0
    loaded = load_config(lab_cfg)
    loaded.cfg.dns.enabled = True
    calls = []

    async def fake_ptr(ip):
        calls.append(ip)
        return ("pc-a0.example.net", "ok") if ip == "192.0.2.50" else (None, "nxdomain")

    repo = Repo(open_db(loaded.paths.state_file))
    try:
        assert export(loaded, repo, Clock(), ptr_lookup=fake_ptr).exit_code == 0
        first_calls = len(calls)
        assert export(loaded, repo, Clock(), ptr_lookup=fake_ptr).exit_code == 0
    finally:
        repo.conn.close()
    assert first_calls == 5 and len(calls) == first_calls        # second export: cache only

    produced = (tmp_path / "out" / "nodes.csv").read_bytes()
    stamps = set(TS.findall(produced))
    assert len(stamps) >= 1
    normalized = TS.sub(b"<TS>", produced)
    golden = (GOLDEN / "nodes.csv").read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    assert normalized == golden

    devices = (tmp_path / "out" / "devices.csv").read_text().splitlines()
    names = {line.split(",", 1)[0] for line in devices[1:]}
    switches = {line.split(",")[5] for line in normalized.decode().splitlines()[1:]
                if line.split(",")[5]}
    assert switches <= names                                   # the join key always holds


def test_explain_trunk_transit_and_arp(lab_cfg, capsys):
    assert collect(capsys, lab_cfg) == 0
    code, result = explain(capsys, lab_cfg, A0)
    assert code == 0
    node = result["nodes"][0]
    verdicts = {(s["device"], s["port"]): s["verdict"] for s in node["sightings"]}
    assert verdicts == {("sw-access-01", "1/1/3"): "position", ("sw-generic-02", "2"): "shadowed"}
    assert node["current_ip"] == "192.0.2.50"
    assert {i["ip"] for i in node["ips"]} == {"192.0.2.50", "2001:db8::50", "fe80::50"}

    _code, result = explain(capsys, lab_cfg, B0)
    trunk = result["nodes"][0]["sightings"][0]
    assert result["nodes"][0]["positions"] == []
    assert (trunk["verdict"], trunk["role_reasons"]) == ("uplink", ["mac_count"])

    _code, result = explain(capsys, lab_cfg, "00:00:5e:00:53:14")
    assert "polled device (PRN-2F-01)" in result["nodes"][0]["excluded"]

    code, result = explain(capsys, lab_cfg, "192.0.2.40")
    assert code == 0 and result["nodes"][0]["mac"] == "00:00:5e:00:53:c0"
    assert explain(capsys, lab_cfg, "00:00:5e:00:99:99")[0] == 1

    assert main(["--config", str(lab_cfg), "explain", A0]) == 0
    text = capsys.readouterr().out
    assert "transit (same time on sw-access-01 1/1/3, fewer MACs)" in text


def test_cisco_per_vlan_instances_over_snmpv3_and_v2c(lab, tmp_path, capsys):
    cisco = lab.agent("sw-cisco")
    for label, extra in (("v3", ""), ("v2c", "  - address: 127.0.0.21\n    credential: v2c-lab\n")):
        work = tmp_path / label
        cfg = write_config(work, lab, seeds=[cisco], extra_devices=extra, files="[nodes]")
        assert collect(capsys, cfg) == 0
        _code, result = explain(capsys, cfg, D0)
        position = result["nodes"][0]["positions"][0]
        assert (position["port"], position["vlan"], position["vlan_source"]) == (
            "Gi1/0/1", 10, "context"), label


def test_vlan_indexing_off_only_sees_the_default_instance(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("sw-cisco")],
                       extra_devices="  - address: 127.0.0.21\n    vlan_indexing: 'off'\n")
    assert collect(capsys, cfg) == 0
    assert explain(capsys, cfg, D0)[0] == 1
    _code, result = explain(capsys, cfg, D1)
    assert result["nodes"][0]["positions"][0]["vlan"] is None


def test_forced_arp_on_a_switch_without_arp_is_reported(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("sw-generic")],
                       extra_devices="  - address: 127.0.0.12\n    features: {arp: force}\n")
    code, report = run_json(capsys, "--config", str(cfg), "collect")
    assert code == 1
    assert report["devices"][0]["functions"]["arp"]["status"] == "forced_absent"
    assert report["devices"][0]["functions"]["fdb"]["status"] == "ok"


def test_show_nodes_filter_and_empty_export_guard(lab, lab_cfg, tmp_path, capsys):
    assert collect(capsys, lab_cfg) == 0
    code, rows = run_json(capsys, "--config", str(lab_cfg), "show", "nodes", "--filter",
                          "sw-cisco")
    assert code == 0 and {r["mac"] for r in rows} == {D0, D1}

    lonely = write_config(tmp_path / "lonely", lab, seeds=[lab.agent("printer")],
                          files="[devices, nodes]")
    assert collect(capsys, lonely) == 0
    out_dir = tmp_path / "lonely" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "nodes.csv").write_text("previous\n")
    assert main(["--config", str(lonely), "-q", "export"]) == 1
    capsys.readouterr()
    assert (out_dir / "nodes.csv").read_text() == "previous\n"
    assert (out_dir / "devices.csv").exists()


def test_manual_uplink_and_access_ports_apply_at_once(lab_cfg, capsys):
    assert collect(capsys, lab_cfg) == 0
    assert main(["--config", str(lab_cfg), "device", "set", "127.0.0.11",
                 "access_ports=1/1/12"]) == 0
    capsys.readouterr()
    _code, result = explain(capsys, lab_cfg, B0)
    assert result["nodes"][0]["positions"][0]["port"] == "1/1/12"
    assert main(["--config", str(lab_cfg), "device", "set", "127.0.0.11", "uplinks=1/1/3"]) == 0
    capsys.readouterr()
    _code, result = explain(capsys, lab_cfg, A0)
    assert result["nodes"][0]["positions"][0]["device"] == "sw-generic-02"   # fallback to transit

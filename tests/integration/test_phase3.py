"""Phase 3 end to end: LLDP/CDP, exploration, neighbour-based roles, links, snapshot, maps."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from snowth_my_net.cli import main
from tests.support.lab import write_config

GOLDEN = Path(__file__).resolve().parents[1] / "golden"
TS = re.compile(rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
ALL_FILES = "[devices, nodes, links, snapshot, map]"


def run_json(capsys, *argv):
    code = main(["--json", *argv])
    return code, json.loads(capsys.readouterr().out)


def golden(name: str) -> bytes:
    return (GOLDEN / name).read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


@pytest.fixture
def exported(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=lab.all_seeds(), files=ALL_FILES)
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    assert main(["--config", str(cfg), "-q", "export"]) == 0
    capsys.readouterr()
    return cfg, tmp_path / "out"


def test_exploration_from_a_single_seed(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("sw-access")])
    code, report = run_json(capsys, "--config", str(cfg), "collect")
    assert code == 0
    found = {d["sys_name"]: (d["origin"], d["status"]) for d in report["devices"]}
    assert found == {"sw-access-01.example.net": ("seed", "ok"),
                     "sw-cisco-03.example.net": ("neighbor", "ok")}
    notes = "\n".join(report["notes"])
    assert "SEP00005E0053F0 (192.0.2.77): skipped (capabilities bridge,telephone)" in notes
    assert "core-rtr (203.0.113.1): skipped (outside discovery.allowed)" in notes


def test_exploration_respects_max_depth_and_the_switch(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("sw-access")])
    cfg.write_text(cfg.read_text().replace("  allowed: [127.0.0.0/8]",
                                           "  allowed: [127.0.0.0/8]\n  max_depth: 0"))
    code, report = run_json(capsys, "--config", str(cfg), "collect")
    assert code == 0 and len(report["devices"]) == 1
    assert any("max_depth 0" in note for note in report["notes"])


def test_links_and_nodes_match_the_golden_files(exported):
    _cfg, out = exported
    assert TS.sub(b"<TS>", (out / "links.csv").read_bytes()) == golden("links.csv")
    assert TS.sub(b"<TS>", (out / "nodes.csv").read_bytes()).replace(
        b"pc-a0.example.net", b"") == golden("nodes.csv").replace(b"pc-a0.example.net", b"")


def test_neighbor_rules_for_trunk_phone_ap_and_router(exported, capsys):
    cfg, _out = exported
    code, result = run_json(capsys, "--config", str(cfg), "explain", "00:00:5e:00:53:b0")
    assert code == 0
    reasons = result["nodes"][0]["sightings"][0]["role_reasons"]
    assert reasons == ["neighbor_managed", "mac_count"]
    _code, result = run_json(capsys, "--config", str(cfg), "explain", "00:00:5e:00:53:f1")
    assert result["nodes"][0]["positions"][0]["port"] == "1/1/7"          # behind the phone
    _code, result = run_json(capsys, "--config", str(cfg), "explain", "00:00:5e:00:53:f2")
    assert result["nodes"][0]["positions"][0]["device"] == "sw-generic-02"  # Wi-Fi client
    _code, result = run_json(capsys, "--config", str(cfg), "explain", "00:00:5e:00:53:d2")
    sighting = result["nodes"][0]["sightings"][0]
    assert (sighting["verdict"], sighting["role_reasons"]) == ("uplink", ["neighbor_infra"])
    fallback = cfg.read_text().replace("dns:\n", "nodes:\n  uplink_fallback: true\ndns:\n", 1)
    cfg.write_text(fallback)
    _code, result = run_json(capsys, "--config", str(cfg), "explain", "00:00:5e:00:53:d2")
    assert result["nodes"][0]["position_kind"] == "behind_uplink"


def test_snapshot_contents(exported):
    _cfg, out = exported
    snap = json.loads((out / "snapshot.json").read_text())
    assert snap["schema"] == "snowth_my_net/snapshot/1"
    assert set(snap) == {"schema", "generated_at", "tool_version", "last_collect", "devices",
                         "nodes", "links", "errors"}
    access = next(d for d in snap["devices"] if d["name"] == "sw-access-01")
    trunk = next(i for i in access["interfaces"] if i["name"] == "1/1/12")
    assert trunk["role"] == "uplink" and "neighbor_managed" in trunk["role_reasons"]
    assert {n["remote_device"] for n in access["neighbors"]} == {"sw-cisco-03", "SEP00005E0053F0"}
    assert {v["name"] for v in access["vlans"]} == {"USERS", "VOICE"}
    assert access["collection"]["lldp"]["status"] == "ok"
    assert any(e["device"].startswith("127.0.0.19") for e in snap["errors"])
    assert len(snap["links"]) == 3 and len(snap["nodes"]) == 19


def test_maps_are_written(exported):
    _cfg, out = exported
    dot = (out / "map.dot").read_text()
    assert dot.count(" -- ") == 3 and '"sw-access-01\\n127.0.0.11\\nswitch"' in dot
    assert (out / "map.mmd").read_text().startswith("graph LR")
    html = (out / "map.html").read_text()
    data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>',
                                html, re.S)[1])
    assert {n["label"] for n in data["nodes"] if n["kind"] == "external"} == {"core-rtr"}
    assert "https://" not in html


def test_grouped_endpoints_on_the_map(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=lab.all_seeds(), files="[map]")
    grouped = "  files: [map]\n  map: {formats: [dot], endpoints: grouped}"
    cfg.write_text(cfg.read_text().replace("  files: [map]", grouped))
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    assert main(["--config", str(cfg), "-q", "export"]) == 0
    capsys.readouterr()
    dot = (tmp_path / "out" / "map.dot").read_text()
    assert '"1/1/7 · 2 hosts"' in dot


def test_show_links(exported, capsys):
    cfg, _out = exported
    code, rows = run_json(capsys, "--config", str(cfg), "show", "links", "--filter", "cisco")
    assert code == 0 and {r["protocol"] for r in rows} == {"LLDP+CDP", "CDP"}

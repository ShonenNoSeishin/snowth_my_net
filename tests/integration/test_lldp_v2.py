"""LLDP-V2-MIB (802.1AB-2009) as a fallback for agents that do not serve LLDP-MIB."""

from __future__ import annotations

import json

from snowth_my_net.cli import main
from tests.support.lab import write_config


def test_neighbours_come_from_lldp_v2_with_their_local_port(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("lldp-v2")], files="[snapshot, links]")
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    assert main(["--config", str(cfg), "-q", "export"]) == 0
    capsys.readouterr()
    snapshot = json.loads((tmp_path / "out" / "snapshot.json").read_text())
    device = next(d for d in snapshot["devices"] if d["name"] == "sw-v2")
    assert device["collection"]["lldp"]["status"] == "ok"
    neighbours = {n["remote_device"]: n for n in device["neighbors"]}
    assert set(neighbours) == {"sw-access-01", "ap-v2"}
    # the V2 index names the local ifIndex: no port-mapping guesswork
    assert neighbours["sw-access-01"]["local_port"] == "1:2"
    assert neighbours["sw-access-01"]["remote_port"] == "1/1/9"
    assert neighbours["sw-access-01"]["management_addresses"] == ["127.0.0.11"]
    assert neighbours["ap-v2"]["capabilities"] == ["wlan_ap"]
    links = (tmp_path / "out" / "links.csv").read_text()
    assert ("sw-v2,1:2,sw-access-01,1/1/9,LLDP" in links
            or "sw-access-01,1/1/9,sw-v2,1:2,LLDP" in links), links


def test_lldp_v2_devices_are_explored_like_the_others(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("lldp-v2")])
    code = main(["--json", "--config", str(cfg), "discover"])
    report = json.loads(capsys.readouterr().out)
    assert code == 0
    names = {(d["sys_name"] or "").split(".")[0] for d in report["devices"]}
    assert {"sw-v2", "sw-access-01"} <= names        # the neighbour was followed

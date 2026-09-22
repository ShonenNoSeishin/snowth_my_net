"""ARP of non-global VRFs, read in their own SNMP context (devices[].vrfs)."""

from __future__ import annotations

import json

from snowth_my_net.cli import main
from tests.support.lab import write_config

GLOBAL, BLUE_1, BLUE_2, DMZ = ("00:00:5e:00:58:01", "00:00:5e:00:58:02",
                               "00:00:5e:00:58:03", "00:00:5e:00:58:04")


def collected(lab, tmp_path, capsys, extra_devices="", expected=0):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("vrf-router")], files="[nodes]",
                       extra_devices=extra_devices)
    assert main(["--config", str(cfg), "-q", "collect"]) == expected
    capsys.readouterr()
    return cfg


def ips(capsys, cfg) -> dict[str, str]:
    assert main(["--json", "--config", str(cfg), "show", "nodes"]) == 0
    return {n["mac"]: n["ip"] for n in json.loads(capsys.readouterr().out)}


def test_auto_reads_every_vrf_the_router_declares(lab, tmp_path, capsys):
    cfg = collected(lab, tmp_path, capsys)
    assert ips(capsys, cfg) == {GLOBAL: "192.0.2.200", BLUE_1: "10.10.0.5",
                                BLUE_2: "10.10.0.6", DMZ: "198.51.100.5"}
    assert main(["--json", "--config", str(cfg), "explain", BLUE_1]) == 0
    explained = json.loads(capsys.readouterr().out)
    sources = explained["nodes"][0]["ips"][0]["sources"]
    assert [s["table"] for s in sources] == ["media@blue"]      # provenance is kept


def test_off_reads_only_the_global_table(lab, tmp_path, capsys):
    cfg = collected(lab, tmp_path, capsys,
                    extra_devices="  - address: 127.0.0.27\n    vrfs: off\n")
    assert ips(capsys, cfg) == {GLOBAL: "192.0.2.200"}


def test_an_explicit_list_reads_those_contexts_only(lab, tmp_path, capsys):
    cfg = collected(lab, tmp_path, capsys,
                    extra_devices="  - address: 127.0.0.27\n    vrfs: [dmz]\n")
    assert ips(capsys, cfg) == {GLOBAL: "192.0.2.200", DMZ: "198.51.100.5"}


def test_an_unknown_context_is_a_partial_arp_not_a_lost_collect(lab, tmp_path, capsys):
    cfg = collected(lab, tmp_path, capsys,
                    extra_devices="  - address: 127.0.0.27\n    vrfs: [dmz, nosuchvrf]\n"
                                  "    snmp: {timeout: 1, retries: 0}\n", expected=1)
    assert ips(capsys, cfg)[DMZ] == "198.51.100.5"            # what answered is kept
    assert main(["--json", "--config", str(cfg), "show", "runs"]) == 0
    capsys.readouterr()
    code = main(["--json", "--config", str(cfg), "collect"])
    report = json.loads(capsys.readouterr().out)
    outcome = report["devices"][0]["functions"]["arp"]
    assert code == 1 and outcome["status"] == "partial" and "nosuchvrf" in outcome["detail"]

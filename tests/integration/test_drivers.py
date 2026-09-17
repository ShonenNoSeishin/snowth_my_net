"""Phase 5 against snmpsim: vendor drivers, synthetic access points, sub-interface folding."""

from __future__ import annotations

import csv
import io
import json

import pytest

from snowth_my_net.cli import main
from tests.support.lab import write_config

DRIVER_AGENTS = ("fw", "fortigate", "mikrotik", "wlc", "ex-units")


def rows(path):
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))


@pytest.fixture
def exported(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent(n) for n in DRIVER_AGENTS],
                       files="[devices, nodes, links, snapshot]")
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    assert main(["--config", str(cfg), "-q", "export"]) == 0
    capsys.readouterr()
    return cfg, tmp_path / "out"


def test_identity_from_private_mibs(exported):
    _cfg, out = exported
    devices = {d["Device Name"]: d for d in rows(out / "devices.csv")}
    picked = {name: (d["Model"], d["Serial"], d["Operating System"], d["OS Version"],
                     d["Device Type"]) for name, d in devices.items()}
    assert picked["fw-edge"] == ("XGS2100", "X21002ABCDEF12", "SFOS", "20.0.1 MR-1-Build342",
                                 "firewall")
    assert picked["fgt-branch"] == ("", "FGT60FTK20000001", "FortiOS", "7.2.5 build1517",
                                    "firewall")
    assert picked["mt-office"] == ("RB5009UG+S+", "HCQ0812ABC1", "RouterOS", "7.12.1", "")
    snapshot = json.loads((out / "snapshot.json").read_text())
    collection = {d["name"]: d["collection"] for d in snapshot["devices"]}
    assert collection["fgt-branch"]["driver"]["status"] == "ok"
    assert collection["wlc-01"]["driver:cisco-wlc"]["status"] == "ok"


def test_controller_publishes_access_points_and_positions_clients(exported, capsys):
    cfg, out = exported
    devices = {d["Device Name"]: d for d in rows(out / "devices.csv")}
    assert (devices["ap-hall"]["IP Address"], devices["ap-hall"]["Model"],
            devices["ap-hall"]["Location"], devices["ap-hall"]["Device Type"]) == (
        "192.0.2.70", "AIR-AP2802I-E-K9", "Main hall", "wireless")
    assert "reported by wlc-01" in devices["ap-lab"]["Device Details"]
    nodes = {n["MAC Address"]: n for n in rows(out / "nodes.csv")}
    assert (nodes["00:00:5e:00:56:04"]["Switch"], nodes["00:00:5e:00:56:04"]["Port"],
            nodes["00:00:5e:00:56:04"]["IP Address"]) == ("ap-hall", "radio1", "192.0.2.101")
    assert (nodes["00:00:5e:00:56:06"]["Switch"], nodes["00:00:5e:00:56:06"]["Port"]) == (
        "ap-lab", "radio1")
    assert "00:00:5e:00:56:07" not in nodes          # its AP is unknown to the controller
    names = {d["Device Name"] for d in rows(out / "devices.csv")}
    assert {n["Switch"] for n in nodes.values() if n["Switch"]} <= names   # join invariant

    # A second collect updates the same synthetic devices (matched by base MAC).
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    capsys.readouterr()
    code = main(["--json", "--config", str(cfg), "show", "devices"])
    listed = json.loads(capsys.readouterr().out)
    assert code == 0 and [d["name"] for d in listed].count("ap-hall") == 1


def test_mikrotik_stations_and_juniper_units(exported, capsys):
    cfg, out = exported
    nodes = {n["MAC Address"]: n for n in rows(out / "nodes.csv")}
    assert (nodes["00:00:5e:00:56:01"]["Switch"], nodes["00:00:5e:00:56:01"]["Port"],
            nodes["00:00:5e:00:56:01"]["IP Address"]) == ("mt-office", "wlan1", "192.0.2.131")
    assert (nodes["00:00:5e:00:56:08"]["Switch"], nodes["00:00:5e:00:56:08"]["Port"],
            nodes["00:00:5e:00:56:08"]["VLAN"]) == ("ex-floor2", "ge-0/0/1", "10")
    # C0 was learnt on ge-0/0/2.0, whose physical port has an LLDP bridge neighbour: uplink.
    assert nodes["00:00:5e:00:53:c0"]["Switch"] == ""
    main(["--config", str(cfg), "explain", "00:00:5e:00:53:c0"])
    assert "ge-0/0/2" in capsys.readouterr().out


def test_driver_none_keeps_the_standard_path(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("fw")], extra_devices=(
        "  - address: 127.0.0.13\n    driver: none\n"))
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    capsys.readouterr()
    code = main(["--json", "--config", str(cfg), "show", "devices"])
    device = json.loads(capsys.readouterr().out)[0]
    assert code == 0 and device["model"] == "" and device["os"] == "SFOS"


def test_check_shows_the_driver(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("fortigate")])
    main(["--config", str(cfg), "check", lab.agent("fortigate")])
    text = capsys.readouterr().out
    assert "driver:fortinet ok(serial, os_version)" in text
    assert "FortiOS 7.2.5 build1517" in text


ACME_DRIVER = '''
from snowth_my_net.api import AccessPoint, Extension, Observations, Station, text

extension = Extension("acme")
acme = extension.driver("acme-wlc", object_ids=["1.3.6.1.4.1.14179.1.1.4.3"])


@acme.identity
async def identity(device, snmp):
    return {"model": "ACME-" + device.name}


@acme.observations
async def observations(device, snmp):
    names = await snmp.walk("1.3.6.1.4.1.14179.2.2.1.1.3")
    aps = [AccessPoint(mac="00:00:5e:00:53:70", name=text(names[0][1]) + "-py",
                       address="192.0.2.70",
                       stations=[Station("00:00:5e:00:56:aa", 1)])]
    return Observations(stations=[Station("00:00:5e:00:56:bb", 1)],
                        arp=[("00:00:5e:00:56:aa", "192.0.2.170")], access_points=aps)
'''


def test_python_extension_driver(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("wlc")], files="[devices, nodes]")
    (tmp_path / "extensions").mkdir()
    (tmp_path / "extensions" / "acme.py").write_text(ACME_DRIVER)
    cfg.write_text(cfg.read_text().replace("general:\n", "general:\n  python_extensions: [acme]\n",
                                           1))
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    assert main(["--config", str(cfg), "-q", "export"]) == 0
    capsys.readouterr()
    devices = {d["Device Name"]: d for d in rows(tmp_path / "out" / "devices.csv")}
    assert devices["wlc-01"]["Model"] == "ACME-wlc-01"
    assert "ap-hall-py" in devices and "ap-lab" not in devices     # the extension won
    nodes = {n["MAC Address"]: n for n in rows(tmp_path / "out" / "nodes.csv")}
    assert (nodes["00:00:5e:00:56:aa"]["Switch"], nodes["00:00:5e:00:56:aa"]["Port"],
            nodes["00:00:5e:00:56:aa"]["IP Address"]) == ("ap-hall-py", "radio1", "192.0.2.170")
    assert (nodes["00:00:5e:00:56:bb"]["Switch"], nodes["00:00:5e:00:56:bb"]["Port"]) == (
        "wlc-01", "Port 1")

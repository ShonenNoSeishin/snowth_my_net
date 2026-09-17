"""Vendor drivers: selection, identity refinement (shape checks) and configuration."""

from __future__ import annotations

import pytest

from snowth_my_net import drivers
from snowth_my_net.collect.model import Identification
from snowth_my_net.config.loader import parse_config_text
from snowth_my_net.config.validate import ConfigError
from snowth_my_net.drivers.base import fill_identity


def test_selection_by_sysobjectid_setting_none_and_name():
    assert drivers.select(None, "1.3.6.1.4.1.12356.101.1.643").name == "fortinet"
    assert drivers.select("auto", "1.3.6.1.4.1.14988.1").name == "mikrotik"
    assert drivers.select(None, "1.3.6.1.4.1.2604.5").name == "sophos"
    assert drivers.select(None, "1.3.6.1.4.1.2604.5.2") is None      # other Sophos products
    assert drivers.select(None, "1.3.6.1.4.1.14179.1.1.4.3").name == "cisco-wlc"
    assert drivers.select(None, "1.3.6.1.4.1.9.1.1208") is None
    assert drivers.select("none", "1.3.6.1.4.1.14988.1") is None
    assert drivers.select("cisco-wlc", "1.3.6.1.4.1.9.1.2170").name == "cisco-wlc"
    assert drivers.select(None, "1.3.6.1.4.1.1298801") is None       # prefix, not a sub-tree


@pytest.mark.parametrize(("driver", "values", "expected"), [
    ("fortinet", {"fnSysSerial": b"FGT60FTK20000001",
                  "fgSysVersion": b"v7.2.5,build1517,230606 (GA.F)"},
     {"serial": "FGT60FTK20000001", "os_name": "FortiOS", "os_version": "7.2.5 build1517"}),
    ("fortinet", {"fgSysVersion": b"v6.4.15"}, {"serial": "", "os_name": "FortiOS",
                                                "os_version": "6.4.15"}),
    ("sophos", {"sfosDeviceType": b"XGS2100", "sfosDeviceFWVersion": b"SFOS 20.0.1 MR-1-Build342",
                "sfosDeviceAppKey": b"X21002ABCDEF12"},
     {"model": "XGS2100", "os_name": "SFOS", "os_version": "20.0.1 MR-1-Build342",
      "serial": "X21002ABCDEF12"}),
    ("sophos", {"sfosDeviceType": b"Tuesday 17 September", "sfosDeviceFWVersion": b"unknown",
                "sfosDeviceAppKey": b"not a key!"}, {}),
    ("mikrotik", {"mtxrLicVersion": b"7.12.1", "mtxrSerialNumber": b"HCQ0812ABC1",
                  "mtxrBoardName": b"RB5009UG+S+"},
     {"serial": "HCQ0812ABC1", "model": "RB5009UG+S+", "os_name": "RouterOS",
      "os_version": "7.12.1"}),
])
def test_identity_refinement(driver, values, expected):
    assert drivers.by_name(driver).refine(values, Identification()) == expected


def test_only_empty_fields_are_filled():
    ident = Identification(model="EX2300", os_version="21.4R3")
    filled = fill_identity(ident, {"model": "other", "os_version": "", "serial": " SN1 "})
    assert filled == ["serial"] and (ident.model, ident.serial) == ("EX2300", "SN1")


def test_driver_setting_is_validated(tmp_path):
    from snowth_my_net.config.loader import load_config

    cfg = tmp_path / "c.yml"
    base = "general: {{state_dir: {0}}}\ndevices:\n  - address: 192.0.2.1\n    driver: {1}\n"
    for ok in ("auto", "none", "mikrotik"):
        cfg.write_text(base.format(tmp_path, ok))
        load_config(cfg)
    cfg.write_text(base.format(tmp_path, "juniper"))
    with pytest.raises(ConfigError, match="unknown driver 'juniper'"):
        load_config(cfg)
    with pytest.raises(ConfigError, match="not a driver name"):
        parse_config_text(base.format(tmp_path, "'Bad Name'"))


def test_every_object_a_driver_reads_can_be_tested_by_hand():
    from snowth_my_net.collect.presets import PRESETS
    from snowth_my_net.drivers import cisco_wlc, mikrotik

    in_presets = {c.oid for p in PRESETS for c in p.columns}
    wanted = {oid for d in drivers.DRIVERS for oid in d.identity_requests().values()}
    wanted.add(mikrotik.WL_RTAB_IFACE)
    wanted |= {tuple(int(x) for x in f"{cisco_wlc.AP_ENTRY}.{n}".split("."))
               for k, n in cisco_wlc.AP_COLUMNS.items() if k in ("name", "model", "serial", "ip")}
    wanted |= {tuple(int(x) for x in f"{cisco_wlc.STATION_ENTRY}.{n}".split("."))
               for n in cisco_wlc.STATION_COLUMNS.values()}
    assert wanted - in_presets == set()

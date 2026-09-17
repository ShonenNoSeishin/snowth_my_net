"""Vendor drivers with fake agents: identity edge cases, MikroTik stations, AireOS controllers,
drivers from Python extensions, and their integration in a collect (no network)."""

from __future__ import annotations

from typing import ClassVar

import pytest

from snowth_my_net import drivers
from snowth_my_net.api import AccessPoint, Extension, Observations, Station
from snowth_my_net.collect.engine import driver_identity
from snowth_my_net.collect.functions import Rows
from snowth_my_net.collect.model import DeviceResult, Identification
from snowth_my_net.collect.tables.bridge import FdbEntry
from snowth_my_net.collect.tables.system import SystemInfo
from snowth_my_net.config.effective import settings_for
from snowth_my_net.config.loader import parse_config_text
from snowth_my_net.drivers.base import Driver, index_mac
from snowth_my_net.drivers.cisco_wlc import AP_ENTRY, STATION_ENTRY, CiscoWlc, _ip
from snowth_my_net.drivers.mikrotik import WL_RTAB_IFACE, MikroTik
from snowth_my_net.drivers.python import ExtensionDriver, ExtensionDriverError
from snowth_my_net.snmp.client import SnmpTimeout
from snowth_my_net.snmp.target import Target
from snowth_my_net.snmp.values import parse_oid
from tests.unit.test_cov_collect_engine import FakeClient, Lab, make_collector, system_values

STA = (0, 0, 94, 0, 86, 1)


def result(system=None, ident=None, fdb=None, pvid=None):
    r = DeviceResult(Target("192.0.2.1"), "seed", 0, settings_for(parse_config_text(""),
                                                                  "192.0.2.1"))
    r.system, r.ident = system, ident or Identification()
    r.fdb, r.pvid = fdb or [], pvid or {}
    return r


def test_index_mac_and_ip_helpers():
    assert index_mac(STA) == "00:00:5e:00:56:01"
    assert index_mac((0, 0, 94, 0, 86)) is None and index_mac((0, 0, 300, 0, 86, 1)) is None
    assert _ip(b"\xc0\x00\x02\x01") == "192.0.2.1" and _ip(b"\x00\x00\x00\x00") == ""
    assert _ip("192.0.2.9") == "192.0.2.9" and _ip("not-ip") == "" and _ip(None) == ""
    assert _ip(b"\x01\x02") == ""


async def test_base_driver_defaults():
    class Plain(Driver):
        name = "plain"
        object_ids = ("1.3.6.1.4.1.1",)

    driver = Plain()
    assert driver.matches("1.3.6.1.4.1.1") and driver.matches("1.3.6.1.4.1.1.5")
    assert not driver.matches("1.3.6.1.4.1.12")
    assert await driver.identify(FakeClient(), result()) == {}
    assert driver.refine({}, Identification()) == {}
    assert await driver.extra(FakeClient(), result(), Rows()) is None


def test_refine_edge_cases():
    fortinet = drivers.by_name("fortinet")
    assert fortinet.refine({"fnSysSerial": b"FG1", "fgSysVersion": b"garbage"},
                           Identification()) == {"serial": "FG1"}
    mikrotik = MikroTik()
    assert mikrotik.refine({"mtxrLicVersion": b"n/a"}, Identification()) == {
        "serial": "", "model": ""}


async def test_mikrotik_stations():
    rtab = {WL_RTAB_IFACE + STA + (7,): 7,                          # station on wlan1
            WL_RTAB_IFACE + (0, 0, 94, 0, 86, 2, 8): b"weird",       # ifIndex from the index
            WL_RTAB_IFACE + (0, 0, 94, 0, 86, 3): 7,                 # short index: ignored
            WL_RTAB_IFACE + (0, 0, 0, 0, 0, 0, 7): 7,                # all-zero MAC: ignored
            WL_RTAB_IFACE + (0, 0, 94, 0, 86, 4, 9): 9}              # already in the FDB
    known = FdbEntry("00:00:5e:00:56:04", 9, 0, "none", "qbridge")
    r = result(fdb=[known], pvid={7: 30})
    rows = Rows()
    await MikroTik().extra(FakeClient(rtab), r, rows)
    assert [(e.mac, e.ifindex, e.vlan, e.vlan_source, e.method) for e in r.fdb[1:]] == [
        ("00:00:5e:00:56:01", 7, 30, "pvid", "mikrotik_wlan"),
        ("00:00:5e:00:56:02", 8, 0, "none", "mikrotik_wlan")]
    assert rows.count == 2


def wlc_values(ap_ip=b"\xc0\x00\x02\x46"):
    ap = (0, 0, 94, 0, 83, 112)
    other = (0, 0, 94, 0, 83, 113)
    values = {}
    for index, name in ((ap, b"ap-hall"), (other, b""), ((0, 0, 94, 0, 83), b"short")):
        values[parse_oid(f"{AP_ENTRY}.3") + index] = name
    values[parse_oid(f"{AP_ENTRY}.19") + ap] = ap_ip
    values[parse_oid(f"{AP_ENTRY}.16") + ap] = b"AIR-AP2802I"
    for sta, ap_mac, slot, ip in ((STA, bytes(ap), 1, b"\xc0\x00\x02\x65"),
                                  ((0, 0, 94, 0, 86, 2), bytes(ap), b"x", None),
                                  ((0, 0, 94, 0, 86, 3), bytes(other), 0, None),
                                  ((0, 0, 94, 0, 86), bytes(ap), 0, None)):
        values[parse_oid(f"{STATION_ENTRY}.4") + sta] = ap_mac
        values[parse_oid(f"{STATION_ENTRY}.5") + sta] = slot
        if ip:
            values[parse_oid(f"{STATION_ENTRY}.2") + sta] = ip
    return values


async def test_cisco_wlc_access_points_and_clients():
    r = result(system=SystemInfo(name="wlc-01"))
    await CiscoWlc().extra(FakeClient(wlc_values()), r, Rows())
    (ap,) = r.synthetic
    assert (ap.name, ap.address, ap.model) == ("ap-hall", "192.0.2.70", "AIR-AP2802I")
    assert ap.type_reason == "access point joined to the controller wlc-01"
    assert ap.ports == {1: "radio1", 0: "radio0"}
    assert ap.stations == [("00:00:5e:00:56:01", 1, 0), ("00:00:5e:00:56:02", 0, 0)]
    assert [(a.mac, a.ip, a.table) for a in r.arp] == [("00:00:5e:00:56:01", "192.0.2.101",
                                                        "wlc")]

    headless = result(system=None)
    await CiscoWlc().extra(FakeClient(wlc_values()), headless, Rows())
    assert headless.synthetic[0].type_reason == "access point joined to a wireless controller"

    failing = result(system=SystemInfo(name="wlc"))
    client = FakeClient(wlc_values(), fail={parse_oid(STATION_ENTRY): SnmpTimeout("slow")})
    with pytest.raises(SnmpTimeout):
        await CiscoWlc().extra(client, failing, Rows())
    assert [a.name for a in failing.synthetic] == ["ap-hall"]        # APs read before are kept
    radios = result(system=SystemInfo(name="wlc"))
    values = wlc_values()
    values[parse_oid(f"{STATION_ENTRY}.5") + STA] = 5
    await CiscoWlc().extra(FakeClient(values), radios, Rows())
    assert radios.synthetic[0].ports[5] == "radio5"


# --------------------------------------------------------------------------- Python drivers


def extension_driver(identity=None, observations=None, name="ext"):
    ext = Extension("acme")
    declared = ext.driver(name, object_ids=["1.3.6.1.4.1.99999"])
    if identity:
        declared.identity(identity)
    if observations:
        declared.observations(observations)
    return ExtensionDriver(declared, "acme")


async def test_extension_driver_identity_and_errors():
    async def good(device, snmp):
        got = await snmp.get("1.3.6.1.2.1.1.5.0")
        return {"model": got["1.3.6.1.2.1.1.5.0"].decode(), "serial": "", "color": "red",
                "os_version": 7}

    async def bad_type(device, snmp):
        return ["model"]

    async def raises(device, snmp):
        raise RuntimeError("oops")

    async def snmp_error(device, snmp):
        raise SnmpTimeout("late")

    r = result(system=SystemInfo(name="dev", object_id="1.3.6.1.4.1.99999.2"))
    client = FakeClient({(1, 3, 6, 1, 2, 1, 1, 5, 0): b"X200"})
    assert await extension_driver(good).identify(client, r) == {"model": "X200",
                                                                 "os_version": "7"}
    assert await extension_driver(observations=good).identify(client, r) == {}
    with pytest.raises(ExtensionDriverError, match="identity returns a dict"):
        await extension_driver(bad_type).identify(client, r)
    with pytest.raises(ExtensionDriverError, match=r"acme\.ext raised RuntimeError: oops"):
        await extension_driver(raises).identify(client, r)
    with pytest.raises(SnmpTimeout):
        await extension_driver(snmp_error).identify(client, result())
    driver = extension_driver(good)
    assert driver.matches("1.3.6.1.4.1.99999.2") and not driver.has_extra
    assert "Python extension acme" in driver.title


async def test_extension_driver_observations():
    async def observe(device, snmp):
        return Observations(
            stations=[Station("00:00:5e:00:56:01", 3, 10), Station("00:00:5e:00:56:01", 3, 10),
                      Station("bad-mac", 3), Station("00:00:5e:00:56:02", 4)],
            arp=[("00:00:5e:00:56:01", "192.0.2.101"), ("00:00:5e:00:56:02", "2001:db8::2"),
                 ("bad", "192.0.2.9"), ("00:00:5e:00:56:03", "")],
            access_points=[
                AccessPoint("00:00:5e:00:53:70", "ap-1", "192.0.2.70", radio_names={1: "5GHz"},
                            stations=[Station("00:00:5e:00:56:05", 1), Station("zz", 1),
                                      Station("00:00:5e:00:56:06", 0)]),
                AccessPoint("bad", "ap-2", "192.0.2.71"),
                AccessPoint("00:00:5e:00:53:72", "", "192.0.2.72")])

    async def nothing(device, snmp):
        return None

    async def wrong(device, snmp):
        return {"stations": []}

    r = result(system=SystemInfo(name="ctrl"))
    rows = Rows()
    driver = extension_driver(observations=observe)
    assert driver.has_extra
    await driver.extra(FakeClient(), r, rows)
    assert [(e.mac, e.ifindex, e.vlan, e.vlan_source) for e in r.fdb] == [
        ("00:00:5e:00:56:01", 3, 10, "fdb"), ("00:00:5e:00:56:02", 4, 0, "none")]
    assert [(a.ip, a.family) for a in r.arp] == [("192.0.2.101", 4), ("2001:db8::2", 6)]
    (ap,) = r.synthetic
    assert ap.ports == {1: "5GHz", 0: "radio0"}
    assert ap.stations == [("00:00:5e:00:56:05", 1, 0), ("00:00:5e:00:56:06", 0, 0)]
    assert "reported by ctrl (ext driver)" in ap.type_reason
    assert rows.count == 5

    anonymous = result()
    await driver.extra(FakeClient(), anonymous, Rows())
    assert "reported by a controller" in anonymous.synthetic[0].type_reason
    empty = result()
    await extension_driver(observations=nothing).extra(FakeClient(), empty, Rows())
    assert empty.fdb == [] and empty.synthetic == []
    with pytest.raises(ExtensionDriverError, match="returns Observations"):
        await extension_driver(observations=wrong).extra(FakeClient(), result(), Rows())


def test_selection_prefers_extension_drivers():
    async def identity(device, snmp):
        return {}

    ext = extension_driver(identity, name="mikrotik-ext")
    ext.object_ids = ("1.3.6.1.4.1.14988.1",)
    assert drivers.select(None, "1.3.6.1.4.1.14988.1", [ext]) is ext
    assert drivers.select("mikrotik", "1.3.6.1.4.1.14988.1", [ext]).name == "mikrotik"
    assert drivers.select("mikrotik-ext", "1.3.6.1.4.1.9", [ext]) is ext
    assert drivers.by_name("nope") is None


# --------------------------------------------------------------------------- in a collect


async def test_collect_with_drivers(tmp_path, monkeypatch):
    lab = Lab(monkeypatch)
    identity = {parse_oid("1.3.6.1.4.1.14988.1.1.4.4.0"): b"7.12.1",
                parse_oid("1.3.6.1.4.1.14988.1.1.7.8.0"): b"RB5009"}
    lab.add("192.0.2.1", FakeClient({**system_values("mt", object_id="1.3.6.1.4.1.14988.1"),
                                     **identity, WL_RTAB_IFACE + STA + (7,): 7}))
    lab.add("192.0.2.2", FakeClient({**system_values("wlc", object_id="1.3.6.1.4.1.9.1.2170"),
                                     **wlc_values()}))
    lab.add("192.0.2.3", FakeClient({**system_values("mt2", object_id="1.3.6.1.4.1.14988.1"),
                                     **identity}, fail={WL_RTAB_IFACE: SnmpTimeout("slow")}))
    collector, repo = make_collector(tmp_path, """  seeds: [192.0.2.1, 192.0.2.2, 192.0.2.3]
devices:
  - {address: 192.0.2.2, driver: cisco-wlc}
""")
    report = await collector.run()
    by_host = {r.target.host: r for r in report.results}
    mt = by_host["192.0.2.1"]
    assert mt.driver == "mikrotik" and mt.ident.model == "RB5009"
    assert mt.outcomes["driver"].status == "ok" and mt.outcomes["driver:mikrotik"].rows == 1
    assert any(e.method == "mikrotik_wlan" for e in mt.fdb)
    wlc = by_host["192.0.2.2"]
    assert wlc.driver == "cisco-wlc" and wlc.outcomes["driver:cisco-wlc"].status == "ok"
    assert repo.conn.execute("SELECT driver FROM devices WHERE sys_name = 'ap-hall'"
                             ).fetchone()[0] == "synthetic:cisco-wlc"
    assert by_host["192.0.2.3"].outcomes["driver:mikrotik"].status == "timeout"
    assert report.status == "partial"


async def test_driver_identity_types_a_device_once_the_model_is_known():
    class Juniper(Driver):
        name = "jnp"
        identity_oids: ClassVar[dict[str, str]] = {"model": "1.3.6.1.4.1.2636.3.1.2.0"}

        def refine(self, values, ident):
            return {"model": values["model"].decode()}

    r = result(system=SystemInfo(descr="Juniper", object_id="1.3.6.1.4.1.2636.1.1.1.4"),
               ident=Identification(vendor="Juniper"))
    client = FakeClient({parse_oid("1.3.6.1.4.1.2636.3.1.2.0"): b"EX4300-48T"})
    rows = Rows()
    await driver_identity(Juniper())(client, r, rows)
    assert r.ident.model == "EX4300-48T" and r.ident.device_type == "switch"

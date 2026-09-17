"""MikroTik RouterOS (MIKROTIK-MIB).

* Identity: board name, serial number and RouterOS version from the private MIB.
* Wi-Fi: stations registered on the router's own wireless interfaces
  (``mtxrWlRtabTable``, indexed by station MAC and ifIndex) become sightings on that interface,
  so clients of a MikroTik access point get a position like clients of a switch port.
"""

from __future__ import annotations

from typing import ClassVar

from snowth_my_net.collect.model import DeviceResult, Identification
from snowth_my_net.collect.tables.bridge import FdbEntry
from snowth_my_net.drivers.base import VERSION_RE, Driver, text
from snowth_my_net.snmp.client import SnmpClient, Value
from snowth_my_net.snmp.values import normalize_mac, parse_oid

WL_RTAB_IFACE = parse_oid("1.3.6.1.4.1.14988.1.1.1.2.1.2")


class MikroTik(Driver):
    name = "mikrotik"
    title = "MikroTik RouterOS"
    vendor = "MikroTik"
    object_ids = ("1.3.6.1.4.1.14988.1",)
    identity_oids: ClassVar[dict[str, str]] = {
        "mtxrLicVersion": "1.3.6.1.4.1.14988.1.1.4.4.0",
        "mtxrSerialNumber": "1.3.6.1.4.1.14988.1.1.7.3.0",
        "mtxrBoardName": "1.3.6.1.4.1.14988.1.1.7.8.0",
    }
    has_extra = True

    def refine(self, values: dict[str, Value], ident: Identification) -> dict[str, str]:
        found = {"serial": text(values.get("mtxrSerialNumber")),
                 "model": text(values.get("mtxrBoardName"))}
        version = text(values.get("mtxrLicVersion"))
        if VERSION_RE.search(version):
            found["os_name"] = "RouterOS"
            found["os_version"] = version
        return found

    async def extra(self, client: SnmpClient, r: DeviceResult, rows) -> None:
        rows.key = "stations"
        stations = rows.column("stations")
        seen = {(e.mac, e.ifindex) for e in r.fdb}
        try:
            async for oid, value in client.walk(WL_RTAB_IFACE):
                index = oid[len(WL_RTAB_IFACE):]
                if len(index) != 7:
                    continue
                mac = normalize_mac(bytes(index[:6]))
                ifindex = value if isinstance(value, int) else index[6]
                if mac is None or (mac, ifindex) in seen:
                    continue
                seen.add((mac, ifindex))
                stations[index] = mac
                r.fdb.append(FdbEntry(mac, ifindex, r.pvid.get(ifindex, 0),
                                      "pvid" if ifindex in r.pvid else "none", "mikrotik_wlan"))
        finally:
            rows.key = "stations"

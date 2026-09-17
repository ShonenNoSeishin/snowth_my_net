"""Cisco AireOS wireless LAN controllers (AIRESPACE-WIRELESS-MIB).

With lightweight access points, client traffic is tunnelled to the controller: switches only
see the clients behind the controller's uplink, so they would have no position. This driver
publishes each joined access point as a **synthetic device** (in ``devices.csv``, with its name,
IP, model and serial) and each associated client as a sighting on that AP's radio, with the
client IP learnt by the controller as an ARP entry. The APs' own LLDP/CDP announcements on the
switches then link them to their switch port.

Catalyst 9800 controllers (CISCO-LWAPP-*-MIB) are not covered yet.
"""

from __future__ import annotations

import ipaddress

from snowth_my_net.collect.model import DeviceResult
from snowth_my_net.collect.tables.arp import ArpEntry
from snowth_my_net.drivers.base import Driver, SyntheticDevice, text
from snowth_my_net.snmp.client import SnmpClient
from snowth_my_net.snmp.values import normalize_mac, parse_oid

AP_ENTRY = "1.3.6.1.4.1.14179.2.2.1.1"
AP_COLUMNS = {"name": 3, "location": 4, "software": 8, "model": 16, "serial": 17, "ip": 19}
STATION_ENTRY = "1.3.6.1.4.1.14179.2.1.4.1"
STATION_COLUMNS = {"ip": 2, "ap": 4, "slot": 5, "ssid": 7}
RADIO_NAMES = {0: "radio0", 1: "radio1", 2: "radio2", 3: "radio3"}


def _ip(value) -> str:
    try:
        if (isinstance(value, bytes) and len(value) == 4) or (isinstance(value, str) and value):
            address = ipaddress.ip_address(value)
        else:
            return ""
    except ValueError:
        return ""
    return "" if address.is_unspecified else str(address)


class CiscoWlc(Driver):
    name = "cisco-wlc"
    title = "Cisco AireOS wireless controller"
    vendor = "Cisco"
    # The Airespace product id. Controllers announcing a Cisco product id instead are served
    # with devices[].driver: cisco-wlc (no guessed list of product ids).
    object_ids = ("1.3.6.1.4.1.14179.1.1.4.3",)
    has_extra = True

    async def _table(self, client: SnmpClient, entry: str, columns: dict[str, int], rows,
                     prefix: str) -> dict[tuple[int, ...], dict[str, object]]:
        table: dict[tuple[int, ...], dict[str, object]] = {}
        for label, number in columns.items():
            base = parse_oid(f"{entry}.{number}")
            column = rows.column(f"{prefix}.{label}")
            async for oid, value in client.walk(base):
                index = oid[len(base):]
                column[index] = value
                table.setdefault(index, {})[label] = value
        return table

    async def extra(self, client: SnmpClient, r: DeviceResult, rows) -> None:
        rows.key = "ap.name"
        aps: dict[str, SyntheticDevice] = {}
        try:
            for index, row in (await self._table(client, AP_ENTRY, AP_COLUMNS, rows,
                                                 "ap")).items():
                mac = normalize_mac(bytes(index)) if len(index) == 6 else None
                name = text(row.get("name"))
                if mac is None or not name:
                    continue
                aps[mac] = SyntheticDevice(
                    key_mac=mac, name=name, address=_ip(row.get("ip")),
                    model=text(row.get("model")), serial=text(row.get("serial")),
                    os_version=text(row.get("software")), location=text(row.get("location")),
                    type_reason=f"access point joined to the controller {r.system.name}"
                    if r.system else "access point joined to a wireless controller")
            stations = await self._table(client, STATION_ENTRY, STATION_COLUMNS, rows, "sta")
        finally:
            r.synthetic = list(aps.values())
        for index, row in stations.items():
            mac = normalize_mac(bytes(index)) if len(index) == 6 else None
            ap_value = row.get("ap")
            ap = aps.get(normalize_mac(ap_value) if isinstance(ap_value, bytes) else "")
            if mac is None or ap is None:
                continue
            slot = row.get("slot") if isinstance(row.get("slot"), int) else 0
            ap.ports.setdefault(slot, RADIO_NAMES.get(slot, f"radio{slot}"))
            ap.stations.append((mac, slot, 0))
            address = _ip(row.get("ip"))
            if address:
                r.arp.append(ArpEntry(mac, address, 4, None, "wlc"))

"""Drivers declared by Python extensions (``extension.driver``), run like built-in drivers."""

from __future__ import annotations

from snowth_my_net.collect.model import DeviceResult, Identification
from snowth_my_net.collect.tables.arp import ArpEntry
from snowth_my_net.collect.tables.bridge import FdbEntry
from snowth_my_net.drivers.base import Driver, SyntheticDevice
from snowth_my_net.snmp.client import SnmpClient, SnmpError
from snowth_my_net.snmp.values import normalize_mac

IDENTITY_FIELDS = ("model", "serial", "os_name", "os_version")


class ExtensionDriverError(SnmpError):
    kind = "error"


def _view(r: DeviceResult):
    from snowth_my_net.api import DeviceView

    system, ident = r.system, r.ident or Identification()
    return DeviceView(r.target.host, system.name if system else "", ident.vendor, ident.model,
                      ident.os_name, ident.os_version, ident.device_type,
                      system.object_id if system else "")


class ExtensionDriver(Driver):
    """Adapter: the declaration comes from ``snowth_my_net.api.PythonDriver``."""

    def __init__(self, declared, extension: str) -> None:
        self.declared, self.extension = declared, extension
        self.name = declared.name
        self.title = declared.description or f"driver from the Python extension {extension}"
        self.object_ids = tuple(declared.object_ids)
        self.has_extra = declared.observations_func is not None
        self._identity: dict[str, str] = {}

    async def _call(self, func, client: SnmpClient, r: DeviceResult):
        from snowth_my_net.collect.custom import ClientSnmp

        try:
            return await func(_view(r), ClientSnmp(client, 10_000))
        except SnmpError:
            raise
        except Exception as exc:  # extension code
            raise ExtensionDriverError(f"{self.extension}.{self.name} raised "
                                       f"{type(exc).__name__}: {exc}") from exc

    async def identify(self, client: SnmpClient, r: DeviceResult) -> dict[str, str]:
        if self.declared.identity_func is None:
            return {}
        found = await self._call(self.declared.identity_func, client, r)
        if not isinstance(found, dict):
            raise ExtensionDriverError(f"{self.name}: identity returns a dict")
        return {k: str(v) for k, v in found.items() if k in IDENTITY_FIELDS and v}

    async def extra(self, client: SnmpClient, r: DeviceResult, rows) -> None:
        from snowth_my_net.api import Observations

        rows.key = "observations"
        result = await self._call(self.declared.observations_func, client, r)
        if result is None:
            return
        if not isinstance(result, Observations):
            raise ExtensionDriverError(f"{self.name}: observations returns Observations(...)")
        count = rows.column("observations")
        known = {(e.mac, e.ifindex, e.vlan) for e in r.fdb}
        for station in result.stations:
            mac = normalize_mac(station.mac)
            if mac and (mac, station.port, station.vlan) not in known:
                known.add((mac, station.port, station.vlan))
                r.fdb.append(FdbEntry(mac, station.port, station.vlan,
                                      "fdb" if station.vlan else "none", self.name))
                count[(len(count),)] = mac
        for mac_text, address in result.arp:
            mac = normalize_mac(mac_text)
            if mac and address:
                family = 6 if ":" in address else 4
                r.arp.append(ArpEntry(mac, address, family, None, self.name))
                count[(len(count),)] = mac
        for ap in result.access_points:
            key = normalize_mac(ap.mac)
            if key is None or not ap.name:
                continue
            syn = SyntheticDevice(key, ap.name, ap.address, ap.model, ap.serial, ap.os_version,
                                  ap.location, type_reason=f"access point reported by "
                                  f"{r.system.name if r.system else 'a controller'} "
                                  f"({self.name} driver)")
            for station in ap.stations:
                mac = normalize_mac(station.mac)
                if mac:
                    syn.ports.setdefault(station.port, ap.radio_names.get(
                        station.port, f"radio{station.port}"))
                    syn.stations.append((mac, station.port, station.vlan))
            r.synthetic.append(syn)
            count[(len(count),)] = key

# Vendor drivers

The standard MIBs (IF-MIB, BRIDGE/Q-BRIDGE, IP-MIB, LLDP, ENTITY-MIB) are always collected on
every device, whatever it announces. A driver only **adds** what those MIBs cannot say for a
family of products:

* **identity** from private objects: model, serial number, OS name and version, applied to
  fields that the standard collection left empty;
* **observations** after the standard collection: Wi-Fi stations, ARP entries, and access points
  described by a controller.

A driver never switches a standard function off. Its work is recorded like any other function
(`driver` and `driver:<name>` in `snapshot.json` → `collection`, in the TUI *Last collect* tab and
in `check`), and a driver error only makes that function fail.

## Selection

A driver is chosen by the device's sysObjectID. `devices[].driver` changes that:

```yaml
devices:
  - address: 192.0.2.10
    driver: cisco-wlc      # use it although the controller announces a Cisco product id
  - address: 192.0.2.11
    driver: none           # standard collection only
```

`check` shows the driver and what it filled, e.g. `driver:fortinet ok(serial, os_version)`.
Every object a driver reads has a preset in the OID tester (`probe ADDR <preset>` or the TUI),
so it can be verified by hand on your devices before you trust it.

## Built-in drivers

| Driver | Selected for (sysObjectID) | Adds | Preset(s) |
|---|---|---|---|
| `fortinet` | `1.3.6.1.4.1.12356.101.1.*`, `…12356.15.*` (FortiGate, FortiWiFi) | serial (`fnSysSerial`), FortiOS version and build (`fgSysVersion`) | `fortinet` |
| `sophos` | `1.3.6.1.4.1.2604.5` (Sophos Firewall / XGS, SFOS) | model (`sfosDeviceType`), SFOS version (`sfosDeviceFWVersion`), serial = appliance key (`sfosDeviceAppKey`) | `sophos-sfos` |
| `mikrotik` | `1.3.6.1.4.1.14988.1` (RouterOS) | board name, serial, RouterOS version; Wi-Fi stations registered on the router's own wireless interfaces (`mtxrWlRtabTable`) as positions on those interfaces | `mikrotik`, `mikrotik-wifi` |
| `cisco-wlc` | `1.3.6.1.4.1.14179.1.1.4.3` (AireOS; others with `driver: cisco-wlc`) | one **synthetic device** per joined access point (name, IP, model, serial, software, location) and each client as a position on its AP radio, with the IP learnt by the controller | `cisco-wlc-aps`, `cisco-wlc-clients` |

Values are only accepted when they have the expected shape (a version looks like a version, a
model like a model), so an agent serving something else under the same OIDs changes nothing.

The drivers were built from the vendors' MIB definitions and tested on synthetic agents; if a
device of yours disagrees, `probe` shows what it really serves, `driver: none` switches the
driver off for it, and a custom collector or a Python driver can do better.

### Wireless controllers and synthetic access points

With lightweight APs, client traffic is tunnelled to the controller: switches only see the
clients behind the controller's port, which becomes an uplink, so the clients would have no
position. The `cisco-wlc` driver publishes each AP in `devices.csv` (Device Type `wireless`,
Device Details `<model> (reported by <controller>)`) and each client in `nodes.csv` with
`Switch` = the AP name and `Port` = `radio0`, `radio1`… The join `Switch` ⊂ `Device Name` holds.

* An AP is identified by its base MAC. If the AP is also polled directly (or discovered through
  LLDP/CDP), both are the same device: the polled identity is kept and the stations are added.
* An AP without a management IP is not published (every output needs an address).
* Radios (ifType `ieee80211`) are never turned into uplinks by the MAC-count threshold: many
  stations on a radio are expected. This also applies to the wireless interfaces of routers and
  to any radio reported by a standard agent.
* Synthetic devices are refreshed by every collect of the controller and forgotten after
  `general.retention_days` like any device.
* Not covered yet: Catalyst 9800 controllers (CISCO-LWAPP MIBs), Aruba and Fortinet controllers,
  UniFi (clients are only in the controller's API). A Python driver can add them.

## Standard behaviour that looked vendor-specific

Some gaps turned out to be generic and are handled for every device, without a driver:

* **Logical units** (`ge-0/0/5.0` on Juniper, `Gi0/1.10`, `eth0.100`): MACs learnt on a logical
  unit are attributed to its physical port when `ifStackTable` stacks the unit on exactly one
  interface **and** the unit is named `<port>.<number>`. The port role (LLDP neighbour, uplink
  lists, MAC count) is then evaluated where it belongs. Tunnels, IRB/VLAN interfaces and
  bundles are never folded.
* **NX-OS CDP device IDs** `hostname(SERIAL)` are cleaned.
* **Cisco per-VLAN MAC tables** are read on answer, see [troubleshooting](troubleshooting.md).

## Writing a driver

A Python extension can declare a driver with the same capabilities as the built-in ones (and is
tried before them, so it can replace one):

```python
from snowth_my_net.api import AccessPoint, Extension, Observations, Station, text

extension = Extension("acme")
acme = extension.driver("acme-os", object_ids=["1.3.6.1.4.1.99999.1"])

@acme.identity
async def identity(device, snmp):
    values = await snmp.get("1.3.6.1.4.1.99999.1.1.0")
    return {"os_version": text(values["1.3.6.1.4.1.99999.1.1.0"])}

@acme.observations
async def observations(device, snmp):
    return Observations(
        stations=[Station(mac=text(v), port=7) for _i, v in await snmp.walk("1.3.6.1.4.1.99999.2")],
        arp=[("00:00:5e:00:53:01", "192.0.2.50")],
        access_points=[AccessPoint(mac="00:00:5e:00:53:70", name="ap-1", address="192.0.2.70",
                                   stations=[Station("00:00:5e:00:53:02", port=1)])])
```

See [extensions](extensions.md#python-extensions) for loading and `snowth_my_net.testing.run_driver`
for tests without devices.

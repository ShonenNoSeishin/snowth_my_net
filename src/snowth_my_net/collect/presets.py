"""OID presets for testing a device by hand (``probe`` and the TUI OID tester).

A preset is a named group of standard columns (or scalars). Each preset lists the device types
for which it is *suggested*; it never restricts anything: every preset can be tried on every
device, and the collection itself never depends on the device type.
"""

from __future__ import annotations

from dataclasses import dataclass

from snowth_my_net.snmp import oids
from snowth_my_net.snmp.values import Oid, parse_oid

ALL_TYPES = frozenset({"switch", "router", "firewall", "wireless", "server", "printer",
                       "facility", "other"})
NETWORK = frozenset({"switch", "router", "firewall", "wireless"})
L3 = frozenset({"switch", "router", "firewall"})


@dataclass(frozen=True)
class Column:
    label: str
    oid: Oid
    kind: str = "auto"                       # auto | mac | caps | enum
    enum: tuple[tuple[int, str], ...] = ()

    def enum_name(self, value: int) -> str | None:
        return dict(self.enum).get(value)


@dataclass(frozen=True)
class Preset:
    name: str
    title_en: str
    title_fr: str
    columns: tuple[Column, ...]
    mode: str = "walk"                        # walk (table columns) | get (scalars)
    types: frozenset[str] = ALL_TYPES         # suggested for these types

    def title(self, lang: str) -> str:
        return self.title_fr if lang == "fr" else self.title_en


def _c(label: str, oid: str | Oid, kind: str = "auto", enum: dict[int, str] | None = None
       ) -> Column:
    return Column(label, parse_oid(oid) if isinstance(oid, str) else oid, kind,
                  tuple(sorted((enum or {}).items())))


STATUS_ENUM = {1: "up", 2: "down", 3: "testing", 4: "unknown", 5: "dormant", 6: "notPresent",
               7: "lowerLayerDown"}
FDB_STATUS = {1: "other", 2: "invalid", 3: "learned", 4: "self", 5: "mgmt"}
ARP_TYPE = {1: "other", 2: "invalid", 3: "dynamic", 4: "static", 5: "local"}
ARP_STATE = {1: "reachable", 2: "stale", 3: "delay", 4: "probe", 5: "invalid", 6: "unknown",
             7: "incomplete"}
ENT_CLASS = {1: "other", 2: "unknown", 3: "chassis", 4: "backplane", 5: "container",
             6: "powerSupply", 7: "fan", 8: "sensor", 9: "module", 10: "port", 11: "stack",
             12: "cpu"}
VTP_STATE = {1: "operational", 2: "suspended", 3: "mtuTooBigForDevice",
             4: "mtuTooBigForTrunk"}
UPS_BATTERY = {1: "unknown", 2: "normal", 3: "low", 4: "depleted"}

PRESETS: tuple[Preset, ...] = (
    Preset("system", "System group", "Groupe système", (
        _c("sysDescr", oids.SYS_DESCR), _c("sysObjectID", oids.SYS_OBJECT_ID),
        _c("sysName", oids.SYS_NAME), _c("sysLocation", oids.SYS_LOCATION),
        _c("sysContact", oids.SYS_CONTACT), _c("sysUpTime", oids.SYS_UPTIME),
        _c("sysServices", oids.SYS_SERVICES)), mode="get"),
    Preset("entity", "Chassis and modules (ENTITY-MIB)", "Châssis et modules (ENTITY-MIB)", (
        _c("class", oids.ENT_PHYSICAL_CLASS, "enum", ENT_CLASS),
        _c("descr", oids.ENT_PHYSICAL_DESCR), _c("model", oids.ENT_PHYSICAL_MODEL_NAME),
        _c("serial", oids.ENT_PHYSICAL_SERIAL_NUM),
        _c("software", oids.ENT_PHYSICAL_SOFTWARE_REV))),
    Preset("interfaces", "Interfaces (IF-MIB)", "Interfaces (IF-MIB)", (
        _c("ifName", oids.IF_NAME), _c("ifDescr", oids.IF_DESCR), _c("ifType", oids.IF_TYPE),
        _c("ifOperStatus", oids.IF_OPER_STATUS, "enum", STATUS_ENUM),
        _c("ifPhysAddress", oids.IF_PHYS_ADDRESS, "mac"), _c("ifAlias", oids.IF_ALIAS))),
    Preset("ip-addresses", "Device IPv4 addresses (ipAddrTable)",
           "Adresses IPv4 de l'équipement (ipAddrTable)", (
               _c("ipAdEntIfIndex", oids.IP_AD_ENT_IF_INDEX),
               _c("ipAdEntNetMask", oids.IP_AD_ENT_NET_MASK))),
    Preset("ip-address-table", "Device addresses v4/v6 (ipAddressTable)",
           "Adresses v4/v6 de l'équipement (ipAddressTable)", (
               _c("ipAddressIfIndex", oids.IP_ADDRESS_IF_INDEX),
               _c("ipAddressType", oids.IP_ADDRESS_TYPE))),
    Preset("arp-media", "ARP table (ipNetToMediaTable, legacy)",
           "Table ARP (ipNetToMediaTable, ancienne)", (
               _c("ipNetToMediaPhysAddress", oids.IP_NET_TO_MEDIA_PHYS_ADDRESS, "mac"),
               _c("ipNetToMediaType", oids.IP_NET_TO_MEDIA_TYPE, "enum", ARP_TYPE)), types=L3),
    Preset("arp-physical", "ARP/NDP table (ipNetToPhysicalTable)",
           "Table ARP/NDP (ipNetToPhysicalTable)", (
               _c("ipNetToPhysicalPhysAddress", oids.IP_NET_TO_PHYSICAL_PHYS_ADDRESS, "mac"),
               _c("ipNetToPhysicalType", oids.IP_NET_TO_PHYSICAL_TYPE, "enum", ARP_TYPE),
               _c("ipNetToPhysicalState", oids.IP_NET_TO_PHYSICAL_STATE, "enum", ARP_STATE)),
           types=L3),
    Preset("fdb-qbridge", "MAC table with VLAN (Q-BRIDGE-MIB)",
           "Table MAC avec VLAN (Q-BRIDGE-MIB)", (
        _c("dot1qTpFdbPort", oids.DOT1Q_TP_FDB_PORT),
        _c("dot1qTpFdbStatus", oids.DOT1Q_TP_FDB_STATUS, "enum", FDB_STATUS)),
        types=frozenset({"switch", "wireless"})),
    Preset("fdb-bridge", "MAC table (BRIDGE-MIB)", "Table MAC (BRIDGE-MIB)", (
        _c("dot1dTpFdbPort", oids.DOT1D_TP_FDB_PORT),
        _c("dot1dTpFdbStatus", oids.DOT1D_TP_FDB_STATUS, "enum", FDB_STATUS)),
        types=frozenset({"switch", "wireless"})),
    Preset("bridge-ports", "Bridge port to ifIndex", "Port de bridge vers ifIndex", (
        _c("dot1dBasePortIfIndex", oids.DOT1D_BASE_PORT_IF_INDEX),),
        types=frozenset({"switch", "wireless"})),
    Preset("vlans", "VLAN names (Q-BRIDGE-MIB)", "Noms des VLAN (Q-BRIDGE-MIB)", (
        _c("dot1qVlanStaticName", oids.DOT1Q_VLAN_STATIC_NAME),),
        types=frozenset({"switch"})),
    Preset("pvid", "Port VLAN (PVID)", "VLAN des ports (PVID)", (
        _c("dot1qPvid", oids.DOT1Q_PVID),), types=frozenset({"switch"})),
    Preset("cisco-vlans", "Cisco VLANs (CISCO-VTP-MIB)", "VLAN Cisco (CISCO-VTP-MIB)", (
        _c("vtpVlanState", oids.VTP_VLAN_STATE, "enum", VTP_STATE),
        _c("vtpVlanName", oids.VTP_VLAN_NAME)), types=frozenset({"switch"})),
    Preset("lldp-local", "Local LLDP ports", "Ports LLDP locaux", (
        _c("lldpLocPortIdSubtype", oids.LLDP_LOC_PORT_ID_SUBTYPE),
        _c("lldpLocPortId", oids.LLDP_LOC_PORT_ID),
        _c("lldpLocPortDesc", oids.LLDP_LOC_PORT_DESC)), types=NETWORK),
    Preset("lldp-neighbors", "LLDP neighbors", "Voisins LLDP", (
        _c("lldpRemSysName", oids.LLDP_REM_ENTRY + (9,)),
        _c("lldpRemPortId", oids.LLDP_REM_ENTRY + (7,)),
        _c("lldpRemPortDesc", oids.LLDP_REM_ENTRY + (8,)),
        _c("lldpRemChassisId", oids.LLDP_REM_ENTRY + (5,)),
        _c("lldpRemSysCapEnabled", oids.LLDP_REM_ENTRY + (12,), "caps")), types=NETWORK),
    Preset("cdp-neighbors", "CDP neighbors", "Voisins CDP", (
        _c("cdpCacheDeviceId", oids.CDP_CACHE_ENTRY + (6,)),
        _c("cdpCacheDevicePort", oids.CDP_CACHE_ENTRY + (7,)),
        _c("cdpCachePlatform", oids.CDP_CACHE_ENTRY + (8,))),
        types=frozenset({"switch", "router"})),
    Preset("printer", "Printer (Printer-MIB)", "Imprimante (Printer-MIB)", (
        _c("prtGeneralPrinterName", oids.PRT_GENERAL_ENTRY + (16,)),
        _c("prtGeneralSerialNumber", oids.PRT_GENERAL_ENTRY + (17,))),
        types=frozenset({"printer"})),
    Preset("ups", "UPS (UPS-MIB)", "Onduleur (UPS-MIB)", (
        _c("upsIdentManufacturer", "1.3.6.1.2.1.33.1.1.1.0"),
        _c("upsIdentModel", "1.3.6.1.2.1.33.1.1.2.0"),
        _c("upsIdentUPSSoftwareVersion", "1.3.6.1.2.1.33.1.1.3.0"),
        _c("upsBatteryStatus", "1.3.6.1.2.1.33.1.2.1.0", "enum", UPS_BATTERY),
        _c("upsEstimatedMinutesRemaining", "1.3.6.1.2.1.33.1.2.3.0")),
        mode="get", types=frozenset({"facility"})),
    Preset("host", "Host resources (HOST-RESOURCES-MIB)", "Ressources hôte (HOST-RESOURCES-MIB)", (
        _c("hrStorageDescr", "1.3.6.1.2.1.25.2.3.1.3"),
        _c("hrStorageSize", "1.3.6.1.2.1.25.2.3.1.5"),
        _c("hrStorageUsed", "1.3.6.1.2.1.25.2.3.1.6")), types=frozenset({"server"})),
    # Objects read by the vendor drivers: check them by hand before trusting a driver.
    Preset("fortinet", "Fortinet: serial and FortiOS version (fortinet driver)",
           "Fortinet : numéro de série et version FortiOS (driver fortinet)", (
        _c("fnSysSerial", "1.3.6.1.4.1.12356.100.1.1.1.0"),
        _c("fgSysVersion", "1.3.6.1.4.1.12356.101.4.1.1.0")),
        mode="get", types=frozenset({"firewall", "wireless", "switch"})),
    Preset("sophos-sfos", "Sophos SFOS: model, firmware, appliance key (sophos driver)",
           "Sophos SFOS : modèle, firmware, clé d'appliance (driver sophos)", (
        _c("sfosDeviceName", "1.3.6.1.4.1.2604.5.1.1.2.0"),
        _c("sfosDeviceType", "1.3.6.1.4.1.2604.5.1.1.3.0"),
        _c("sfosDeviceFWVersion", "1.3.6.1.4.1.2604.5.1.1.4.0"),
        _c("sfosDeviceAppKey", "1.3.6.1.4.1.2604.5.1.1.5.0")),
        mode="get", types=frozenset({"firewall"})),
    Preset("mikrotik", "MikroTik: board, serial, RouterOS version (mikrotik driver)",
           "MikroTik : carte, numéro de série, version RouterOS (driver mikrotik)", (
        _c("mtxrBoardName", "1.3.6.1.4.1.14988.1.1.7.8.0"),
        _c("mtxrSerialNumber", "1.3.6.1.4.1.14988.1.1.7.3.0"),
        _c("mtxrLicVersion", "1.3.6.1.4.1.14988.1.1.4.4.0")),
        mode="get", types=frozenset({"router", "wireless", "switch"})),
    Preset("mikrotik-wifi", "MikroTik: Wi-Fi stations (mikrotik driver)",
           "MikroTik : stations Wi-Fi (driver mikrotik)", (
        _c("mtxrWlRtabIface", "1.3.6.1.4.1.14988.1.1.1.2.1.2"),
        _c("mtxrWlRtabStrength", "1.3.6.1.4.1.14988.1.1.1.2.1.3")),
        types=frozenset({"router", "wireless"})),
    Preset("cisco-wlc-aps", "Cisco AireOS: access points (cisco-wlc driver)",
           "Cisco AireOS : points d'accès (driver cisco-wlc)", (
        _c("bsnAPName", "1.3.6.1.4.1.14179.2.2.1.1.3"),
        _c("bsnAPModel", "1.3.6.1.4.1.14179.2.2.1.1.16"),
        _c("bsnAPSerialNumber", "1.3.6.1.4.1.14179.2.2.1.1.17"),
        _c("bsnApIpAddress", "1.3.6.1.4.1.14179.2.2.1.1.19")),
        types=frozenset({"wireless"})),
    Preset("cisco-wlc-clients", "Cisco AireOS: clients (cisco-wlc driver)",
           "Cisco AireOS : clients (driver cisco-wlc)", (
        _c("bsnMobileStationIpAddress", "1.3.6.1.4.1.14179.2.1.4.1.2"),
        _c("bsnMobileStationAPMacAddr", "1.3.6.1.4.1.14179.2.1.4.1.4", "mac"),
        _c("bsnMobileStationAPIfSlotId", "1.3.6.1.4.1.14179.2.1.4.1.5"),
        _c("bsnMobileStationSsid", "1.3.6.1.4.1.14179.2.1.4.1.7")),
        types=frozenset({"wireless"})),
    Preset("enterprise", "Vendor private sub-tree (first values)",
           "Sous-arbre privé du constructeur (premières valeurs)", (), mode="enterprise"),
)

BY_NAME = {p.name: p for p in PRESETS}


def get_preset(name: str) -> Preset | None:
    return BY_NAME.get(name)


def suggestions(device_type: str | None) -> list[tuple[Preset, bool]]:
    """Every preset, suggested ones first. Without a type, everything is suggested."""
    if not device_type:
        return [(p, True) for p in PRESETS]
    ordered = [(p, True) for p in PRESETS if device_type in p.types]
    ordered += [(p, False) for p in PRESETS if device_type not in p.types]
    return ordered

"""SNMPv2-MIB system group plus the identity scalars fetched in the same GET."""

from __future__ import annotations

from dataclasses import dataclass

from snowth_my_net.snmp import oids
from snowth_my_net.snmp.values import Oid, decode_text, normalize_mac, oid_str

# One GET, one round trip: everything needed to identify and de-duplicate a device early.
IDENTITY_OIDS: tuple[Oid, ...] = (
    oids.SYS_DESCR, oids.SYS_OBJECT_ID, oids.SYS_UPTIME, oids.SYS_CONTACT, oids.SYS_NAME,
    oids.SYS_LOCATION, oids.SYS_SERVICES, oids.DOT1D_BASE_BRIDGE_ADDRESS,
    oids.LLDP_LOC_CHASSIS_ID_SUBTYPE, oids.LLDP_LOC_CHASSIS_ID, oids.LLDP_LOC_SYS_CAP_ENABLED,
)

LLDP_CHASSIS_SUBTYPE_MAC = 4

# LldpSystemCapabilitiesMap bit positions (IEEE 802.1AB)
LLDP_CAPS = ("other", "repeater", "bridge", "wlan_ap", "router", "telephone", "docsis", "station",
             "cvlan", "svlan", "two_port_mac_relay")


@dataclass
class SystemInfo:
    descr: str = ""
    object_id: str = ""
    uptime: int | None = None
    contact: str = ""
    name: str = ""
    location: str = ""
    services: int | None = None
    bridge_mac: str | None = None
    chassis_mac: str | None = None
    lldp_caps: int | None = None  # bit n set = capability LLDP_CAPS[n] enabled

    @property
    def base_mac(self) -> str | None:
        return self.bridge_mac or self.chassis_mac

    @property
    def pen(self) -> int | None:
        parts = self.object_id.split(".")
        if len(parts) > 6 and parts[:6] == ["1", "3", "6", "1", "4", "1"]:
            return int(parts[6])
        return None

    def lldp_cap_names(self) -> set[str]:
        return caps_names(self.lldp_caps)


def decode_lldp_caps(value: bytes | None) -> int | None:
    """``BITS`` encoding: bit 0 is the most significant bit of the first octet."""
    if not isinstance(value, bytes | bytearray) or not value:
        return None
    mask = 0
    for n in range(min(len(value) * 8, len(LLDP_CAPS))):
        if value[n // 8] & (0x80 >> (n % 8)):
            mask |= 1 << n
    return mask


def caps_names(mask: int | None) -> set[str]:
    if not mask:
        return set()
    return {name for n, name in enumerate(LLDP_CAPS) if mask & (1 << n)}


def parse_system(values: dict[Oid, object]) -> SystemInfo:
    def text(oid: Oid) -> str:
        v = values.get(oid)
        return decode_text(v) if isinstance(v, bytes | str) else ""

    def integer(oid: Oid) -> int | None:
        v = values.get(oid)
        return v if isinstance(v, int) else None

    obj = values.get(oids.SYS_OBJECT_ID)
    chassis_mac = None
    if integer(oids.LLDP_LOC_CHASSIS_ID_SUBTYPE) == LLDP_CHASSIS_SUBTYPE_MAC:
        raw = values.get(oids.LLDP_LOC_CHASSIS_ID)
        chassis_mac = normalize_mac(raw) if isinstance(raw, bytes | str) else None
    bridge = values.get(oids.DOT1D_BASE_BRIDGE_ADDRESS)
    caps = values.get(oids.LLDP_LOC_SYS_CAP_ENABLED)
    return SystemInfo(
        descr=text(oids.SYS_DESCR),
        object_id=oid_str(obj) if isinstance(obj, tuple) else "",
        uptime=integer(oids.SYS_UPTIME),
        contact=text(oids.SYS_CONTACT),
        name=text(oids.SYS_NAME),
        location=text(oids.SYS_LOCATION),
        services=integer(oids.SYS_SERVICES),
        bridge_mac=normalize_mac(bridge) if isinstance(bridge, bytes | str) else None,
        chassis_mac=chassis_mac,
        lldp_caps=decode_lldp_caps(caps if isinstance(caps, bytes) else None),
    )

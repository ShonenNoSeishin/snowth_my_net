"""Identification catalog: vendors, operating systems and device-type evidence.

Everything here is data, kept deliberately conservative: a type is attached only to evidence
that cannot be wrong within its scope (DESIGN.md §7.5); when in doubt the entry is absent and
the type stays empty. Entries were checked against public vendor product-ID MIBs and a corpus
of real identification strings (see ``tests/data/identify_corpus.jsonl``), including the
counter-examples that justify each exclusion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def _e(suffix: str) -> str:
    """Full OID of an enterprise sub-tree: ``_e("9.1.669")`` -> ``1.3.6.1.4.1.9.1.669``."""
    return f"1.3.6.1.4.1.{suffix}"


def oid_under(oid: str, prefix: str) -> bool:
    return oid == prefix or oid.startswith(prefix + ".")


# --------------------------------------------------------------------------- vendors


@dataclass(frozen=True)
class Vendor:
    name: str
    generic: bool = False  # PEN of a shared SNMP stack: says nothing about the product vendor


VENDORS: dict[int, Vendor] = {
    9: Vendor("Cisco"), 11: Vendor("HPE"), 89: Vendor("RADLAN", generic=True),
    171: Vendor("D-Link"), 232: Vendor("HPE"), 236: Vendor("Samsung"), 253: Vendor("Xerox"),
    297: Vendor("FUJIFILM"), 311: Vendor("Microsoft"), 318: Vendor("APC"), 367: Vendor("Ricoh"),
    368: Vendor("Axis"), 476: Vendor("Vertiv"), 534: Vendor("Eaton"), 641: Vendor("Lexmark"),
    674: Vendor("Dell"), 705: Vendor("Eaton"), 890: Vendor("Zyxel"), 1347: Vendor("Kyocera"),
    1602: Vendor("Canon"), 1718: Vendor("Server Technology"), 1916: Vendor("Extreme Networks"),
    2001: Vendor("OKI"), 2011: Vendor("Huawei"), 2385: Vendor("Sharp"), 2435: Vendor("Brother"),
    2604: Vendor("Sophos"), 2606: Vendor("Rittal"), 2620: Vendor("Check Point"),
    2636: Vendor("Juniper"), 3854: Vendor("AKCP"), 4413: Vendor("Broadcom", generic=True),
    4526: Vendor("Netgear"), 4555: Vendor("Socomec"), 5491: Vendor("Riello"),
    6027: Vendor("Dell"), 6486: Vendor("Alcatel-Lucent Enterprise"), 6574: Vendor("Synology"),
    6876: Vendor("VMware"), 8072: Vendor("net-snmp", generic=True), 8741: Vendor("SonicWall"),
    10642: Vendor("Zebra"), 11863: Vendor("TP-Link"), 12356: Vendor("Fortinet"),
    13742: Vendor("Raritan"), 14179: Vendor("Cisco"), 14823: Vendor("HPE Aruba"),
    14988: Vendor("MikroTik"), 15983: Vendor("Fortinet"), 18334: Vendor("Konica Minolta"),
    20916: Vendor("AVTECH"), 21239: Vendor("Vertiv"), 24681: Vendor("QNAP"),
    25053: Vendor("Ruckus"), 25461: Vendor("Palo Alto Networks"), 25506: Vendor("H3C"),
    26928: Vendor("Aerohive"), 29671: Vendor("Cisco Meraki"), 30065: Vendor("Arista"),
    30803: Vendor("Vyatta"), 40310: Vendor("Cumulus Networks"), 41112: Vendor("Ubiquiti"),
    44641: Vendor("VyOS"), 47196: Vendor("HPE Aruba"),
}

# Brand split inside one known PEN: (PEN, pattern on sysDescr, vendor).
VENDOR_SPLITS: tuple[tuple[int, re.Pattern[str], str], ...] = (
    (25506, re.compile(r"^HPE?\b"), "HPE"),
)

# Only for unknown or generic PENs: unmistakable product banners naming their vendor.
VENDOR_FROM_DESCR: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(?:UAP|USW|U6|U7|UCG|UDM|UXG)-|^US-\d|^EdgeSwitch\b|^Ubiquiti\b"), "Ubiquiti"),
    (re.compile(r"Cisco Small Business|Cisco Systems, Inc\b"), "Cisco"),
    (re.compile(r"^Juniper Networks, Inc\."), "Juniper"),
)


# --------------------------------------------------------------------------- operating systems


@dataclass(frozen=True)
class OsRule:
    os: str
    match: re.Pattern[str] | None = None      # sysDescr must match (when set)
    oid: str | None = None                    # sysObjectID must be under this OID (when set)
    exact: bool = False                       # ... or be exactly this OID
    vendors: frozenset[str] | None = None     # vendor must be one of these (when set)
    version: re.Pattern[str] | None = None    # group "v" (and optional "r") on sysDescr
    version_format: str = "{v}"
    sole_type: str | None = None              # this OS only runs on this kind of device


def _re(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.DOTALL)


_CISCO = frozenset({"Cisco"})
_HPE = frozenset({"HPE", "HPE Aruba", "H3C"})
_CISCO_VERSION = _re(r"Version (?P<v>[\w.()\-]+)")

# First matching rule wins: specific before generic.
OS_RULES: tuple[OsRule, ...] = (
    OsRule("IOS-XR", _re(r"Cisco IOS XR Software"), vendors=_CISCO, version=_CISCO_VERSION,
           sole_type="router"),
    OsRule("FTD", _re(r"Cisco Fire[Pp][Oo][Ww][Ee][Rr] Threat Defense"), vendors=_CISCO,
           version=_re(r"Threat Defense, Version (?P<v>[\w.()\-]+)"), sole_type="firewall"),
    OsRule("ASA", _re(r"Cisco Adaptive Security Appliance"), vendors=_CISCO,
           version=_re(r"Appliance Version (?P<v>[\w.()\-]+)"), sole_type="firewall"),
    OsRule("NX-OS", _re(r"Cisco NX-OS"), vendors=_CISCO, version=_CISCO_VERSION,
           sole_type="switch"),
    OsRule("IOS-XE", _re(r"IOS[- ]XE|IOSXE|LINUX_IOSD"), vendors=_CISCO, version=_CISCO_VERSION),
    OsRule("AireOS", _re(r"^Cisco Controller\b"), vendors=_CISCO, sole_type="wireless"),
    OsRule("IOS", _re(r"Cisco IOS Software|Cisco Internetwork Operating System"),
           vendors=_CISCO, version=_CISCO_VERSION),
    OsRule("AOS-CX", oid=_e("47196.4.1.1.1"),
           version=_re(r"\b(?P<v>[A-Z]{2}\.10\.\d{2}\.\d{4,})\b"), sole_type="switch"),
    OsRule("ArubaOS-Switch", _re(r"revision [A-Z]{1,2}\.\d{2}\.\d{2}"), vendors=_HPE,
           version=_re(r"revision (?P<v>[A-Z]{1,2}\.\d{2}\.\d{2}(?:\.\d{4})?)"),
           sole_type="switch"),
    OsRule("Comware", _re(r"Comware (?:Platform )?Software"), vendors=_HPE,
           version=_re(r"Software Version (?P<v>[\d.]+)(?:,? Release (?P<r>\w+))?"),
           version_format="{v} R{r}"),
    OsRule("ArubaOS", _re(r"^(?:ArubaOS|AOS-8|AOS-W)\b"),
           vendors=frozenset({"HPE Aruba", "Dell", "Alcatel-Lucent Enterprise"}),
           version=_re(r"Version (?P<v>[\w.\-]+)")),
    OsRule("Junos", _re(r"\bJUNOS\b"), vendors=frozenset({"Juniper"}),
           version=_re(r"JUNOS (?P<v>[\w.\-]+)")),
    OsRule("OS10", oid=_e("674.11000.5000.100.2"),
           version=_re(r"OS Version: (?P<v>[\w.\-]+)"), sole_type="switch"),
    OsRule("OS9", oid=_e("6027.1"),
           version=_re(r"Application Software Version: (?P<v>[\w.()\-]+)"), sole_type="switch"),
    OsRule("EOS", _re(r"Arista Networks EOS"), vendors=frozenset({"Arista"}),
           version=_re(r"EOS version (?P<v>[\w.\-]+)")),
    OsRule("FortiOS", oid=_e("12356.101.1"), sole_type="firewall"),
    OsRule("FortiOS", oid=_e("12356.15"), sole_type="firewall"),
    OsRule("FortiSwitchOS", oid=_e("12356.106"), sole_type="switch"),
    OsRule("FortiAP", oid=_e("12356.120.10"), sole_type="wireless"),
    OsRule("SFOS", oid=_e("2604.5"), exact=True, sole_type="firewall"),
    OsRule("PAN-OS", vendors=frozenset({"Palo Alto Networks"})),
    OsRule("SwOS", oid=_e("14988.2"), version=_re(r"SwOS v(?P<v>[\d.]+)"), sole_type="switch"),
    OsRule("RouterOS", oid=_e("14988.1"), version=_re(r"^RouterOS \S+ (?P<v>\d[\w.]*)")),
    OsRule("EdgeOS", _re(r"^EdgeOS\b"), vendors=frozenset({"Ubiquiti"}),
           version=_re(r"^EdgeOS v(?P<v>[\d.]+)"), sole_type="router"),
    OsRule("EdgeSwitch", _re(r"^EdgeSwitch\b"), vendors=frozenset({"Ubiquiti"}),
           version=_re(r"^EdgeSwitch[^,]*, (?P<v>[\d.]+)"), sole_type="switch"),
    OsRule("Cumulus Linux", oid=_e("40310"), sole_type="switch"),
    OsRule("ESXi", _re(r"VMware ESXi"), vendors=frozenset({"VMware"}),
           version=_re(r"VMware ESXi (?P<v>[\d.]+)"), sole_type="server"),
    OsRule("Windows", _re(r"Software: Windows"), vendors=frozenset({"Microsoft"}),
           version=_re(r"Windows Version (?P<v>[\d.]+)")),
    OsRule("Linux", _re(r"^Linux "), version=_re(r"^Linux \S+ (?P<v>[\w.\-+~]+)")),
)

# Model from sysDescr when ENTITY-MIB has no chassis model (vendor-scoped).
MODEL_FROM_DESCR: dict[str, tuple[re.Pattern[str], ...]] = {
    "Juniper": (_re(r"^Juniper Networks, Inc\. (?P<m>[\w\-]+)"),
                _re(r"^Juniper (?P<m>SRX\w+)")),
    "Arista": (_re(r"running on an Arista Networks (?P<m>[\w\-]+)"),),
    "Dell": (_re(r"System Type: (?P<m>[\w\-]+)"), _re(r"Series: (?P<m>[\w\-]+)"),
             _re(r"^(?P<m>PowerConnect [\w\-]+)"),
             _re(r"^Dell (?:EMC )?Networking (?P<m>N\d{4}\w*)")),
    "MikroTik": (_re(r"^RouterOS (?P<m>[\w\-+]+)"), _re(r"^(?P<m>CSS\d[\w\-+]*) SwOS")),
    "Fortinet": (_re(r"^(?P<m>Forti(?:Gate|WiFi|Switch)-[\w\-]+)"),),
    "Ubiquiti": (_re(r"^(?P<m>(?:UAP|USW|U6|U7)-[\w\-+]+|E7|EdgeRouter[\w\- ]*?|"
                     r"EdgeSwitch)\b"),),
    "Cisco": (_re(r"\((?P<m>C\d{4}-[\w\-]+)\)"), _re(r"Cisco (?P<m>RV\d{3}\w*)"),
              _re(r"(?:Cisco Systems, Inc|Cisco Small Business) (?P<m>WAP\d{3}\w*)")),
    "Cisco Meraki": (_re(r"^=?(?:Meraki )?(?P<m>(?:MR|MS|MX|CW)\d+\w*|C9[2-6]\d\d)"),),
    "Netgear": (_re(r"^(?P<m>(?:GS|GSM|XS|XSM|MS|M4)\d{3}\w*)"),),
}


# --------------------------------------------------------------------------- device types


@dataclass(frozen=True)
class OidRule:
    """Rule 2: a sysObjectID sub-tree whose products are all of one type (vendor-scoped by
    construction since the prefix contains the PEN)."""

    prefix: str
    device_type: str
    label: str
    exact: bool = False
    exclude: tuple[str, ...] = ()

    def matches(self, oid: str) -> bool:
        hit = oid == self.prefix if self.exact else oid_under(oid, self.prefix)
        return hit and not any(oid_under(oid, e) for e in self.exclude)


def _ids(base: str, ids, device_type: str, label: str) -> tuple[OidRule, ...]:
    return tuple(OidRule(_e(f"{base}.{i}"), device_type, label) for i in ids)


_CISCO_FIREWALL_IDS = (
    669, 670, 672, 745, 753, 914, 1101, *range(1194, 1206), *range(1302, 1314), 1275, 1276,
    1277, 1334, 1335, 1336, *range(1407, 1412), 1902, 2114, 2294, 2295, 2313, 2315, 2319,
    *range(2404, 2410), 2483, 2662, 2663, 2774, 2775, 2778, 2870, 2991, 3041, 3043,
    *range(3053, 3058), 3166, 3257, 3305,
)
_CISCO_WLC_IDS = (818, 828, 1069, 1279, 1295, 1615, 1631, 1926, 1927, 2170, 2171, 2427, 1645,
                  2026, 2067, 2391, 2530, 2669, 2860, 2861)
_JUNIPER_ROUTERS = (21, 25, 29, 57, 69, 87, 88, 89, 90, 97, 108, 152, 154, 155, 167)
_JUNIPER_FIREWALLS = (26, 28, 34, 35, 36, 39, 40, 41, 49, 58, 64, 65, 86, 129, 133, 134, 135,
                      136, 137, 140, 141, 142, 143, 164)
_JUNIPER_SWITCHES = (30, 31, 32, 33, 43, 44, 63, 76, 82, 85, 109, 131, 132, 169)

TYPE_BY_OID: tuple[OidRule, ...] = (
    # Cisco
    *_ids("9.1", _CISCO_FIREWALL_IDS, "firewall", "Cisco ASA/Firepower product id"),
    *_ids("9.1", _CISCO_WLC_IDS, "wireless", "Cisco wireless controller product id"),
    *_ids("9.1", (3280, 3281, 3282), "wireless", "Cisco industrial access point product id"),
    *_ids("9.1", (1018, 1639, 2349, 2413, 3006), "router", "Cisco IOS-XR router product id"),
    OidRule(_e("14179.1.1.4.3"), "wireless", "Airespace/Cisco wireless controller"),
    OidRule(_e("9.12.3.1.3"), "switch", "Cisco cevChassis (Nexus/MDS) product id"),
    OidRule(_e("9.6.1.23"), "router", "Cisco Small Business RV router"),
    *_ids("9.6.1", (31, 32, 34), "wireless", "Cisco Small Business access point"),
    OidRule(_e("9.6.1.37.240"), "wireless", "Cisco Business Wireless"),
    # HPE / Aruba
    OidRule(_e("11.2.3.7.11"), "switch", "HP ProCurve/Aruba switch product id",
            exclude=(_e("11.2.3.7.11.37"), _e("11.2.3.7.11.38"), _e("11.2.3.7.11.39"),
                     _e("11.2.3.7.11.40"), _e("11.2.3.7.11.54"))),
    OidRule(_e("11.2.3.7.8.5"), "switch", "HP ProCurve stack"),
    OidRule(_e("47196.4.1.1.1"), "switch", "HPE Aruba AOS-CX device id"),
    OidRule(_e("14823.1.2"), "wireless", "Aruba access point product id"),
    # Juniper (ids are interleaved: explicit table)
    *_ids("2636.1.1.1.2", _JUNIPER_ROUTERS, "router", "Juniper MX/PTX/ACX product id"),
    *_ids("2636.1.1.1.2", _JUNIPER_FIREWALLS, "firewall", "Juniper SRX product id"),
    *_ids("2636.1.1.1.2", _JUNIPER_SWITCHES, "switch", "Juniper EX/QFX product id"),
    *_ids("2636.1.1.1.4", (63, 82, 131), "switch", "Juniper EX/QFX product variation"),
    # Fortinet, Sophos, SonicWall
    OidRule(_e("12356.101.1"), "firewall", "FortiGate/FortiWiFi product id"),
    OidRule(_e("12356.15"), "firewall", "FortiGate (legacy product id)"),
    OidRule(_e("12356.106"), "switch", "FortiSwitch product id"),
    OidRule(_e("12356.120.10"), "wireless", "FortiAP product id"),
    OidRule(_e("15983.1.1"), "wireless", "Meru/FortiWLC controller"),
    OidRule(_e("2604.5"), "firewall", "Sophos Firewall (SFOS)", exact=True),
    OidRule(_e("8741.1"), "firewall", "SonicWall TZ/NSA firewall"),
    # Dell
    OidRule(_e("674.11000.5000.100.2"), "switch", "Dell OS10 switch product id"),
    OidRule(_e("6027.1"), "switch", "Dell/Force10 switch product id"),
    OidRule(_e("674.10898"), "printer", "Dell printer product id"),
    OidRule(_e("674.10902.2"), "facility", "Dell UPS"),
    OidRule(_e("674.10903.200.3"), "facility", "Dell rack PDU"),
    # Others
    OidRule(_e("30065.1.3011"), "switch", "Arista DCS switch product id"),
    OidRule(_e("14988.2"), "switch", "MikroTik SwOS switch"),
    OidRule(_e("41112.1.4"), "wireless", "Ubiquiti airMAX"),
    OidRule(_e("26928.1"), "wireless", "Aerohive access point"),
    *_ids("25053.3.1", (4, 5), "wireless", "Ruckus access point"),
    OidRule(_e("6486.800.1.1.2.2.2"), "wireless", "Alcatel-Lucent OmniAccess WLAN"),
    OidRule(_e("40310"), "switch", "Cumulus Linux"),
    OidRule(_e("44641"), "router", "VyOS"),
    OidRule(_e("30803"), "router", "Vyatta"),
    OidRule(_e("311.1.1.3.1.1"), "other", "Microsoft Windows workstation product OID"),
    OidRule(_e("311.1.1.3.1.2"), "server", "Microsoft Windows server product OID"),
    OidRule(_e("311.1.1.3.1.3"), "server", "Microsoft Windows domain controller product OID"),
    OidRule(_e("6876.4.1"), "server", "VMware ESXi", exact=True),
    # Printers without Printer-MIB are still printers
    OidRule(_e("11.2.3.9.1"), "printer", "HP JetDirect"),
    OidRule(_e("11.1"), "printer", "HP JetDirect", exact=True),
    OidRule(_e("2435.2.3.9.1"), "printer", "Brother printer"),
    *_ids("1602.4", (2, 3, 7), "printer", "Canon printer"),
    OidRule(_e("367.1.1"), "printer", "Ricoh printer"),
    OidRule(_e("253.8.62.1"), "printer", "Xerox printer"),
    OidRule(_e("297.1.11.93"), "printer", "FUJIFILM/Fuji Xerox printer"),
    OidRule(_e("18334.1"), "printer", "Konica Minolta printer"),
    OidRule(_e("2385.3.1"), "printer", "Sharp printer"),
    OidRule(_e("2001.1.1.1.1"), "printer", "OKI printer"),
    OidRule(_e("10642"), "printer", "Zebra printer"),
    OidRule(_e("236.11.5"), "printer", "Samsung printer"),
    OidRule(_e("1347.41"), "printer", "Kyocera printer"),
    # Facility sub-trees of multi-product vendors
    *_ids("13742", (4, 6, 8), "facility", "Raritan PDU / environment monitor"),
    *_ids("21239", ("42.1", 2, "5.1"), "facility", "Geist/Vertiv PDU or environment monitor"),
    *_ids("1718", (3, 4), "facility", "Server Technology PDU"),
    *_ids("232.165", (3, 5, 7, 11), "facility", "HPE UPS/PDU"),
)


@dataclass(frozen=True)
class ModelRule:
    pattern: re.Pattern[str]
    device_type: str
    label: str


def _m(pattern: str, device_type: str, label: str, flags: int = 0) -> ModelRule:
    return ModelRule(re.compile(pattern, flags), device_type, label)


# Rule 2b: model families, ALWAYS scoped to their vendor ("S4148" is a switch only at Dell).
# Applied to the chassis model (ENTITY-MIB) or the vendor-scoped model from sysDescr.
TYPE_BY_MODEL: dict[str, tuple[ModelRule, ...]] = {
    "Cisco": (
        _m(r"^(C9800|AIR-CT)", "wireless", "Cisco wireless controller"),
        _m(r"^(AIR-[A-Z]*AP|C91\d\dAX|CW91\d\d|WAP\d{3})", "wireless", "Cisco access point"),
        _m(r"^(WS-C|C9[2-6]\d\d|C1000-|C1200-|C1300-|CBS\d{3}-|SG\d{3}-|SF\d{3}-|IE-\d|N\dK-)",
           "switch", "Cisco switch family"),
        _m(r"^(ISR\d|C11\d\d|C8[235]\d\d|ASR\d|CISCO[1-4]9\d\d|RV\d{3})", "router",
           "Cisco router family"),
        _m(r"^(ASA\d|FPR-?\d|Firepower)", "firewall", "Cisco firewall family"),
    ),
    "Cisco Meraki": (
        _m(r"^(MR|CW)\d", "wireless", "Meraki access point"),
        _m(r"^(MS\d|C9[2-6]\d\d)", "switch", "Meraki switch"),
    ),
    "Juniper": (
        _m(r"^(ex|qfx)\d", "switch", "Juniper EX/QFX", re.I),
        _m(r"^v?srx\d*", "firewall", "Juniper SRX", re.I),
        _m(r"^(v?mx|ptx|acx)\d*\b", "router", "Juniper MX/PTX/ACX", re.I),
    ),
    "Dell": (
        _m(r"^PowerConnect W-", "wireless", "Dell PowerConnect W (Aruba controller)"),
        _m(r"^(S\d{4}[A-Z]*-ON|Z\d{4}[A-Z]*-ON|N\d{4}[A-Z]*|PowerConnect \d)", "switch",
           "Dell networking switch family"),
    ),
    "Fortinet": (
        _m(r"^(FortiGate|FortiWiFi|FGT|FWF|FGR)", "firewall", "FortiGate"),
        _m(r"^(FortiSwitch|FSW|FS-\d)", "switch", "FortiSwitch"),
        _m(r"^(FortiAP|FAP)", "wireless", "FortiAP"),
    ),
    "MikroTik": (
        _m(r"^(CRS\d|CSS\d)", "switch", "MikroTik CRS/CSS"),
        _m(r"^CCR\d", "router", "MikroTik CCR"),
        _m(r"^(cAP|wAP)\b", "wireless", "MikroTik cAP/wAP"),
    ),
    "Ubiquiti": (
        _m(r"^(UAP|U6|U7)-|^E7$", "wireless", "UniFi access point"),
        _m(r"^(USW|US)-|^EdgeSwitch$", "switch", "UniFi/EdgeSwitch switch"),
        _m(r"^EdgeRouter", "router", "EdgeRouter"),
    ),
    "Netgear": (
        _m(r"^(GS|GSM|XS|XSM|M4)\d{3}", "switch", "Netgear switch family"),
        _m(r"^WA[CX]\d", "wireless", "Netgear access point"),
    ),
}


@dataclass(frozen=True)
class VendorRule:
    """Rule 4: every SNMP-managed product of the PEN is of one type (minus explicit vetoes)."""

    pen: int
    device_type: str
    label: str
    exclude: tuple[str, ...] = ()
    veto: re.Pattern[str] | None = None


TYPE_BY_VENDOR: dict[int, VendorRule] = {r.pen: r for r in (
    VendorRule(318, "facility", "APC makes power, cooling and environment equipment",
               exclude=(_e("318.1.3.33"),)),              # PowerChute: software on a host
    VendorRule(534, "facility", "Eaton network cards manage power equipment",
               exclude=(_e("534.2.4"),)),                 # onlinetDaemon: host software
    VendorRule(705, "facility", "Eaton (MGE) UPS and PDUs"),
    VendorRule(2606, "facility", "Rittal racks, power and climate equipment"),
    VendorRule(476, "facility", "Liebert/Vertiv power and cooling equipment"),
    VendorRule(5491, "facility", "Riello UPS"),
    VendorRule(4555, "facility", "Socomec UPS and PDUs"),
    VendorRule(3854, "facility", "AKCP environment monitors"),
    VendorRule(20916, "facility", "AVTECH Room Alert environment monitors"),
    VendorRule(641, "printer", "Lexmark makes only printers"),
    VendorRule(25461, "firewall", "Palo Alto Networks next-generation firewalls",
               exclude=(_e("25461.2.3.7"), _e("25461.2.3.30"), _e("25461.2.3.32"),
                        _e("25461.2.3.33")),              # Panorama, M-100, GP-100, WF-500
               veto=re.compile(r"Panorama|WildFire|\bM-\d{3}\b|\bGP-\d{3}\b|\bWF-\d{3}\b", re.I)),
)}

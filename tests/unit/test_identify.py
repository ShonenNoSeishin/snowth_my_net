import json
from collections import Counter
from pathlib import Path

import pytest

from snowth_my_net.collect.identify import factory_name_reason, identify
from snowth_my_net.collect.model import TypeEvidence
from snowth_my_net.collect.tables.entity import Chassis
from snowth_my_net.collect.tables.system import SystemInfo

CORPUS = Path(__file__).resolve().parents[1] / "data" / "identify_corpus.jsonl"
RECORDS = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines()]


def run(descr="", oid="", model="", printer=False, ups=False, caps=None, override=None):
    system = SystemInfo(descr=descr, object_id=oid, lldp_caps=caps)
    chassis = [Chassis(index=1, model=model)] if model else []
    return identify(system, chassis, TypeEvidence(printer_mib=printer, ups_mib=ups), override)


@pytest.mark.parametrize("rec", RECORDS, ids=[r["id"] for r in RECORDS])
def test_corpus_record(rec):
    ident = run(rec["sysDescr"], rec["sysObjectID"], rec["model"], rec["printer_mib"],
                rec["ups_mib"])
    assert ident.device_type in ("", rec["truth"]), "a wrong type is worse than no type"
    assert ident.device_type == rec["expect"]


def test_corpus_has_as_many_empty_cases_as_typed_ones():
    counts = Counter(bool(r["expect"]) for r in RECORDS)
    assert counts[False] >= counts[True] > 100


# Bits of lldpLocSysCapEnabled as stored (bit n = capability n): bridge=4, wlan_ap=8,
# router=16, telephone=32.
BRIDGE, WLAN, ROUTER, PHONE = 1 << 2, 1 << 3, 1 << 4, 1 << 5


@pytest.mark.parametrize(
    "caps, expected",
    [(WLAN | BRIDGE, "wireless"), (WLAN | ROUTER, ""), (BRIDGE | ROUTER, ""), (BRIDGE, ""),
     (PHONE | BRIDGE, ""), (None, "")],
)
def test_own_lldp_capabilities(caps, expected):
    assert run("Some device", "1.3.6.1.4.1.99999.1", caps=caps).device_type == expected


def test_rule_order_and_override():
    ident = run("x", "1.3.6.1.4.1.8072.3.2.10", printer=True)
    assert (ident.device_type, ident.type_rule) == ("printer", "function_mib")
    ident = run("x", "1.3.6.1.4.1.99999.3", ups=True)
    assert (ident.device_type, ident.type_rule) == ("facility", "function_mib")
    ident = run("x", "1.3.6.1.4.1.8072.3.2.10", override="server")
    assert (ident.device_type, ident.type_rule) == ("server", "config")


def test_never_evidence():
    # Linux / net-snmp, multi-type vendors, bare part numbers: always empty.
    assert run("Linux fw01 5.15.0 #1 SMP x86_64", "1.3.6.1.4.1.8072.3.2.10").device_type == ""
    assert run("Cisco IOS Software, C800 Software", "1.3.6.1.4.1.9.1.99999").device_type == ""
    assert run("HP J9772A 2530-48G", "1.3.6.1.4.1.11.9.9", model="J9772A").device_type == ""
    assert run("RouterOS RB951G-2HnD", "1.3.6.1.4.1.14988.1").device_type == ""


def test_model_families_are_scoped_to_their_vendor():
    dell = run("Dell EMC Networking OS10 Enterprise.", "1.3.6.1.4.1.674.99", model="S4148F-ON")
    assert dell.device_type == "switch"
    other = run("Some box", "1.3.6.1.4.1.99999.9", model="S4148F-ON")
    assert other.device_type == ""


def test_palo_alto_vetoes():
    fw = run("Palo Alto Networks PA-3200 series firewall", "1.3.6.1.4.1.25461.2.3.20")
    assert (fw.device_type, fw.type_rule) == ("firewall", "vendor")
    assert run("Palo Alto Networks", "1.3.6.1.4.1.25461").device_type == "firewall"
    assert run("Palo Alto Networks Panorama", "1.3.6.1.4.1.25461.2.3.7").device_type == ""
    assert run("Palo Alto Networks M-100", "1.3.6.1.4.1.25461.2.3.99").device_type == ""


def test_facility_vendor_exclusions():
    assert run("APC Web/SNMP Management Card", "1.3.6.1.4.1.318.1.3.27").device_type == "facility"
    assert run("PowerChute Business Edition", "1.3.6.1.4.1.318.1.3.33.1").device_type == ""


def test_juniper_srx_is_a_firewall_despite_its_banner():
    ident = run("Juniper Networks, Inc. srx340 internet router, kernel JUNOS 15.1X49-D120.3",
                "1.3.6.1.4.1.2636.1.1.1.2.9999")
    assert (ident.device_type, ident.model, ident.os_name) == ("firewall", "srx340", "Junos")
    assert ident.os_version == "15.1X49-D120.3"


@pytest.mark.parametrize(
    "vendor_oid, descr, os_name, version",
    [
        ("9.1.2494", "Cisco IOS Software [Cupertino], Catalyst L3 Switch Software (CAT9K_IOSXE), "
         "Version 17.9.4, RELEASE SOFTWARE (fc5)", "IOS-XE", "17.9.4"),
        ("9.1.1208", "Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M), Version "
         "15.2(7)E4, RELEASE SOFTWARE (fc2)", "IOS", "15.2(7)E4"),
        ("9.12.3.1.3.1955", "Cisco NX-OS(tm) nxos.9.3.8.bin, Software (nxos), Version 9.3(8), "
         "RELEASE SOFTWARE", "NX-OS", "9.3(8)"),
        ("9.1.2409", "Cisco Firepower Threat Defense, Version 7.2.5 (Build 208), ASA Version "
         "9.18(3)", "FTD", "7.2.5"),
        ("25506.11.1.120", "HPE Comware Platform Software, Software Version 7.1.070, Release "
         "3208P03", "Comware", "7.1.070 R3208P03"),
        ("30065.1.3011.7050", "Arista Networks EOS version 4.28.3M running on an Arista Networks "
         "DCS-7050SX3-48YC8", "EOS", "4.28.3M"),
        ("11.2.3.7.11.139", "HP J9775A 2530-48G Switch, revision YA.16.11.0014, ROM YA.15.20",
         "ArubaOS-Switch", "YA.16.11.0014"),
        ("47196.4.1.1.1.254", "Aruba JL679A 6100 12G CL4 2SFP+ 139W Swch PL.10.13.1005",
         "AOS-CX", "PL.10.13.1005"),
        ("2604.5", "Linux localhost 6.6.44 #1 SMP x86_64", "SFOS", ""),
        ("14988.2", "CSS326-24G-2S+ SwOS v2.18", "SwOS", "2.18"),
    ],
)
def test_operating_systems(vendor_oid, descr, os_name, version):
    ident = run(descr, f"1.3.6.1.4.1.{vendor_oid}")
    assert (ident.os_name, ident.os_version) == (os_name, version)


def test_os_version_falls_back_to_entity_software_revision():
    system = SystemInfo(descr="Some switch", object_id="1.3.6.1.4.1.99999.5")
    ident = identify(system, [Chassis(index=1, model="X", sw_rev="3.2.1")], TypeEvidence())
    assert ident.os_version == "3.2.1" and ident.os_name == ""


def test_hpe_brand_inside_the_h3c_pen():
    assert run("HPE Comware Platform Software", "1.3.6.1.4.1.25506.11.1.1").vendor == "HPE"
    assert run("H3C Comware Platform Software", "1.3.6.1.4.1.25506.1.1").vendor == "H3C"


@pytest.mark.parametrize(
    "name, model, descr, flagged",
    [
        ("Switch", "", "", True),
        ("ProCurve Switch 2510-48", "J9020A",
         "ProCurve J9020A Switch 2510-48, revision Q.11.17", True),
        ("C9300-48P", "C9300-48P", "", True),
        ("", "", "", True),
        ("core-01", "C9300-48P", "Cisco IOS Software", False),
        ("sw floor 2", "", "Managed switch", False),
    ],
)
def test_factory_sysnames(name, model, descr, flagged):
    assert (factory_name_reason(name, model, descr) is not None) is flagged

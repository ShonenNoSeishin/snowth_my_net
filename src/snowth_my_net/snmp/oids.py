"""Numeric OIDs used by snowth_my_net (no MIB compilation, no pysmi at run time)."""

from __future__ import annotations

from snowth_my_net.snmp.values import parse_oid as _o

# SNMPv2-MIB system group (scalars, ".0" instances)
SYS_DESCR = _o("1.3.6.1.2.1.1.1.0")
SYS_OBJECT_ID = _o("1.3.6.1.2.1.1.2.0")
SYS_UPTIME = _o("1.3.6.1.2.1.1.3.0")
SYS_CONTACT = _o("1.3.6.1.2.1.1.4.0")
SYS_NAME = _o("1.3.6.1.2.1.1.5.0")
SYS_LOCATION = _o("1.3.6.1.2.1.1.6.0")
SYS_SERVICES = _o("1.3.6.1.2.1.1.7.0")

# BRIDGE-MIB scalars
DOT1D_BASE_BRIDGE_ADDRESS = _o("1.3.6.1.2.1.17.1.1.0")

# LLDP-MIB local system scalars
LLDP_LOC_CHASSIS_ID_SUBTYPE = _o("1.0.8802.1.1.2.1.3.1.0")
LLDP_LOC_CHASSIS_ID = _o("1.0.8802.1.1.2.1.3.2.0")
LLDP_LOC_SYS_CAP_ENABLED = _o("1.0.8802.1.1.2.1.3.6.0")

# ENTITY-MIB entPhysicalTable columns
ENT_PHYSICAL_ENTRY = _o("1.3.6.1.2.1.47.1.1.1.1")
ENT_PHYSICAL_DESCR = ENT_PHYSICAL_ENTRY + (2,)
ENT_PHYSICAL_CONTAINED_IN = ENT_PHYSICAL_ENTRY + (4,)
ENT_PHYSICAL_CLASS = ENT_PHYSICAL_ENTRY + (5,)
ENT_PHYSICAL_NAME = ENT_PHYSICAL_ENTRY + (7,)
ENT_PHYSICAL_SOFTWARE_REV = ENT_PHYSICAL_ENTRY + (10,)
ENT_PHYSICAL_SERIAL_NUM = ENT_PHYSICAL_ENTRY + (11,)
ENT_PHYSICAL_MODEL_NAME = ENT_PHYSICAL_ENTRY + (13,)

# IF-MIB
IF_ENTRY = _o("1.3.6.1.2.1.2.2.1")
IF_DESCR = IF_ENTRY + (2,)
IF_TYPE = IF_ENTRY + (3,)
IF_SPEED = IF_ENTRY + (5,)
IF_PHYS_ADDRESS = IF_ENTRY + (6,)
IF_ADMIN_STATUS = IF_ENTRY + (7,)
IF_OPER_STATUS = IF_ENTRY + (8,)
IFX_ENTRY = _o("1.3.6.1.2.1.31.1.1.1")
IF_NAME = IFX_ENTRY + (1,)
IF_HIGH_SPEED = IFX_ENTRY + (15,)
IF_ALIAS = IFX_ENTRY + (18,)
IF_STACK_STATUS = _o("1.3.6.1.2.1.31.1.2.1.3")
# IEEE8023-LAG-MIB dot3adAggPortAttachedAggID
DOT3AD_AGG_PORT_ATTACHED_AGG_ID = _o("1.2.840.10006.300.43.1.2.1.1.13")

# IP-MIB device addresses
IP_AD_ENT_IF_INDEX = _o("1.3.6.1.2.1.4.20.1.2")
IP_AD_ENT_NET_MASK = _o("1.3.6.1.2.1.4.20.1.3")
IP_ADDRESS_IF_INDEX = _o("1.3.6.1.2.1.4.34.1.3")
IP_ADDRESS_TYPE = _o("1.3.6.1.2.1.4.34.1.4")
IP_ADDRESS_PREFIX = _o("1.3.6.1.2.1.4.34.1.5")

# BRIDGE-MIB / Q-BRIDGE-MIB forwarding databases
DOT1D_BASE_PORT_IF_INDEX = _o("1.3.6.1.2.1.17.1.4.1.2")
DOT1D_TP_FDB_PORT = _o("1.3.6.1.2.1.17.4.3.1.2")
DOT1D_TP_FDB_STATUS = _o("1.3.6.1.2.1.17.4.3.1.3")
DOT1Q_TP_FDB_PORT = _o("1.3.6.1.2.1.17.7.1.2.2.1.2")
DOT1Q_TP_FDB_STATUS = _o("1.3.6.1.2.1.17.7.1.2.2.1.3")
DOT1Q_VLAN_FDB_ID = _o("1.3.6.1.2.1.17.7.1.4.2.1.3")
DOT1Q_VLAN_STATIC_NAME = _o("1.3.6.1.2.1.17.7.1.4.3.1.1")
DOT1Q_PVID = _o("1.3.6.1.2.1.17.7.1.4.5.1.1")

# CISCO-VTP-MIB / CISCO-VLAN-MEMBERSHIP-MIB
VTP_VLAN_STATE = _o("1.3.6.1.4.1.9.9.46.1.3.1.1.2")
# VRF names, to read the ARP of non-global VRFs in their own SNMP context.
CV_VRF_NAME = _o("1.3.6.1.4.1.9.9.711.1.1.1.1.2")            # CISCO-VRF-MIB cvVrfName
MPLS_L3VPN_VRF_OPER_STATUS = _o("1.3.6.1.2.1.10.166.11.1.2.2.1.6")   # index = the VRF name
VTP_VLAN_NAME = _o("1.3.6.1.4.1.9.9.46.1.3.1.1.4")
VM_VLAN = _o("1.3.6.1.4.1.9.9.68.1.2.2.1.2")

# IP-MIB neighbour caches (ARP / NDP)
IP_NET_TO_PHYSICAL_PHYS_ADDRESS = _o("1.3.6.1.2.1.4.35.1.4")
IP_NET_TO_PHYSICAL_TYPE = _o("1.3.6.1.2.1.4.35.1.6")
IP_NET_TO_PHYSICAL_STATE = _o("1.3.6.1.2.1.4.35.1.7")
IP_NET_TO_MEDIA_PHYS_ADDRESS = _o("1.3.6.1.2.1.4.22.1.2")
IP_NET_TO_MEDIA_TYPE = _o("1.3.6.1.2.1.4.22.1.4")

# LLDP-MIB
LLDP_LOC_PORT_ID_SUBTYPE = _o("1.0.8802.1.1.2.1.3.7.1.2")
LLDP_LOC_PORT_ID = _o("1.0.8802.1.1.2.1.3.7.1.3")
LLDP_LOC_PORT_DESC = _o("1.0.8802.1.1.2.1.3.7.1.4")
LLDP_REM_ENTRY = _o("1.0.8802.1.1.2.1.4.1.1")
LLDP_REM_MAN_ADDR_IF_SUBTYPE = _o("1.0.8802.1.1.2.1.4.2.1.3")

# LLDP-V2-MIB (IEEE 802.1AB-2009), served instead of LLDP-MIB by some agents. The remote table
# is indexed by timeMark.localIfIndex.destMAC(6).index, so the local port needs no mapping.
LLDP_V2_REM_ENTRY = _o("1.3.111.2.802.1.1.13.1.4.1.1")
LLDP_V2_REM_MAN_ADDR_IF_SUBTYPE = _o("1.3.111.2.802.1.1.13.1.4.2.1.3")

# CISCO-CDP-MIB cdpCacheTable
CDP_CACHE_ENTRY = _o("1.3.6.1.4.1.9.9.23.1.2.1.1")

# Function MIBs used as vendor-neutral type evidence (RFC 3805 Printer-MIB, RFC 1628 UPS-MIB)
PRT_GENERAL_ENTRY = _o("1.3.6.1.2.1.43.5.1.1")
UPS_IDENT = _o("1.3.6.1.2.1.33.1.1")

ENTERPRISES = _o("1.3.6.1.4.1")

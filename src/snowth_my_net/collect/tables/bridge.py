"""BRIDGE-MIB / Q-BRIDGE-MIB forwarding databases: pure parsers.

A forwarding entry becomes an observation ``(mac, ifIndex, vlan)``:

* Q-BRIDGE ``dot1qTpFdbTable`` is indexed by ``fdbId.mac``. The FDB id is translated into a
  VLAN with ``dot1qVlanFdbId`` (many agents use an internal id that is NOT the VLAN number);
  without that table the id is taken as the VLAN when it is a valid VLAN number.
* BRIDGE-MIB ``dot1dTpFdbTable`` has no VLAN: the port's PVID is used.
* The bridge port is translated into an ifIndex with ``dot1dBasePortIfIndex``; agents without
  that table number bridge ports like ifIndexes.
* Only ``learned`` entries are kept (a missing status column counts as learned); port 0 means
  "unknown / the bridge itself" and is dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

from snowth_my_net.snmp.index import decode_mac_index
from snowth_my_net.snmp.values import is_multicast

STATUS_LEARNED = 3
FIRST_VLAN, LAST_VLAN = 1, 4094
CISCO_RESERVED_VLANS = frozenset({1002, 1003, 1004, 1005})

Column = dict[tuple[int, ...], object]


@dataclass(frozen=True)
class FdbEntry:
    mac: str
    ifindex: int
    vlan: int            # 0 = unknown
    vlan_source: str     # fdb | fdb_assumed | pvid | context | none
    method: str          # qbridge | bridge | cisco_vlan


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def base_ports(column: Column) -> dict[int, int]:
    """``dot1dBasePortIfIndex``: bridge port -> ifIndex."""
    result = {}
    for suffix, value in column.items():
        number = _int(value)
        if len(suffix) == 1 and number is not None and number > 0:
            result[suffix[0]] = number
    return result


def pvids(column: Column) -> dict[int, int]:
    """``dot1qPvid``: bridge port -> VLAN."""
    result = {}
    for suffix, value in column.items():
        number = _int(value)
        if len(suffix) == 1 and number is not None and FIRST_VLAN <= number <= LAST_VLAN:
            result[suffix[0]] = number
    return result


def fdb_id_to_vlan(column: Column) -> dict[int, int]:
    """``dot1qVlanFdbId`` (index ``timeMark.vlan``, value fdbId) -> ``{fdbId: vlan}``.

    An FDB id shared by several VLANs (shared VLAN learning) cannot name a VLAN: dropped.
    """
    seen: dict[int, set[int]] = {}
    for suffix, value in column.items():
        fdb_id = _int(value)
        if len(suffix) < 1 or fdb_id is None:
            continue
        seen.setdefault(fdb_id, set()).add(suffix[-1])
    return {fdb: next(iter(vlans)) for fdb, vlans in seen.items() if len(vlans) == 1}


def vlan_names(column: Column, index_len: int = 1) -> dict[int, str]:
    """``dot1qVlanStaticName`` (index vlan) or ``vtpVlanName`` (index domain.vlan)."""
    names = {}
    for suffix, value in column.items():
        if len(suffix) == index_len and isinstance(value, bytes | str):
            text = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
            names[suffix[-1]] = text.strip("\x00 ").strip()
    return names


def operational_vlans(vtp_state: Column) -> list[int]:
    """``vtpVlanState`` (index domain.vlan): operational VLANs, Cisco reserved ones excluded."""
    vlans = {s[-1] for s, v in vtp_state.items() if len(s) == 2 and _int(v) == 1}
    return sorted(v for v in vlans if FIRST_VLAN <= v <= LAST_VLAN
                  and v not in CISCO_RESERVED_VLANS)


def _learned(status: object) -> bool:
    return status is None or _int(status) == STATUS_LEARNED


def _ifindex(port: int, ports: dict[int, int]) -> int:
    return ports.get(port, port) if ports else port


def parse_qbridge(port_col: Column, status_col: Column, fdb_vlans: dict[int, int],
                  ports: dict[int, int], port_pvid: dict[int, int]) -> list[FdbEntry]:
    entries = []
    for suffix, value in port_col.items():
        port = _int(value)
        if len(suffix) != 7 or not port or not _learned(status_col.get(suffix)):
            continue
        mac = decode_mac_index(suffix[1:])
        if mac is None or is_multicast(mac) or mac == "00:00:00:00:00:00":
            continue
        fdb_id = suffix[0]
        if fdb_id in fdb_vlans:
            vlan, source = fdb_vlans[fdb_id], "fdb"
        elif not fdb_vlans and FIRST_VLAN <= fdb_id <= LAST_VLAN:
            vlan, source = fdb_id, "fdb_assumed"
        elif port in port_pvid:
            vlan, source = port_pvid[port], "pvid"
        else:
            vlan, source = 0, "none"
        entries.append(FdbEntry(mac, _ifindex(port, ports), vlan, source, "qbridge"))
    return entries


def parse_dot1d(port_col: Column, status_col: Column, ports: dict[int, int],
                port_pvid: dict[int, int], vlan: int | None = None,
                method: str = "bridge") -> list[FdbEntry]:
    """``dot1dTpFdbTable``; ``vlan`` is known when walked in a Cisco per-VLAN context."""
    entries = []
    for suffix, value in port_col.items():
        port = _int(value)
        if len(suffix) != 6 or not port or not _learned(status_col.get(suffix)):
            continue
        mac = decode_mac_index(suffix)
        if mac is None or is_multicast(mac) or mac == "00:00:00:00:00:00":
            continue
        if vlan is not None:
            entry_vlan, source = vlan, "context"
        elif port in port_pvid:
            entry_vlan, source = port_pvid[port], "pvid"
        else:
            entry_vlan, source = 0, "none"
        entries.append(FdbEntry(mac, _ifindex(port, ports), entry_vlan, source, method))
    return entries

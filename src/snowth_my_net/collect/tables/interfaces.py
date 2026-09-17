"""IF-MIB interfaces, short port names and link-aggregation membership."""

from __future__ import annotations

import re
from dataclasses import dataclass

from snowth_my_net.snmp.values import decode_text, normalize_mac

IFTYPE_LAG = 161  # ieee8023adLag
SPEED_UNKNOWN = 4294967295

# Only unambiguous long forms are shortened (``Ethernet`` alone differs between vendors).
_ABBREVIATIONS = (
    ("TwentyFiveGigE", "Twe"), ("TwentyFiveGigabitEthernet", "Twe"), ("HundredGigE", "Hu"),
    ("HundredGigabitEthernet", "Hu"), ("FortyGigabitEthernet", "Fo"), ("FortyGigE", "Fo"),
    ("TenGigabitEthernet", "Te"), ("FiveGigabitEthernet", "Fi"), ("TwoGigabitEthernet", "Tw"),
    ("AppGigabitEthernet", "Ap"), ("GigabitEthernet", "Gi"), ("FastEthernet", "Fa"),
    ("Port-channel", "Po"),
)
_ABBREV_RE = re.compile(
    r"^(" + "|".join(re.escape(long) for long, _ in _ABBREVIATIONS) + r")\s*(?=\d)",
    re.IGNORECASE,
)
_ABBREV_MAP = {long.lower(): short for long, short in _ABBREVIATIONS}


def short_port_name(name: str) -> str:
    """``GigabitEthernet1/0/5`` -> ``Gi1/0/5``; any other form is returned unchanged."""
    return _ABBREV_RE.sub(lambda m: _ABBREV_MAP[m.group(1).lower()], name.strip(), count=1)


@dataclass
class Interface:
    ifindex: int
    name: str = ""
    descr: str = ""
    alias: str = ""
    if_type: int | None = None
    admin_status: int | None = None
    oper_status: int | None = None
    speed_mbps: int | None = None
    phys_mac: str | None = None
    lag_ifindex: int | None = None

    @property
    def port_name(self) -> str:
        """Short port name used in every output: ifName, else ifDescr, else the ifIndex."""
        return short_port_name(self.name or self.descr) or str(self.ifindex)


def build_interfaces(
    columns: dict[str, dict[int, object]],
    stack: list[tuple[int, int]] | None = None,
    lag_attached: dict[int, int] | None = None,
) -> dict[int, Interface]:
    """``columns`` maps a column name to ``{ifIndex: value}`` (see ``COLUMN_NAMES``)."""

    def text(col: str, idx: int) -> str:
        v = columns.get(col, {}).get(idx)
        return decode_text(v) if isinstance(v, bytes | str) else ""

    def integer(col: str, idx: int) -> int | None:
        v = columns.get(col, {}).get(idx)
        return v if isinstance(v, int) else None

    indexes: set[int] = set()
    for values in columns.values():
        indexes.update(values)
    result: dict[int, Interface] = {}
    for idx in sorted(indexes):
        high = integer("ifHighSpeed", idx)
        low = integer("ifSpeed", idx)
        if high:
            speed = high
        elif low and low != SPEED_UNKNOWN:
            speed = low // 1_000_000
        else:
            speed = None
        mac = columns.get("ifPhysAddress", {}).get(idx)
        result[idx] = Interface(
            ifindex=idx,
            name=text("ifName", idx),
            descr=text("ifDescr", idx),
            alias=text("ifAlias", idx),
            if_type=integer("ifType", idx),
            admin_status=integer("ifAdminStatus", idx),
            oper_status=integer("ifOperStatus", idx),
            speed_mbps=speed,
            phys_mac=normalize_mac(mac) if isinstance(mac, bytes) and len(mac) == 6 else None,
        )

    for higher, lower in stack or []:
        agg = result.get(higher)
        if agg and agg.if_type == IFTYPE_LAG and lower in result:
            result[lower].lag_ifindex = higher
    for port, agg_index in (lag_attached or {}).items():
        if agg_index and port in result and agg_index != port and agg_index in result:
            result[port].lag_ifindex = agg_index
    return result

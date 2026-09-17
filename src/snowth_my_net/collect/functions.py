"""Collection functions: walk the columns a function needs, then parse whatever arrived.

Each function fills a :class:`Rows` accumulator while walking and parses it in a ``finally``
block, so rows received before a timeout are kept (the caller then marks the function
``partial``).
"""

from __future__ import annotations

from snowth_my_net.collect.model import DeviceResult
from snowth_my_net.collect.tables.entity import TEXT_COLUMNS, build_chassis, rows_to_fetch
from snowth_my_net.collect.tables.interfaces import build_interfaces
from snowth_my_net.collect.tables.ipaddr import (
    merge_addresses,
    parse_ip_addr_table,
    parse_ip_address_table,
)
from snowth_my_net.snmp import oids
from snowth_my_net.snmp.client import SnmpClient
from snowth_my_net.snmp.values import Oid

GET_BATCH = 16


class Rows:
    """Accumulates walked columns; ``count`` is the number of rows of the key column."""

    def __init__(self) -> None:
        self.columns: dict[str, dict[tuple[int, ...], object]] = {}
        self.key: str | None = None

    def column(self, name: str) -> dict[tuple[int, ...], object]:
        return self.columns.setdefault(name, {})

    @property
    def count(self) -> int:
        if self.key is not None:
            return len(self.columns.get(self.key, {}))
        return max((len(c) for c in self.columns.values()), default=0)


async def walk_into(client: SnmpClient, rows: Rows, name: str, base: Oid) -> None:
    col = rows.column(name)
    async for oid, value in client.walk(base):
        col[oid[len(base):]] = value


async def has_rows(client: SnmpClient, base: Oid) -> bool:
    """True when the agent has at least one instance under ``base`` (a single request)."""
    async for _ in client.walk(base):
        return True
    return False


async def count_rows(client: SnmpClient, base: Oid) -> int:
    n = 0
    async for _ in client.walk(base):
        n += 1
    return n


def by_index(column: dict[tuple[int, ...], object]) -> dict[int, object]:
    """Single-integer indexes only (ifIndex, entPhysicalIndex…)."""
    return {suffix[0]: v for suffix, v in column.items() if len(suffix) == 1}


def _ints(column: dict[tuple[int, ...], object]) -> dict[int, int]:
    return {k: v for k, v in by_index(column).items() if isinstance(v, int)}


async def entity(client: SnmpClient, r: DeviceResult, rows: Rows) -> None:
    rows.key = "class"
    texts: dict[int, dict[int, object]] = {}
    try:
        await walk_into(client, rows, "class", oids.ENT_PHYSICAL_CLASS)
        await walk_into(client, rows, "contained", oids.ENT_PHYSICAL_CONTAINED_IN)
        classes, contained = _ints(rows.column("class")), _ints(rows.column("contained"))
        wanted = [(idx, col) for idx in rows_to_fetch(classes, contained) for col in TEXT_COLUMNS]
        for start in range(0, len(wanted), GET_BATCH):
            batch = wanted[start:start + GET_BATCH]
            requested = [oids.ENT_PHYSICAL_ENTRY + (col, idx) for idx, col in batch]
            values = await client.get(requested)
            for (idx, col), oid in zip(batch, requested, strict=True):
                texts.setdefault(idx, {})[col] = values.get(oid)
    finally:
        r.chassis = build_chassis(_ints(rows.column("class")), _ints(rows.column("contained")),
                                  texts)


async def type_evidence(client: SnmpClient, r: DeviceResult, rows: Rows) -> None:
    r.evidence.printer_mib = await has_rows(client, oids.PRT_GENERAL_ENTRY)
    r.evidence.ups_mib = await has_rows(client, oids.UPS_IDENT)
    rows.column("evidence")[(1,)] = True  # the function itself always "has data"


IF_COLUMNS: dict[str, Oid] = {
    "ifDescr": oids.IF_DESCR, "ifName": oids.IF_NAME, "ifType": oids.IF_TYPE,
    "ifSpeed": oids.IF_SPEED, "ifHighSpeed": oids.IF_HIGH_SPEED,
    "ifPhysAddress": oids.IF_PHYS_ADDRESS, "ifAdminStatus": oids.IF_ADMIN_STATUS,
    "ifOperStatus": oids.IF_OPER_STATUS, "ifAlias": oids.IF_ALIAS,
}


async def interfaces(client: SnmpClient, r: DeviceResult, rows: Rows) -> None:
    rows.key = "ifDescr"
    try:
        for name, base in IF_COLUMNS.items():
            await walk_into(client, rows, name, base)
        await walk_into(client, rows, "stack", oids.IF_STACK_STATUS)
        await walk_into(client, rows, "lag", oids.DOT3AD_AGG_PORT_ATTACHED_AGG_ID)
    finally:
        stack = [(s[0], s[1]) for s in rows.column("stack") if len(s) == 2]
        r.interfaces = build_interfaces(
            {name: by_index(rows.column(name)) for name in IF_COLUMNS}, stack,
            _ints(rows.column("lag")))
        if not rows.column("ifDescr"):
            rows.key = "ifName"


async def ipaddr(client: SnmpClient, r: DeviceResult, rows: Rows) -> None:
    try:
        await walk_into(client, rows, "adIf", oids.IP_AD_ENT_IF_INDEX)
        await walk_into(client, rows, "adMask", oids.IP_AD_ENT_NET_MASK)
        await walk_into(client, rows, "addrIf", oids.IP_ADDRESS_IF_INDEX)
        await walk_into(client, rows, "addrType", oids.IP_ADDRESS_TYPE)
        await walk_into(client, rows, "addrPrefix", oids.IP_ADDRESS_PREFIX)
    finally:
        r.addresses = merge_addresses(
            parse_ip_address_table(rows.column("addrIf"), rows.column("addrType"),
                                   rows.column("addrPrefix")),
            parse_ip_addr_table(rows.column("adIf"), rows.column("adMask")),
        )
        rows.key = ("adIf" if len(rows.column("adIf")) >= len(rows.column("addrIf"))
                    else "addrIf")

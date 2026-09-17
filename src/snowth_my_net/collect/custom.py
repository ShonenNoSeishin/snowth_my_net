"""Running custom collectors: applicability, reading, value conversion, standard-field fills.

YAML collectors and Python collectors share the same path: a Python collector is a
``CollectorCfg`` whose values come from a function instead of OIDs.
"""

from __future__ import annotations

import asyncio
import ipaddress
from dataclasses import dataclass, field
from typing import Any

from snowth_my_net.collect.probe import format_value
from snowth_my_net.collect.tables.system import caps_names, decode_lldp_caps
from snowth_my_net.config.extensions import (
    AppliesTo,
    CollectorCfg,
    LoadedCollector,
    ValueSpec,
    WalkSpec,
    parse_collector,
)
from snowth_my_net.snmp.client import SnmpClient, SnmpError, Value
from snowth_my_net.snmp.values import normalize_mac, oid_str, parse_oid


@dataclass
class DeviceFacts:
    """What a collector may be scoped on."""

    address: str
    vendor: str
    device_type: str
    object_id: str
    name: str = ""
    model: str = ""
    os_name: str = ""
    os_version: str = ""


def applies(collector: CollectorCfg, facts: DeviceFacts) -> bool:
    scope = collector.applies_to
    if scope.empty:
        return True
    checks = []
    if scope.vendors:
        checks.append(facts.vendor.casefold() in {v.casefold() for v in scope.vendors})
    if scope.types:
        checks.append(facts.device_type in scope.types)
    if scope.addresses:
        try:
            ip = ipaddress.ip_address(facts.address)
            checks.append(any(n and ip.version == n.version and ip in n
                              for n in scope.addresses))
        except ValueError:
            checks.append(False)
    if scope.sys_object_ids:
        oid = facts.object_id + "."
        checks.append(any(oid.startswith(p.strip().lstrip(".").rstrip(".") + ".")
                          for p in scope.sys_object_ids))
    return all(checks)


def convert(value: Value, spec: ValueSpec) -> tuple[str | None, str | None]:
    """``(display value, raw value)``; ``(None, None)`` when the object does not exist."""
    if value is None:
        return None, None
    raw = value.hex() if isinstance(value, bytes) else (
        oid_str(value) if isinstance(value, tuple) else str(value))
    kind = spec.type
    names = {int(k): v for k, v in spec.values.items()}
    if kind in ("integer", "timeticks", "enum") and isinstance(value, int):
        if kind == "enum":
            return names.get(value, str(value)), raw
        if kind == "timeticks":
            seconds = value // 100
            days, rest = divmod(seconds, 86400)
            return f"{days}d {rest // 3600:02d}:{rest % 3600 // 60:02d}:{rest % 60:02d}", raw
        number = value * spec.scale if spec.scale is not None else value
        text = f"{number:g}" if isinstance(number, float) else str(number)
        return (f"{text} {spec.unit}".strip()), raw
    if kind == "mac" and isinstance(value, bytes | str):
        return normalize_mac(value) or raw, raw
    if kind == "hex" and isinstance(value, bytes):
        return value.hex(":"), raw
    if kind == "ip" and isinstance(value, bytes) and len(value) in (4, 16):
        return str(ipaddress.ip_address(value)), raw
    if kind == "oid" and isinstance(value, tuple):
        return oid_str(value), raw
    if kind == "lldp_caps" and isinstance(value, bytes):
        return ", ".join(sorted(caps_names(decode_lldp_caps(value)))), raw
    if kind == "bits" and isinstance(value, bytes):
        bits = [n for n in range(len(value) * 8) if value[n // 8] & (0x80 >> (n % 8))]
        return ", ".join(names.get(n, str(n)) for n in bits), raw
    if kind == "text" and isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00").strip(), raw
    display = format_value(value)
    if spec.unit and isinstance(value, int):
        display = f"{display} {spec.unit}"
    return display, raw


@dataclass
class CustomResult:
    rows: list[tuple[str, str, str | None, str | None]] = field(default_factory=list)
    truncated: bool = False

    def values(self) -> dict[str, str]:
        """get: collectors -> {column: value}."""
        return {column: value for idx, column, value, _raw in self.rows
                if idx == "" and value is not None}


class ExtensionError(SnmpError):
    """A Python collector raised or returned something unusable (recorded as an error)."""

    kind = "error"


@dataclass
class PythonCollectorCfg(CollectorCfg):
    func: Any = None
    columns: list[str] = field(default_factory=list)
    table: bool = False
    extension: str = ""

    def value_specs(self) -> dict[str, ValueSpec]:
        return {c: ValueSpec("python", "text") for c in self.columns}

    @property
    def kind(self) -> str:
        return "python"


def python_collector_cfg(collector, scope: AppliesTo, every: int,
                         extension: str) -> PythonCollectorCfg:
    """Turn an ``api.PythonCollector`` declaration into a runnable collector."""
    walk = (WalkSpec(columns=dict.fromkeys(collector.columns, "python"), index=collector.index)
            if collector.table else None)
    return PythonCollectorCfg(
        name=collector.name, description=collector.description, applies_to=scope,
        walk=walk, fills=dict(collector.fills), every=every, mode=collector.mode,
        limit=collector.limit, func=collector.func, columns=list(collector.columns),
        table=collector.table, extension=extension)


class ClientSnmp:
    """The ``ReadOnlySnmp`` given to Python collectors: GET and walk only."""

    def __init__(self, client: SnmpClient, limit: int) -> None:
        self._client, self._limit = client, limit

    async def get(self, *oids: str) -> dict[str, Any]:
        parsed = {oid: parse_oid(oid) for oid in oids}
        values = await self._client.get(list(parsed.values()))
        return {oid: _plain(values.get(key)) for oid, key in parsed.items()}

    async def walk(self, oid: str, limit: int | None = None) -> list[tuple[str, Any]]:
        base = parse_oid(oid)
        cap = min(limit or self._limit, self._limit)
        rows = []
        async for found, value in self._client.walk(base):
            if len(rows) >= cap:
                break
            rows.append((oid_str(found[len(base):]), _plain(value)))
        return rows


def _plain(value: Value) -> Any:
    return oid_str(value) if isinstance(value, tuple) else value


def _cell(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return format_value(value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


async def run_python_collector(client: SnmpClient | None, collector: PythonCollectorCfg,
                               result: CustomResult, facts: DeviceFacts | None,
                               snmp: Any = None) -> None:
    """``snmp`` replaces the client-backed ReadOnlySnmp (the test harness passes a fake)."""
    from snowth_my_net.api import DeviceView

    facts = facts or DeviceFacts(str(getattr(client, "target", "")), "", "", "")
    device = DeviceView(facts.address, facts.name, facts.vendor, facts.model, facts.os_name,
                        facts.os_version, facts.device_type, facts.object_id)
    try:
        data = await collector.func(device, snmp or ClientSnmp(client, collector.limit))
    except (SnmpError, TimeoutError, asyncio.CancelledError):
        raise
    except Exception as exc:
        raise ExtensionError(f"{collector.extension}.{collector.name} raised "
                             f"{type(exc).__name__}: {exc}") from exc
    if data is None:
        return
    if collector.table:
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise ExtensionError(f"{collector.name}: a table collector returns a list of dicts")
        if len(data) > collector.limit:
            data, result.truncated = data[:collector.limit], True
        for position, row in enumerate(data):
            index = str(row.get("index", position))
            for column in collector.columns:
                value = _cell(row.get(column))
                if value is not None:
                    result.rows.append((index, column, value, None))
        return
    if not isinstance(data, dict):
        raise ExtensionError(f"{collector.name}: a collector returns a dict of its columns")
    for column in collector.columns:
        value = _cell(data.get(column))
        if value is not None:
            result.rows.append(("", column, value, None))


async def run_collector(client: SnmpClient, collector: CollectorCfg,
                        result: CustomResult, facts: DeviceFacts | None = None) -> None:
    """Fill ``result`` progressively (rows read before a timeout are kept)."""
    if isinstance(collector, PythonCollectorCfg):
        await run_python_collector(client, collector, result, facts)
        return
    specs = collector.value_specs()
    if collector.walk is None:
        oids = {name: parse_oid(spec.oid) for name, spec in specs.items()}
        values = await client.get(list(oids.values()))
        for name, oid in oids.items():
            display, raw = convert(values.get(oid), specs[name])
            if display is not None:
                result.rows.append(("", name, display, raw))
        return
    for name, spec in specs.items():
        base = parse_oid(spec.oid)
        count = 0
        async for oid, value in client.walk(base):
            if count >= collector.limit:
                result.truncated = True
                break
            display, raw = convert(value, spec)
            result.rows.append((oid_str(oid[len(base):]), name, display, raw))
            count += 1


def fills_for(collector: CollectorCfg, values: dict[str, str]) -> dict[str, str]:
    return {target: values[source] for target, source in collector.fills.items()
            if values.get(source)}


def all_collectors(file_collectors: list[LoadedCollector], stored: dict[str, dict]
                   ) -> tuple[list[LoadedCollector], list[str]]:
    """Collectors from extension files, plus the valid ones created in the TUI.

    A stored collector whose name is also defined in a file is ignored (the file wins).
    """
    result = list(file_collectors)
    names = {c.cfg.name for c in result}
    warnings = []
    for name, definition in sorted(stored.items()):
        if name in names:
            warnings.append(f"collector {name!r} from the state is shadowed by an extension file")
            continue
        try:
            result.append(LoadedCollector(parse_collector(definition), "tui"))
        except Exception as exc:  # a broken stored definition must not stop the collect
            warnings.append(f"collector {name!r} from the state is invalid: {exc}")
    return result, warnings

"""Testing OIDs by hand: connect to one device, GET or walk a preset or any numeric OID.

Everything goes through the read-only SNMP client, with the device's own timeouts and pacing.
Walks are bounded (``limit`` rows per column).
"""

from __future__ import annotations

import asyncio
import ipaddress
import time
from dataclasses import dataclass, field

from snowth_my_net.collect.presets import Column, Preset
from snowth_my_net.collect.tables.system import (
    IDENTITY_OIDS,
    SystemInfo,
    caps_names,
    decode_lldp_caps,
    parse_system,
)
from snowth_my_net.config.effective import DeviceSettings, settings_for
from snowth_my_net.config.loader import LoadedConfig, ResolvedCredential
from snowth_my_net.snmp.client import EnginePool, SnmpClient, SnmpError, SnmpParams, Value
from snowth_my_net.snmp.credentials import candidates_for, probe
from snowth_my_net.snmp.target import Target
from snowth_my_net.snmp.values import Oid, oid_str, parse_oid

DEFAULT_LIMIT = 50


class ProbeInputError(ValueError):
    pass


# --------------------------------------------------------------------------- values


def _printable(raw: bytes) -> str | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    stripped = text.rstrip("\x00")
    if all(ch.isprintable() or ch in "\r\n\t" for ch in stripped):
        return stripped.replace("\r\n", " ⏎ ").replace("\n", " ⏎ ")
    return None


def format_value(value: Value, column: Column | None = None) -> str:
    """Human-readable rendering of a decoded SNMP value."""
    kind = column.kind if column else "auto"
    if value is None:
        return "∅ (no such object)"
    if isinstance(value, tuple):
        return oid_str(value)
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        name = column.enum_name(value) if column and kind == "enum" else None
        return f"{name}({value})" if name else str(value)
    if isinstance(value, str):
        return value
    if kind == "caps":
        names = sorted(caps_names(decode_lldp_caps(value)))
        return ", ".join(names) if names else f"0x{value.hex()}"
    if len(value) == 6 and (kind == "mac" or _printable(value) is None):
        return ":".join(f"{b:02x}" for b in value)
    if not value:
        return '""'
    text = _printable(value)
    if text is not None:
        return text
    return "0x" + value.hex()


# --------------------------------------------------------------------------- results


@dataclass
class ProbeTable:
    title: str
    headers: list[str]
    rows: list[list[str]] = field(default_factory=list)
    status: str = "ok"                  # ok | absent | timeout | error
    detail: str = ""
    truncated: bool = False
    duration_ms: int = 0
    requests: int = 0

    def as_dict(self) -> dict:
        return {"title": self.title, "headers": self.headers, "rows": self.rows,
                "status": self.status, "detail": self.detail, "truncated": self.truncated,
                "duration_ms": self.duration_ms, "requests": self.requests}


def parse_oid_input(text: str) -> Oid:
    cleaned = text.strip().lstrip(".")
    if not cleaned or not all(part.isdigit() for part in cleaned.split(".")):
        raise ProbeInputError(f"{text!r} is neither a preset name nor a numeric OID")
    oid = parse_oid(cleaned)
    if len(oid) < 2:
        raise ProbeInputError(f"{text!r} is too short to be an OID")
    return oid


async def _walk_column(client: SnmpClient, base: Oid, limit: int) -> tuple[dict, bool]:
    values: dict[tuple[int, ...], Value] = {}
    truncated = False
    async for oid, value in client.walk(base):
        if len(values) >= limit:
            truncated = True
            break
        values[oid[len(base):]] = value
    return values, truncated


async def _timed(client: SnmpClient, table: ProbeTable, coro, timeout: float) -> None:
    start, before = time.monotonic(), client.requests
    try:
        async with asyncio.timeout(timeout):
            await coro
    except TimeoutError:
        table.status, table.detail = "timeout", f"no complete answer within {timeout:.0f}s"
    except SnmpError as exc:
        table.status = "timeout" if exc.kind == "timeout" else "error"
        table.detail = str(exc)
    table.duration_ms = int((time.monotonic() - start) * 1000)
    table.requests = client.requests - before


async def run_preset(client: SnmpClient, preset: Preset, lang: str, limit: int = DEFAULT_LIMIT,
                     pen: int | None = None, timeout: float = 60) -> ProbeTable:
    if preset.mode == "enterprise":
        if pen is None:
            table = ProbeTable(preset.title(lang), ["OID", "value"])
            table.status, table.detail = "error", "unknown vendor sub-tree (no sysObjectID)"
            return table
        table = await run_oid(client, parse_oid(f"1.3.6.1.4.1.{pen}"), "walk", limit, timeout)
        table.title = f"{preset.title(lang)} — 1.3.6.1.4.1.{pen}"
        return table

    if preset.mode == "get":
        table = ProbeTable(preset.title(lang), ["object", "value", "OID"])

        async def do_get() -> None:
            values = await client.get([c.oid for c in preset.columns])
            for c in preset.columns:
                table.rows.append([c.label, format_value(values.get(c.oid), c), oid_str(c.oid)])
            if all(values.get(c.oid) is None for c in preset.columns):
                table.status = "absent"

        await _timed(client, table, do_get(), timeout)
        return table

    table = ProbeTable(preset.title(lang), ["index", *(c.label for c in preset.columns)])

    async def do_walk() -> None:
        merged: dict[tuple[int, ...], list[str]] = {}
        for i, column in enumerate(preset.columns):
            values, cut = await _walk_column(client, column.oid, limit)
            table.truncated |= cut
            for index, value in values.items():
                row = merged.setdefault(index, [""] * len(preset.columns))
                row[i] = format_value(value, column)
        for index in sorted(merged)[:limit]:
            table.rows.append([oid_str(index), *merged[index]])
        table.truncated |= len(merged) > limit
        if not merged:
            table.status = "absent"

    await _timed(client, table, do_walk(), timeout)
    return table


async def run_oid(client: SnmpClient, oid: Oid, mode: str = "auto", limit: int = DEFAULT_LIMIT,
                  timeout: float = 60) -> ProbeTable:
    """``mode``: get, walk, or auto (GET first, walk when there is no such instance)."""
    table = ProbeTable(oid_str(oid), ["OID", "value"])

    async def do() -> None:
        nonlocal mode
        if mode in ("get", "auto"):
            value = (await client.get([oid])).get(oid)
            if value is not None or mode == "get":
                table.rows.append([oid_str(oid), format_value(value)])
                if value is None:
                    table.status = "absent"
                return
        values, cut = await _walk_column(client, oid, limit)
        table.truncated = cut
        table.rows = [[oid_str(oid + index), format_value(v)] for index, v in values.items()]
        if not values:
            table.status = "absent"

    await _timed(client, table, do(), timeout)
    return table


# --------------------------------------------------------------------------- connection


@dataclass
class Connection:
    target: Target
    settings: DeviceSettings
    client: SnmpClient | None = None
    credential: str | None = None
    system: SystemInfo | None = None
    attempts: list[tuple[str, str]] = field(default_factory=list)
    error: str | None = None
    rtt_ms: int | None = None

    @property
    def ok(self) -> bool:
        return self.client is not None


async def connect(loaded: LoadedConfig, credentials: list[ResolvedCredential], target: Target,
                  pool: EnginePool, manual: dict | None = None,
                  remembered: str | None = None) -> Connection:
    settings = settings_for(loaded.cfg, target.host, manual)
    conn = Connection(target, settings)
    try:
        ipaddress.ip_address(target.host)
    except ValueError:
        conn.error = f"{target.host!r} is not an IP address"
        return conn
    s = settings.snmp
    params = SnmpParams(timeout=s.timeout, retries=s.retries, max_repetitions=s.max_repetitions,
                        use_bulk=s.use_bulk, per_device_concurrency=s.per_device_concurrency,
                        pace_ms=s.pace_ms, max_rows=s.max_rows_per_table)
    cands = candidates_for(target.ip, credentials, remembered, settings.credential)
    if not cands:
        conn.error = "no credential in scope for this address"
        return conn
    start = time.monotonic()
    result = await probe(pool, target, cands, params, s.probe_timeout, IDENTITY_OIDS)
    conn.attempts = result.attempts
    if not result.ok or result.credential is None:
        conn.error = f"no answer ({result.summary()})"
        return conn
    conn.rtt_ms = int((time.monotonic() - start) * 1000)
    conn.credential = result.credential.name
    conn.system = parse_system(result.values)
    conn.client = SnmpClient(pool.get(result.credential.name), result.credential, target, params)
    return conn

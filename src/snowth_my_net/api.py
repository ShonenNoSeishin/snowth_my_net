"""Public API for Python extensions — stable for a given ``API_VERSION``.

An extension is a Python file in the extensions directory (``extensions/acme.py``) or an
installed package exposing the entry point group ``snowth_my_net.extensions``. It is loaded only
when its name is listed in ``general.python_extensions``, and it must define a module-level
``extension``::

    from snowth_my_net.api import Extension, Field, text

    extension = Extension("acme")

    @extension.collector("acme-sensors", columns=["temperature", "firmware"],
                         applies_to={"vendors": ["Acme"]}, every="1h",
                         fills={"os_version": "firmware"})
    async def sensors(device, snmp):
        values = await snmp.get("1.3.6.1.4.1.99999.1.1.0", "1.3.6.1.4.1.99999.1.2.0")
        return {"temperature": values["1.3.6.1.4.1.99999.1.1.0"],
                "firmware": text(values["1.3.6.1.4.1.99999.1.2.0"])}

Extension points:

* ``collector`` — ``async def f(device: DeviceView, snmp: ReadOnlySnmp) -> dict`` (or a list of
  rows with ``table=True``). Values are stored like those of YAML collectors: shown in the
  device sheet, in ``snapshot.json`` and in the ``custom:<name>`` report dataset.
* ``report_dataset`` — ``def f(ctx: DatasetContext) -> list[dict]``, available to reports as
  ``py:<name>``.
* ``exporter`` — ``def f(snapshot: dict) -> bytes``, written by ``export`` to the output
  directory.

The SNMP object only offers ``get`` and ``walk``: extensions stay read-only towards devices.
Test an extension without a network with :mod:`snowth_my_net.testing`.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from snowth_my_net.reports.datasets import Field

__all__ = ["API_VERSION", "DatasetContext", "DeviceView", "Extension", "ExtensionDefinitionError",
           "Field", "ReadOnlySnmp", "Value", "ip", "mac", "number", "text"]

API_VERSION = 1
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

Value = bytes | int | str | None
"""An SNMP value: ``bytes`` (OCTET STRING), ``int`` (integers, counters, gauges, timeticks),
``str`` (OBJECT IDENTIFIER in dotted form, IP addresses) or ``None`` (no such object)."""


class ExtensionDefinitionError(ValueError):
    """An extension declares something invalid (name, columns, scope…)."""


@dataclass(frozen=True)
class DeviceView:
    """What a collector knows about the device it runs on (read-only)."""

    address: str
    name: str = ""
    vendor: str = ""
    model: str = ""
    os_name: str = ""
    os_version: str = ""
    device_type: str = ""
    object_id: str = ""


class ReadOnlySnmp(Protocol):
    async def get(self, *oids: str) -> dict[str, Value]:
        """GET scalars; the result maps each requested OID (as given) to its value."""
        ...

    async def walk(self, oid: str, limit: int = 10_000) -> list[tuple[str, Value]]:
        """Walk a sub-tree; returns ``(index, value)`` with the index relative to ``oid``."""
        ...


class DatasetContext(Protocol):
    now: int

    def dataset_rows(self, name: str) -> list[dict]:
        """Rows of another dataset (``devices``, ``nodes``, ``custom:<name>``…)."""
        ...


# --------------------------------------------------------------------------- value helpers


def text(value: Value) -> str:
    """Printable text; NUL padding and surrounding spaces removed."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00 \t\r\n")
    return str(value)


def number(value: Value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(text(value))
    except ValueError:
        return None


def mac(value: Value) -> str | None:
    from snowth_my_net.snmp.values import normalize_mac

    return normalize_mac(value) if isinstance(value, bytes | str) else None


def ip(value: Value) -> str | None:
    if isinstance(value, bytes) and len(value) in (4, 16):
        return str(ipaddress.ip_address(value))
    if isinstance(value, str):
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------- registration


CollectorFunc = Callable[[DeviceView, ReadOnlySnmp], Awaitable[Any]]


@dataclass
class PythonCollector:
    name: str
    func: CollectorFunc
    columns: list[str]
    table: bool = False
    index: str = "raw"
    applies_to: dict = field(default_factory=dict)
    every: str | int = 0
    mode: str = "auto"
    fills: dict = field(default_factory=dict)
    description: str = ""
    limit: int = 10_000


@dataclass
class PythonDataset:
    name: str
    func: Callable[[DatasetContext], list[dict]]
    fields: list[Field]
    description: str = ""


@dataclass
class PythonExporter:
    filename: str
    func: Callable[[dict], bytes]
    description: str = ""


class Extension:
    def __init__(self, name: str, api_version: int = API_VERSION) -> None:
        if not NAME_RE.match(name):
            raise ExtensionDefinitionError(f"extension name {name!r}: use lowercase letters, "
                                           "digits, '-' and '_'")
        self.name = name
        self.api_version = api_version
        self.collectors: list[PythonCollector] = []
        self.datasets: list[PythonDataset] = []
        self.exporters: list[PythonExporter] = []

    def collector(self, name: str, *, columns: list[str], table: bool = False,
                  index: str = "raw", applies_to: dict | None = None, every: str | int = 0,
                  mode: str = "auto", fills: dict | None = None, description: str = "",
                  limit: int = 10_000):
        """Declare a collector. ``columns`` lists the values it returns; with ``table=True``
        it returns a list of rows, each with an ``index`` key (``index="port"`` when that
        index is an ifIndex)."""
        if not NAME_RE.match(name):
            raise ExtensionDefinitionError(f"collector name {name!r}: use lowercase letters, "
                                           "digits, '-' and '_'")
        if not columns or any(not isinstance(c, str) or not c or c == "index" for c in columns):
            raise ExtensionDefinitionError(f"collector {name!r}: columns must be non-empty "
                                           "names ('index' is reserved)")
        if index not in ("raw", "port"):
            raise ExtensionDefinitionError(f"collector {name!r}: index is 'raw' or 'port'")
        if mode not in ("auto", "force"):
            raise ExtensionDefinitionError(f"collector {name!r}: mode is 'auto' or 'force'")
        if table and fills:
            raise ExtensionDefinitionError(f"collector {name!r}: fills need a scalar collector")
        unknown = [source for source in (fills or {}).values() if source not in columns]
        if unknown:
            raise ExtensionDefinitionError(f"collector {name!r}: fills use unknown columns "
                                           f"{', '.join(map(str, unknown))}")

        def register(func: CollectorFunc) -> CollectorFunc:
            self.collectors.append(PythonCollector(
                name, func, list(columns), table, index, dict(applies_to or {}), every, mode,
                dict(fills or {}), description or (func.__doc__ or "").strip().split("\n")[0],
                limit))
            return func

        return register

    def report_dataset(self, name: str, *, fields: list[Field], description: str = ""):
        """Declare a dataset for reports (``py:<name>``)."""
        if not NAME_RE.match(name):
            raise ExtensionDefinitionError(f"dataset name {name!r}: use lowercase letters, "
                                           "digits, '-' and '_'")
        if not fields or not all(isinstance(f, Field) for f in fields):
            raise ExtensionDefinitionError(f"dataset {name!r}: fields must be Field(...) items")

        def register(func):
            self.datasets.append(PythonDataset(name, func, list(fields), description))
            return func

        return register

    def exporter(self, filename: str, *, description: str = ""):
        """Declare a file written by ``export`` (relative to the output directory)."""
        if (not filename or filename.startswith(("/", ".")) or ".." in filename.split("/")
                or "\\" in filename):
            raise ExtensionDefinitionError(f"exporter file {filename!r}: a relative path "
                                           "inside the output directory")

        def register(func):
            self.exporters.append(PythonExporter(filename, func, description))
            return func

        return register

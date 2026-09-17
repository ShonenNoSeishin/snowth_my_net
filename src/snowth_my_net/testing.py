"""Test harness for Python extensions: no network, no state.

    from snowth_my_net import testing

    ext = testing.load("extensions/acme.py")
    snmp = testing.FakeSnmp({"1.3.6.1.4.1.99999.1.1.0": 41,
                             "1.3.6.1.4.1.99999.1.2.0": b"2.4.1"})
    values = testing.run_collector(ext, "acme-sensors", snmp, vendor="Acme")
    assert values == {"temperature": "41", "firmware": "2.4.1"}

``run_collector`` returns what snowth_my_net would store: text values keyed by column (or a list
of ``{"index": …, column: …}`` rows for table collectors).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from snowth_my_net.api import DeviceView, Extension, Value

__all__ = ["FakeSnmp", "device", "export", "load", "run_collector", "run_dataset"]


def _key(oid: str) -> tuple[int, ...]:
    return tuple(int(part) for part in oid.strip().strip(".").split("."))


class FakeSnmp:
    """A ``ReadOnlySnmp`` over a dict ``{oid: value}`` (values as a device would return them)."""

    def __init__(self, values: dict[str, Value]) -> None:
        self.values = {_key(oid): value for oid, value in values.items()}
        self.requests: list[tuple[str, str]] = []

    async def get(self, *oids: str) -> dict[str, Value]:
        self.requests += [("get", oid) for oid in oids]
        return {oid: self.values.get(_key(oid)) for oid in oids}

    async def walk(self, oid: str, limit: int = 10_000) -> list[tuple[str, Value]]:
        self.requests.append(("walk", oid))
        base = _key(oid)
        rows = [(".".join(map(str, key[len(base):])), value)
                for key, value in sorted(self.values.items())
                if key[:len(base)] == base and len(key) > len(base)]
        return rows[:limit]


def device(address: str = "192.0.2.1", **fields: str) -> DeviceView:
    return DeviceView(address, **fields)


def load(path: str | Path) -> Extension:
    """Load an extension file the way snowth_my_net does (module-level ``extension``)."""
    from snowth_my_net.config.python_ext import _import_file

    path = Path(path)
    extension = _import_file(path.stem, path)
    if not isinstance(extension, Extension):
        raise TypeError(f"{path} must define 'extension = Extension(...)'")
    return extension


def run_collector(extension: Extension, collector: str, snmp: FakeSnmp | None = None,
                  view: DeviceView | None = None, **device_fields: str) -> Any:
    """Run one collector and return the values as they would be stored."""
    from snowth_my_net.collect.custom import (
        CustomResult,
        DeviceFacts,
        python_collector_cfg,
        run_python_collector,
    )
    from snowth_my_net.config.extensions import AppliesTo
    from snowth_my_net.config.validate import build, parse_duration

    declared = next((c for c in extension.collectors if c.name == collector), None)
    if declared is None:
        raise KeyError(f"no collector {collector!r} in extension {extension.name!r}")
    cfg = python_collector_cfg(declared, build(AppliesTo, declared.applies_to),
                               parse_duration(declared.every), extension.name)
    view = view or device(**device_fields)
    facts = DeviceFacts(view.address, view.vendor, view.device_type, view.object_id, view.name,
                        view.model, view.os_name, view.os_version)
    result = CustomResult()
    asyncio.run(run_python_collector(None, cfg, result, facts, snmp or FakeSnmp({})))
    if not declared.table:
        return {column: value for _index, column, value, _raw in result.rows}
    rows: dict[str, dict] = {}
    for index, column, value, _raw in result.rows:
        rows.setdefault(index, {"index": index})[column] = value
    return list(rows.values())


class _Context:
    def __init__(self, datasets: dict[str, list[dict]], now: int) -> None:
        self.now, self._datasets = now, datasets

    def dataset_rows(self, name: str) -> list[dict]:
        if name not in self._datasets:
            raise KeyError(f"dataset {name!r} not provided to run_dataset")
        return self._datasets[name]


def run_dataset(extension: Extension, name: str,
                datasets: dict[str, list[dict]] | None = None, now: int | None = None
                ) -> list[dict]:
    """Rows of a Python dataset; ``datasets`` provides the rows of other datasets it reads."""
    declared = next((d for d in extension.datasets if d.name == name), None)
    if declared is None:
        raise KeyError(f"no dataset {name!r} in extension {extension.name!r}")
    return declared.func(_Context(datasets or {}, now or int(time.time())))


def export(extension: Extension, filename: str, snapshot: dict) -> bytes:
    declared = next((e for e in extension.exporters if e.filename == filename), None)
    if declared is None:
        raise KeyError(f"no exporter {filename!r} in extension {extension.name!r}")
    data = declared.func(snapshot)
    return data.encode("utf-8") if isinstance(data, str) else data

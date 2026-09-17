"""Custom collectors: extra OIDs declared in YAML (``extensions/*.yml``) or created in the TUI.

A collector says what to read, on which devices, and how to interpret it::

    collectors:
      - name: fortigate-system
        applies_to: {vendors: [Fortinet]}
        get:
          os_version: {oid: 1.3.6.1.4.1.12356.101.4.1.1.0, type: text}
        fills: {os_version: os_version}
      - name: poe-ports
        applies_to: {types: [switch]}
        walk:
          index: port
          columns:
            status: {oid: 1.3.6.1.2.1.105.1.1.1.6, type: enum, values: {1: disabled, 3: delivering}}

``applies_to`` only chooses where the OIDs are read in addition to the standard collection; it
never removes anything. Without ``applies_to`` the collector is tried on every device.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from snowth_my_net.config.schema import DeviceType
from snowth_my_net.config.validate import ConfigError, Duration, Network, build

ValueType = Literal["auto", "text", "integer", "mac", "ip", "oid", "hex", "enum", "bits",
                    "timeticks", "lldp_caps"]
FillTarget = Literal["os_name", "os_version", "model", "serial", "device_type", "location"]
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
OID_RE = re.compile(r"^\.?\d+(\.\d+)+$")


@dataclass
class ValueSpec:
    oid: str
    type: ValueType = "auto"
    values: dict[str, str] = field(default_factory=dict)   # enum / bits names
    scale: float | None = None                             # integer * scale
    unit: str = ""

    def check(self) -> list[str]:
        errs = []
        if not OID_RE.match(self.oid.strip()):
            errs.append(f"oid {self.oid!r} is not a numeric OID")
        if self.type in ("enum", "bits") and not self.values:
            errs.append(f"type {self.type} needs values (number: name)")
        bad = [k for k in self.values if not str(k).lstrip("-").isdigit()]
        if bad:
            errs.append(f"values keys must be numbers, got {', '.join(map(str, bad))}")
        return errs


@dataclass
class AppliesTo:
    vendors: list[str] = field(default_factory=list)
    types: list[DeviceType] = field(default_factory=list)
    addresses: list[Network] = field(default_factory=list)
    sys_object_ids: list[str] = field(default_factory=list)   # prefixes

    def check(self) -> list[str]:
        return [f"sys_object_ids: {o!r} is not a numeric OID" for o in self.sys_object_ids
                if not OID_RE.match(o.strip())]

    @property
    def empty(self) -> bool:
        return not (self.vendors or self.types or self.addresses or self.sys_object_ids)


@dataclass
class WalkSpec:
    columns: dict[str, ValueSpec | str]
    index: Literal["raw", "port"] = "raw"     # port: the index is an ifIndex

    def check(self) -> list[str]:
        return [] if self.columns else ["walk needs at least one column"]


@dataclass
class CollectorCfg:
    name: str
    description: str = ""
    applies_to: AppliesTo = field(default_factory=AppliesTo)
    get: dict[str, ValueSpec | str] = field(default_factory=dict)
    walk: WalkSpec | None = None
    fills: dict[FillTarget, str] = field(default_factory=dict)
    fill_override: bool = False               # fill even when the standard value is not empty
    every: Duration = 0                       # 0: at every collect
    mode: Literal["auto", "force"] = "auto"
    limit: int = 10_000                       # rows per walked column

    def check(self) -> list[str]:
        errs = []
        if not NAME_RE.match(self.name):
            errs.append(f"name {self.name!r}: use lowercase letters, digits, '-' and '_'")
        if not self.get and self.walk is None:
            errs.append(f"collector {self.name!r}: needs get: or walk:")
        if self.get and self.walk is not None:
            errs.append(f"collector {self.name!r}: use either get: or walk:, not both "
                        "(split it in two collectors)")
        for column, spec in self.value_specs().items():
            if spec is not None:        # None: already reported by the type validation
                errs += [f"{self.kind}.{column}: {e}" for e in spec.check()]
        for target, source in self.fills.items():
            if source not in self.get:
                errs.append(f"fills.{target}: {source!r} is not a get: value of this collector")
        if self.limit < 1:
            errs.append("limit must be > 0")
        return errs

    def value_specs(self) -> dict[str, ValueSpec]:
        raw = self.walk.columns if self.walk is not None else self.get
        return {k: ValueSpec(v) if isinstance(v, str) else v for k, v in (raw or {}).items()}

    @property
    def kind(self) -> str:
        return "walk" if self.walk is not None else "get"


@dataclass
class ExtensionFile:
    collectors: list[CollectorCfg] = field(default_factory=list)
    version: Literal[1] = 1


@dataclass
class LoadedCollector:
    cfg: CollectorCfg
    origin: str                                # file path, or "tui"


def parse_collector(data: Any) -> CollectorCfg:
    """Validate one collector definition (from the TUI or an import)."""
    return build(CollectorCfg, data)


def load_extension_dir(directory: Path | None) -> list[LoadedCollector]:
    """Every ``*.yml``/``*.yaml`` of the directory; raises ConfigError listing all problems."""
    if directory is None or not directory.is_dir():
        return []
    loaded: list[LoadedCollector] = []
    errors: list[str] = []
    for path in sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")]):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            ext = build(ExtensionFile, data)
        except yaml.YAMLError as exc:
            errors.append(f"{path}: invalid YAML: {exc}")
            continue
        except ConfigError as exc:
            errors += [f"{path}: {e.removeprefix('<config>: ')}" for e in exc.errors]
            continue
        loaded += [LoadedCollector(c, str(path)) for c in ext.collectors]
    names = [c.cfg.name for c in loaded]
    for name in sorted({n for n in names if names.count(n) > 1}):
        errors.append(f"collector name {name!r} is defined more than once "
                      f"({', '.join(c.origin for c in loaded if c.cfg.name == name)})")
    if errors:
        raise ConfigError(errors)
    return loaded

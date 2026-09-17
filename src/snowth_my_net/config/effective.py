"""Effective per-device settings: defaults, then ``devices:`` entries, then manual settings.

Every ``devices:`` entry whose ``address`` (IP or CIDR) contains the device address applies;
the most specific one wins field by field (a /32 beats a /24, which beats a /16). Among equally
specific entries, the later one in the file wins. Manual settings (TUI, ``device set``) are
applied last and win over the file. ``DeviceSettings.sources`` records where each non-default
value comes from, so that every interface can show it.
"""

from __future__ import annotations

import dataclasses
import ipaddress
from dataclasses import dataclass, field
from typing import Any

from snowth_my_net.config.schema import Config, DeviceOverride, SnmpCfg

FEATURES = ("entity", "interfaces", "ipaddr", "fdb", "arp", "lldp", "cdp")
SIMPLE_FIELDS = ("name", "type", "credential", "vlan_indexing", "uplinks", "access_ports",
                 "uplink_mac_threshold", "driver", "tolerate_failure", "ha_mode", "disabled")
SNMP_FIELDS = ("timeout", "retries", "max_repetitions", "use_bulk", "per_device_concurrency",
               "pace_ms", "table_timeout", "device_timeout", "max_rows_per_table")

SOURCE_DEFAULT, SOURCE_CONFIG, SOURCE_MANUAL = "default", "config", "manual"


@dataclass
class DeviceSettings:
    name: str | None = None
    type: str | None = None
    credential: str | None = None
    features: dict[str, str] = field(default_factory=lambda: dict.fromkeys(FEATURES, "auto"))
    vlan_indexing: str = "auto"
    uplinks: list[str] = field(default_factory=list)
    access_ports: list[str] = field(default_factory=list)
    uplink_mac_threshold: int = 50
    snmp: SnmpCfg = field(default_factory=SnmpCfg)
    driver: str | None = None
    tolerate_failure: bool = False
    ha_mode: str | None = None
    disabled: bool = False
    sources: dict[str, str] = field(default_factory=dict)

    def feature(self, name: str) -> str:
        return self.features.get(name, "auto")

    def source(self, key: str) -> str:
        return self.sources.get(key, SOURCE_DEFAULT)

    def get(self, key: str) -> Any:
        """Value of a flat key such as ``type``, ``features.arp`` or ``snmp.pace_ms``."""
        head, _, tail = key.partition(".")
        if head == "features":
            return self.feature(tail)
        if head == "snmp":
            return getattr(self.snmp, tail)
        return getattr(self, key)

    def set(self, key: str, value: Any, source: str) -> None:
        head, _, tail = key.partition(".")
        if head == "features":
            self.features[tail] = value
        elif head == "snmp":
            self.snmp = dataclasses.replace(self.snmp, **{tail: value})
        else:
            setattr(self, key, value)
        self.sources[key] = source


def matching_overrides(cfg: Config, address: str) -> list[DeviceOverride]:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return []
    matches = [d for d in cfg.devices if d and ip.version == d.address.version
               and ip in d.address]
    return sorted(matches, key=lambda d: d.address.prefixlen)  # stable: file order kept


def settings_for(cfg: Config, address: str,
                 manual: dict[str, dict[str, Any]] | None = None) -> DeviceSettings:
    s = DeviceSettings(
        uplink_mac_threshold=cfg.nodes.uplink_mac_threshold,
        snmp=dataclasses.replace(cfg.general.snmp),
    )
    for ov in matching_overrides(cfg, address):
        for attr in SIMPLE_FIELDS:
            value = getattr(ov, attr)
            if value is not None:
                s.set(attr, value, SOURCE_CONFIG)
        for feat in FEATURES:
            value = getattr(ov.features, feat)
            if value is not None:
                s.set(f"features.{feat}", value, SOURCE_CONFIG)
        for attr in SNMP_FIELDS:
            value = getattr(ov.snmp, attr)
            if value is not None:
                s.set(f"snmp.{attr}", value, SOURCE_CONFIG)
    if manual:
        try:
            key = str(ipaddress.ip_address(address))
        except ValueError:
            key = address
        for setting, value in (manual.get(key) or {}).items():
            s.set(setting, value, SOURCE_MANUAL)
    return s


def baseline_for(cfg: Config, address: str) -> DeviceSettings:
    """Settings without any manual value: what "back to automatic" would give."""
    return settings_for(cfg, address, None)

"""Per-device settings made by hand (TUI or ``device set``), validated like the YAML.

A manual setting is a flat ``key -> value`` pair attached to an IP address, for instance
``type -> "firewall"`` or ``features.arp -> "force"``. Manual settings take precedence over
``devices:`` entries of the configuration file, field by field. They never hold secrets: a
credential is referenced by its name only.
"""

from __future__ import annotations

import difflib
import ipaddress
from typing import Any

import yaml

from snowth_my_net.config.schema import Config, DeviceOverride
from snowth_my_net.config.validate import ConfigError, build
from snowth_my_net.snmp.target import AddressError, split_host_port

FEATURE_NAMES = ("entity", "interfaces", "ipaddr", "fdb", "arp", "lldp", "cdp")
SNMP_KEYS = ("timeout", "retries", "max_repetitions", "use_bulk", "pace_ms")

# Keys that can be set by hand, in display order.
MANUAL_KEYS: tuple[str, ...] = (
    "type", "name", "credential", "disabled", "tolerate_failure",
    *(f"features.{f}" for f in FEATURE_NAMES),
    "vlan_indexing", "uplinks", "access_ports", "uplink_mac_threshold", "ha_mode",
    *(f"snmp.{k}" for k in SNMP_KEYS),
)
LIST_KEYS = frozenset({"uplinks", "access_ports"})

ManualSettings = dict[str, dict[str, Any]]  # IP address -> {key: value}


class ManualError(ValueError):
    pass


def normalize_address(text: str) -> str:
    """IP literal of an address, without any port (``10.0.0.1:1161`` -> ``10.0.0.1``)."""
    try:
        host, _port = split_host_port(text)
        return str(ipaddress.ip_address(host))
    except (AddressError, ValueError):
        raise ManualError(f"{text!r} is not an IP address") from None


def check_key(key: str) -> str:
    if key in MANUAL_KEYS:
        return key
    close = difflib.get_close_matches(key, MANUAL_KEYS, n=1)
    hint = f" (did you mean '{close[0]}'?)" if close else ""
    raise ManualError(f"unknown setting '{key}'{hint}; settable keys: {', '.join(MANUAL_KEYS)}")


def coerce(key: str, raw: str) -> Any:
    """Turn command-line text into a typed value (``true``, ``5``, ``a,b``…)."""
    check_key(key)
    if key in LIST_KEYS:
        return [part.strip() for part in raw.split(",") if part.strip()]
    if raw.strip() == "":
        raise ManualError(f"{key}: empty value (use 'device unset' to remove a setting)")
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError:
        return raw


def validate(key: str, value: Any, cfg: Config | None = None) -> Any:
    """Validate one value with the ``devices:`` schema; returns the normalized value."""
    check_key(key)
    data: dict[str, Any] = {"address": "192.0.2.1"}  # placeholder, not stored
    head, _, tail = key.partition(".")
    if tail:
        data[head] = {tail: value}
    else:
        data[key] = value
    try:
        override = build(DeviceOverride, data)
    except ConfigError as exc:
        raise ManualError("; ".join(e.removeprefix("<config>: ") for e in exc.errors)) from None
    result = getattr(getattr(override, head), tail) if tail else getattr(override, key)
    if result is None:
        raise ManualError(f"{key}: a value is required")
    if key == "credential" and cfg is not None:
        names = [c.name for c in cfg.credentials]
        if result not in names:
            raise ManualError(f"credential: unknown credential '{result}' "
                              f"(configured: {', '.join(names) or 'none'})")
    return result


def parse_assignment(text: str, cfg: Config | None = None) -> tuple[str, Any]:
    """``key=value`` from the command line -> validated ``(key, value)``."""
    key, sep, raw = text.partition("=")
    if not sep:
        raise ManualError(f"{text!r}: expected key=value")
    key = check_key(key.strip())
    return key, validate(key, coerce(key, raw), cfg)


def to_override_entries(settings: ManualSettings) -> list[dict[str, Any]]:
    """Manual settings as ``devices:`` entries (for export to the YAML file)."""
    entries = []
    for address in sorted(settings, key=lambda a: ipaddress.ip_address(a).packed):
        entry: dict[str, Any] = {"address": address}
        for key in MANUAL_KEYS:
            if key not in settings[address]:
                continue
            head, _, tail = key.partition(".")
            if tail:
                entry.setdefault(head, {})[tail] = settings[address][key]
            else:
                entry[key] = settings[address][key]
        entries.append(entry)
    return entries


def from_override_entries(entries: Any, cfg: Config | None = None) -> ManualSettings:
    """Inverse of :func:`to_override_entries`; only single-address entries are accepted."""
    if not isinstance(entries, list):
        raise ManualError("expected a list of devices entries")
    result: ManualSettings = {}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or "address" not in entry:
            raise ManualError(f"entry {i}: expected a mapping with an address")
        try:
            net = ipaddress.ip_network(str(entry["address"]), strict=False)
        except ValueError:
            raise ManualError(f"entry {i}: invalid address {entry['address']!r}") from None
        if net.num_addresses != 1:
            raise ManualError(f"entry {i}: {net} is a range; manual settings apply to one "
                              "address (keep ranges in config.yml)")
        address = str(net.network_address)
        values = result.setdefault(address, {})
        for field, value in entry.items():
            if field == "address":
                continue
            if isinstance(value, dict) and field in ("features", "snmp"):
                for sub, sub_value in value.items():
                    key = check_key(f"{field}.{sub}")
                    values[key] = validate(key, sub_value, cfg)
            else:
                values[check_key(field)] = validate(field, value, cfg)
    return result

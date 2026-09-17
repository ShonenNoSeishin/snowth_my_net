"""Device names — the join key between ``devices.csv`` and ``nodes.csv``/``links.csv``.

Every output that names a device goes through :func:`assign_names`, so that the ``Switch``
column of ``nodes.csv`` is always byte-identical to a ``Device Name`` of ``devices.csv``.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass

from snowth_my_net.config.schema import DeviceNameCfg
from snowth_my_net.snmp.values import one_line


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def base_name(sys_name: str, mgmt_ip: str, override: str | None, cfg: DeviceNameCfg) -> str:
    if override:
        return one_line(override)
    name = one_line(sys_name or "")
    if not name:
        return mgmt_ip
    if _is_ip(name):
        return name
    if cfg.strip_domain == "first_dot":
        name = name.split(".", 1)[0]
    elif cfg.strip_domain == "suffixes":
        lowered = name.lower()
        for suffix in sorted(cfg.domain_suffixes, key=len, reverse=True):
            dotted = "." + suffix.strip().lstrip(".").lower()
            if dotted != "." and lowered.endswith(dotted):
                name = name[: -len(dotted)]
                break
    return name or mgmt_ip


@dataclass(frozen=True)
class NameInput:
    key: int            # device id
    sys_name: str
    mgmt_ip: str
    override: str | None = None


def assign_names(devices: Iterable[NameInput], cfg: DeviceNameCfg) -> dict[int, str]:
    """Final, unique (case-insensitively) names: duplicates get a `` (IP)`` suffix."""
    items = list(devices)
    bases = {d.key: base_name(d.sys_name, d.mgmt_ip, d.override, cfg) for d in items}
    counts: dict[str, int] = {}
    for name in bases.values():
        counts[name.casefold()] = counts.get(name.casefold(), 0) + 1
    result = {}
    for d in items:
        name = bases[d.key]
        if (cfg.duplicate_names == "suffix_ip" and counts[name.casefold()] > 1
                and name != d.mgmt_ip):
            name = f"{name} ({d.mgmt_ip})"
        result[d.key] = name
    return result

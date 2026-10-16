"""Data shown by the terminal interface, independent of Textual (unit-testable)."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any

from snowth_my_net.config.effective import baseline_for, settings_for
from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.config.manual import validate
from snowth_my_net.export.run import exported_devices
from snowth_my_net.snmp.target import split_host_port
from snowth_my_net.state.repo import Repo


@dataclass
class DeviceRow:
    target: str              # address used to poll (may carry a port)
    host: str                # IP address, key of manual settings
    device_id: int | None
    name: str
    device_type: str
    type_rule: str
    vendor: str
    model: str
    status: str              # ok | partial | failed | never
    last_seen: int | None
    error: str

    @property
    def type_mark(self) -> str:
        if not self.device_type:
            return "?"
        return {"manual": "✎", "config": "⚙"}.get(self.type_rule, "")

    def matches(self, text: str, shown: str = "") -> bool:
        """``shown``: the type and status as the table writes them (translated), which a reader
        types as well as the internal words."""
        needle = text.strip().casefold()
        if not needle:
            return True
        haystack = " ".join((self.name, self.target, self.device_type, self.vendor, self.model,
                             self.status, shown))
        return needle in haystack.casefold()


def _sort_key(row: DeviceRow) -> tuple:
    try:
        ip = ipaddress.ip_address(row.host)
        return (row.name.casefold(), ip.version, ip.packed)
    except ValueError:
        return (row.name.casefold(), 9, row.host.encode())


def list_devices(loaded: LoadedConfig, repo: Repo, now: int) -> list[DeviceRow]:
    devices, names = exported_devices(loaded, repo, now)
    rows: list[DeviceRow] = []
    known = set()
    for d in devices:
        known.add(d["mgmt_address"])
        status = d["last_collect_status"] or "never"
        rows.append(DeviceRow(
            target=d["mgmt_address"], host=split_host_port(d["mgmt_address"])[0],
            device_id=d["id"], name=names[d["id"]], device_type=d["device_type"] or "",
            type_rule=d["type_rule"] or "", vendor=d["vendor"] or "", model=d["model"] or "",
            status=status if status in ("ok", "partial", "failed") else "never",
            last_seen=d["last_seen"], error=""))
    manual = repo.manual_settings()
    for t in repo.targets():
        if t["device_id"] is not None or t["is_alias"] or t["address"] in known:
            continue
        host = split_host_port(t["address"])[0]
        s = settings_for(loaded.cfg, host, manual)
        rows.append(DeviceRow(
            target=t["address"], host=host, device_id=None, name=s.name or t["address"],
            device_type=s.type or "", type_rule=s.source("type") if s.type else "",
            vendor="", model="", status="failed" if t["last_error"] else "never",
            last_seen=t["last_ok_at"], error=t["last_error"] or ""))
    rows.sort(key=_sort_key)
    return rows


FORM_KEYS = ("type", "name", "credential", "disabled", "tolerate_failure",
             "features.entity", "features.interfaces", "features.ipaddr", "features.fdb",
             "features.arp", "features.lldp", "features.cdp",
             "snmp.max_repetitions", "snmp.pace_ms", "snmp.use_bulk")


@dataclass
class FormChange:
    to_set: dict[str, Any]
    to_unset: list[str]

    @property
    def empty(self) -> bool:
        return not self.to_set and not self.to_unset


def plan_form_change(loaded: LoadedConfig, host: str, manual: dict,
                     values: dict[str, Any]) -> FormChange:
    """Compare form values with the baseline (config.yml + defaults) and the manual settings.

    A value equal to the baseline removes the manual setting ("back to automatic" for that
    field); any other value becomes a manual setting. ``None`` for ``type``, ``name`` or
    ``credential`` means "automatic". Raises ``ManualError`` on invalid values.
    """
    baseline = baseline_for(loaded.cfg, host)
    current = manual.get(host, {})
    to_set: dict[str, Any] = {}
    to_unset: list[str] = []
    for key, value in values.items():
        if value is None or value == "":
            if key in current:
                to_unset.append(key)
            continue
        value = validate(key, value, loaded.cfg)
        if value == baseline.get(key):
            if key in current:
                to_unset.append(key)
        elif current.get(key) != value:
            to_set[key] = value
    return FormChange(to_set, to_unset)

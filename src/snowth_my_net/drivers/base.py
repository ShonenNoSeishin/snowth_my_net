"""Driver base class and the data a driver may contribute."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import ClassVar

from snowth_my_net.collect.model import DeviceResult, Identification
from snowth_my_net.snmp.client import SnmpClient, Value
from snowth_my_net.snmp.values import Oid, decode_text, normalize_mac, one_line, parse_oid

IFTYPE_80211 = 71


@dataclass
class SyntheticDevice:
    """A device that is not polled itself but described by the device being collected."""

    key_mac: str                        # identity: base MAC (matched against device_macs)
    name: str
    address: str = ""                   # management IP, when known
    model: str = ""
    serial: str = ""
    os_version: str = ""
    location: str = ""
    device_type: str = "wireless"
    type_reason: str = ""
    ports: dict[int, str] = field(default_factory=dict)          # pseudo ifIndex -> name
    stations: list[tuple[str, int, int]] = field(default_factory=list)   # (mac, port, vlan)


def index_mac(index: tuple[int, ...]) -> str | None:
    """A MAC address encoded as the 6 sub-identifiers of a table index, else None."""
    if len(index) != 6 or not all(0 <= part <= 255 for part in index):
        return None
    return normalize_mac(bytes(index))


def text(value: Value) -> str:
    return one_line(decode_text(value)) if isinstance(value, bytes | str) else ""


class Driver:
    name: ClassVar[str] = ""
    title: ClassVar[str] = ""
    vendor: ClassVar[str] = ""
    object_ids: ClassVar[tuple[str, ...]] = ()     # sysObjectID sub-trees this driver serves
    identity_oids: ClassVar[dict[str, str]] = {}   # label -> scalar OID read for refine()
    has_extra: ClassVar[bool] = False

    def matches(self, object_id: str) -> bool:
        return any(object_id == base or object_id.startswith(base + ".")
                   for base in self.object_ids)

    def identity_requests(self) -> dict[str, Oid]:
        return {label: parse_oid(oid) for label, oid in self.identity_oids.items()}

    def refine(self, values: dict[str, Value], ident: Identification) -> dict[str, str]:
        """Return the identity fields this driver can tell (only empty ones are applied)."""
        return {}

    async def identify(self, client: SnmpClient, r: DeviceResult) -> dict[str, str]:
        """Identity fields; the default reads ``identity_oids`` and calls ``refine``."""
        requests = self.identity_requests()
        if not requests:
            return {}
        values = await client.get(list(requests.values()))
        by_label = {label: values.get(oid) for label, oid in requests.items()}
        assert r.ident is not None
        return self.refine(by_label, r.ident)

    async def extra(self, client: SnmpClient, r: DeviceResult, rows) -> None:
        """Observations added after the standard collection (see ``drivers/__init__``)."""


def fill_identity(ident: Identification, found: dict[str, str]) -> list[str]:
    """Apply driver values to empty fields; returns the names of the fields filled."""
    filled = []
    for key, value in found.items():
        value = one_line(value)
        if value and not getattr(ident, key):
            setattr(ident, key, value)
            filled.append(key)
    return filled


VERSION_RE = re.compile(r"\d+(?:\.\d+)+")

"""Sophos Firewall / XGS running SFOS (SFOS-FIREWALL-MIB, sfosXGDeviceInfo).

sysDescr is a generic Linux banner and ENTITY-MIB is absent: model, firmware version and
serial number (the appliance key) only exist in the private MIB. Values are accepted only when
they have the expected shape, so an agent serving something else under these OIDs is ignored.
Verify on a device with ``snowth_my_net probe ADDR sophos-sfos``.
"""

from __future__ import annotations

import re
from typing import ClassVar

from snowth_my_net.collect.model import Identification
from snowth_my_net.drivers.base import Driver, text
from snowth_my_net.snmp.client import Value

SFOS_VERSION = re.compile(r"(?:SFOS\s+)?(?P<v>\d+(?:\.\d+)+(?:\s+MR-?\d+)?(?:-Build\d+)?)",
                          re.IGNORECASE)
MODEL = re.compile(r"^(?:XGS?|SG|XG)\s?\d+[A-Za-z]*(?:\s?(?:w|rev\.?\s?\d+))?$|^SFVH?\S*$",
                   re.IGNORECASE)


class SophosSfos(Driver):
    name = "sophos"
    title = "Sophos Firewall (SFOS)"
    vendor = "Sophos"
    object_ids = ("1.3.6.1.4.1.2604.5",)
    identity_oids: ClassVar[dict[str, str]] = {
        "sfosDeviceType": "1.3.6.1.4.1.2604.5.1.1.3.0",
        "sfosDeviceFWVersion": "1.3.6.1.4.1.2604.5.1.1.4.0",
        "sfosDeviceAppKey": "1.3.6.1.4.1.2604.5.1.1.5.0",
    }

    def matches(self, object_id: str) -> bool:
        return object_id in self.object_ids        # 2604.5 exactly: other Sophos products differ

    def refine(self, values: dict[str, Value], ident: Identification) -> dict[str, str]:
        found = {}
        model = text(values.get("sfosDeviceType"))
        if MODEL.match(model):
            found["model"] = model
        m = SFOS_VERSION.match(text(values.get("sfosDeviceFWVersion")))
        if m:
            found["os_name"] = "SFOS"
            found["os_version"] = m["v"]
        key = text(values.get("sfosDeviceAppKey"))
        if re.fullmatch(r"[A-Za-z0-9-]{6,40}", key):
            found["serial"] = key
        return found

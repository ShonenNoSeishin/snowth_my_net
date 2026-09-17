"""Fortinet FortiGate / FortiWiFi (FORTINET-CORE-MIB, FORTINET-FORTIGATE-MIB).

sysDescr of a FortiGate is only the hostname or model: the version and serial number come from
the private MIB. ``fgSysVersion`` reads ``v7.2.5,build1517,230606 (GA.F)``.
"""

from __future__ import annotations

import re
from typing import ClassVar

from snowth_my_net.collect.model import Identification
from snowth_my_net.drivers.base import Driver, text
from snowth_my_net.snmp.client import Value

FG_VERSION = re.compile(r"v?(?P<v>\d+(?:\.\d+)+)(?:,\s*build(?P<b>\d+))?")


class Fortinet(Driver):
    name = "fortinet"
    title = "Fortinet FortiGate"
    vendor = "Fortinet"
    object_ids = ("1.3.6.1.4.1.12356.101.1", "1.3.6.1.4.1.12356.15")
    identity_oids: ClassVar[dict[str, str]] = {
        "fnSysSerial": "1.3.6.1.4.1.12356.100.1.1.1.0",
        "fgSysVersion": "1.3.6.1.4.1.12356.101.4.1.1.0",
    }

    def refine(self, values: dict[str, Value], ident: Identification) -> dict[str, str]:
        found = {"serial": text(values.get("fnSysSerial"))}
        m = FG_VERSION.match(text(values.get("fgSysVersion")))
        if m:
            found["os_name"] = "FortiOS"
            found["os_version"] = m["v"] + (f" build{m['b']}" if m["b"] else "")
        return found

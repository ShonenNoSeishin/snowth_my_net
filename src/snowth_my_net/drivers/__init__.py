"""Vendor drivers: fill what the standard MIBs cannot say, never replace them.

A driver is chosen for a device when it matches its sysObjectID (or when named in
``devices[].driver``). It can:

* refine the identity from private objects (model, serial, OS version) — only empty fields are
  filled, so the standard collection keeps priority;
* add observations after the standard collection: FDB-like sightings (Wi-Fi clients seen by an
  access point or a router), ARP entries, and synthetic devices (access points published by a
  wireless controller, so that their clients have a position in ``nodes.csv``).

A driver never switches a standard function off, and its failure is recorded as the outcome
of the ``driver`` function of the device, like any other function.
"""

from __future__ import annotations

from snowth_my_net.drivers.base import Driver, SyntheticDevice
from snowth_my_net.drivers.cisco_wlc import CiscoWlc
from snowth_my_net.drivers.fortinet import Fortinet
from snowth_my_net.drivers.mikrotik import MikroTik
from snowth_my_net.drivers.sophos import SophosSfos

DRIVERS: tuple[Driver, ...] = (Fortinet(), SophosSfos(), MikroTik(), CiscoWlc())
NAMES = tuple(d.name for d in DRIVERS)

__all__ = ["DRIVERS", "NAMES", "Driver", "SyntheticDevice", "by_name", "select"]


def by_name(name: str, extra: tuple[Driver, ...] | list[Driver] = ()) -> Driver | None:
    return next((d for d in (*extra, *DRIVERS) if d.name == name), None)


def select(setting: str | None, object_id: str,
           extra: tuple[Driver, ...] | list[Driver] = ()) -> Driver | None:
    """``devices[].driver``: unset or ``auto`` = by sysObjectID, ``none`` = no driver, else the
    named driver (whatever the device announces). Drivers of Python extensions (``extra``) are
    tried first, so an extension can serve a device better than a built-in driver."""
    if setting == "none":
        return None
    if setting and setting != "auto":
        return by_name(setting, extra)
    return next((d for d in (*extra, *DRIVERS) if d.matches(object_id)), None)

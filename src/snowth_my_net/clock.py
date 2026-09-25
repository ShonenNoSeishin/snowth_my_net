"""UTC clock abstraction, so that tests can freeze time.

Every timestamp stored or written by snowth_my_net is an integer number of seconds since the
epoch, taken from the collector's clock (never from a device clock) and rendered in UTC.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime


class Clock:
    """Wall clock (epoch seconds) plus a monotonic clock for deadlines."""

    def now(self) -> int:
        return int(time.time())

    def monotonic(self) -> float:
        return time.monotonic()


class FrozenClock(Clock):
    """Deterministic clock for tests; only moves when told to."""

    def __init__(self, epoch: int) -> None:
        self._epoch = epoch
        self._mono = 0.0

    def now(self) -> int:
        return self._epoch

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: int) -> None:
        self._epoch += seconds
        self._mono += seconds


def iso_z(epoch: int | None) -> str:
    """Render epoch seconds as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC), or ``""`` when unknown."""
    if epoch is None:
        return ""
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_time(epoch: int | None) -> str:
    """The same instant where the reader is, as ``YYYY-MM-DD HH:MM:SS``.

    Everything stored, exported and logged stays in UTC — that is what an importer and a log
    reader need. A page is read by a person, who counts in the hours of their own day, so the
    interface (and only the interface) renders the local time of the machine that serves it
    (``TZ``). The UTC value is kept in the cell's tooltip.
    """
    if epoch is None:
        return ""
    return datetime.fromtimestamp(epoch).astimezone().strftime("%Y-%m-%d %H:%M")


def local_zone(epoch: int | None = None) -> str:
    """The zone, to say once on a page which hours it shows: ``Europe/Brussels``.

    The configured name is preferred over today's abbreviation, which would read ``CEST`` in
    August and ``CET`` in January while the page shows both.
    """
    configured = os.environ.get("TZ", "").strip()
    if configured:
        return configured
    moment = datetime.fromtimestamp(epoch if epoch is not None else time.time()).astimezone()
    offset = moment.strftime("%z")
    return f"{moment.tzname()} ({offset[:3]}:{offset[3:]})" if offset else moment.tzname() or "UTC"

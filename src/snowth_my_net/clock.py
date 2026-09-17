"""UTC clock abstraction, so that tests can freeze time.

Every timestamp stored or written by snowth_my_net is an integer number of seconds since the
epoch, taken from the collector's clock (never from a device clock) and rendered in UTC.
"""

from __future__ import annotations

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

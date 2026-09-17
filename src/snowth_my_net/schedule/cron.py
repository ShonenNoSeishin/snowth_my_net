"""Five-field cron expressions: validation, matching, next fire times, longest gap.

Supported: ``*``, numbers, ranges ``a-b``, steps ``*/n`` and ``a-b/n``, lists, month and day
names, and the shortcuts ``@yearly @annually @monthly @weekly @daily @midnight @hourly``
(``@reboot`` is refused: it has no meaning for a schedule). When both day-of-month and
day-of-week are restricted, a day matches if EITHER matches (Vixie cron semantics). This subset is
understood identically by cron, cronie, systemd-cron and supercronic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SHORTCUTS = {"@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *", "@monthly": "0 0 1 * *",
             "@weekly": "0 0 * * 0", "@daily": "0 0 * * *", "@midnight": "0 0 * * *",
             "@hourly": "0 * * * *"}
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DAYS = {d: i for i, d in enumerate(["sun", "mon", "tue", "wed", "thu", "fri", "sat"])}
FIELDS = (("minute", 0, 59, {}), ("hour", 0, 23, {}), ("day of month", 1, 31, {}),
          ("month", 1, 12, MONTHS), ("day of week", 0, 7, DAYS))


class CronError(ValueError):
    pass


def _value(text: str, low: int, high: int, names: dict[str, int], label: str) -> int:
    key = text.lower()
    if key in names:
        return names[key]
    if not text.isdigit():
        raise CronError(f"{label}: {text!r} is not a number")
    number = int(text)
    if not low <= number <= high:
        raise CronError(f"{label}: {number} is outside {low}-{high}")
    return number


def _field(text: str, low: int, high: int, names: dict[str, int], label: str) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        if not part:
            raise CronError(f"{label}: empty list item")
        base, _, step_text = part.partition("/")
        step = 1
        if step_text:
            if not step_text.isdigit() or int(step_text) == 0:
                raise CronError(f"{label}: invalid step {step_text!r}")
            step = int(step_text)
        if base == "*":
            start, end = low, high
        elif "-" in base:
            a, _, b = base.partition("-")
            start, end = _value(a, low, high, names, label), _value(b, low, high, names, label)
            if start > end:
                raise CronError(f"{label}: range {base!r} is reversed")
        else:
            start = _value(base, low, high, names, label)
            end = high if step_text else start
        values.update(range(start, end + 1, step))
    return frozenset(values)


@dataclass(frozen=True)
class CronExpr:
    text: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    day_restricted: bool
    weekday_restricted: bool

    def matches(self, moment: datetime) -> bool:
        if moment.minute not in self.minutes or moment.hour not in self.hours:
            return False
        if moment.month not in self.months:
            return False
        day_ok = moment.day in self.days
        weekday_ok = (moment.isoweekday() % 7) in self.weekdays
        if self.day_restricted and self.weekday_restricted:
            return day_ok or weekday_ok
        return day_ok and weekday_ok

    def fire_times(self, start: datetime, end: datetime):
        """Every matching minute in ``[start, end)`` (aware datetimes)."""
        moment = start.replace(second=0, microsecond=0)
        if moment < start:
            moment += timedelta(minutes=1)
        while moment < end:
            if moment.month not in self.months:
                moment = (moment.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(
                    day=1)
                continue
            if moment.hour not in self.hours:
                moment = moment.replace(minute=0) + timedelta(hours=1)
                continue
            if self.matches(moment):
                yield moment
            moment += timedelta(minutes=1)


def parse_cron(text: str) -> CronExpr:
    raw = text.strip()
    if raw.lower() == "@reboot":
        raise CronError("@reboot is not a schedule")
    expanded = SHORTCUTS.get(raw.lower(), raw)
    parts = expanded.split()
    if len(parts) != 5:
        raise CronError(f"{text!r}: expected 5 fields (minute hour day month weekday), "
                        f"got {len(parts)}")
    sets = [_field(p, low, high, names, label) for p, (label, low, high, names)
            in zip(parts, FIELDS, strict=True)]
    weekdays = frozenset(0 if d == 7 else d for d in sets[4])
    return CronExpr(raw, sets[0], sets[1], sets[2], sets[3], weekdays,
                    day_restricted=parts[2] != "*", weekday_restricted=parts[4] != "*")


def longest_gap(expr: CronExpr, tz: ZoneInfo | None = None, days: int = 14,
                now: datetime | None = None) -> timedelta | None:
    """Longest interval between two consecutive fire times over ``days`` (None: fires <2×)."""
    zone = tz or ZoneInfo("UTC")
    start = (now or datetime.now(zone)).astimezone(zone)
    previous = None
    gap = None
    for moment in expr.fire_times(start, start + timedelta(days=days)):
        if previous is not None:
            delta = moment - previous
            gap = delta if gap is None or delta > gap else gap
        previous = moment
    return gap

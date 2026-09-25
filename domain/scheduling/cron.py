"""Pure domain rule: cron expression parsing and next-occurrence computation.

Framework-free: no Policy, no I/O, no side effects. Five-field cron
(minute hour day-of-month month day-of-week), minute resolution.

Supported field syntax: ``*``, ``*/n``, ``a-b``, ``a-b/n``,
``a,b,c`` and plain numbers. Day-of-week: 0-6 with 0 = Sunday
(7 is also accepted as Sunday).
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class CronSpec:
    minutes: frozenset
    hours: frozenset
    days: frozenset
    months: frozenset
    weekdays: frozenset


def _parse_field(
    field: str,
    minimum: int,
    maximum: int,
) -> frozenset:
    """Parse one cron field into a set of matching integers."""

    values: set[int] = set()

    for part in field.split(","):

        part = part.strip()

        if not part:
            raise ValueError(
                f"empty cron field part in {field!r}"
            )

        step = 1

        if "/" in part:
            part, step_text = part.split("/", 1)
            step = int(step_text)

            if step < 1:
                raise ValueError(
                    f"bad cron step in {field!r}"
                )

        if part == "*":
            low, high = minimum, maximum

        elif "-" in part:
            low_text, high_text = part.split("-", 1)
            low, high = int(low_text), int(high_text)

        else:
            low = high = int(part)

        if low < minimum or high > maximum or low > high:
            raise ValueError(
                f"cron value out of range in {field!r}"
            )

        values.update(
            range(low, high + 1, step)
        )

    if not values:
        raise ValueError(
            f"cron field matched nothing: {field!r}"
        )

    return frozenset(values)


def parse_cron(expression: str) -> CronSpec:
    """Parse a 5-field cron expression; raise ValueError when invalid."""

    if not isinstance(expression, str):
        raise ValueError("cron expression must be a string")

    fields = expression.split()

    if len(fields) != 5:
        raise ValueError(
            "cron expression needs exactly 5 fields "
            "(minute hour day month weekday)"
        )

    minute, hour, day, month, weekday = fields

    weekdays = _parse_field(weekday, 0, 7)

    # Normalize 7 -> 0 (both mean Sunday).
    if 7 in weekdays:
        weekdays = frozenset(
            {0 if w == 7 else w for w in weekdays}
        )

    return CronSpec(
        minutes=_parse_field(minute, 0, 59),
        hours=_parse_field(hour, 0, 23),
        days=_parse_field(day, 1, 31),
        months=_parse_field(month, 1, 12),
        weekdays=weekdays,
    )


def _matches(spec: CronSpec, moment: datetime) -> bool:
    # Cron day semantics: when BOTH day-of-month and day-of-week are
    # restricted (not "*"), a day matches if EITHER matches (standard
    # cron behavior). When one is "*", only the other constrains.
    dom_restricted = spec.days != frozenset(range(1, 32))
    dow_restricted = spec.weekdays != frozenset(range(0, 7))

    if dom_restricted and dow_restricted:
        day_ok = (
            moment.day in spec.days
            or (moment.weekday() + 1) % 7 in spec.weekdays
        )
    elif dom_restricted:
        day_ok = moment.day in spec.days
    elif dow_restricted:
        day_ok = (moment.weekday() + 1) % 7 in spec.weekdays
    else:
        day_ok = True

    return (
        moment.minute in spec.minutes
        and moment.hour in spec.hours
        and moment.month in spec.months
        and day_ok
    )


def next_after(
    expression: str,
    after: datetime,
    limit_days: int = 366 * 2,
) -> datetime:
    """Next datetime strictly after ``after`` matching the expression.

    Raises ValueError for an invalid expression, RuntimeError when no
    occurrence exists within ``limit_days``.
    """

    spec = parse_cron(expression)

    candidate = after.replace(second=0, microsecond=0) + timedelta(
        minutes=1
    )
    deadline = after + timedelta(days=limit_days)

    while candidate <= deadline:

        if _matches(spec, candidate):
            return candidate

        candidate += timedelta(minutes=1)

    raise RuntimeError(
        f"no cron occurrence within {limit_days} days: "
        f"{expression!r}"
    )

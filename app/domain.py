"""Core time/domain logic: operational day, day kind, holidays, shift blocks.

All times are naive Europe/Oslo wall-clock times. Intervals are half-open
[start, end). The operational day runs 07:00 -> 07:00 next day: a shift
belongs to the calendar date it starts on, and "now" before 07:00 belongs to
yesterday's operational day.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

OPERATIONAL_DAY_START = dt.time(7, 0)


def parse_time(value: str) -> dt.time:
    hours, minutes = value.split(":")
    return dt.time(int(hours), int(minutes))


def easter_sunday(year: int) -> dt.date:
    # Anonymous Gregorian computus.
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def norwegian_holidays(year: int) -> set[dt.date]:
    easter = easter_sunday(year)

    def off(days: int) -> dt.date:
        return easter + dt.timedelta(days=days)

    return {
        dt.date(year, 1, 1),      # 1. nyttårsdag
        off(-3),                  # skjærtorsdag
        off(-2),                  # langfredag
        off(0),                   # 1. påskedag
        off(1),                   # 2. påskedag
        dt.date(year, 5, 1),      # arbeidernes dag
        dt.date(year, 5, 17),     # grunnlovsdagen
        off(39),                  # Kristi himmelfartsdag
        off(49),                  # 1. pinsedag
        off(50),                  # 2. pinsedag
        dt.date(year, 12, 25),    # 1. juledag
        dt.date(year, 12, 26),    # 2. juledag
    }


def day_kind(date: dt.date) -> str:
    """'weekday' or 'weekend_holiday' (D21: holidays follow the weekend regime)."""
    if date.weekday() >= 5 or date in norwegian_holidays(date.year):
        return "weekend_holiday"
    return "weekday"


def operational_day(now: dt.datetime) -> dt.date:
    if now.time() < OPERATIONAL_DAY_START:
        return now.date() - dt.timedelta(days=1)
    return now.date()


@dataclass(frozen=True)
class Segment:
    start: dt.datetime
    end: dt.datetime  # exclusive; may be on the next calendar date

    def contains(self, when: dt.datetime) -> bool:
        return self.start <= when < self.end


def shift_segments(
    date: dt.date,
    shift_start: dt.time,
    shift_end: dt.time,
    rotation_time: dt.time | None,
) -> list[Segment]:
    """Cut a shift on `date` into planning blocks at its category's rotation
    time (rotation_rules, D35). A shift ending at or before its start crosses
    midnight. A rotation point on the shift's boundary does not cut."""
    start = dt.datetime.combine(date, shift_start)
    end = dt.datetime.combine(date, shift_end)
    if end <= start:
        end += dt.timedelta(days=1)
    if rotation_time is not None:
        cut = dt.datetime.combine(date, rotation_time)
        if start < cut < end:
            return [Segment(start, cut), Segment(cut, end)]
    return [Segment(start, end)]

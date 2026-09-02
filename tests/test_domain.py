"""Unit tests for app.domain — run with:  python -m unittest discover -s tests"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import domain  # noqa: E402


class HolidayTests(unittest.TestCase):
    def test_easter_sunday(self):
        self.assertEqual(domain.easter_sunday(2026), dt.date(2026, 4, 5))
        self.assertEqual(domain.easter_sunday(2025), dt.date(2025, 4, 20))
        self.assertEqual(domain.easter_sunday(2027), dt.date(2027, 3, 28))

    def test_norwegian_holidays_2026(self):
        holidays = domain.norwegian_holidays(2026)
        self.assertIn(dt.date(2026, 5, 17), holidays)          # grunnlovsdagen
        self.assertIn(dt.date(2026, 4, 2), holidays)           # skjærtorsdag
        self.assertIn(dt.date(2026, 4, 3), holidays)           # langfredag
        self.assertIn(dt.date(2026, 4, 6), holidays)           # 2. påskedag
        self.assertIn(dt.date(2026, 5, 14), holidays)          # Kr. himmelfartsdag
        self.assertIn(dt.date(2026, 5, 25), holidays)          # 2. pinsedag
        self.assertNotIn(dt.date(2026, 4, 1), holidays)

    def test_day_kind(self):
        self.assertEqual(domain.day_kind(dt.date(2026, 9, 7)), "weekday")          # Monday
        self.assertEqual(domain.day_kind(dt.date(2026, 9, 12)), "weekend_holiday")  # Saturday
        self.assertEqual(domain.day_kind(dt.date(2026, 5, 14)), "weekend_holiday")  # holiday Thu
        self.assertEqual(domain.day_kind(dt.date(2026, 12, 25)), "weekend_holiday")


class OperationalDayTests(unittest.TestCase):
    def test_daytime_belongs_to_same_date(self):
        now = dt.datetime(2026, 9, 7, 13, 0)
        self.assertEqual(domain.operational_day(now), dt.date(2026, 9, 7))

    def test_after_midnight_belongs_to_previous_date(self):
        now = dt.datetime(2026, 9, 8, 3, 30)
        self.assertEqual(domain.operational_day(now), dt.date(2026, 9, 7))

    def test_boundary_at_0700(self):
        self.assertEqual(
            domain.operational_day(dt.datetime(2026, 9, 8, 7, 0)), dt.date(2026, 9, 8)
        )
        self.assertEqual(
            domain.operational_day(dt.datetime(2026, 9, 8, 6, 59)), dt.date(2026, 9, 7)
        )


class ShiftSegmentTests(unittest.TestCase):
    DATE = dt.date(2026, 9, 7)

    def cut(self, start, end, rotation):
        return domain.shift_segments(
            self.DATE, domain.parse_time(start), domain.parse_time(end),
            domain.parse_time(rotation) if rotation else None,
        )

    def test_early_shift_cuts_at_11(self):
        segments = self.cut("07:00", "15:00", "11:00")
        self.assertEqual([(s.start.hour, s.end.hour) for s in segments], [(7, 11), (11, 15)])

    def test_late_shift_cuts_at_18(self):
        segments = self.cut("14:00", "22:00", "18:00")
        self.assertEqual([(s.start.hour, s.end.hour) for s in segments], [(14, 18), (18, 22)])

    def test_mid_shift_cuts_at_16(self):
        segments = self.cut("12:00", "20:00", "16:00")
        self.assertEqual([(s.start.hour, s.end.hour) for s in segments], [(12, 16), (16, 20)])

    def test_rotation_outside_shift_does_not_cut(self):
        segments = self.cut("12:00", "20:00", "11:00")
        self.assertEqual(len(segments), 1)

    def test_rotation_on_boundary_does_not_cut(self):
        segments = self.cut("15:00", "22:00", "15:00")
        self.assertEqual(len(segments), 1)

    def test_night_shift_crosses_midnight(self):
        (segment,) = self.cut("22:00", "07:00", None)
        self.assertEqual(segment.start, dt.datetime(2026, 9, 7, 22, 0))
        self.assertEqual(segment.end, dt.datetime(2026, 9, 8, 7, 0))

    def test_half_open_contains(self):
        (segment,) = self.cut("15:00", "22:00", None)
        self.assertTrue(segment.contains(dt.datetime(2026, 9, 7, 15, 0)))
        self.assertFalse(segment.contains(dt.datetime(2026, 9, 7, 22, 0)))


if __name__ == "__main__":
    unittest.main()

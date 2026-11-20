import unittest
from datetime import date

from days import add_days, business_days, days_between, is_leap, month_end, weekday_name


class LeapTest(unittest.TestCase):
    def test_2024_is_leap(self):
        self.assertTrue(is_leap(2024))

    def test_1900_is_not_leap(self):
        self.assertFalse(is_leap(1900))

    def test_2000_is_leap(self):
        self.assertTrue(is_leap(2000))

    def test_2023_is_not_leap(self):
        self.assertFalse(is_leap(2023))


class WeekdayTest(unittest.TestCase):
    def test_known_day(self):
        self.assertEqual(weekday_name(date(2026, 11, 14)), "Saturday")


class AddDaysTest(unittest.TestCase):
    def test_crosses_month(self):
        self.assertEqual(add_days(date(2026, 1, 31), 1), date(2026, 2, 1))

    def test_negative(self):
        self.assertEqual(add_days(date(2026, 3, 1), -1), date(2026, 2, 28))


class DaysBetweenTest(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(days_between(date(2026, 1, 1), date(2026, 1, 10)), 9)

    def test_is_signed(self):
        self.assertEqual(days_between(date(2026, 1, 10), date(2026, 1, 1)), -9)


class MonthEndTest(unittest.TestCase):
    def test_february_leap(self):
        self.assertEqual(month_end(2024, 2), date(2024, 2, 29))

    def test_december(self):
        self.assertEqual(month_end(2026, 12), date(2026, 12, 31))


class BusinessDaysTest(unittest.TestCase):
    def test_one_week(self):
        # 2026-11-09 是周一，到 11-13 周五，共 5 个工作日
        self.assertEqual(business_days(date(2026, 11, 9), date(2026, 11, 13)), 5)

    def test_skips_weekend(self):
        self.assertEqual(business_days(date(2026, 11, 13), date(2026, 11, 16)), 2)


if __name__ == "__main__":
    unittest.main()

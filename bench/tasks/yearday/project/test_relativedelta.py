"""回归测试：relativedelta(yearday=n) 必须等价于「1 月 1 日起第 n 天」。

即 first + relativedelta(yearday=n) == first + timedelta(days=n-1)。
"""
import calendar
import datetime
import unittest

from relativedelta import relativedelta


class YeardayOrdinalTest(unittest.TestCase):
    def test_yearday_is_ordinal_day(self):
        for year in (1900, 2000, 2001, 2024):
            first = datetime.date(year, 1, 1)
            last = 366 + calendar.isleap(year)
            for n in range(1, last):
                with self.subTest(year=year, yearday=n):
                    got = first + relativedelta(yearday=n)
                    want = first + datetime.timedelta(days=n - 1)
                    self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()

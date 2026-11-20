"""可见测试 —— agent 能看到、能跑。它们一开始就是全绿的。

这是个陷阱，也是现实：可见测试全绿不等于做对了。
隐藏测试（agent 看不到）会去碰边界情况。
"""
from __future__ import annotations

import unittest

from stats import mean, median, stdev, summary


class TestHappyPath(unittest.TestCase):
    def test_mean_basic(self):
        self.assertEqual(mean([1, 2, 3]), 2)

    def test_median_sorted_odd(self):
        self.assertEqual(median([1, 2, 3]), 2)

    def test_median_sorted_even(self):
        self.assertEqual(median([1, 2, 3, 4]), 2.5)

    def test_summary_shape(self):
        out = summary([1, 2, 3])
        self.assertEqual(set(out), {"mean", "median", "stdev"})


if __name__ == "__main__":
    unittest.main()

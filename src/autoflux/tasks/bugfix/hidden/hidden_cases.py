"""隐藏测试 —— agent 永远看不到这个文件。

评测时它被注入到工作区的副本里，跑完副本即销毁。
这些用例专挑可见测试没覆盖的边界：空输入、乱序、样本标准差。
"""
from __future__ import annotations

import unittest

from stats import mean, median, stdev


class TestMeanEdges(unittest.TestCase):
    def test_mean_empty_raises(self):
        with self.assertRaises(ValueError):
            mean([])

    def test_mean_basic(self):
        self.assertAlmostEqual(mean([1, 2, 3, 4]), 2.5)


class TestMedianEdges(unittest.TestCase):
    def test_median_sorted_odd(self):
        self.assertEqual(median([1, 2, 3]), 2)

    def test_median_unsorted(self):
        self.assertEqual(median([3, 1, 2]), 2)
        self.assertEqual(median([10, 1, 5, 3]), 4)


class TestStdevEdges(unittest.TestCase):
    def test_stdev_is_sample_not_population(self):
        # 样本标准差（除以 n-1），[2,4,4,4,5,5,7,9] 应为 2.138...
        self.assertAlmostEqual(stdev([2, 4, 4, 4, 5, 5, 7, 9]), 2.138, places=3)

    def test_stdev_single_value_raises(self):
        with self.assertRaises(ValueError):
            stdev([5])


if __name__ == "__main__":
    unittest.main()

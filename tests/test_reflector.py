from __future__ import annotations

import unittest

from autoflux.reflector import TemplateReflector
from autoflux.types import Score


class TestReflector(unittest.TestCase):
    def test_refuses_without_signal(self):
        r = TemplateReflector()
        with self.assertRaises(ValueError):
            r.reflect(None, ["a"], [])  # type: ignore[arg-type]

    def test_uses_signal(self):
        r = TemplateReflector()
        text = r.reflect(Score(1, 3, ("FAIL: test_x",)), ["read_file"], [])
        self.assertIn("1/3", text)
        self.assertIn("规则：", text)

    def test_perfect_score_keeps_current(self):
        r = TemplateReflector()
        text = r.reflect(Score(3, 3), [], [])
        self.assertIn("通过", text)

    def test_diagnosis_beats_blank_details(self):
        """盲评测只给总分；诊断里的明细必须被用上。"""
        r = TemplateReflector()
        text = r.reflect(
            Score(7, 10),
            [],
            [],
            diagnosis="FAIL: test_stdev_single_value_raises\nFAIL: test_median_unsorted",
        )
        self.assertIn("test_stdev_single_value_raises", text)
        self.assertNotIn("未提供失败明细", text)

    def test_without_diagnosis_says_so(self):
        r = TemplateReflector()
        text = r.reflect(Score(7, 10), [], [])
        self.assertIn("未提供失败明细", text)


if __name__ == "__main__":
    unittest.main()

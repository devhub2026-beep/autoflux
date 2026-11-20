from __future__ import annotations

import unittest
from pathlib import Path

from autoflux.employment import Dataset, verify

DATA = Path(__file__).resolve().parents[1] / "examples" / "employment" / "data" / "wages_2025.csv"


class DatasetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ds = Dataset(DATA)

    def test_reads_nineteen_industries(self) -> None:
        self.assertEqual(len(self.ds.rows), 19)

    def test_facts(self) -> None:
        self.assertEqual(self.ds.total.wage, 129441)
        self.assertEqual(self.ds.top.wage, 248752)
        self.assertEqual(self.ds.low.wage, 62461)
        self.assertEqual(self.ds.fastest.growth, 10.3)
        self.assertEqual([r.name for r in self.ds.falling], ["房地产业", "租赁和商务服务业"])
        self.assertEqual(len(self.ds.above_total), 10)
        self.assertAlmostEqual(self.ds.gap_ratio, 3.98, places=2)

    def test_context_has_table_and_facts(self) -> None:
        text = self.ds.context()
        self.assertIn("248752", text)
        self.assertIn("19", text)
        self.assertIn("住宿和餐饮业", text)


class VerifyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ds = Dataset(DATA)

    def test_true_numbers_pass(self) -> None:
        answer = (
            "最高是信息传输、软件和信息技术服务业 248752 元，最低是住宿和餐饮业 62461 元，"
            "相差 3.98 倍；全国合计 129441 元；农、林、牧、渔业增长 10.3%。"
        )
        self.assertEqual(verify(answer, self.ds), [])

    def test_fabricated_number_is_caught(self) -> None:
        answer = "全国合计 150000 元，最高行业 248752 元。"
        problems = verify(answer, self.ds)
        self.assertEqual(len(problems), 1)
        self.assertIn("150000", problems[0])

    def test_derived_numbers_pass(self) -> None:
        # 186291 = 248752 - 62461，表里没有这两个数并列，但能算出来
        answer = "最高与最低相差 186291 元。"
        self.assertEqual(verify(answer, self.ds), [])

    def test_years_and_counts_are_ignored(self) -> None:
        answer = "2025 年有 19 个行业门类，其中 10 个高于合计，我给 3 条建议。"
        self.assertEqual(verify(answer, self.ds), [])

    def test_growth_with_two_decimals_still_matches(self) -> None:
        answer = "农、林、牧、渔业名义增长 10.30%。"
        self.assertEqual(verify(answer, self.ds), [])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from autoflux.skillbook import Skillbook, normalize

from . import ScratchCase


class TestSkillbook(ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        self.path = self.root / "state.db"
        self.book = Skillbook(self.path)

    def tearDown(self) -> None:
        self.book.close()
        super().tearDown()

    def test_add_and_read(self):
        self.assertIsNotNone(self.book.add("规则：先跑测试再改代码"))
        self.assertIn("规则：先跑测试再改代码", self.book.skills())

    def test_duplicate_rejected(self):
        self.book.add("规则：先跑测试再改代码")
        self.assertIsNone(self.book.add("规则：先跑测试再改代码！"))
        self.assertEqual(self.book.count(), 1)

    def test_empty_rejected(self):
        self.assertIsNone(self.book.add("   "))

    def test_persist_across_instances(self):
        self.book.add("规则：动手前先读文件")
        self.book.close()
        again = Skillbook(self.path)
        self.assertIn("规则：动手前先读文件", again.skills())
        again.close()

    def test_wins_ordering(self):
        self.book.add("规则：A")
        self.book.add("规则：B")
        self.book.bump_win([2])
        self.assertEqual(self.book.skills()[0], "规则：B")

    def test_normalize(self):
        self.assertEqual(normalize("Rule: A!"), normalize("rule a"))


if __name__ == "__main__":
    unittest.main()

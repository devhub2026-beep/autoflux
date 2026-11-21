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

    # -- 淘汰 ---------------------------------------------------------
    def _age(self, ident: int, days: int) -> None:
        self.book._con.execute(
            "UPDATE strategies SET created_at = created_at - ? WHERE id = ?",
            (days * 86400, ident),
        )
        self.book._con.commit()

    def test_prune_drops_old_rule_that_never_won(self):
        ident = self.book.add("规则：卡住就把依赖全删了重装")
        assert ident is not None
        self.book.bump_use([ident, ident, ident])
        self._age(ident, 45)
        self.assertEqual(self.book.prune(), 1)
        self.assertEqual(self.book.count(), 0)

    def test_prune_keeps_winner_and_unused_rule(self):
        winner = self.book.add("规则：先读失败的断言再动手")
        unused = self.book.add("规则：新写下的，还没轮到它上场")
        assert winner is not None and unused is not None
        self.book.bump_use([winner, winner, winner, winner, winner])
        self.book.bump_win([winner])
        self._age(winner, 45)
        self._age(unused, 45)
        self.assertEqual(self.book.prune(), 0)
        self.assertEqual(self.book.count(), 2)

    def test_prune_caps_total_and_keeps_newest(self):
        for i in range(210):
            self.book.add(f"规则：第{i}条")
        self.assertEqual(self.book.prune(max_rows=200), 10)
        self.assertEqual(self.book.count(), 200)
        kept = self.book.skills(limit=200)
        self.assertNotIn("规则：第0条", kept)
        self.assertIn("规则：第209条", kept)


if __name__ == "__main__":
    unittest.main()

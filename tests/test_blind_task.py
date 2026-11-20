from __future__ import annotations

import unittest

from autoflux.tasks.bugfix.task import BugfixBlindTask, BugfixTask

from . import ScratchCase


class TestBlindVariant(ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        self.ws = self.root / "ws"

    def test_blind_hides_details_but_keeps_score(self):
        task = BugfixBlindTask()
        task.prepare(self.ws)
        score = task.evaluate(self.ws)
        self.assertEqual((score.passed, score.total), (6, 10))
        self.assertEqual(score.details, ())

    def test_blind_matches_open_score(self):
        open_task = BugfixTask()
        open_task.prepare(self.ws)
        blind_task = BugfixBlindTask()
        a = open_task.evaluate(self.ws)
        b = blind_task.evaluate(self.ws)
        self.assertEqual((a.passed, a.total), (b.passed, b.total))
        self.assertNotEqual(a.details, b.details)

    def test_diagnose_gives_back_the_details(self):
        """evaluate 藏起来的明细，diagnose 必须能给出——这是反思的报酬。"""
        task = BugfixBlindTask()
        task.prepare(self.ws)
        self.assertEqual(task.evaluate(self.ws).details, ())
        diag = task.diagnose(self.ws)
        self.assertIn("test_mean_empty_raises", diag)
        self.assertIn("FAIL", diag)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path

from autoflux.tasks.bugfix.task import BugfixTask

from . import ScratchCase

_FIXES = Path(__file__).resolve().parents[1] / "src/autoflux/tasks/bugfix/fixes"


class TestBugfixEvaluator(ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        self.ws = self.root / "ws"
        self.task = BugfixTask()
        self.task.prepare(self.ws)

    def test_initial_score(self):
        score = self.task.evaluate(self.ws)
        # 4 个可见测试 + 6 个隐藏测试；初始代码通过 6 个
        self.assertEqual(score.total, 10)
        self.assertEqual(score.passed, 6)

    def test_hidden_cases_not_exposed(self):
        self.assertFalse(any(self.ws.rglob("hidden_cases.py")))

    def test_evaluation_does_not_pollute_workspace(self):
        before = sorted(p.name for p in self.ws.rglob("*"))
        self.task.evaluate(self.ws)
        after = sorted(p.name for p in self.ws.rglob("*"))
        self.assertEqual(before, after)

    def test_full_fix_scores_perfect(self):
        (self.ws / "stats.py").write_text(
            (_FIXES / "full_stats.py").read_text(encoding="utf-8"), encoding="utf-8"
        )
        score = self.task.evaluate(self.ws)
        self.assertEqual(score.passed, score.total)


if __name__ == "__main__":
    unittest.main()

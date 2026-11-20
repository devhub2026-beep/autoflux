"""goal 模式的部分分：判定命令是 unittest 时，失败也要给出「几分之几」。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from autoflux.tasks.goal import GoalTask

_TEST = """import unittest

class T(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(1, 1)

    def test_ok2(self):
        self.assertEqual(2, 2)

    def test_bad(self):
        self.assertEqual(1, 2)
"""


class PartialScoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.src = self.root / "project"
        self.src.mkdir()
        (self.src / "test_demo.py").write_text(_TEST, encoding="utf-8")

    def _task(self) -> GoalTask:
        return GoalTask(
            goal="让测试全过",
            check=f'"{sys.executable}" -m unittest discover -q',
            source=self.src,
        )

    def test_failing_unittest_gives_partial_score(self) -> None:
        task = self._task()
        score = task.evaluate(self.src)
        self.assertEqual((score.passed, score.total), (2, 3))
        self.assertLess(score.ratio, 1.0)

    def test_passing_unittest_gives_full_score(self) -> None:
        (self.src / "test_demo.py").write_text(
            _TEST.replace("self.assertEqual(1, 2)", "self.assertEqual(1, 1)"),
            encoding="utf-8",
        )
        score = self._task().evaluate(self.src)
        # 退出码 0 就是满分（不看 unittest 的条数）
        self.assertEqual(score.ratio, 1.0)
        self.assertEqual(score.passed, score.total)

    def test_non_unittest_check_stays_binary(self) -> None:
        task = GoalTask(goal="x", check="exit /b 1", source=self.src)
        score = task.evaluate(self.src)
        self.assertEqual((score.passed, score.total), (0, 1))


if __name__ == "__main__":
    unittest.main()

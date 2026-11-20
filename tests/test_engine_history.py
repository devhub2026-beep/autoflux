from __future__ import annotations

import unittest

from autoflux.config import Limits
from autoflux.graph import MAX_RECENT_CHARS, GraphEngine
from autoflux.skillbook import Skillbook
from autoflux.stop import StopPolicy
from autoflux.trace import NullTracer
from autoflux.types import Action

from . import ScratchCase


class TestEngineHistory(ScratchCase):
    """历史记录的回归测试：重复输出不重复塞、上下文按预算裁剪。"""

    def setUp(self) -> None:
        super().setUp()
        self.book = Skillbook(self.root / "s.db")
        self.engine = GraphEngine(
            task=None,  # type: ignore[arg-type]
            agent=None,  # type: ignore[arg-type]
            tools=[],
            reflector=None,  # type: ignore[arg-type]
            skillbook=self.book,
            stop_policy=StopPolicy(Limits()),
            tracer=NullTracer(),
            workdir=self.root / "ws",
        )
        self.engine._seen = {}

    def tearDown(self) -> None:
        self.book.close()
        super().tearDown()

    def test_repeated_output_is_collapsed(self):
        hist: list[str] = []
        act = Action("tool", "read_file", {"path": "stats.py"})
        self.engine._record(hist, 0, act, "CONTENT")
        self.engine._record(hist, 1, act, "CONTENT")
        self.assertIn("CONTENT", hist[0])
        self.assertIn("未重复展示", hist[1])

    def test_changed_output_is_kept(self):
        hist: list[str] = []
        act = Action("tool", "read_file", {"path": "stats.py"})
        self.engine._record(hist, 0, act, "OLD")
        self.engine._record(hist, 1, act, "NEW")
        self.assertIn("NEW", hist[1])

    def test_full_content_not_truncated_to_400(self):
        hist: list[str] = []
        body = "x" * 1500
        self.engine._record(hist, 0, Action("tool", "read_file", {"path": "a"}), body)
        self.assertEqual(hist[0].count("x"), 1500)

    def test_recent_respects_char_budget(self):
        hist = ["y" * 1000 for _ in range(20)]
        recent = self.engine._recent(hist)
        self.assertLessEqual(sum(len(r) for r in recent), MAX_RECENT_CHARS + 1000)
        self.assertGreaterEqual(len(recent), 1)
        self.assertEqual(recent[-1], hist[-1])


if __name__ == "__main__":
    unittest.main()

"""卡住提醒：四条客观计数各自触发，健康状态不打扰。"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from autoflux.graph import GraphEngine


def note(**state) -> str:
    return GraphEngine._note(SimpleNamespace(), state)  # type: ignore[arg-type]


class NudgeTest(unittest.TestCase):
    def test_repeat_triggers(self) -> None:
        text = note(step=5, action_seq=["tool:read_file"] * 3)
        self.assertIn("连续 3 步", text)

    def test_repeat_needs_three_in_a_row(self) -> None:
        text = note(step=5, action_seq=["a", "b", "a"])
        self.assertNotIn("同一件事", text)

    def test_stall_triggers(self) -> None:
        text = note(step=12, last_progress_step=2, action_seq=[])
        self.assertIn("没有新的评测结果", text)

    def test_no_plan_after_six_steps(self) -> None:
        text = note(step=6, plan=[], action_seq=[])
        self.assertIn("还没写过计划", text)

    def test_plan_written_but_not_ticked(self) -> None:
        text = note(step=5, plan=[("a", False), ("b", False)], action_seq=[])
        self.assertIn("只划掉了 0 项", text)

    def test_plan_all_ticked_is_quiet(self) -> None:
        text = note(step=5, plan=[("a", True), ("b", True)], action_seq=[])
        self.assertNotIn("只划掉", text)

    def test_healthy_state_is_silent(self) -> None:
        text = note(
            step=3,
            last_progress_step=2,
            action_seq=["tool:read_file", "submit"],
            plan=[("a", True)],
        )
        self.assertEqual(text, "")


if __name__ == "__main__":
    unittest.main()

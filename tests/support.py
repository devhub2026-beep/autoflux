"""测试专用的确定性替身。

生产代码里**没有**这种东西：产品只认 LLM 后端。
这里的剧本 agent 只用来在测试里固定动作序列，好让「循环机制」本身可验证。
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from autoflux.protocols import Tool
from autoflux.types import Action, Observation

_FIXES = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "autoflux"
    / "tasks"
    / "bugfix"
    / "fixes"
)


class ScriptedAgent:
    """按顺序播放一串写死的动作。它不思考，只是测试里的输入源。"""

    def __init__(self, plan: Sequence[Action]) -> None:
        self._plan = list(plan)
        self._i = 0

    def decide(self, obs: Observation, tools: Sequence[Tool], skills: Sequence[str]) -> Action:
        if self._i >= len(self._plan):
            return Action("stop", text="剧本已放完")
        action = self._plan[self._i]
        self._i += 1
        return action


def build_scripted_plan() -> list[Action]:
    """先部分修 -> 提交 -> 反思 -> 全修 -> 再提交。"""
    partial = (_FIXES / "partial_stats.py").read_text(encoding="utf-8")
    full = (_FIXES / "full_stats.py").read_text(encoding="utf-8")

    return [
        Action("tool", "read_file", {"path": "stats.py"}),
        Action("submit"),  # 先看看现状，别急着改
        Action("tool", "read_file", {"path": "stats.py"}),
        Action("tool", "write_file", {"path": "stats.py", "content": partial}),
        Action("submit"),
        Action("reflect"),  # 拿失败明细做一次复盘
        Action("tool", "write_file", {"path": "stats.py", "content": full}),
        Action("tool", "run_tests"),
        Action("submit"),
    ]

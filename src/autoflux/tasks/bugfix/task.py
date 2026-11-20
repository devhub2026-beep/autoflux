"""bugfix 任务：修一个统计模块的三处 bug。

分数 = 隐藏测试通过率。agent 看不到隐藏测试。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ...evaluator import EvalSpec, run_evaluation
from ...types import Score

_ROOT = Path(__file__).parent


class BugfixTask:
    name = "bugfix"

    def brief(self) -> str:
        return (
            "修好工作区里的代码：workspace/stats.py 里有埋好的 bug，"
            "判分用隐藏测试（你现在看不到），可见测试只是陷阱并非全部要求。"
        )

    def prepare(self, dest: Path) -> None:
        shutil.copytree(_ROOT / "workspace", dest, dirs_exist_ok=True)

    def evaluate(self, workspace: Path) -> Score:
        return run_evaluation(workspace, EvalSpec(hidden_dir=_ROOT / "hidden"))


class BugfixBlindTask(BugfixTask):
    """同一个 bug，但评测只回总分，不给失败明细。

    这是刻意造出来的「信息缺口」：它知道自己 8/10，但不知道错在哪两个。
    想拿到明细只有一个办法——花一步反思，而反思会调用这里的 ``diagnose``
    去把隐藏日志捞出来。反思因此有了动机：它买的是信息，不是安慰。
    """

    name = "bugfix-blind"

    def evaluate(self, workspace: Path) -> Score:
        full = super().evaluate(workspace)
        return Score(full.passed, full.total)

    def diagnose(self, workspace: Path) -> str:
        """反思时可取用的诊断：把失败明细交出来。"""
        full = super().evaluate(workspace)
        if not full.details:
            return "全部通过，无失败明细。"
        return "\n".join(full.details)


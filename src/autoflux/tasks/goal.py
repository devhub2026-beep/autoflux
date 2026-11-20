"""目标模式：人给一句话目标和一条外部检查命令，剩下全由 agent 决定。

和 bugfix 那种「任务写死在代码里」的区别：
- 做什么、先做哪一步、改哪个文件、何时提交、何时放弃，都不在代码里
- 代码只提供两样东西：一句话目标（进提示词）、一条外部命令（判真假）
- 判定仍然是外部的：退出码 0 才算过，模型不能自己给自己打分
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..evaluator import parse_unittest
from ..types import Score

_IGNORE = shutil.ignore_patterns(
    ".git", ".venv", "__pycache__", "*.pyc", ".idea", "runs", ".autoflux",
    "node_modules", "dist", "build", "*.egg-info", ".pytest_cache",
)


class GoalTask:
    """把「做什么」交给 agent，把「算不算过」交给外部命令。"""

    name = "goal"

    def __init__(
        self,
        goal: str,
        check: str,
        source: Path,
        timeout: float = 180.0,
        max_detail: int = 1200,
    ) -> None:
        self.goal = goal
        self.check = check
        self.source = Path(source).resolve()
        self.timeout = timeout
        self.max_detail = max_detail

    def brief(self) -> str:
        """给 agent 看的任务书：目标是什么、怎么算过。"""
        return (
            f"{self.goal}\n\n"
            "工作区里已经有一份起始目录的副本，你只能改工作区里的文件。"
            f"提交时系统会在工作区执行判定命令：{self.check}\n"
            "退出码 0 算过。失败时你可以用 reflect 换到失败输出。"
        )

    def prepare(self, dest: Path) -> None:
        dest = Path(dest).resolve()
        if dest == self.source or self.source in dest.parents:
            raise ValueError(f"工作区不能放在起始目录里面：{dest}")
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(self.source, dest, ignore=_IGNORE)

    def evaluate(self, workspace: Path) -> Score:
        rc, out = self._run(workspace)
        if rc == 0:
            return Score(1, 1)
        # 判定命令通常是 unittest：失败时也有 `Ran N tests` 和 `FAILED (...)`，
        # 那就是现成的部分分。读不出来才退回 0/1。
        partial = parse_unittest(out)
        if partial is not None and partial.total > 0:
            passed = partial.passed
            if passed >= partial.total:  # 退出码非 0，就不能算满分
                passed = partial.total - 1
            details = tuple(self._tail(d) for d in (partial.details or ()))
            return Score(passed, partial.total, details)
        return Score(0, 1, (self._tail(out),))

    def diagnose(self, workspace: Path) -> str:
        rc, out = self._run(workspace)
        return f"检查命令退出码 {rc}\n{self._tail(out, 4000)}"

    # -- 内部 ---------------------------------------------------------
    def _run(self, workspace: Path) -> tuple[int, str]:
        try:
            proc = subprocess.run(  # noqa: S602 —— 判定命令本来就是用户给的一行 shell
                self.check,
                shell=True,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return 124, f"检查命令超时（超过 {self.timeout:g} 秒）"
        except OSError as exc:
            return 127, f"检查命令无法启动：{exc}"
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    def _tail(self, text: str, limit: int | None = None) -> str:
        limit = limit or self.max_detail
        text = (text or "").strip()
        return text[-limit:] if len(text) > limit else text

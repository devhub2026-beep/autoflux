"""核心数据类型。

这里只有数据，没有行为分支——引擎的所有判断都依赖这些不可变结构。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .usage import Usage

ActionKind = Literal["tool", "plan", "reflect", "submit", "stop"]


@dataclass(frozen=True)
class Score:
    """一次评测的结果。由 Task 的评测器产出，agent 无权修改。"""

    passed: int
    total: int
    details: tuple[str, ...] = ()

    @property
    def ratio(self) -> float:
        if self.total <= 0:
            return 0.0
        return self.passed / self.total

    def __str__(self) -> str:
        head = f"{self.passed}/{self.total} ({self.ratio:.0%})"
        if not self.details:
            return head
        body = "\n".join(f"  - {d}" for d in self.details)
        return f"{head}\n{body}"


@dataclass(frozen=True)
class ActionResult:
    """工具调用的结果。failed 只用于「没跑到」，不用于「跑出来但结果不对」。"""

    output: str = ""
    failed: bool = False


@dataclass(frozen=True)
class Action:
    """agent 的一次决策。

    kind == "tool"     -> 调用 name 指定的工具，参数在 args
    kind == "plan"     -> 写/改自己的子目标清单，args["steps"] 是字符串列表
    kind == "reflect"  -> 请求反思；text 可作为额外的反思提示
    kind == "submit"   -> 提交当前工作区接受评测
    kind == "stop"     -> 主动放弃，text 里应当写清楚卡在哪
    """

    kind: ActionKind
    name: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    text: str = ""

    def describe(self) -> str:
        if self.kind == "tool":
            return f"tool:{self.name}({', '.join(f'{k}={v!r}' for k, v in self.args.items())})"
        if self.kind == "plan":
            steps = self.args.get("steps") or []
            return f"plan({len(steps)} 项)"
        if self.kind == "reflect":
            return "reflect"
        if self.kind == "submit":
            return "submit"
        return f"stop({self.text})"


@dataclass(frozen=True)
class Observation:
    """喂给 agent 的全部信息。agent 不看别的东西。"""

    step: int
    attempt: int
    recent: tuple[str, ...]
    workspace: tuple[str, ...]
    skills: tuple[str, ...]
    last_signal: Score | None = None
    plan: tuple[tuple[str, bool], ...] = ()
    # 引擎自己算出来的提醒（重复动作、长时间没有评测、没有计划）。
    # 它不是规则，只是把「你卡住了」这件事摆到 agent 眼前。
    note: str = ""


@dataclass(frozen=True)
class AttemptRecord:
    attempt: int
    score: Score
    steps_used: int
    reflections: int


@dataclass
class RunResult:
    """一次 run 的总结，CLI 直接打印它。"""

    task: str
    attempts: list[AttemptRecord]
    stop_reason: str
    steps_used: int
    reflections: int
    best: Score | None = None
    plan: tuple[tuple[str, bool], ...] = ()
    usage: Usage = field(default_factory=Usage)

    def curve(self) -> str:
        if not self.attempts:
            return "(无尝试)"
        marks = []
        for a in self.attempts:
            marks.append(f"{a.score.ratio:.2f}")
        return " -> ".join(marks)

    def plan_lines(self) -> list[str]:
        return [f"  {'[x]' if done else '[ ]'} {text}" for text, done in self.plan]

    def summary(self) -> str:
        lines = [
            f"任务        {self.task}",
            f"停止原因    {self.stop_reason}",
            f"尝试次数    {len(self.attempts)}",
            f"步数        {self.steps_used}",
            f"反思次数    {self.reflections}",
            f"分数曲线    {self.curve()}",
        ]
        if self.best is not None:
            lines.append(f"最好成绩    {self.best.passed}/{self.best.total}")
        lines.extend(self.usage.lines())
        if self.plan:
            lines.append("计划")
            lines.extend(self.plan_lines())
        return "\n".join(lines)

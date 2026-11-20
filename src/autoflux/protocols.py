"""三个契约：Tool / Agent / Task。

引擎只认这三个 Protocol。换模型、换工具、换任务都不需要动引擎。
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

from .types import Action, Observation, Score


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str

    def run(self, **kwargs: object) -> str:
        """执行并返回给 agent 看的文本结果。异常由引擎捕获并转成文本。"""
        ...


@runtime_checkable
class Agent(Protocol):
    def decide(
        self,
        obs: Observation,
        tools: Sequence[Tool],
        skills: Sequence[str],
    ) -> Action:
        """看当前观测，决定下一步。没有固定的阶段顺序，这里返回什么就执行什么。"""
        ...


@runtime_checkable
class Task(Protocol):
    name: str

    def prepare(self, dest: Path) -> None:
        """把任务的初始工作区铺到 dest。"""
        ...

    def evaluate(self, workspace: Path) -> Score:
        """对工作区打分。必须是确定性的、agent 不可见的评测。"""
        ...


@runtime_checkable
class Reflector(Protocol):
    def reflect(
        self,
        signal: Score,
        trace: Sequence[str],
        skills: Sequence[str],
        diagnosis: str = "",
    ) -> str:
        """产出一条可入库的反思。signal 必须来自评测器；diagnosis 是可选的诊断。"""
        ...

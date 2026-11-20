"""三个契约：Tool / Agent / Task。

引擎只认这三个 Protocol。换模型、换工具、换任务都不需要动引擎。
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from .types import Action, Observation, Score


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str

    # 具体工具各收各的参数（read_file 要 path，run_python 要 code），
    # 所以这里只能声明「可调用、返回文本」，不能写死签名。
    # 声明成只读属性（而不是 `run: Callable`），类里用普通方法实现才对得上。
    @property
    def run(self) -> Callable[..., str]: ...


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

"""任务注册表。

加一个新任务 = 写一个实现 Task 协议的类 + 在这里登记一行。引擎不用改。
"""
from __future__ import annotations

from typing import Callable

from ..protocols import Task
from .bugfix.task import BugfixBlindTask, BugfixTask

_REGISTRY: dict[str, Callable[[], Task]] = {
    "bugfix": BugfixTask,
    "bugfix-blind": BugfixBlindTask,
}


def get(name: str) -> Task:
    try:
        factory = _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"没有这个任务：{name}；可用：{', '.join(sorted(_REGISTRY))}"
        ) from None
    return factory()


def names() -> list[str]:
    return sorted(_REGISTRY)

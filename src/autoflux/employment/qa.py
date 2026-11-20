"""问答：先答一版，再用数据集核对里面每个数字，不对就重写。

这是「编数打回」这条卖点的实现——判定不是模型自评，而是一个
能读懂表的校验器：数字在表里找不到，就把问题原样塞回去让它改。
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from .dataset import Dataset
from .verify import verify

SYSTEM = """你是一个就业数据助手。你只根据下面这张表回答，规则：

1. 表里没有的，直接说「表里没有这个数据」，不要推测、不要给预测。
2. 你写出的每一个数字都必须出自这张表，或者是表里的数直接算出来的（差值、倍数）。
3. 先给结论，再给数字依据；涉及行业时点出行业全名。
4. 中文回答，120–260 字，不要客套话。
5. 不要编造数据来源以外的年份、单位、口径。
"""


class Completer(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str: ...


def build_messages(
    question: str,
    ds: Dataset,
    history: Sequence[dict[str, str]] = (),
    problems: Sequence[str] = (),
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM + "\n\n【数据表】\n" + ds.context()}
    ]
    for turn in list(history)[-6:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    user = question
    if problems:
        user += (
            "\n\n上一版答案里有这些数字在这张表里找不到："
            + "；".join(problems)
            + "。请重写，只使用表里的数字；表里没有就直说没有。"
        )
    messages.append({"role": "user", "content": user})
    return messages


def ask(
    llm: Completer,
    ds: Dataset,
    question: str,
    history: Sequence[dict[str, str]] = (),
    attempts: int = 3,
) -> dict[str, Any]:
    """返回 {answer, verified, problems, attempts}。attempts 是实际调用模型的次数。"""
    problems: list[str] = []
    used = 0
    for _ in range(max(1, attempts)):
        used += 1
        text = llm.complete(build_messages(question, ds, history, problems)).strip()
        problems = verify(text, ds)
        if not problems:
            return {"answer": text, "verified": True, "problems": [], "attempts": used}
    return {"answer": text, "verified": False, "problems": problems, "attempts": used}

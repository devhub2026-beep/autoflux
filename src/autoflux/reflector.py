"""反思。

两条硬规矩：

1. **反思必须有外部信号。** 没有评测结果的「反思」会稳定退化成自我安慰。
2. **反思可以换来诊断。** 有些任务的评测只回一个总分；这时反思是一次
   「花一步去查日志」的动作——它买到的不是安慰，是信息。这是反思唯一
   有动机被使用的形态。
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

from .types import Score


def _shorten(line: str, width: int = 90) -> str:
    """把一行压短——规则里不该复读整份文件内容。"""
    flat = " ".join(line.split())
    return flat if len(flat) <= width else flat[:width] + "…"


class TemplateReflector:
    """离线反射器：不依赖模型，由分数与诊断拼出可入库的策略。"""

    def reflect(
        self,
        signal: Score,
        trace: Sequence[str],
        skills: Sequence[str],
        diagnosis: str = "",
    ) -> str:
        if signal is None:
            raise ValueError("反思必须带外部信号：没有 Score 不允许反思")

        head = f"评测 {signal.passed}/{signal.total}（{signal.ratio:.0%}）"
        if signal.ratio >= 1.0:
            return f"{head} 通过。规则：保持当前实现，改动前先跑一遍可见测试。"

        # 优先用真诊断；没有诊断时退回分数里带的明细
        raw = diagnosis.strip() or "；".join(signal.details)
        lines = [_shorten(line, 60) for line in raw.splitlines() if line.strip()]
        named = "；".join(lines[:3]) if lines else "评测未提供失败明细"

        return (
            f"{head} 未通过（{named}）。"
            "规则：改动前先把失败用例最小复现出来，确认边界输入（空、单元素、乱序）的行为，"
            "再改实现，改完重跑全部可见测试。"
        )


class LLMReflector:
    """把分数、诊断和轨迹交给模型，产出策略。

    ``complete`` 是一个 ``prompt -> text`` 的可调用对象，通常来自 agents/llm.py。
    """

    def __init__(self, complete: Callable[[str], str]) -> None:
        self._complete = complete

    def reflect(
        self,
        signal: Score,
        trace: Sequence[str],
        skills: Sequence[str],
        diagnosis: str = "",
    ) -> str:
        if signal is None:
            raise ValueError("反思必须带外部信号：没有 Score 不允许反思")

        known = "\n".join(f"- {s}" for s in skills) if skills else "（空）"
        recent = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(trace[-10:]))
        diag = diagnosis.strip() or "（评测没有提供额外诊断，只有分数）"

        prompt = f"""你是这个 agent 的复盘者。下面是一次真实评测的结果和它最近的动作。

【评测】{signal.passed}/{signal.total} 通过（{signal.ratio:.0%}）
【失败明细】
{chr(10).join(signal.details) or "（无）"}

【诊断输出】
{diag}

【最近动作】
{recent or "（无）"}

【已掌握的规则】
{known}

请写一条**可复用的规则**（不是日记，不要复述发生了什么），要求：
1. 一句话，以「规则：」开头；
2. 必须能指导下一次同类任务的具体动作；
3. 不要和上面已有的规则重复。
只输出这条规则。"""

        return self._complete(prompt).strip()

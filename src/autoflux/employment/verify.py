"""答案校验：数字必须能在表里找到，或者是表里的数算出来的。

这是这层「外部判定」的全部：不判断文笔、不判断结论对不对，
只判断**它有没有编数**。编了就打回，让它重写。
"""
from __future__ import annotations

import re

from .dataset import Dataset

NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _decimals(text: str) -> int:
    return len(text.split(".", 1)[1]) if "." in text else 0


def _same(n: float, allowed: float, shown_decimals: int) -> bool:
    if abs(n - allowed) <= 1e-9:
        return True
    # 只允许「按答案里写的精度四舍五入」，不再按百分比放宽：
    # 以前用 0.5% 的相对误差，150000 会被 150285 认下来，编的数就漏过去了。
    return round(float(allowed), shown_decimals) == round(n, shown_decimals)


def extract_numbers(answer: str) -> list[tuple[str, str]]:
    """返回 [(原文, 附近 12 个字的上下文)]，年份与小整数不算。"""
    found = []
    for m in NUMBER.finditer(answer):
        raw = m.group(0)
        value = float(raw)
        if 1900 <= value <= 2100 and "." not in raw:
            continue                      # 年份
        if value.is_integer() and 0 <= value <= 30 and _decimals(raw) == 0:
            continue                      # 「三条建议」「19 个行业」这类计数
        start = max(0, m.start() - 12)
        found.append((raw, answer[start : m.end() + 4].replace("\n", " ").strip()))
    return found


def verify(answer: str, ds: Dataset) -> list[str]:
    """返回问题列表；空列表 = 每个数字都有出处。"""
    allowed = ds.allowed()
    problems: list[str] = []
    for raw, where in extract_numbers(answer):
        value = float(raw)
        dec = _decimals(raw)
        if any(_same(value, a, dec) for a in allowed):
            continue
        problems.append(f"「{where}」里的 {raw} 在数据表里找不到")
    return problems

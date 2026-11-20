"""仓库库存：条目可以嵌套（category -> item -> 数量），合并/统计用。"""
from __future__ import annotations

from typing import Any


def merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """同名键深合并；两边都是数字就相加。"""
    out = dict(base)
    out.update(extra)
    return out


def add_item(stock: dict[str, Any], category: str, name: str, count: int) -> None:
    """往库里加货；数量必须是正整数。"""
    if count < 1:
        raise ValueError("数量必须是正整数")
    stock.setdefault(category, {})
    stock[category][name] = stock[category].get(name, 0) + count


def total(stock: dict[str, Any]) -> int:
    """所有条目数量之和。"""
    return sum(len(items) for items in stock.values())


def low_stock(stock: dict[str, Any], threshold: int = 2) -> list[str]:
    """返回 '类别/名字' 形式的清单，数量小于等于阈值。"""
    out: list[str] = []
    for category, items in stock.items():
        for name, count in items.items():
            if count < threshold:
                out.append(f"{category}/{name}")
    return out

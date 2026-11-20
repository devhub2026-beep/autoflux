"""统计局工资表：读进来、算好、供问答与校验使用。"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Row:
    name: str
    wage: int
    prev: int
    growth: float
    # 表里的原始序号：排名要看工资，但「哪些行业在跌」按统计局的表序说话更稳
    order: int = 0


class Dataset:
    """一张表 + 从表里算出来的事实。

    问答时只让它看 `context()`；校验时拿 `allowed()`——两边同源，
    所以「答案里的每个数字都能在表里找到（或是表里的数算出来的）」是可判定的。
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        rows: list[Row] = []
        total: Row | None = None
        with self.path.open(encoding="utf-8-sig") as fh:
            for seq, raw in enumerate(csv.DictReader(fh)):
                row = Row(
                    name=raw["行业门类"].strip(),
                    wage=int(raw["2025_年平均工资_元"]),
                    prev=int(raw["2024_年平均工资_元"]),
                    growth=float(raw["名义增长率_百分比"]),
                    order=seq,
                )
                if row.name == "合计":
                    total = row
                else:
                    rows.append(row)
        if total is None:
            raise ValueError("表里没有「合计」行，不知道全国平均")
        self.rows = sorted(rows, key=lambda r: r.wage, reverse=True)
        self.total = total

    # ---- 事实 ---------------------------------------------------------
    @property
    def top(self) -> Row:
        return self.rows[0]

    @property
    def low(self) -> Row:
        return self.rows[-1]

    @property
    def fastest(self) -> Row:
        return max(self.rows, key=lambda r: r.growth)

    @property
    def falling(self) -> list[Row]:
        """负增长的行业，按原表顺序（不是按工资高低）。

        工资排名用 self.rows，但「谁在跌」这类时间维度的说法要跟统计局的表序走，
        否则同一份数据在不同地方给出不同的先后顺序。
        """
        return sorted(
            (r for r in self.rows if r.growth < 0), key=lambda r: r.order
        )

    @property
    def above_total(self) -> list[Row]:
        return [r for r in self.rows if r.wage > self.total.wage]

    @property
    def gap_ratio(self) -> float:
        return self.top.wage / self.low.wage

    def find(self, name: str) -> Row | None:
        for row in self.rows:
            if row.name == name:
                return row
        for row in self.rows:
            if name and name in row.name:
                return row
        return None

    # ---- 给模型看的上下文 ---------------------------------------------
    def context(self) -> str:
        lines = [
            "| 行业门类 | 2025 年平均工资（元） | 2024 年（元） | 名义增长率（%） |",
            "| --- | ---: | ---: | ---: |",
            f"| 全国合计 | {self.total.wage} | {self.total.prev} | {self.total.growth} |",
        ]
        for row in self.rows:
            lines.append(f"| {row.name} | {row.wage} | {row.prev} | {row.growth} |")
        lines.append("")
        lines.append(
            f"算好的事实：行业数 {len(self.rows)}；高于全国合计的 {len(self.above_total)} 个；"
            f"最高 {self.top.name} {self.top.wage} 元；最低 {self.low.name} {self.low.wage} 元；"
            f"最高/最低 {self.gap_ratio:.2f} 倍；增速最快 {self.fastest.name} {self.fastest.growth}%；"
            f"负增长 {len(self.falling)} 个（"
            + "、".join(f"{r.name} {r.growth}%" for r in self.falling)
            + "）。"
        )
        return "\n".join(lines)

    # ---- 校验用的允许值集合 -------------------------------------------
    def allowed(self) -> set[float]:
        values: set[float] = {float(self.total.wage), float(self.total.prev), float(self.total.growth)}
        for row in self.rows:
            values.update({float(row.wage), float(row.prev), float(row.growth)})
        # 表里能直接算出来的事实，不算「编的」
        values.update(
            {
                float(len(self.rows)),
                float(len(self.above_total)),
                float(len(self.falling)),
                float(self.top.wage - self.low.wage),
                round(self.gap_ratio, 2),
                round(self.gap_ratio, 1),
                round(self.gap_ratio),
                round(self.gap_ratio * 100, 1),   # 说成百分比也算对
            }
        )
        # 往年的增量：2025 - 2024
        for row in list(self.rows) + [self.total]:
            values.add(float(row.wage - row.prev))
        return values

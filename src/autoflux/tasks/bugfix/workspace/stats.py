"""统计小工具。给 demo 用的初始代码 —— 里面有 bug，别当正经库用。"""
from __future__ import annotations


def mean(values):
    return sum(values) / len(values)


def median(values):
    n = len(values)
    mid = n // 2
    if n % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


def stdev(values):
    n = len(values)
    m = mean(values)
    total = sum((x - m) ** 2 for x in values)
    return (total / n) ** 0.5


def summary(values):
    return {"mean": mean(values), "median": median(values), "stdev": stdev(values)}

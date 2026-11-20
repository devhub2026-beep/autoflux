"""完整修复：三个 bug 全修。给脚本替身演示用。"""
from __future__ import annotations


def mean(values):
    if not values:
        raise ValueError("mean() 不接受空序列")
    return sum(values) / len(values)


def median(values):
    if not values:
        raise ValueError("median() 不接受空序列")
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def stdev(values):
    if len(values) < 2:
        raise ValueError("样本标准差至少需要 2 个值")
    m = mean(values)
    total = sum((x - m) ** 2 for x in values)
    return (total / (len(values) - 1)) ** 0.5


def summary(values):
    return {"mean": mean(values), "median": median(values), "stdev": stdev(values)}

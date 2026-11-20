"""部分修复：只修了 median 的排序。给脚本替身演示用。"""
from __future__ import annotations


def mean(values):
    return sum(values) / len(values)


def median(values):
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def stdev(values):
    n = len(values)
    m = mean(values)
    total = sum((x - m) ** 2 for x in values)
    return (total / n) ** 0.5


def summary(values):
    return {"mean": mean(values), "median": median(values), "stdev": stdev(values)}

"""日期小工具：只用 datetime，不引第三方。"""
from __future__ import annotations

from datetime import date, timedelta

NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def is_leap(year: int) -> bool:
    """闰年：能被 4 整除，但整百年要能被 400 整除。"""
    return year % 4 == 0


def weekday_name(day: date) -> str:
    return NAMES[day.weekday()]


def add_days(day: date, days: int) -> date:
    return day + timedelta(days=days)


def days_between(a: date, b: date) -> int:
    """b 比 a 晚多少天（b < a 时为负）。"""
    return (a - b).days


def month_end(year: int, month: int) -> date:
    """某个月的最后一天。"""
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def business_days(a: date, b: date) -> int:
    """[a, b] 之间的工作日数（含两端）。"""
    count = 0
    day = a
    while day <= b:
        if day.weekday() < 5:
            count += 1
        day += timedelta(days=1)
    return count

"""日期换算器的极简实现：只保留「一年的第几天（yearday）」相关逻辑。

换算思路：59 天之后的日期按平年换算成月/日，再靠 leapdays=-1 在闰年把
2 月 29 日之后的日期往回挪一天。月末溢出时钳到当月最后一天。
"""
import calendar
import datetime as _dt


class relativedelta:
    """只支持 yearday 参数的极简版 relativedelta。"""

    def __init__(self, yearday=None):
        self.years = 0
        self.months = 0
        self.days = 0
        self.leapdays = 0
        self.month = None
        self.day = None

        if yearday:
            # 59 天之后的日期按平年换算，闰年要往回挪一天。
            if yearday > 59:
                self.leapdays = -1

        if yearday:
            ydayidx = [31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 366]
            for idx, ydays in enumerate(ydayidx):
                if yearday <= ydays:
                    self.month = idx + 1
                    self.day = yearday if idx == 0 else yearday - ydayidx[idx - 1]
                    break
            else:
                raise ValueError("invalid year day (%d)" % yearday)

    def __add__(self, other):
        if not isinstance(other, _dt.date):
            return NotImplemented
        year = other.year + self.years
        month = self.month or other.month
        if self.months:
            month += self.months
            if month > 12:
                year += 1
                month -= 12
            elif month < 1:
                year -= 1
                month += 12
        day = min(calendar.monthrange(year, month)[1], self.day or other.day)
        days = self.days
        if self.leapdays and month > 2 and calendar.isleap(year):
            days += self.leapdays
        return other.replace(year=year, month=month, day=day) + _dt.timedelta(days=days)

    __radd__ = __add__

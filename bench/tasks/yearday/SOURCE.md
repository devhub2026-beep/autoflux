# yearday 任务来源

真实 bug：dateutil/dateutil gh pr #1583
「Fix yearday=366 resolving to Dec 30 instead of Dec 31 in leap years」

- 合入：2026-11-01
- 链接：https://github.com/dateutil/dateutil/pull/1583
- 上游改动：`src/dateutil/relativedelta.py` 的 yearday 分支（+5/−1）
- 上游回归测试：`tests/test_relativedelta.py` 的 `test_yearday_is_ordinal_day`

移植方式：把上游 `relativedelta` 与 yearday 相关的换算逻辑
（ydayidx 表、leapdays=-1 回挪、`__add__` 的月末钳位）原样搬进
`project/relativedelta.py`，裁掉与 yearday 无关的部分；
`project/test_relativedelta.py` 是上游回归测试的 unittest 等价版。

bug 本身（`yearday > 59` 一律回挪一天）与修复（`59 < yearday < 366`）
均与上游逐字对应：闰年里 366 换算成 12 月 32 日，被钳到 12 月 31 日，
此时再回挪一天就撞上了 365 的结果（12 月 30 日）。

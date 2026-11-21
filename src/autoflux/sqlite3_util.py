"""sqlite 的并发约定：WAL + busy_timeout + 对 locked 的退避重试。

两个 run 同时反思时，它们会写同一个 skillbook。sqlite 默认遇到写锁就抛
`database is locked`——busy_timeout 让 sqlite 自己等一会儿，剩下的用重试兜住。
WAL 让「一边写、一边读」不互相卡死。

这些参数不是抄来的：默认 5 秒的忙等在 web 上不够（一次反思里可能连着几次写），
所以拉长到 30 秒；重试只是兜底，正常路径根本走不到。
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

DEFAULT_TIMEOUT = 30.0
LOCK_RETRIES = 6
LOCK_BASE_DELAY = 0.05

T = TypeVar("T")


def _locked(exc: sqlite3.OperationalError) -> bool:
    text = str(exc).lower()
    return "locked" in text or "busy" in text


def write_with_retry(
    fn: Callable[[], T],
    retries: int = LOCK_RETRIES,
    base_delay: float = LOCK_BASE_DELAY,
) -> T:
    """执行一次写；碰到 locked 就等一会儿再来，别把整次 run 判死。"""
    last: sqlite3.OperationalError | None = None
    for attempt in range(retries):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            if not _locked(exc):
                raise
            last = exc
            if attempt + 1 < retries:
                time.sleep(base_delay * (2**attempt))
    raise RuntimeError(f"sqlite 一直锁着，重试 {retries} 次仍未成功：{last}") from last


def connect(
    path: str | Path,
    timeout: float = DEFAULT_TIMEOUT,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    """按项目的并发约定打开一个库。"""
    target = str(path)
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target, timeout=timeout, check_same_thread=check_same_thread)
    # PRAGMA 不吃占位参数，值只能是字面量；这里由我们自己拼，数字是可信的
    con.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
    # 切换到 WAL 会短暂拿排他锁：几个 run 同时启动时这里也要能等
    write_with_retry(lambda: con.execute("PRAGMA journal_mode = WAL"))
    con.execute("PRAGMA synchronous = NORMAL")
    return con


def pragma(con: sqlite3.Connection, name: str) -> Any:
    """读一个 PRAGMA 的当前值，给测试和自检用。"""
    row = con.execute(f"PRAGMA {name}").fetchone()
    return row[0] if row else None

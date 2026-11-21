"""Skillbook：跨轮、跨会话存活的策略库。

这是 ACE 那套东西里真正值钱的部分——反思如果只写进上下文，下一轮就没了；
写进这里，下一轮、下一次运行、下一个任务都还在。
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from .sqlite3_util import connect, write_with_retry

_SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    normalized TEXT NOT NULL UNIQUE,
    source     TEXT NOT NULL DEFAULT 'reflect',
    created_at REAL NOT NULL,
    uses       INTEGER NOT NULL DEFAULT 0,
    wins       INTEGER NOT NULL DEFAULT 0
);
"""


def normalize(text: str) -> str:
    """去掉空白和标点后比较，避免同一条反思被存十遍。"""
    return re.sub(r"[\s\W_]+", "", text).lower()


class Skillbook:
    """sqlite 支撑的持久策略库。

    多个 run 会同时写它（每次反思都写），所以开库走 `connect()`：
    WAL + 30 秒 busy_timeout + 对 locked 的退避重试。
    """

    def __init__(self, path: str | Path, timeout: float = 30.0) -> None:
        self.path = Path(path)
        self._con = connect(self.path, timeout=timeout)
        write_with_retry(self._init_schema)

    def _init_schema(self) -> None:
        self._con.execute(_SCHEMA)
        self._con.commit()

    # -- 写入 ---------------------------------------------------------
    def add(self, text: str, source: str = "reflect") -> int | None:
        """存入一条策略。重复的返回 None。"""
        body = text.strip()
        if not body:
            return None
        key = normalize(body)
        if not key:
            return None
        try:
            def go() -> sqlite3.Cursor:
                cur = self._con.execute(
                    "INSERT INTO strategies (text, normalized, source, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (body, key, source, time.time()),
                )
                self._con.commit()
                return cur

            cur = write_with_retry(go)
        except sqlite3.IntegrityError:
            self._con.rollback()
            return None
        rowid = cur.lastrowid
        return int(rowid) if rowid is not None else None

    def bump_use(self, ids: list[int]) -> None:
        if not ids:
            return
        self._bump("uses", ids)

    def bump_win(self, ids: list[int]) -> None:
        if not ids:
            return
        self._bump("wins", ids)

    def _bump(self, column: str, ids: list[int]) -> None:
        # 两个列名写死在这里，不拼字符串——拼出来的 SQL 让别人看着不放心
        sql = (
            "UPDATE strategies SET uses = uses + 1 WHERE id = ?"
            if column == "uses"
            else "UPDATE strategies SET wins = wins + 1 WHERE id = ?"
        )

        def go() -> None:
            self._con.executemany(sql, [(i,) for i in ids])
            self._con.commit()

        write_with_retry(go)

    # -- 读取 ---------------------------------------------------------
    def skills(self, limit: int = 12) -> list[str]:
        """取最近、且被验证过更有效的若干条。"""
        rows = self._con.execute(
            "SELECT id, text FROM strategies ORDER BY wins DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        self._last_ids = [r[0] for r in rows]
        return [r[1] for r in rows]

    def last_ids(self) -> list[int]:
        """上一次 skills() 取到的那些行，用于记战功。"""
        return list(getattr(self, "_last_ids", []))

    def search(self, keyword: str, limit: int = 5) -> list[str]:
        rows = self._con.execute(
            "SELECT text FROM strategies WHERE text LIKE ? ORDER BY created_at DESC LIMIT ?",
            (f"%{keyword}%", limit),
        ).fetchall()
        return [r[0] for r in rows]

    # -- 清理 ---------------------------------------------------------
    def prune(
        self,
        max_rows: int = 200,
        futile_uses: int = 3,
        stale_days: int = 30,
    ) -> int:
        """把库压回可控规模，返回删掉的条数。

        这个库只进不出的话，跑几百轮以后每轮都要把这些废话塞进提示词，
        越反思越笨。两条规矩：

        1. 反复用过、一次都没赢、而且已经 `stale_days` 天没动静的，是「试了也不管用」
           的策略，删；
        2. 总数超过 `max_rows` 时，按「赢过 > 用过 > 新」留前 `max_rows` 条，其余删。

        从没被用过的新规则不按第 1 条删——它还没轮到上场。
        """
        cutoff = time.time() - stale_days * 86400

        def go() -> int:
            cur = self._con.execute(
                "DELETE FROM strategies WHERE wins = 0 AND uses >= ? AND created_at < ?",
                (futile_uses, cutoff),
            )
            removed = max(cur.rowcount, 0)
            cur = self._con.execute(
                "DELETE FROM strategies WHERE id NOT IN ("
                "SELECT id FROM strategies "
                "ORDER BY wins DESC, uses DESC, created_at DESC, id DESC LIMIT ?)",
                (max_rows,),
            )
            removed += max(cur.rowcount, 0)
            self._con.commit()
            return removed

        return write_with_retry(go)

    def count(self) -> int:
        return int(self._con.execute("SELECT COUNT(*) FROM strategies").fetchone()[0])

    def all(self) -> list[tuple[int, str, int, int]]:
        return self._con.execute(
            "SELECT id, text, uses, wins FROM strategies ORDER BY id"
        ).fetchall()

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> Skillbook:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

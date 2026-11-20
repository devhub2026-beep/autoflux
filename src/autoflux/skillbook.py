"""Skillbook：跨轮、跨会话存活的策略库。

这是 ACE 那套东西里真正值钱的部分——反思如果只写进上下文，下一轮就没了；
写进这里，下一轮、下一次运行、下一个任务都还在。
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

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
    """sqlite 支撑的持久策略库。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(self.path)
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
            cur = self._con.execute(
                "INSERT INTO strategies (text, normalized, source, created_at) "
                "VALUES (?, ?, ?, ?)",
                (body, key, source, time.time()),
            )
            self._con.commit()
            rowid = cur.lastrowid
            return int(rowid) if rowid is not None else None
        except sqlite3.IntegrityError:
            return None

    def bump_use(self, ids: list[int]) -> None:
        if not ids:
            return
        self._con.executemany(
            "UPDATE strategies SET uses = uses + 1 WHERE id = ?",
            [(i,) for i in ids],
        )
        self._con.commit()

    def bump_win(self, ids: list[int]) -> None:
        if not ids:
            return
        self._con.executemany(
            "UPDATE strategies SET wins = wins + 1 WHERE id = ?",
            [(i,) for i in ids],
        )
        self._con.commit()

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

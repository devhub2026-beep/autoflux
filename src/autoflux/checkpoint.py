"""把 LangGraph 的检查点存进 sqlite：进程退出、断电之后还能接着跑。

MemorySaver 只在内存里，进程一死状态就没了。这个 saver 每次节点执行完把
checkpoint 写进一个 sqlite 文件，下次用同一个 thread_id 打开就能从断点继续。

只实现同步接口——这个项目的引擎本来就是同步的。
"""
from __future__ import annotations

import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)

from .sqlite3_util import connect, write_with_retry

# class 里有个 list 方法，类作用域内 `list[...]` 会被当成方法名，所以挪到模块级
Writes = list[tuple[str, str, Any]]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    parent_id TEXT,
    checkpoint BLOB NOT NULL,
    metadata BLOB,
    UNIQUE (thread_id, checkpoint_id)
);
CREATE TABLE IF NOT EXISTS writes (
    thread_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    value BLOB NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_id, task_id, idx)
);
"""


class SqliteSaver(BaseCheckpointSaver):
    """最小可用的 sqlite saver：put / get_tuple / list / put_writes / delete_thread。"""

    def __init__(self, path: str | Path = ":memory:") -> None:
        super().__init__()
        self.path = str(path)
        self._conn = connect(self.path, check_same_thread=False)
        # LangGraph 会在工作线程里调 put / put_writes，同一个连接必须串行化
        self._lock = threading.RLock()
        write_with_retry(self._init_schema)

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- 写 -----------------------------------------------------------
    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id = config["configurable"]["thread_id"]
        parent_id = config["configurable"].get("checkpoint_id")
        ctype, cblob = self.serde.dumps_typed(checkpoint)
        mtype, mblob = self.serde.dumps_typed(dict(metadata or {}))
        with self._lock:
            def go() -> None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO checkpoints"
                    " (thread_id, checkpoint_id, parent_id, checkpoint, metadata)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        thread_id,
                        checkpoint["id"],
                        parent_id,
                        _pack(ctype, cblob),
                        _pack(mtype, mblob),
                    ),
                )
                self._conn.commit()

            write_with_retry(go)
        # LangGraph 1.x 要求 put 把「带新 checkpoint_id 的 config」还回去
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id", "")
        rows = []
        for idx, (channel, value) in enumerate(writes):
            vtype, vblob = self.serde.dumps_typed(value)
            rows.append(
                (thread_id, checkpoint_id, task_id, idx, channel, _pack(vtype, vblob))
            )
        with self._lock:
            def go() -> None:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO writes"
                    " (thread_id, checkpoint_id, task_id, idx, channel, value)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    rows,
                )
                self._conn.commit()

            write_with_retry(go)

    # -- 读 -----------------------------------------------------------
    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id")
        if checkpoint_id:
            row = self._conn.execute(
                "SELECT checkpoint_id, parent_id, checkpoint, metadata FROM checkpoints"
                " WHERE thread_id = ? AND checkpoint_id = ?",
                (thread_id, checkpoint_id),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT checkpoint_id, parent_id, checkpoint, metadata FROM checkpoints"
                " WHERE thread_id = ? ORDER BY rowid DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        if row is None:
            return None
        cid, parent_id, cblob, mblob = row
        return CheckpointTuple(
            config={
                "configurable": {"thread_id": thread_id, "checkpoint_id": cid}
            },
            checkpoint=self.serde.loads_typed(_unpack(cblob)),
            metadata=self.serde.loads_typed(_unpack(mblob)) if mblob else {},
            parent_config=(
                {"configurable": {"thread_id": thread_id, "checkpoint_id": parent_id}}
                if parent_id
                else None
            ),
            pending_writes=self._writes(thread_id, cid),
        )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        thread_id = (config or {}).get("configurable", {}).get("thread_id")
        sql = "SELECT thread_id, checkpoint_id FROM checkpoints"
        params: list[Any] = []
        if thread_id:
            sql += " WHERE thread_id = ?"
            params.append(thread_id)
        sql += " ORDER BY rowid DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        for tid, cid in self._conn.execute(sql, params).fetchall():
            got = self.get_tuple(
                {"configurable": {"thread_id": tid, "checkpoint_id": cid}}
            )
            if got is not None:
                yield got

    def delete_thread(self, thread_id: str) -> None:
        def go() -> None:
            self._conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
            self._conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
            self._conn.commit()

        with self._lock:
            write_with_retry(go)

    # -- 内部 ---------------------------------------------------------
    def _writes(self, thread_id: str, checkpoint_id: str) -> Writes:
        rows = self._conn.execute(
            "SELECT task_id, channel, value FROM writes"
            " WHERE thread_id = ? AND checkpoint_id = ? ORDER BY task_id, idx",
            (thread_id, checkpoint_id),
        ).fetchall()
        return [(task_id, channel, self.serde.loads_typed(_unpack(blob)))
                for task_id, channel, blob in rows]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SqliteSaver:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _pack(kind: str, blob: bytes) -> bytes:
    return kind.encode("utf-8") + b"\x00" + blob


def _unpack(raw: bytes) -> tuple[str, bytes]:
    kind, _, blob = raw.partition(b"\x00")
    return kind.decode("utf-8"), blob

"""并发写同一份 sqlite：不许抛 database is locked。

真实场景：网页上同时开两个 run，它们各自反思、往同一个 skillbook 里写；
每个 run 又有自己的 checkpointer。这里用线程把「同时写」压出来。
"""
from __future__ import annotations

import sqlite3
import threading
import time
import unittest
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from autoflux.checkpoint import SqliteSaver
from autoflux.skillbook import Skillbook
from autoflux.sqlite3_util import pragma

from . import ScratchCase


class Counter(TypedDict, total=False):
    n: int


def _bump(state: Counter) -> Counter:
    return {"n": int(state.get("n") or 0) + 1}


def _halt(state: Counter) -> str:
    return "end" if int(state.get("n") or 0) >= 3 else "more"


def _graph(saver: SqliteSaver):
    g = StateGraph(Counter)
    g.add_node("bump", _bump)
    g.add_edge(START, "bump")
    g.add_conditional_edges("bump", _halt, {"more": "bump", "end": END})
    return g.compile(checkpointer=saver)


class TestSqliteConventions(ScratchCase):
    def test_wal_and_busy_timeout_are_on(self):
        book = Skillbook(self.root / "s.db")
        self.addCleanup(book.close)
        self.assertEqual(str(pragma(book._con, "journal_mode")).lower(), "wal")
        self.assertEqual(pragma(book._con, "busy_timeout"), 30000)

    def test_parallel_writers_all_succeed(self):
        path = self.root / "s.db"
        workers = 6
        each = 25
        # 连接必须在本线程里建（sqlite 的 check_same_thread 规矩）；
        # 建库错开几十毫秒，压的是「写」的并发，不是「切 WAL」的竞争
        barrier = threading.Barrier(workers)
        errors: list[BaseException] = []

        def writer(worker: int) -> None:
            try:
                time.sleep(0.05 * worker)
                book = Skillbook(path)
                barrier.wait(timeout=15)
                for i in range(each):
                    book.add(f"规则：写入者{worker} 第{i}条")
                book.close()
            except BaseException as exc:  # 线程里的错要带回主线程
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(w,)) for w in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        self.assertEqual(errors, [])
        with Skillbook(path) as book:
            self.assertEqual(book.count(), workers * each)

    def test_write_survives_short_external_lock(self):
        """外部连接把库锁住 0.5 秒：靠重试撑过去，而不是直接抛给调用方。"""
        path = self.root / "s.db"
        book = Skillbook(path, timeout=0.05)
        self.addCleanup(book.close)

        # 锁由别的线程释放，所以这个连接要允许跨线程使用
        holder = sqlite3.connect(path, timeout=0, check_same_thread=False)
        holder.execute("BEGIN IMMEDIATE")

        def release() -> None:
            time.sleep(0.5)
            holder.commit()
            holder.close()

        threading.Thread(target=release, daemon=True).start()
        ident = book.add("规则：等别人写完再写自己的")
        self.assertIsNotNone(ident)
        self.assertEqual(book.count(), 1)

    def test_prune_and_add_do_not_deadlock(self):
        path = self.root / "s.db"
        errors: list[BaseException] = []
        start = threading.Barrier(3)

        def author(tag: str) -> None:
            book = Skillbook(path)
            try:
                start.wait(timeout=10)
                for i in range(30):
                    book.add(f"规则：{tag}-{i}")
            except BaseException as exc:
                errors.append(exc)
            finally:
                book.close()

        def pruner() -> None:
            book = Skillbook(path)
            try:
                start.wait(timeout=10)
                for _ in range(5):
                    book.prune(max_rows=40)
                    time.sleep(0.02)
            except BaseException as exc:
                errors.append(exc)
            finally:
                book.close()

        threads = [
            threading.Thread(target=author, args=("a",)),
            threading.Thread(target=author, args=("b",)),
            threading.Thread(target=pruner),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        self.assertEqual(errors, [])


class TestCheckpointConcurrency(ScratchCase):
    def test_two_savers_write_same_file_at_once(self):
        path = self.root / "cp.sqlite"
        errors: list[BaseException] = []

        def run(thread_id: str) -> None:
            saver = SqliteSaver(path)
            try:
                _graph(saver).invoke({"n": 0}, {"configurable": {"thread_id": thread_id}})
            except BaseException as exc:
                errors.append(exc)
            finally:
                saver.close()

        threads = [
            threading.Thread(target=run, args=("t-a",)),
            threading.Thread(target=run, args=("t-b",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        self.assertEqual(errors, [])
        with SqliteSaver(path) as saver:
            for thread_id in ("t-a", "t-b"):
                got = saver.get_tuple({"configurable": {"thread_id": thread_id}})
                self.assertIsNotNone(got)
                assert got is not None
                self.assertEqual(got.checkpoint["channel_values"]["n"], 3)

    def test_saver_uses_wal(self):
        with SqliteSaver(self.root / "cp.sqlite") as saver:
            self.assertEqual(str(pragma(saver._conn, "journal_mode")).lower(), "wal")


if __name__ == "__main__":
    unittest.main()

"""sqlite checkpointer 的契约：换个进程/换个实例也能接着跑。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from autoflux.checkpoint import SqliteSaver


class Counter(TypedDict, total=False):
    n: int


def _bump(state: Counter) -> Counter:
    return {"n": int(state.get("n") or 0) + 1}


def _halt(state: Counter) -> str:
    return "end" if int(state.get("n") or 0) >= 3 else "more"


def _build(saver):
    g = StateGraph(Counter)
    g.add_node("bump", _bump)
    g.add_edge(START, "bump")
    g.add_conditional_edges("bump", _halt, {"more": "bump", "end": END})
    return g.compile(checkpointer=saver)


class SqliteSaverTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "cp.sqlite"

    def test_state_survives_new_instance(self) -> None:
        cfg = {"configurable": {"thread_id": "t1"}}
        saver = SqliteSaver(self.db)
        out = _build(saver).invoke({"n": 0}, cfg)
        self.assertEqual(out["n"], 3)
        saver.close()

        # 换一个实例、换一个连接，状态还在
        again = SqliteSaver(self.db)
        self.addCleanup(again.close)
        tuple_now = again.get_tuple(cfg)
        self.assertIsNotNone(tuple_now)
        self.assertEqual(tuple_now.checkpoint["channel_values"]["n"], 3)

    def test_latest_checkpoint_is_last_one(self) -> None:
        cfg = {"configurable": {"thread_id": "t2"}}
        with SqliteSaver(self.db) as saver:
            _build(saver).invoke({"n": 0}, cfg)
            latest = saver.get_tuple(cfg)
        self.assertEqual(latest.checkpoint["channel_values"]["n"], 3)

    def test_threads_are_isolated(self) -> None:
        with SqliteSaver(self.db) as saver:
            graph = _build(saver)
            graph.invoke({"n": 0}, {"configurable": {"thread_id": "a"}})
            self.assertIsNone(saver.get_tuple({"configurable": {"thread_id": "b"}}))

    def test_delete_thread(self) -> None:
        with SqliteSaver(self.db) as saver:
            cfg = {"configurable": {"thread_id": "gone"}}
            _build(saver).invoke({"n": 0}, cfg)
            saver.delete_thread("gone")
            self.assertIsNone(saver.get_tuple(cfg))

    def test_list_returns_history(self) -> None:
        with SqliteSaver(self.db) as saver:
            cfg = {"configurable": {"thread_id": "hist"}}
            _build(saver).invoke({"n": 0}, cfg)
            rows = list(saver.list(cfg))
        self.assertGreaterEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()

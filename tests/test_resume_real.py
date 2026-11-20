"""真续跑：进程里换一个 engine、换一个 saver 实例，从上次的 checkpoint 接着走。"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Sequence

from autoflux.checkpoint import SqliteSaver
from autoflux.config import Limits
from autoflux.graph import GraphEngine
from autoflux.protocols import Tool
from autoflux.reflector import TemplateReflector
from autoflux.skillbook import Skillbook
from autoflux.stop import StopPolicy
from autoflux.tools.fs import default_tools
from autoflux.trace import NullTracer
from autoflux.types import Action, Observation, Score


class NeverTask:
    """永远不给分的任务：只用来观察步数有没有接着涨。"""

    name = "never"
    goal = "永远不成"

    def prepare(self, workdir: Path) -> None:
        workdir.mkdir(parents=True, exist_ok=True)

    def brief(self) -> str:
        return "永远不成"

    def evaluate(self, workdir: Path) -> Score:
        return Score(0, 1, ("还没成",))


class WipingTask(NeverTask):
    """prepare 会先把工作区清空再铺初始文件——用它证明续跑不会重来一遍。"""

    name = "wipe"

    def prepare(self, workdir: Path) -> None:
        if workdir.exists():
            shutil.rmtree(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "from_source.txt").write_text("原始文件", encoding="utf-8")


class Ticker:
    """每问一次就写一个新文件。"""

    def __init__(self) -> None:
        self.n = 0
        self.seen = 0

    def decide(self, obs: Observation, tools: Sequence[Tool], skills: Sequence[str]) -> Action:
        self.n += 1
        self.seen = len(obs.recent)
        return Action("tool", "write_file", {"path": f"f{self.n}.txt", "content": "x"})


class ResumeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.workdir = self.root / "ws"
        self.db = self.root / "cp.sqlite"
        self.book = Skillbook(self.root / "s.db")
        self.addCleanup(self.book.close)

    def _engine(
        self,
        saver: SqliteSaver,
        agent,
        max_steps: int = 3,
        task=None,
        workdir: Path | None = None,
    ) -> GraphEngine:
        ws = workdir or self.workdir
        return GraphEngine(
            task=task or NeverTask(),
            agent=agent,
            tools=default_tools(ws),
            reflector=TemplateReflector(),
            skillbook=self.book,
            stop_policy=StopPolicy(Limits(max_steps=max_steps, max_attempts=5)),
            workdir=ws,
            thread_id="same-thread",
            tracer=NullTracer(),
            checkpointer=saver,
        )

    def test_second_engine_continues_from_checkpoint(self) -> None:
        saver = SqliteSaver(self.db)
        try:
            first = self._engine(saver, Ticker()).run()
        finally:
            saver.close()
        self.assertNotEqual(first.stop_reason, "达标")
        self.assertEqual(first.steps_used, 3)

        saver2 = SqliteSaver(self.db)
        try:
            ticker = Ticker()
            second = self._engine(saver2, ticker).run()
        finally:
            saver2.close()

        self.assertTrue(second.steps_used > 0)
        # 续跑时模型看到的是旧历史，不是从零开始
        self.assertGreater(ticker.seen, 0)

    def test_fresh_thread_starts_from_zero(self) -> None:
        with SqliteSaver(self.db) as saver:
            engine = self._engine(saver, Ticker())
            engine.thread_id = "other-thread"
            fresh = engine.run()
        self.assertEqual(fresh.steps_used, 3)

    def test_resume_keeps_workdir_instead_of_recopying_source(self) -> None:
        """工作区里是上一轮改到一半的文件，续跑不能再拿起始目录覆盖一遍。"""
        ws = self.root / "wipe-ws"
        with SqliteSaver(self.db) as saver:
            self._engine(saver, Ticker(), max_steps=1, task=WipingTask(), workdir=ws).run()
        self.assertTrue((ws / "from_source.txt").exists())

        note = ws / "agent_note.txt"
        note.write_text("上一轮写的，不能丢", encoding="utf-8")
        (ws / "from_source.txt").unlink()          # 如果重新 prepare，这个会被重新造出来

        with SqliteSaver(self.db) as saver2:
            self._engine(saver2, Ticker(), max_steps=1, task=WipingTask(), workdir=ws).run()

        self.assertTrue(note.exists(), "续跑把工作区里的进度抹掉了")
        self.assertFalse((ws / "from_source.txt").exists(), "续跑又复制了一遍起始目录")


if __name__ == "__main__":
    unittest.main()

"""LangGraph 引擎的测试。

重点不是「能跑通」，而是三条规矩在图上依然成立：
  1. 图里只有环，没有阶段链；
  2. 没分不许反思；
  3. 分还是外部评测给的。
"""
from __future__ import annotations

from autoflux.config import Limits
from autoflux.graph import GraphEngine
from autoflux.reflector import TemplateReflector
from autoflux.skillbook import Skillbook
from autoflux.stop import StopPolicy
from autoflux.tasks import bugfix
from autoflux.tools.fs import default_tools
from autoflux.trace import NullTracer
from autoflux.types import Action

from . import ScratchCase
from .support import ScriptedAgent, build_scripted_plan


class TestGraphEngine(ScratchCase):
    def _engine(self, plan=None, limits=None):
        workdir = self.root / "ws"
        book = Skillbook(self.root / "state.db")
        self.addCleanup(book.close)
        engine = GraphEngine(
            task=bugfix.BugfixTask(),
            agent=ScriptedAgent(plan if plan is not None else build_scripted_plan()),
            tools=default_tools(workdir),
            reflector=TemplateReflector(),
            skillbook=book,
            stop_policy=StopPolicy(limits or Limits(max_steps=40, max_attempts=5)),
            tracer=NullTracer(),
            workdir=workdir,
            snapshot_path=self.root / "state.json",
        )
        return engine

    def test_plan_reaches_full_score_through_graph(self):
        result = self._engine().run()
        self.assertIsNotNone(result.best)
        self.assertEqual(result.best.ratio, 1.0)
        self.assertGreaterEqual(len(result.attempts), 1)
        self.assertTrue((self.root / "state.json").exists())

    def test_graph_is_one_loop_no_stage_chain(self):
        engine = self._engine()
        nodes = set(engine.build().get_graph().nodes)
        self.assertTrue({"guard", "decide", "act", "reflect", "judge"} <= nodes)
        # plan 是 agent 可选的动作，不是必经阶段；没有「执行」「总结」这类阶段节点
        self.assertIn("plan", nodes)
        self.assertFalse({"execute", "summarize", "setup", "plan_then_execute"} & nodes)

    def test_reflect_without_any_signal_is_skipped(self):
        plan = [Action("reflect"), Action("stop", text="不做了")]
        result = self._engine(plan=plan).run()
        self.assertEqual(result.reflections, 0)
        self.assertEqual(result.attempts, [])

    def test_reflect_after_score_counts(self):
        plan = [Action("submit"), Action("reflect"), Action("stop", text="够了")]
        result = self._engine(plan=plan).run()
        self.assertEqual(len(result.attempts), 1)
        self.assertEqual(result.reflections, 1)

    def test_stop_policy_caps_steps(self):
        plan = [Action("tool", name="list_files")] * 20
        result = self._engine(plan=plan, limits=Limits(max_steps=3)).run()
        self.assertLessEqual(result.steps_used, 3)

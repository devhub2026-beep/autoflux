"""v0.3 的三件事：计划是动作、卡住会被指出、能从断点接着跑。"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from autoflux.agents.llm import LLMAgent
from autoflux.config import Limits, LLMSettings
from autoflux.graph import GraphEngine
from autoflux.reflector import TemplateReflector
from autoflux.skillbook import Skillbook
from autoflux.stop import StopPolicy
from autoflux.tasks import bugfix
from autoflux.tools.fs import default_tools
from autoflux.trace import NullTracer
from autoflux.types import Action, Observation

from . import ScratchCase
from .support import ScriptedAgent, build_scripted_plan


class _Base(ScratchCase):
    def engine(self, plan, *, limits=None, snapshot=None):
        workdir = self.root / "ws"
        book = Skillbook(self.root / "s.db")
        self.addCleanup(book.close)
        return GraphEngine(
            task=bugfix.BugfixTask(),
            agent=ScriptedAgent(plan),
            tools=default_tools(workdir),
            reflector=TemplateReflector(),
            skillbook=book,
            stop_policy=StopPolicy(limits or Limits(max_steps=30, max_attempts=5)),
            tracer=NullTracer(),
            workdir=workdir,
            snapshot_path=snapshot,
        )


class TestPlanIsAnAction(_Base):
    def test_plan_updates_plan_and_history(self):
        plan = [
            Action("plan", args={"steps": ["先看报错", "再改代码"]}),
            Action("plan", args={"steps": [{"text": "先看报错", "done": True}, "再改代码"]}),
            Action("stop", text="先这样"),
        ]
        result = self.engine(plan).run()
        self.assertEqual(result.plan, (("先看报错", True), ("再改代码", False)))
        self.assertIn("计划", result.summary())

    def test_plan_is_not_a_mandatory_stage(self):
        # 一次都不写计划也能跑完并达标：它是选项，不是阶段
        plan = [Action("submit"), Action("stop", text="够了")]
        result = self.engine(plan).run()
        self.assertEqual(result.plan, ())
        self.assertGreaterEqual(len(result.attempts), 1)

    def test_agent_stop_reason_is_kept(self):
        result = self.engine([Action("stop", text="这活儿我干不了")]).run()
        self.assertEqual(result.stop_reason, "这活儿我干不了")


class TestPromptShowsPlanAndNote(unittest.TestCase):
    def _prompt(self, plan=(), note=""):
        with mock.patch.dict(os.environ, {"AUTOFLUX_API_KEY": "test-key"}):
            agent = LLMAgent(LLMSettings(), mission="修好它")
        obs = Observation(
            step=3,
            attempt=1,
            recent=("刚才做了 A",),
            workspace=("a.py",),
            skills=(),
            plan=tuple(plan),
            note=note,
        )
        return agent._build_prompt(obs, [], ())

    def test_plan_is_rendered_with_checkboxes(self):
        text = self._prompt(plan=(("看报错", True), ("改代码", False)))
        self.assertIn("[x] 看报错", text)
        self.assertIn("[ ] 改代码", text)

    def test_note_is_rendered(self):
        text = self._prompt(note="你已经连续 3 步做同一件事")
        self.assertIn("【提醒】", text)
        self.assertIn("连续 3 步", text)

    def test_no_plan_no_note_is_quiet(self):
        text = self._prompt()
        self.assertIn("（还没写过）", text)
        self.assertNotIn("【提醒】", text)


class TestStuckNote(_Base):
    def test_repeated_action_is_pointed_out(self):
        engine = self.engine([])
        state = {
            "step": 3,
            "action_seq": ["tool:list_files"] * 3,
            "last_progress_step": 2,
            "plan": [],
        }
        self.assertIn("连续 3 步", engine._note(state))

    def test_long_stall_is_pointed_out(self):
        engine = self.engine([])
        state = {"step": 9, "action_seq": [], "last_progress_step": 0, "plan": []}
        self.assertIn("没有新的评测结果", engine._note(state))

    def test_missing_plan_is_pointed_out(self):
        engine = self.engine([])
        state = {"step": 7, "action_seq": [], "last_progress_step": 7, "plan": []}
        self.assertIn("还没写过计划", engine._note(state))

    def test_healthy_run_has_no_note(self):
        engine = self.engine([])
        state = {"step": 2, "action_seq": ["a", "b"], "last_progress_step": 2, "plan": [["x", False]]}
        self.assertEqual(engine._note(state), "")


class TestResume(_Base):
    def test_resume_keeps_history_and_attempt_number(self):
        calls = {"n": 0}

        def should_stop():
            calls["n"] += 1
            return calls["n"] > 2  # 走两步之后停

        snapshot = self.root / "state.json"
        plan1 = [Action("tool", "list_files"), Action("tool", "list_files")]
        first = self.engine(plan1, snapshot=snapshot).run(should_stop=should_stop, )
        self.assertGreaterEqual(first.steps_used, 1)
        self.assertTrue(snapshot.exists())

        state = json.loads(snapshot.read_text(encoding="utf-8"))
        workdir = self.root / "ws"
        book = Skillbook(self.root / "s2.db")
        self.addCleanup(book.close)
        plan2 = [Action("submit"), Action("stop", text="到了")]
        resumed = GraphEngine(
            task=bugfix.BugfixTask(),
            agent=ScriptedAgent(plan2),
            tools=default_tools(workdir),
            reflector=TemplateReflector(),
            skillbook=book,
            stop_policy=StopPolicy(Limits(max_steps=30, max_attempts=5)),
            tracer=NullTracer(),
            workdir=workdir,
            snapshot_path=snapshot,
        ).run(resume_state=state)

        self.assertEqual(resumed.attempts[0].attempt, 1)
        self.assertIn("到了", resumed.stop_reason)
        # 续跑用的是同一个工作区，不是从原始 bug 版本重来
        self.assertTrue((workdir / "stats.py").exists())


class TestTimeBudget(_Base):
    def test_elapsed_limit_stops_run(self):
        limits = Limits(max_steps=30, max_seconds=0.0001)
        result = self.engine([Action("tool", "list_files")] * 5, limits=limits).run()
        self.assertIn("时间用尽", result.stop_reason)


class TestFullScriptStillWorks(_Base):
    def test_scripted_play_reaches_full_score(self):
        result = self.engine(build_scripted_plan()).run()
        self.assertEqual(result.best.ratio, 1.0)


if __name__ == "__main__":
    unittest.main()

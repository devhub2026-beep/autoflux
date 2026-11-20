"""提示词契约：交给模型的文字里，必须真的有「这次要干什么」。

加这个文件的原因：goal 模式下模型去修 stats.py —— 因为提示词里从头到尾
没出现过目标，只有一段示例。那不是模型的错，是提示词里根本没有任务。
所以这里断言的是**字面上有没有**，不是「看着像不像」。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from autoflux.agents.llm import LLMAgent
from autoflux.config import LLMSettings
from autoflux.tasks.goal import GoalTask
from autoflux.tools.fs import default_tools
from autoflux.types import Observation

from . import ScratchCase


class _Resp:
    def __init__(self, content: str) -> None:
        self._body = json.dumps(
            {"choices": [{"message": {"content": content}}]}
        ).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _Capture:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def __call__(self, req: Any, timeout: float) -> Any:
        self.payloads.append(json.loads(req.data.decode("utf-8")))
        return _Resp('{"action":"stop","reason":"看提示词"}')

    def text(self) -> str:
        return "\n".join(
            m["content"] for p in self.payloads for m in p["messages"]
        )

    def user_text(self) -> str:
        return "\n".join(p["messages"][-1]["content"] for p in self.payloads)


class TestPromptCarriesMission(ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        self._old = os.environ.get("AUTOFLUX_API_KEY")
        os.environ["AUTOFLUX_API_KEY"] = "test-key"

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("AUTOFLUX_API_KEY", None)
        else:
            os.environ["AUTOFLUX_API_KEY"] = self._old
        super().tearDown()

    def _agent(self, mission: str, capture: _Capture) -> LLMAgent:
        return LLMAgent(LLMSettings(), transport=capture, mission=mission)

    def _obs(self) -> Observation:
        return Observation(step=0, attempt=1, recent=(), workspace=(), skills=())

    def test_goal_text_reaches_the_model(self):
        mission = "在工作区里新建 hello.txt，内容只有一行 hello"
        cap = _Capture()
        self._agent(mission, cap).decide(self._obs(), default_tools(self.root), ())
        self.assertIn(mission, cap.text())
        self.assertIn("【任务】", cap.text())

    def test_check_command_is_explained(self):
        cap = _Capture()
        task = GoalTask(goal="让 hello.txt 出现", check="findstr hello hello.txt", source=self.root)
        self._agent(task.brief(), cap).decide(
            self._obs(), default_tools(self.root), ()
        )
        user = cap.user_text()
        self.assertIn("让 hello.txt 出现", user)
        self.assertIn("findstr hello hello.txt", user)

    def test_no_mission_no_fake_block(self):
        cap = _Capture()
        self._agent("", cap).decide(self._obs(), default_tools(self.root), ())
        self.assertNotIn("【任务】", cap.user_text())

    def test_system_prompt_has_no_task_specific_file(self):
        """示例不该写死某个任务的文件名，否则模型会照着示例猜任务。"""
        cap = _Capture()
        self._agent("建一个 hello.txt", cap).decide(
            self._obs(), default_tools(self.root), ()
        )
        system = cap.payloads[0]["messages"][0]["content"]
        self.assertNotIn("stats.py", system)


class TestGoalTaskBrief(ScratchCase):
    def test_brief_mentions_goal_and_check(self):
        src = self.root / "src"
        src.mkdir()
        task = GoalTask(goal="让 hello.txt 出现", check="findstr hello hello.txt", source=src)
        brief = task.brief()
        self.assertIn("让 hello.txt 出现", brief)
        self.assertIn("findstr hello hello.txt", brief)
        self.assertIn("工作区", brief)

    def test_brief_is_not_inherited_empty(self):
        task = GoalTask(goal="x", check="true", source=Path("."))
        self.assertTrue(task.brief().strip())

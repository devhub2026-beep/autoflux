"""用假传输层把真 LLMAgent 的整条路径离线跑一遍。

没有这一步的时候，`agents/llm.py` 里解析、拼 prompt、错误处理全都是第一次真跑
才被执行——于是每跑一次冒一个 bug。现在这些都在毫秒级测试里覆盖。
"""
from __future__ import annotations

import io
import json
import os
import unittest
import urllib.error
from pathlib import Path
from typing import Any

from autoflux.agents.llm import LLMAgent
from autoflux.config import Limits, LLMSettings
from autoflux.graph import GraphEngine
from autoflux.reflector import LLMReflector, TemplateReflector
from autoflux.skillbook import Skillbook
from autoflux.stop import StopPolicy
from autoflux.tasks.bugfix.task import BugfixBlindTask, BugfixTask
from autoflux.tools.fs import default_tools
from autoflux.trace import NullTracer

from . import ScratchCase

_FIX = Path(__file__).resolve().parents[1] / "src/autoflux/tasks/bugfix/fixes/full_stats.py"


class _Resp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def reply(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content}}]}


class FakeTransport:
    """按顺序回放预设响应，并记录每次请求的 messages。"""

    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, req: Any, timeout: float) -> Any:
        self.requests.append(json.loads(req.data.decode("utf-8")))
        if not self._items:
            raise AssertionError("模型被调用的次数超过了预设响应数")
        item = self._items.pop(0)
        if isinstance(item, Exception):
            # 网络断了就是一直断：同一异常留给下一次重试
            self._items.insert(0, item)
            raise item
        return _Resp(item)


class _Case(ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["AUTOFLUX_TEST_KEY"] = "dummy"
        self.settings = LLMSettings(api_key_env="AUTOFLUX_TEST_KEY", model="fake")

    def agent(self, transport: FakeTransport) -> LLMAgent:
        a = LLMAgent(self.settings, transport=transport)
        a.retries = 3
        a.backoff = 0.0  # 测试里别真睡
        return a


class TestTransportSeam(_Case):
    def test_missing_key_raises(self):
        os.environ.pop("AUTOFLUX_TEST_KEY", None)
        with self.assertRaises(RuntimeError) as ctx:
            LLMAgent(LLMSettings(api_key_env="AUTOFLUX_TEST_KEY"))
        self.assertIn("API key", str(ctx.exception))

    def test_http_error_becomes_runtime_error(self):
        err = urllib.error.HTTPError("http://x", 401, "unauthorized", {}, io.BytesIO(b"bad key"))
        a = self.agent(FakeTransport([err]))
        with self.assertRaises(RuntimeError) as ctx:
            a._chat([{"role": "user", "content": "hi"}])
        self.assertIn("401", str(ctx.exception))

    def test_connection_error_becomes_runtime_error(self):
        err = urllib.error.URLError("dns")
        a = self.agent(FakeTransport([err]))
        with self.assertRaises(RuntimeError) as ctx:
            a._chat([{"role": "user", "content": "hi"}])
        self.assertIn("连不上", str(ctx.exception))

    def test_bad_payload_shape(self):
        a = self.agent(FakeTransport([{"nope": 1}]))
        with self.assertRaises(RuntimeError) as ctx:
            a._chat([{"role": "user", "content": "hi"}])
        self.assertIn("格式异常", str(ctx.exception))

    def test_empty_content_is_empty_string(self):
        a = self.agent(FakeTransport([reply("")]))
        self.assertEqual(a._chat([{"role": "user", "content": "hi"}]), "")


class TestLLMEngineFlow(_Case):
    def test_agent_solves_task_through_tools(self):
        fixed = _FIX.read_text(encoding="utf-8")
        transport = FakeTransport([
            reply('{"action":"tool","tool":"read_file","args":{"path":"stats.py"}}'),
            reply(json.dumps({"action": "write_file", "path": "stats.py", "content": fixed})),
            reply('{"action":"submit"}'),
        ])
        workdir = self.root / "ws"
        book = Skillbook(self.root / "s.db")
        engine = GraphEngine(
            task=BugfixTask(),
            agent=self.agent(transport),
            tools=default_tools(workdir),
            reflector=TemplateReflector(),
            skillbook=book,
            stop_policy=StopPolicy(Limits(max_steps=20, max_attempts=3)),
            tracer=NullTracer(),
            workdir=workdir,
        )
        result = engine.run()
        self.assertEqual(len(result.attempts), 1)
        self.assertEqual(result.attempts[0].score.ratio, 1.0)
        self.assertIn("达标", result.stop_reason)
        # 模型确实被喂了工具清单和文件列表
        self.assertIn("read_file", transport.requests[0]["messages"][1]["content"])
        book.close()

    def test_unknown_action_stops_cleanly(self):
        transport = FakeTransport([reply('{"action":"dance"}')])
        book = Skillbook(self.root / "s.db")
        engine = GraphEngine(
            task=BugfixTask(),
            agent=self.agent(transport),
            tools=default_tools(self.root / "ws"),
            reflector=TemplateReflector(),
            skillbook=book,
            stop_policy=StopPolicy(Limits(max_steps=5, max_attempts=2)),
            tracer=NullTracer(),
            workdir=self.root / "ws",
        )
        result = engine.run()
        self.assertIn("未知动作", result.stop_reason)
        self.assertEqual(result.attempts, [])
        book.close()

    def test_garbage_output_stops_cleanly(self):
        transport = FakeTransport([reply("我觉得应该改一下 stdev")])
        book = Skillbook(self.root / "s.db")
        engine = GraphEngine(
            task=BugfixTask(),
            agent=self.agent(transport),
            tools=default_tools(self.root / "ws"),
            reflector=TemplateReflector(),
            skillbook=book,
            stop_policy=StopPolicy(Limits(max_steps=5, max_attempts=2)),
            tracer=NullTracer(),
            workdir=self.root / "ws",
        )
        result = engine.run()
        self.assertIn("无法解析", result.stop_reason)
        book.close()


class TestBlindReflectionOffline(_Case):
    def test_reflect_pulls_diagnosis_into_rule(self):
        captured: list[str] = []

        def complete(prompt: str) -> str:
            captured.append(prompt)
            return "规则：改 stdev 之前先确认样本/总体的区别。"

        fixed = _FIX.read_text(encoding="utf-8")
        transport = FakeTransport([
            reply('{"action":"submit"}'),                                  # 8/10，盲
            reply('{"action":"reflect"}'),                                 # 买诊断
            reply(json.dumps({"action": "write_file", "path": "stats.py", "content": fixed})),
            reply('{"action":"submit"}'),                                  # 10/10
        ])
        book = Skillbook(self.root / "s.db")
        engine = GraphEngine(
            task=BugfixBlindTask(),
            agent=self.agent(transport),
            tools=default_tools(self.root / "ws"),
            reflector=LLMReflector(complete),
            skillbook=book,
            stop_policy=StopPolicy(Limits(max_steps=20, max_attempts=3)),
            tracer=NullTracer(),
            workdir=self.root / "ws",
        )
        result = engine.run()
        self.assertEqual(result.reflections, 1)
        self.assertEqual(result.attempts[-1].score.ratio, 1.0)
        # 诊断确实进了反思的 prompt
        self.assertTrue(captured)
        self.assertIn("test_stdev_single_value_raises", captured[0])
        # 反思确实进了策略库
        self.assertIn("样本", book.skills()[0])
        book.close()


if __name__ == "__main__":
    unittest.main()

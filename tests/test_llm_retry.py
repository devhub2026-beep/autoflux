"""模型端点抖动时要重试，而不是让整次 run 崩掉。

这条来自一次真实的基线跑：bench 跑到第 16 个，`http.client.IncompleteRead`
把整轮打挂（`IncompleteRead(0 bytes read)`），前面 15 个结果全白跑。
"""
from __future__ import annotations

import http.client
import io
import json
import os
import unittest
import urllib.error
import urllib.request
from typing import Any

from autoflux.agents.llm import LLMAgent, _urllib_transport
from autoflux.config import LLMSettings


def _settings() -> LLMSettings:
    return LLMSettings(
        base_url="http://fake.local/v1",
        model="m",
        api_key_env="AUTOFLUX_TEST_KEY",
        timeout=1.0,
    )


class _Resp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _ok(text: str) -> _Resp:
    return _Resp({"choices": [{"message": {"content": text}}]})


class FlakyTransport:
    """前 n 次抛给定的异常，之后正常返回。"""

    def __init__(self, exc: Exception, times: int, body: _Resp) -> None:
        self.exc, self.times, self.body = exc, times, body
        self.calls = 0

    def __call__(self, req, timeout):
        self.calls += 1
        if self.calls <= self.times:
            raise self.exc
        return self.body


class RetryTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["AUTOFLUX_TEST_KEY"] = "k"
        self.addCleanup(os.environ.pop, "AUTOFLUX_TEST_KEY", None)

    def _agent(self, transport) -> LLMAgent:
        agent = LLMAgent(_settings(), transport=transport)
        agent.retries = 3
        agent.backoff = 0.0
        return agent

    def test_incomplete_read_is_retried(self) -> None:
        exc = http.client.IncompleteRead(b"")
        transport = FlakyTransport(exc, 2, _ok('{"action":"stop","text":"好"}'))
        agent = self._agent(transport)
        action = agent.decide(_obs(), [], ())
        self.assertEqual(action.kind, "stop")
        self.assertEqual(transport.calls, 3)

    def test_broken_pipe_is_retried(self) -> None:
        transport = FlakyTransport(ConnectionResetError("reset"), 1, _ok('{"action":"stop"}'))
        agent = self._agent(transport)
        self.assertEqual(agent.decide(_obs(), [], ()).kind, "stop")

    def test_500_is_retried_then_raises(self) -> None:
        class Boom:
            def __call__(self, req, timeout):
                raise urllib.error.HTTPError("u", 503, "busy", {}, io.BytesIO(b"busy"))

        agent = self._agent(Boom())
        with self.assertRaises(RuntimeError) as ctx:
            agent.decide(_obs(), [], ())
        self.assertIn("重试", str(ctx.exception))

    def test_401_is_not_retried(self) -> None:
        calls = {"n": 0}

        class Auth:
            def __call__(self, req, timeout):
                calls["n"] += 1
                raise urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b"bad key"))

        agent = self._agent(Auth())
        with self.assertRaises(RuntimeError) as ctx:
            agent.decide(_obs(), [], ())
        self.assertEqual(calls["n"], 1)
        self.assertIn("401", str(ctx.exception))

    def test_transport_rejects_non_http_scheme(self) -> None:
        # 端点来自配置，别让 file:// 之类的东西借 urlopen 打开本地文件
        req = urllib.request.Request("file:///etc/passwd")  # noqa: S310 —— 故意构造一个非法端点
        with self.assertRaises(ValueError) as ctx:
            _urllib_transport(req, 1.0)
        self.assertIn("http", str(ctx.exception))


def _obs():
    from autoflux.types import Observation

    return Observation(step=0, attempt=0, recent=(), workspace=(), skills=())


if __name__ == "__main__":
    unittest.main()

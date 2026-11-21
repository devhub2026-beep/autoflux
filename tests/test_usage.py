"""帐要算得清：token、调用次数、没报账的调用、按单价折算的花费。"""
from __future__ import annotations

import json
import os
import unittest
from typing import Any

from autoflux.agents.llm import LLMAgent, complete_fn
from autoflux.config import LLMSettings
from autoflux.runlog import read_meta, stamp_run, usage_from_meta
from autoflux.types import RunResult
from autoflux.usage import Meter, Usage

from . import ScratchCase


class _Resp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _reply(content: str, usage: dict[str, Any] | None = None) -> _Resp:
    payload: dict[str, Any] = {"choices": [{"message": {"content": content}}]}
    if usage is not None:
        payload["usage"] = usage
    return _Resp(payload)


class _Transport:
    def __init__(self, items: list[_Resp]) -> None:
        self._items = list(items)

    def __call__(self, req: Any, timeout: float) -> _Resp:
        return self._items.pop(0)


def _agent(items: list[_Resp], meter: Meter) -> LLMAgent:
    os.environ.setdefault("AUTOFLUX_API_KEY", "test-key")
    return LLMAgent(
        LLMSettings(api_key_env="AUTOFLUX_API_KEY"),
        transport=_Transport(items),
        meter=meter,
    )


class TestUsage(ScratchCase):
    def test_plus_and_cost(self):
        a = Usage(calls=1, prompt_tokens=100, completion_tokens=50)
        b = Usage(calls=2, prompt_tokens=200, completion_tokens=0, unreported_calls=1)
        total = a.plus(b)
        self.assertEqual(total.calls, 3)
        self.assertEqual(total.total_tokens, 350)
        self.assertEqual(total.unreported_calls, 1)
        # 单价是「每百万 token」：1000 入 + 500 出，单价 10 / 20
        self.assertAlmostEqual(
            Usage(prompt_tokens=1000, completion_tokens=500).cost(10.0, 20.0),
            (1000 * 10 + 500 * 20) / 1_000_000,
        )

    def test_lines_hide_cost_without_prices(self):
        text = "\n".join(Usage(calls=1, prompt_tokens=10, completion_tokens=5).lines())
        self.assertIn("模型调用    1 次", text)
        self.assertIn("15", text)
        self.assertNotIn("花费", text)

    def test_unreported_call_is_visible(self):
        u = Usage(calls=1, unreported_calls=1)
        self.assertIn("端点没回 usage", "\n".join(u.lines()))

    def test_agent_records_tokens_from_reply(self):
        meter = Meter()
        agent = _agent([_reply("ok", {"prompt_tokens": 120, "completion_tokens": 30})], meter)
        agent.complete([{"role": "user", "content": "hi"}])
        snap = meter.snapshot()
        self.assertEqual((snap.calls, snap.prompt_tokens, snap.completion_tokens), (1, 120, 30))

    def test_agent_marks_calls_without_usage(self):
        meter = Meter()
        agent = _agent([_reply("ok")], meter)
        agent.complete([{"role": "user", "content": "hi"}])
        snap = meter.snapshot()
        self.assertEqual((snap.calls, snap.unreported_calls, snap.total_tokens), (1, 1, 0))

    def test_complete_fn_shares_meter(self):
        meter = Meter()
        os.environ.setdefault("AUTOFLUX_API_KEY", "test-key")
        fn = complete_fn(
            LLMSettings(api_key_env="AUTOFLUX_API_KEY"),
            transport=_Transport([_reply("ok", {"prompt_tokens": 7, "completion_tokens": 3})]),
            meter=meter,
        )
        fn("hello")
        self.assertEqual(meter.snapshot().total_tokens, 10)


class TestRunLog(ScratchCase):
    def test_stamp_keeps_identity_and_adds_usage(self):
        path = self.root / "runs" / "x" / "run.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"run_id": "x", "goal": "让测试过"}), encoding="utf-8")

        result = RunResult(
            task="goal",
            attempts=[],
            stop_reason="循环自然结束",
            steps_used=3,
            reflections=1,
            usage=Usage(calls=2, prompt_tokens=100, completion_tokens=20),
        )
        stamp_run(path, result.usage, result.summary())

        meta = read_meta(path)
        self.assertEqual(meta["run_id"], "x")
        self.assertEqual(meta["goal"], "让测试过")
        self.assertEqual(meta["usage"]["total_tokens"], 120)
        self.assertIn("finished_at", meta)

    def test_broken_json_is_not_fatal(self):
        path = self.root / "bad.json"
        path.write_text("{oops", encoding="utf-8")
        self.assertEqual(read_meta(path), {})
        self.assertEqual(usage_from_meta({}).calls, 0)
        self.assertEqual(usage_from_meta({"usage": {"calls": "很多"}}).calls, 0)

    def test_usage_from_meta_recovers_previous_run(self):
        usage = usage_from_meta(
            {"usage": {"calls": 3, "prompt_tokens": 30, "completion_tokens": 12,
                       "unreported_calls": 1}}
        )
        self.assertEqual((usage.calls, usage.total_tokens, usage.unreported_calls), (3, 42, 1))


if __name__ == "__main__":
    unittest.main()

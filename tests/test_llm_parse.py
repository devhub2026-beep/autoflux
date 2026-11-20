from __future__ import annotations

import os
import unittest

from autoflux.agents.llm import LLMAgent
from autoflux.config import LLMSettings

from . import ScratchCase

_TOOLS = {"read_file", "write_file", "submit"}


class TestLenientParsing(ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["AUTOFLUX_TEST_KEY"] = "dummy"
        self.agent = LLMAgent(LLMSettings(api_key_env="AUTOFLUX_TEST_KEY"))

    def test_plain_tool(self):
        a = self.agent._parse('{"action":"tool","tool":"read_file","args":{"path":"x"}}', _TOOLS)
        self.assertEqual((a.kind, a.name, a.args["path"]), ("tool", "read_file", "x"))

    def test_tool_name_as_action(self):
        # 模型常见错误：把工具名写进 action
        a = self.agent._parse('{"action":"read_file","path":"x"}', _TOOLS)
        self.assertEqual((a.kind, a.name), ("tool", "read_file"))
        self.assertEqual(a.args["path"], "x")

    def test_missing_action_but_tool_present(self):
        a = self.agent._parse('{"tool":"write_file","args":{"path":"a","content":"b"}}', _TOOLS)
        self.assertEqual(a.kind, "tool")
        self.assertEqual(a.name, "write_file")

    def test_args_under_parameters(self):
        a = self.agent._parse('{"action":"tool","tool":"read_file","parameters":{"path":"y"}}', _TOOLS)
        self.assertEqual(a.args["path"], "y")

    def test_control_actions(self):
        self.assertEqual(self.agent._parse('{"action":"reflect"}', _TOOLS).kind, "reflect")
        self.assertEqual(self.agent._parse('{"action":"submit"}', _TOOLS).kind, "submit")
        stop = self.agent._parse('{"action":"stop","reason":"做不到"}', _TOOLS)
        self.assertEqual((stop.kind, stop.text), ("stop", "做不到"))

    def test_code_fence_stripped(self):
        a = self.agent._parse('```json\n{"action":"submit"}\n```', _TOOLS)
        self.assertEqual(a.kind, "submit")

    def test_garbage_becomes_stop_with_reason(self):
        a = self.agent._parse("我不太确定要做什么", _TOOLS)
        self.assertEqual(a.kind, "stop")
        self.assertIn("无法解析", a.text)

    def test_unknown_action_becomes_stop(self):
        a = self.agent._parse('{"action":"dance"}', _TOOLS)
        self.assertEqual(a.kind, "stop")
        self.assertIn("未知动作", a.text)


if __name__ == "__main__":
    unittest.main()

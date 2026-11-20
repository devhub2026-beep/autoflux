"""问答层：编数打回、重写、把问题原样塞回去。"""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from autoflux.cli import main
from autoflux.employment import Dataset, qa

from . import ScratchCase

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "examples" / "employment" / "data" / "wages_2025.csv"


class FakeLLM:
    """假传输层：按顺序吐预先写好的答案，记录每次收到的 messages。"""

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.answers.pop(0)


class AskTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ds = Dataset(DATA)

    def test_good_answer_costs_one_call(self) -> None:
        llm = FakeLLM(["最高是信息传输、软件和信息技术服务业 248752 元。"])
        out = qa.ask(llm, self.ds, "哪个行业工资最高？")
        self.assertTrue(out["verified"])
        self.assertEqual(out["attempts"], 1)
        self.assertEqual(out["problems"], [])

    def test_fabricated_number_is_rewritten(self) -> None:
        llm = FakeLLM(
            [
                "全国合计 150000 元。",                       # 编的
                "全国合计 129441 元，最高 248752 元。",       # 改对了
            ]
        )
        out = qa.ask(llm, self.ds, "全国平均多少？")
        self.assertTrue(out["verified"])
        self.assertEqual(out["attempts"], 2)
        # 第二轮的提示词里必须带着上一版的具体问题，否则「重写」就是重新猜
        second = llm.calls[1][-1]["content"]
        self.assertIn("150000", second)
        self.assertIn("找不到", second)

    def test_gives_up_after_attempts(self) -> None:
        llm = FakeLLM(["编的 999999 元。", "又编了 888888 元。"])
        out = qa.ask(llm, self.ds, "随便问", attempts=2)
        self.assertFalse(out["verified"])
        self.assertEqual(out["attempts"], 2)
        self.assertEqual(len(out["problems"]), 1)
        self.assertIn("888888", out["problems"][0])

    def test_context_carries_the_table(self) -> None:
        llm = FakeLLM(["全国合计 129441 元。"])
        qa.ask(llm, self.ds, "全国平均多少？")
        system = llm.calls[0][0]["content"]
        self.assertIn("248752", system)
        self.assertIn("住宿和餐饮业", system)
        self.assertIn("行业门类", system)


class AskCliTest(ScratchCase):
    """命令行的接线：跑的是真 _cmd_ask，只把模型换成假的。"""

    def test_ask_command_prints_verified_answer(self) -> None:
        fake = FakeLLM(["全国合计 129441 元，最高行业 248752 元。"])
        buf = io.StringIO()
        with patch("autoflux.cli.LLMAgent", lambda *a, **k: fake), redirect_stdout(buf):
            code = main(["ask", "--question", "全国平均多少？", "--data", str(DATA)])
        self.assertEqual(code, 0)
        self.assertIn("129441", buf.getvalue())
        self.assertIn("通过", buf.getvalue())

    def test_ask_command_reports_unverified(self) -> None:
        fake = FakeLLM(["全国合计 150000 元。", "全国合计 150000 元。"])
        err = io.StringIO()
        with patch("autoflux.cli.LLMAgent", lambda *a, **k: fake):
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = main(
                    [
                        "ask",
                        "--question",
                        "全国平均多少？",
                        "--data",
                        str(DATA),
                        "--attempts",
                        "2",
                    ]
                )
        self.assertEqual(code, 1)
        self.assertIn("150000", err.getvalue())

    def test_missing_table_is_rejected(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err):
            code = main(["ask", "--question", "问", "--data", str(self.root / "没有.csv")])
        self.assertEqual(code, 2)
        self.assertIn("找不到数据表", err.getvalue())


class AskChatTest(ScratchCase):
    """多轮：第二问的提示词里要能看到第一问和它的答案。"""

    def test_chat_carries_history(self) -> None:
        fake = FakeLLM(
            [
                "全国合计 129441 元。",
                "最高是信息传输、软件和信息技术服务业 248752 元。",
            ]
        )
        buf = io.StringIO()
        with patch("autoflux.cli.LLMAgent", lambda *a, **k: fake), \
                patch("builtins.input", side_effect=["全国平均多少？", "哪个行业最高？", ""]):
            with redirect_stdout(buf):
                code = main(["ask", "--chat", "--data", str(DATA)])
        self.assertEqual(code, 0)
        self.assertEqual(len(fake.calls), 2)
        joined = "\n".join(m["content"] for m in fake.calls[1])
        self.assertIn("全国平均多少？", joined)
        self.assertIn("129441", joined)

    def test_ask_needs_question_or_chat(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err):
            code = main(["ask", "--data", str(DATA)])
        self.assertEqual(code, 2)
        self.assertIn("要么给 --question", err.getvalue())


if __name__ == "__main__":
    unittest.main()

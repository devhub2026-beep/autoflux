"""命令行 run/resume 的端到端：真 CLI、真图、真评测，只把模型换成脚本。

引擎层的用例已经把「环」测透了，这里测的是接线——参数有没有落到任务上、
run 目录写了什么、返回码对不对、续跑是不是真的接着上一轮的工作区。
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from autoflux.cli import main
from autoflux.skillbook import Skillbook
from autoflux.types import Action

from . import ScratchCase


class ScriptedAgent:
    """不做决策，按剧本吐动作。"""

    def __init__(self, script: list[Action]) -> None:
        self.script = list(script)

    def decide(self, obs, tools, skills) -> Action:
        return self.script.pop(0) if self.script else Action("submit")


def _agent_factory(script: list[Action]):
    return lambda *args, **kwargs: ScriptedAgent(script)


def _reflector_factory():
    return lambda *args, **kwargs: (lambda prompt: "规则：测试替身")


CHECK_SCRIPT = """import pathlib, sys
p = pathlib.Path("hello.txt")
ok = p.is_file() and p.read_text(encoding="utf-8").strip() == "hello"
sys.exit(0 if ok else 1)
"""


class RunCliTest(ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        self._old_cwd = os.getcwd()
        os.chdir(self.root)                      # run/ 目录、技能库都是相对 cwd 的
        self.addCleanup(os.chdir, self._old_cwd)

        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "check.py").write_text(CHECK_SCRIPT, encoding="utf-8")
        self.check = f'"{sys.executable}" check.py'

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def _patched(self, script: list[Action]):
        return (
            patch("autoflux.cli.LLMAgent", _agent_factory(script)),
            patch("autoflux.cli.complete_fn", _reflector_factory()),
        )

    def test_goal_run_passes_and_writes_run_dir(self) -> None:
        script = [
            Action("tool", "write_file", {"path": "hello.txt", "content": "hello\n"}),
            Action("submit"),
        ]
        p1, p2 = self._patched(script)
        with p1, p2:
            code, out, err = self._run(
                [
                    "run",
                    "--goal", "在工作区新建 hello.txt，内容只有一行 hello",
                    "--project", str(self.project),
                    "--check", self.check,
                    "--max-steps", "6",
                    "--max-attempts", "2",
                ]
            )
        self.assertEqual(code, 0, err)
        self.assertIn("1/1", out)

        run_dirs = [
            p for p in (self.root / "runs").iterdir() if (p / "run.json").is_file()
        ]
        self.assertEqual(len(run_dirs), 1)
        run_dir = run_dirs[0]
        self.assertTrue((run_dir / "run.json").is_file())
        self.assertTrue((run_dir / "state.json").is_file())
        self.assertTrue((run_dir / "trace.jsonl").is_file())
        self.assertTrue((run_dir / "checkpoints.sqlite").is_file())
        meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertIn("hello.txt", meta["goal"])
        self.assertEqual(meta["check"], self.check)

        ws = self.root / "runs" / "workspace"
        self.assertEqual(
            (ws / "hello.txt").read_text(encoding="utf-8").strip(), "hello"
        )

    def test_goal_without_check_is_rejected(self) -> None:
        code, _, err = self._run(
            ["run", "--goal", "随便做点什么", "--project", str(self.project)]
        )
        self.assertEqual(code, 2)
        self.assertIn("必须配 --check", err)

    def test_unknown_task_is_rejected(self) -> None:
        code, _, err = self._run(["run", "--task", "没有这个任务"])
        self.assertEqual(code, 2)
        self.assertIn("没有这个任务", err)

    def test_resume_continues_from_existing_workspace(self) -> None:
        run_id = "20260101-010101-resume"
        run_dir = self.root / "runs" / run_id
        run_dir.mkdir(parents=True)
        ws = self.root / "resume-ws"
        ws.mkdir()
        # 上一轮已经把文件写好了：续跑只需要提交，不能再铺一遍起始目录
        (ws / "hello.txt").write_text("hello", encoding="utf-8")
        (ws / "check.py").write_text(CHECK_SCRIPT, encoding="utf-8")
        (run_dir / "run.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "task": "goal",
                    "goal": "让 hello.txt 内容是 hello",
                    "check": self.check,
                    "project": str(self.project),
                    "workdir": str(ws),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (run_dir / "state.json").write_text(
            json.dumps(
                {
                    "history": ["[评测] 0/1"],
                    "step": 3,
                    "attempt": 2,
                    "reflections": 0,
                    "ratios": [0.0],
                    "attempts": [
                        {"attempt": 1, "passed": 0, "total": 1, "steps": 3, "reflections": 0}
                    ],
                    "last_score": {"passed": 0, "total": 1, "details": []},
                    "plan": [["写 hello.txt", True]],
                    "action_seq": ["write_file"],
                    "last_progress_step": 1,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        p1, p2 = self._patched([Action("submit")])
        with p1, p2:
            code, out, err = self._run(
                ["run", "--resume", str(run_dir), "--max-steps", "4"]
            )
        self.assertEqual(code, 0, err)
        self.assertIn("1/1", out)
        self.assertEqual(
            (ws / "hello.txt").read_text(encoding="utf-8").strip(), "hello"
        )
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(state["attempts"]), 2)   # 续跑没把尝试序号清零

    def test_tasks_lists_builtins(self) -> None:
        code, out, err = self._run(["tasks"])
        self.assertEqual(code, 0, err)
        self.assertIn("bugfix", out)

    def test_skills_command(self) -> None:
        store = self.root / "book.db"
        code, out, err = self._run(["skills", "--store", str(store)])
        self.assertEqual(code, 0, err)
        self.assertIn("还没有学到任何规则", out)

        with Skillbook(store) as book:
            book.add("规则：改动前先复现失败用例")
        code, out, _ = self._run(["skills", "--store", str(store)])
        self.assertEqual(code, 0)
        self.assertIn("先复现失败用例", out)


def io_buffer():
    import io

    return io.StringIO()


if __name__ == "__main__":
    unittest.main()

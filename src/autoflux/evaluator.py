"""评测闸门。

规矩只有一条：**分数来自这里，不来自模型。**

agent 的工作区被复制到临时目录，隐藏测试注入进去，跑完即销毁。
agent 全程看不到隐藏测试，也没法改评测代码。
"""
from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .fspaths import scratch
from .types import Score

_RAN = re.compile(r"Ran (\d+) tests?")
_FAILED = re.compile(r"FAILED \(([^)]*)\)")
_BLOCK = re.compile(r"^(?:FAIL|ERROR): .+$", re.MULTILINE)


@dataclass(frozen=True)
class EvalSpec:
    """怎么跑评测。"""

    hidden_dir: Path | None = None
    timeout: float = 120.0
    python: str = sys.executable


def run_evaluation(workspace: Path, spec: EvalSpec) -> Score:
    """在工作区的干净副本上跑 unittest，返回分数。"""
    if not workspace.exists():
        return Score(0, 1, ("工作区不存在",))

    with scratch("eval-") as td:
        sandbox = td / "ws"
        shutil.copytree(workspace, sandbox)
        if "__pycache__" in {p.name for p in sandbox.rglob("*")}:
            shutil.rmtree(sandbox / "__pycache__", ignore_errors=True)

        if spec.hidden_dir is not None and spec.hidden_dir.exists():
            # 隐藏用例改名成 test_* 才能被 discover 收集；agent 永远看不到它
            for src in sorted(spec.hidden_dir.glob("*.py")):
                shutil.copy2(src, sandbox / f"test_{src.name}")

        try:
            proc = subprocess.run(  # noqa: S603 —— 命令是自己拼的，不走 shell
                [spec.python, "-m", "unittest", "discover", "-s", ".", "-p", "test*.py"],
                cwd=sandbox,
                capture_output=True,
                text=True,
                timeout=spec.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return Score(0, 1, (f"评测超时（{spec.timeout}s）",))

        out = f"{proc.stdout}\n{proc.stderr}"
        return _parse(out)


def parse_unittest(output: str) -> Score | None:
    """从 unittest 输出里读出部分分；读不出来返回 None。

    goal 模式的判定命令通常就是一条 unittest，失败时也带着 `Ran 7 tests` 和
    `FAILED (failures=2)`——这两个数字就是现成的部分分，不需要额外约定。
    """
    ran = _RAN.search(output or "")
    if ran is None:
        return None
    total = int(ran.group(1))
    failed = 0
    failed_match = _FAILED.search(output)
    if failed_match:
        for raw_part in failed_match.group(1).split(","):
            part = raw_part.strip()
            if "=" in part:
                with contextlib.suppress(ValueError):
                    failed += int(part.split("=", 1)[1])
    return Score(max(0, total - failed), total, tuple(_BLOCK.findall(output)[:10]))


def _parse(output: str) -> Score:
    partial = parse_unittest(output)
    if partial is not None:
        return partial
    tail = "\n".join(output.strip().splitlines()[-12:])
    return Score(0, 1, ("评测没能收集到测试：", *tail.splitlines()))

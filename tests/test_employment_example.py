"""就业示例的端到端：标准答案报告必须被 _check.py 判过。

守的是「判分脚本本身还认不认得出正确报告」——规则写错（比如把两个负增长
说成一个）会先在这里爆，而不是等 agent 白跑一轮才发现。
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELFCHECK = ROOT / "examples" / "employment" / "tools" / "selfcheck.py"


def _run_selfcheck(env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(env_extra or {})
    return subprocess.run(  # noqa: S603 —— 跑的是本仓库的脚本
        [sys.executable, str(SELFCHECK)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
        env=env,
    )


class ExampleCheckTest(unittest.TestCase):
    def test_reference_report_passes(self) -> None:
        proc = _run_selfcheck()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("通过", proc.stdout)

    def test_check_survives_non_utf8_console(self) -> None:
        # Windows CI 的控制台默认不是 UTF-8（cp1252），判分脚本自己 print 中文
        # 曾经直接 UnicodeEncodeError；这里模拟一下，脚本必须自己切回 UTF-8。
        proc = _run_selfcheck({"PYTHONIOENCODING": "cp1252"})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("通过", proc.stdout)


if __name__ == "__main__":
    unittest.main()

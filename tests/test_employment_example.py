"""就业示例的端到端：标准答案报告必须被 _check.py 判过。

守的是「判分脚本本身还认不认得出正确报告」——规则写错（比如把两个负增长
说成一个）会先在这里爆，而不是等 agent 白跑一轮才发现。
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELFCHECK = ROOT / "examples" / "employment" / "tools" / "selfcheck.py"


class ExampleCheckTest(unittest.TestCase):
    def test_reference_report_passes(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(SELFCHECK)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("通过", proc.stdout)


if __name__ == "__main__":
    unittest.main()

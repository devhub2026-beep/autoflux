"""测试包。

两件事：把 src/ 放进路径（免安装），并提供一个自己建临时目录的基类
—— 不用 tempfile，原因见 autoflux/fspaths.py 的说明。
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = str(_ROOT / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

_TMP = _ROOT / ".autoflux" / "tmp"
_TMP.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("AUTOFLUX_TMP", str(_TMP))

from autoflux.fspaths import scratch  # noqa: E402


class ScratchCase(unittest.TestCase):
    """每个用例一个干净的目录，跑完删掉。"""

    root: Path

    def setUp(self) -> None:
        self._cm = scratch("test-")
        self.root = self._cm.__enter__()

    def tearDown(self) -> None:
        self._cm.__exit__(None, None, None)

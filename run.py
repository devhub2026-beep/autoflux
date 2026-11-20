"""免安装入口。

    python run.py run --task bugfix

这个文件只是把 ``src/`` 塞进 sys.path，然后转交给 ``autoflux.cli``。
真正的东西都在 ``src/autoflux/`` 里。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from autoflux.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

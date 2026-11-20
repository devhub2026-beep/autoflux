"""临时目录。

**故意不用 tempfile.TemporaryDirectory。**
在 Windows 上，mkdtemp 建出来的目录可能被宿主机的 ACL 策略拒绝读写，
表现为「目录明明存在，但 sqlite 报 unable to open database file、os.walk 报拒绝访问」。
这里改成在项目内自己 mkdir，权限跟随父目录，稳定得多。
"""
from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


def work_root() -> Path:
    """临时文件的根目录。默认在项目内，可用 AUTOFLUX_TMP 覆盖。"""
    raw = os.environ.get("AUTOFLUX_TMP")
    root = Path(raw) if raw else Path.cwd() / ".autoflux" / "tmp"
    root.mkdir(parents=True, exist_ok=True)
    return root


@contextmanager
def scratch(prefix: str = "autoflux-") -> Iterator[Path]:
    """开一个用完即删的目录。"""
    path = work_root() / f"{prefix}{uuid4().hex[:10]}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)

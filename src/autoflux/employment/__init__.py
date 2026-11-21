from __future__ import annotations

from pathlib import Path

from .dataset import Dataset
from .verify import extract_numbers, verify

# 默认数据表的两条来路：装好的包里有一份，仓库里 examples/ 还有一份
_PACKAGED = Path(__file__).with_name("data") / "wages_2025.csv"
_IN_REPO = Path(__file__).resolve().parents[3] / "examples" / "employment" / "data" / "wages_2025.csv"


def default_data_path() -> Path:
    """默认就业数据表：包内优先、仓库内兜底。

    包内那份随 wheel 走，所以 `pip install` 到任何机器、在任何目录下运行，
    `autoflux ask` 都能直接答，不用先 `cd` 到仓库或手动 `--data`。
    """
    if _PACKAGED.is_file():
        return _PACKAGED
    return _IN_REPO


__all__ = ["Dataset", "default_data_path", "extract_numbers", "verify"]

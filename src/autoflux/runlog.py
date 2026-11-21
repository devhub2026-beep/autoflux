"""run.json 的读写约定。

一次 run 的元信息就落在这一个文件里：开跑前写身份（目标、判定命令、工作区），
跑完补上这一轮的账（token、汇总）。续跑读回它，服务重启也从它恢复历史。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .usage import Usage


def read_meta(path: Path) -> dict[str, Any]:
    """读 run.json；不存在或坏了都当空字典——历史记录不该因为一行坏 JSON 消失。"""
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_meta(path: Path, meta: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def usage_from_meta(meta: dict[str, Any]) -> Usage:
    """从 run.json 里读上一段的账；字段缺失或类型不对就当没记过。"""
    raw = meta.get("usage")
    if not isinstance(raw, dict):
        return Usage()

    def pick(key: str) -> int:
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0
        return max(int(value), 0)

    return Usage(
        calls=pick("calls"),
        prompt_tokens=pick("prompt_tokens"),
        completion_tokens=pick("completion_tokens"),
        unreported_calls=pick("unreported_calls"),
    )


def stamp_run(path: Path, usage: Usage, summary: str) -> dict[str, Any]:
    """跑完把这一轮的账记回 run.json：续跑能接上，事后也能查。"""
    meta = read_meta(path)
    meta["usage"] = usage.as_dict()
    meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    meta["summary"] = summary
    write_meta(path, meta)
    return meta

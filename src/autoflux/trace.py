"""事件追踪。每次 run 一个 JSONL 文件，可回放。"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class Tracer:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")

    def emit(self, kind: str, **fields: Any) -> None:
        if self.path is None:
            return
        record = {"t": round(time.time(), 4), "kind": kind, **fields}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


class NullTracer(Tracer):
    def __init__(self) -> None:
        super().__init__(None)

    def emit(self, kind: str, **fields: Any) -> None:
        return

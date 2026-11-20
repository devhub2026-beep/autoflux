"""工作区工具。

每个工具都绑死在一个根目录上，``..`` 之类的逃逸会被拒绝——
因为 agent 手里的写权限必须被物理限制在它的工作区里。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class WorkspaceTool:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _resolve(self, rel: str) -> Path:
        target = (self.root / rel).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"越界路径：{rel}")
        return target


class ListFiles(WorkspaceTool):
    name = "list_files"
    description = "列出工作区里的文件（相对路径）。参数：无。"

    def run(self) -> str:
        files = sorted(
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        )
        return "\n".join(files) if files else "（空）"


class ReadFile(WorkspaceTool):
    name = "read_file"
    description = "读一个文件。参数：path。"

    def run(self, path: str) -> str:
        target = self._resolve(path)
        if not target.is_file():
            return f"ERROR 文件不存在：{path}"
        return target.read_text(encoding="utf-8")


class WriteFile(WorkspaceTool):
    name = "write_file"
    description = "覆盖写一个文件（会创建父目录）。参数：path, content。"

    def run(self, path: str, content: str) -> str:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"已写入 {path}（{len(content)} 字符）"


class RunTests(WorkspaceTool):
    name = "run_tests"
    description = "在工作区跑可见测试（python -m unittest）。参数：无。"

    def run(self) -> str:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test*.py"],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (proc.stdout + proc.stderr).strip()
        return out[-3000:] if out else "（无输出）"


class RunPython(WorkspaceTool):
    name = "run_python"
    description = "在工作区执行一段 Python 代码。参数：code。"

    def run(self, code: str) -> str:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            return f"EXIT {proc.returncode}\n{out}"[-3000:]
        return out[-3000:] if out else "（无输出）"


def default_tools(root: Path) -> list[WorkspaceTool]:
    return [ListFiles(root), ReadFile(root), WriteFile(root), RunTests(root), RunPython(root)]

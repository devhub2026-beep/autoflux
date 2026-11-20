"""agent 后端。

生产只有 LLM 一条路：ScriptedAgent 那种按剧本播放的假货已经删掉，
测试用的确定性替身放在 tests/support.py 里，不进产品。
"""
from __future__ import annotations

from .llm import LLMAgent

__all__ = ["LLMAgent"]

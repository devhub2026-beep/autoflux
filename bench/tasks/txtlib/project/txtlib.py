"""文本小工具。有几个函数是坏的，跑测试就能看到哪几个。"""
from __future__ import annotations

import re


def slugify(text: str) -> str:
    """'Hello  World!' -> 'hello-world'。首尾不留连字符。"""
    lowered = text.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    return slug


def truncate(text: str, limit: int) -> str:
    """超过 limit 就截断并加省略号，总长不超过 limit。"""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def wrap(text: str, width: int) -> list[str]:
    """按词折行，每行不超过 width；单词比 width 长就硬切。"""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current = current + " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def title_case(text: str) -> str:
    """每个词首字母大写，其余小写。"""
    return text.title()


def count_words(text: str) -> int:
    """只数单词，不把标点当词。"""
    return len(text.split())

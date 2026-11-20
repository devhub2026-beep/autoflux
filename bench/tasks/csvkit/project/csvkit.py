"""极小 CSV：只处理一行。字段用逗号分隔，含逗号的字段用双引号包住。"""
from __future__ import annotations


def parse_line(line: str) -> list[str]:
    """'a,"b,c",d' -> ['a', 'b,c', 'd']；双引号内的 "" 表示一个引号。"""
    fields: list[str] = []
    current = ""
    in_quotes = False
    for ch in line:
        if ch == '"':
            in_quotes = not in_quotes
            continue
        if ch == "," and not in_quotes:
            fields.append(current)
            current = ""
            continue
        current += ch
    fields.append(current)
    return fields


def serialize_row(fields: list[str]) -> str:
    """有逗号或引号的字段要用双引号包住，内部引号写两遍。"""
    parts: list[str] = []
    for field in fields:
        if "," in field:
            parts.append(f'"{field}"')
        else:
            parts.append(field)
    return ",".join(parts)


def parse_rows(text: str) -> list[list[str]]:
    return [parse_line(line) for line in text.splitlines() if line.strip()]

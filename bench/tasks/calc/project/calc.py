"""一个很小的四则运算解析器：支持 + - * / 和括号，整数。"""
from __future__ import annotations


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch.isdigit():
            num = ch
            i += 1
            while i < len(text) and text[i].isdigit():
                num += text[i]
                i += 1
            tokens.append(num)
            continue
        if ch in "+-*/()":
            tokens.append(ch)
            i += 1
            continue
        raise ValueError(f"无法识别的字符：{ch!r}")
    return tokens


def evaluate(text: str) -> int:
    """先算乘除后算加减，括号优先；除不尽直接抛 ZeroDivisionError。"""
    tokens = tokenize(text)
    pos = 0

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def take(expected: str | None = None) -> str:
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError("表达式意外结束")
        tok = tokens[pos]
        if expected is not None and tok != expected:
            raise ValueError(f"期望 {expected!r}，实际 {tok!r}")
        pos += 1
        return tok

    def expression() -> int:
        value = term()
        while peek() in ("+", "-"):
            op = take()
            right = term()
            value = value + right if op == "+" else value - right
        return value

    def term() -> int:
        value = factor()
        while peek() in ("*", "/"):
            op = take()
            right = factor()
            if op == "*":
                value = value * right
            else:
                value = value / right
        return value

    def factor() -> int:
        tok = peek()
        if tok == "(":
            take("(")
            value = expression()
            take(")")
            return value
        if tok == "-":
            take("-")
            return -factor()
        return int(take())

    result = expression()
    if pos != len(tokens):
        raise ValueError(f"多余的符号：{tokens[pos:]}")
    return result

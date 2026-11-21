"""Token 与花费记账。

模型端点几乎都会回 `usage`，但不是每个都回；不回的时候不能假装是 0 花费，
单独记一笔「没报账的调用」，这样「token 很少」永远有解释。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class Usage:
    """累计的调用与 token。单位是「次」和「token」，不是钱。"""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # 端点没回 usage 的调用数：这些调用确实发生了，但花了多少无从得知
    unreported_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def plus(self, other: Usage) -> Usage:
        return Usage(
            calls=self.calls + other.calls,
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            unreported_calls=self.unreported_calls + other.unreported_calls,
        )

    def cost(self, price_in: float = 0.0, price_out: float = 0.0) -> float:
        """按「每百万 token 单价」估算花费。单价没配就是 0，不猜。"""
        return (
            self.prompt_tokens / 1_000_000 * price_in
            + self.completion_tokens / 1_000_000 * price_out
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "unreported_calls": self.unreported_calls,
        }

    def lines(self, price_in: float = 0.0, price_out: float = 0.0) -> list[str]:
        if not self.calls:
            return []
        out = [
            f"模型调用    {self.calls} 次",
            (
                f"token       {self.prompt_tokens} 入 / {self.completion_tokens} 出"
                f"（共 {self.total_tokens}）"
            ),
        ]
        if price_in or price_out:
            out.append(f"花费        {self.cost(price_in, price_out):.4f}（按配置单价估算）")
        if self.unreported_calls:
            out.append(f"其中 {self.unreported_calls} 次端点没回 usage，只计了次数")
        return out


class Meter:
    """跨 agent / reflector 共享的一本账。web 里每个 run 一个线程，加锁不亏。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._usage = Usage()

    def add(self, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        with self._lock:
            self._usage = self._usage.plus(
                Usage(calls=1, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
            )

    def add_unreported(self) -> None:
        with self._lock:
            self._usage = self._usage.plus(Usage(calls=1, unreported_calls=1))

    def snapshot(self) -> Usage:
        with self._lock:
            return self._usage

    def replace_with(self, usage: Usage) -> None:
        """续跑时把上一段的账接上，不然 resume 的花费从 0 开始算。"""
        with self._lock:
            self._usage = usage

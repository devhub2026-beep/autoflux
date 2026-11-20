"""停止条件。全部由代码判定。

模型可以说「我做完了」，但只有这里说了算。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .config import Limits


@dataclass
class StopPolicy:
    limits: Limits

    def check(
        self,
        *,
        attempts: Sequence[float],
        steps_used: int,
        elapsed: float = 0.0,
    ) -> str | None:
        """返回停止原因；None 表示继续。attempts 按时间顺序排列。"""
        if steps_used >= self.limits.max_steps:
            return f"步数用尽（{self.limits.max_steps}）"

        if self.limits.max_seconds > 0 and elapsed >= self.limits.max_seconds:
            return f"时间用尽（{int(elapsed)}s >= {int(self.limits.max_seconds)}s）"

        if not attempts:
            return None

        if attempts[-1] >= self.limits.target_score:
            return f"达标（{attempts[-1]:.2f} >= {self.limits.target_score:.2f}）"

        if len(attempts) >= self.limits.max_attempts:
            return f"尝试次数用尽（{self.limits.max_attempts}）"

        k = self.limits.no_improve_limit
        if k > 0 and len(attempts) > k:
            recent = list(attempts[-k:])
            before = list(attempts[:-k])
            if max(recent) <= max(before):
                return f"连续 {k} 次无提升"

        return None

"""重试装饰器：失败几次后放弃，间隔按指数增长。"""
from __future__ import annotations

import time
from typing import Any, Callable, Type


def retry(
    attempts: int = 3,
    delay: float = 0.1,
    backoff: float = 2.0,
    on: Type[BaseException] | tuple[Type[BaseException], ...] = Exception,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """最多调用 attempts 次；第 n 次失败后睡 delay * backoff ** n 秒。"""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: BaseException | None = None
            for index in range(attempts - 1):
                try:
                    return fn(*args, **kwargs)
                except on as exc:  # noqa: PERF203
                    last_error = exc
                    time.sleep(delay * backoff ** index)
            return fn(*args, **kwargs)

        return wrapper

    return decorator

"""配置加载。用标准库 tomllib，不引第三方依赖。"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Limits:
    """停止与预算。全部由代码判定，不靠模型自觉。"""

    max_steps: int = 40
    max_attempts: int = 5
    target_score: float = 1.0
    no_improve_limit: int = 3
    max_seconds: float = 1800.0  # 整轮的时间预算，0 表示不限


@dataclass(frozen=True)
class LLMSettings:
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    api_key_env: str = "AUTOFLUX_API_KEY"
    temperature: float = 0.2
    timeout: float = 120.0


@dataclass(frozen=True)
class Settings:
    task: str = "bugfix"
    store: str = ".autoflux/state.db"
    limits: Limits = Limits()
    llm: LLMSettings = LLMSettings()


def _limits(d: dict[str, Any]) -> Limits:
    base = Limits()
    return replace(
        base,
        max_steps=int(d.get("max_steps", base.max_steps)),
        max_attempts=int(d.get("max_attempts", base.max_attempts)),
        target_score=float(d.get("target_score", base.target_score)),
        no_improve_limit=int(d.get("no_improve_limit", base.no_improve_limit)),
        max_seconds=float(d.get("max_seconds", base.max_seconds)),
    )


def _llm(d: dict[str, Any]) -> LLMSettings:
    base = LLMSettings()
    return replace(
        base,
        base_url=str(d.get("base_url", base.base_url)),
        model=str(d.get("model", base.model)),
        api_key_env=str(d.get("api_key_env", base.api_key_env)),
        temperature=float(d.get("temperature", base.temperature)),
        timeout=float(d.get("timeout", base.timeout)),
    )


def load(path: Path | None) -> Settings:
    """读 TOML。文件不存在就用全默认值。"""
    base = Settings()
    if path is None or not path.exists():
        return base

    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    run = raw.get("run", {})
    store = raw.get("store", {})

    return replace(
        base,
        task=str(run.get("task", base.task)),
        store=str(store.get("path", base.store)),
        limits=_limits(run),
        llm=_llm(raw.get("llm", {})),
    )

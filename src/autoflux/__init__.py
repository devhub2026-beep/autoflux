"""autoflux —— 会自己循环、自己反思的 agent。

对外只暴露这几样东西；其余都是实现细节。
"""
from __future__ import annotations

from .config import Limits, LLMSettings, Settings, load
from .graph import GraphEngine
from .skillbook import Skillbook
from .types import Action, AttemptRecord, Observation, RunResult, Score
from .usage import Meter, Usage

__version__ = "0.6.0"

__all__ = [
    "Action",
    "AttemptRecord",
    "GraphEngine",
    "LLMSettings",
    "Limits",
    "Meter",
    "Observation",
    "RunResult",
    "Score",
    "Settings",
    "Skillbook",
    "Usage",
    "__version__",
    "load",
]

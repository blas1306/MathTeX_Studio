from __future__ import annotations

from .result import AetherRunResult
from .session import AetherSession


def run_aether(source: str) -> AetherRunResult:
    return AetherSession().run(source)

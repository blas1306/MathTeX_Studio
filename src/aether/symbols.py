from __future__ import annotations

from dataclasses import dataclass

from .types import AetherType


@dataclass(frozen=True)
class VariableSymbol:
    name: str
    type_name: AetherType | None


@dataclass(frozen=True)
class FunctionSymbol:
    name: str
    return_type: AetherType | None
    parameters: tuple[VariableSymbol, ...]

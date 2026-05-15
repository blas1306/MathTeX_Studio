from __future__ import annotations


class AetherError(Exception):
    """Base class for Aether language errors."""


class AetherSyntaxError(AetherError):
    """Raised when Aether source cannot be parsed."""


class AetherTypeError(AetherError):
    """Raised when Aether type rules are violated."""


class AetherRuntimeError(AetherError):
    """Raised when Aether execution fails at runtime."""

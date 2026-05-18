from __future__ import annotations

from aether import AetherSession
from console_engine import MathRuntime
from language_runtime import (
    AETHER_RUNTIME,
    MATHLAB_LEGACY_RUNTIME,
    MATHLAB_RUNTIME,
    create_session_for_language,
    run_source_for_file,
    runtime_for_file,
)


def test_runtime_for_aether_file_returns_aether() -> None:
    assert runtime_for_file("demo.ae") == AETHER_RUNTIME


def test_runtime_for_mtx_file_returns_mathlab_legacy() -> None:
    assert runtime_for_file("legacy.mtx") == MATHLAB_RUNTIME
    assert MATHLAB_LEGACY_RUNTIME is MATHLAB_RUNTIME


def test_run_aether_source_returns_output() -> None:
    result = run_source_for_file("hello.ae", 'println("hola");')

    assert result.success
    assert result.runtime == AETHER_RUNTIME
    assert result.output == "hola\n"
    assert result.error is None


def test_run_aether_error_is_reported_without_raising() -> None:
    result = run_source_for_file("broken.ae", "println(x);")

    assert not result.success
    assert result.runtime == AETHER_RUNTIME
    assert result.error == "AetherTypeError: Undefined variable 'x'."


def test_create_session_for_language_returns_aether_session() -> None:
    assert isinstance(create_session_for_language("aether"), AetherSession)


def test_create_session_for_language_returns_mathlab_runtime() -> None:
    assert isinstance(create_session_for_language(".mtx"), MathRuntime)

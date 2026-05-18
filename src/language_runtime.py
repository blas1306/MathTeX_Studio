from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aether import AetherRuntimeError, AetherSession, AetherSyntaxError, AetherTypeError, run_aether
from console_engine import MathRuntime, capture_to_events
from mtex_executor import split_code_statements_with_lines


@dataclass(frozen=True)
class FileRuntime:
    id: str
    display_name: str
    suffixes: tuple[str, ...]


@dataclass(frozen=True)
class SourceRunResult:
    runtime: FileRuntime
    success: bool
    output: str = ""
    error: str | None = None


AETHER_RUNTIME = FileRuntime("aether", "Aether", (".ae",))
MATHLAB_RUNTIME = FileRuntime("mathlab", "MathLab Legacy", (".mtx",))
UNKNOWN_RUNTIME = FileRuntime("unknown", "Current editor", ())

AETHER_ERRORS = (AetherSyntaxError, AetherTypeError, AetherRuntimeError)


def runtime_for_file(path: str | Path | None) -> FileRuntime:
    suffix = _suffix_for_path(path)
    if suffix in AETHER_RUNTIME.suffixes:
        return AETHER_RUNTIME
    if suffix in MATHLAB_RUNTIME.suffixes:
        return MATHLAB_RUNTIME
    return UNKNOWN_RUNTIME


def create_session_for_language(language: str) -> AetherSession | MathRuntime:
    key = (language or "").strip().lower()
    if key in {"aether", "ae", ".ae"}:
        return AetherSession()
    if key in {"mathlab", "mathlab legacy", "mtx", ".mtx"}:
        return MathRuntime()
    raise ValueError(f"No session is registered for language '{language}'.")


def run_source_for_file(
    path: str | Path | None,
    source: str,
    *,
    math_runtime: MathRuntime | None = None,
) -> SourceRunResult:
    runtime = runtime_for_file(path)
    if runtime == AETHER_RUNTIME:
        return _run_aether_source(source)
    if runtime == MATHLAB_RUNTIME:
        return _run_mathlab_source(source, math_runtime=math_runtime)
    return SourceRunResult(
        runtime=runtime,
        success=False,
        error=f"No runtime is registered for {_display_path(path)}.",
    )


def format_aether_error(exc: AetherSyntaxError | AetherTypeError | AetherRuntimeError) -> str:
    return f"{type(exc).__name__}: {exc}"


def _run_aether_source(source: str) -> SourceRunResult:
    try:
        result = run_aether(source)
    except AETHER_ERRORS as exc:
        return SourceRunResult(runtime=AETHER_RUNTIME, success=False, error=format_aether_error(exc))
    return SourceRunResult(runtime=AETHER_RUNTIME, success=True, output=result.output)


def _run_mathlab_source(source: str, *, math_runtime: MathRuntime | None = None) -> SourceRunResult:
    runtime = math_runtime or MathRuntime()
    output_parts: list[str] = []
    try:
        statements = split_code_statements_with_lines(source)
        runtime.reset_environment()
        for statement in statements:
            events = capture_to_events(runtime.execute_console_line(statement.text))
            for event in events:
                if event.text:
                    output_parts.append(event.text.rstrip("\n") + "\n")
            if any(event.kind == "error" for event in events):
                return SourceRunResult(
                    runtime=MATHLAB_RUNTIME,
                    success=False,
                    output="".join(output_parts),
                    error="MathLab Legacy execution stopped due to an error.",
                )
    except Exception as exc:  # pragma: no cover - defensive legacy adapter
        return SourceRunResult(runtime=MATHLAB_RUNTIME, success=False, error=f"{type(exc).__name__}: {exc}")
    return SourceRunResult(runtime=MATHLAB_RUNTIME, success=True, output="".join(output_parts))


def _suffix_for_path(path: str | Path | None) -> str:
    if path is None:
        return ""
    return Path(str(path)).suffix.lower()


def _display_path(path: str | Path | None) -> str:
    if path is None:
        return "the current file"
    name = Path(str(path)).name
    return name or str(path)

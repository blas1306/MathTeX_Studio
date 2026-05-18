from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from console_engine import ConsoleCapture, ConsoleEvent, MathRuntime, capture_to_events
from repl.aether_repl import AetherReplBackend


class ReplBackend(Protocol):
    def execute_console_line(self, line: str) -> ConsoleCapture:
        ...

    def reset_environment(self) -> None:
        ...

    def workspace_snapshot(self) -> list[dict[str, str]]:
        ...


@dataclass(frozen=True)
class ReplProfile:
    id: str
    title: str
    subtitle: str
    prompt: str
    welcome_text: str
    restart_label: str = "Restart REPL"


AETHER_PROFILE = ReplProfile(
    id="aether",
    title="Aether REPL",
    subtitle="Aether interactive REPL session",
    prompt="aether> ",
    welcome_text=(
        "Welcome to Aether Studio\n"
        "Aether interactive REPL session ready.\n"
        "Use print(...) or println(...) for output. Ctrl+L clears the transcript."
    ),
)

MATHLAB_PROFILE = ReplProfile(
    id="mathlab",
    title="MathLab Legacy Console",
    subtitle="Interactive MathLab Legacy console session",
    prompt="mathlab> ",
    welcome_text=(
        "Welcome to Aether Studio\n"
        "MathLab Legacy console ready for .mtx files.\n"
        "Enter runs the current command. Use Up/Down for history and Ctrl+L to clear."
    ),
)


class ReplController:
    def __init__(self, backend: ReplBackend, profile: ReplProfile) -> None:
        self.backend = backend
        self.profile = profile
        self.prompt = profile.prompt
        self.history: list[str] = []
        self.history_index: int | None = None
        self._draft_buffer: str = ""

    def execute_line(self, line: str) -> list[ConsoleEvent]:
        stripped = line.strip()
        if not stripped:
            return []

        self.history.append(stripped)
        self.history_index = None
        self._draft_buffer = ""

        events: list[ConsoleEvent] = []
        for statement in self._split_input(stripped):
            events.extend(capture_to_events(self.backend.execute_console_line(statement)))
        return events

    def clear_console(self) -> list[ConsoleEvent]:
        return [ConsoleEvent(kind="clear", text="")]

    def reset_environment(self) -> list[ConsoleEvent]:
        self.backend.reset_environment()
        self.history_index = None
        self._draft_buffer = ""
        return [ConsoleEvent(kind="status", text=f"{self.profile.title} restarted")]

    def workspace_snapshot(self) -> list[dict[str, str]]:
        return self.backend.workspace_snapshot()

    def history_prev(self, current_buffer: str) -> str:
        if not self.history:
            return current_buffer
        if self.history_index is None:
            self._draft_buffer = current_buffer
            self.history_index = len(self.history) - 1
        else:
            self.history_index = max(0, self.history_index - 1)
        return self.history[self.history_index]

    def history_next(self) -> str:
        if self.history_index is None:
            return self._draft_buffer
        next_index = self.history_index + 1
        if next_index >= len(self.history):
            self.history_index = None
            draft = self._draft_buffer
            self._draft_buffer = ""
            return draft
        self.history_index = next_index
        return self.history[self.history_index]

    def _split_input(self, text: str) -> list[str]:
        splitter = getattr(self.backend, "split_console_input", None)
        if callable(splitter):
            try:
                statements = splitter(text)
            except Exception:
                return [text]
            return [statement.strip() for statement in statements if statement.strip()]
        return [text]


class MathLabReplBackend:
    def __init__(self, runtime: MathRuntime) -> None:
        self.runtime = runtime

    def split_console_input(self, text: str) -> list[str]:
        return self.runtime.split_console_input(text)

    def execute_console_line(self, line: str) -> ConsoleCapture:
        return self.runtime.execute_console_line(line)

    def reset_environment(self) -> None:
        self.runtime.reset_environment()

    def workspace_snapshot(self) -> list[dict[str, str]]:
        return self.runtime.workspace_snapshot()


def create_aether_repl() -> ReplController:
    return ReplController(AetherReplBackend(), AETHER_PROFILE)


def create_mathlab_repl(runtime: MathRuntime | None = None) -> ReplController:
    return ReplController(MathLabReplBackend(runtime or MathRuntime()), MATHLAB_PROFILE)

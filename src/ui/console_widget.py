from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore

from console_engine import ConsoleEngine, ConsoleEvent

CONSOLE_OUTPUT_BG = "#1e1e1e"
CONSOLE_PANEL_TEXT = "#d4d4d4"
CONSOLE_BORDER = "#3c3c3c"
CONSOLE_ERROR = "#ff8f8f"
CONSOLE_WARNING = "#ffd27a"
CONSOLE_PROMPT = "#9cdcfe"
CONSOLE_STATUS = "#a9b3bd"


class ConsoleInput(QtWidgets.QLineEdit):  # type: ignore[misc]
    def __init__(self, engine: ConsoleEngine, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.setClearButtonEnabled(True)
        self.setPlaceholderText("Enter a MathLab command")
        self.setStyleSheet(
            f"""
            QLineEdit {{
                background: {CONSOLE_OUTPUT_BG};
                color: {CONSOLE_PANEL_TEXT};
                font-family: Consolas;
                font-size: 11pt;
                border: 1px solid {CONSOLE_BORDER};
                border-radius: 4px;
                padding: 6px 8px;
            }}
        """
        )

    def keyPressEvent(self, event):  # noqa: N802 - Qt API
        if event.key() == QtCore.Qt.Key.Key_Up:
            self.setText(self.engine.history_prev(self.text()))
            self.setCursorPosition(len(self.text()))
            event.accept()
            return
        if event.key() == QtCore.Qt.Key.Key_Down:
            self.setText(self.engine.history_next())
            self.setCursorPosition(len(self.text()))
            event.accept()
            return
        super().keyPressEvent(event)


class ConsoleWidget(QtWidgets.QWidget):  # type: ignore[misc]
    executed = QtCore.Signal()
    command_started = QtCore.Signal(str)
    command_finished = QtCore.Signal(bool)

    def __init__(
        self,
        engine: ConsoleEngine,
        parent=None,
        *,
        welcome_text: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.engine = engine
        self._welcome_text = welcome_text or "Welcome to MathTeX Studio\nType commands below or build a script in MathLab."

        self.output = QtWidgets.QPlainTextEdit(self)
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(160)
        self.output.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background: {CONSOLE_OUTPUT_BG};
                color: {CONSOLE_PANEL_TEXT};
                font-family: Consolas;
                font-size: 11pt;
                border: 1px solid {CONSOLE_BORDER};
                border-radius: 4px;
                padding: 6px;
            }}
        """
        )

        self.input = ConsoleInput(engine, self)
        self.send_btn = QtWidgets.QPushButton("Send", self)
        self.clear_btn = QtWidgets.QPushButton("Clear", self)
        self.send_btn.setObjectName("mathLabConsoleButton")
        self.clear_btn.setObjectName("mathLabConsoleButton")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.output, 1)
        layout.addWidget(self.input)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.send_btn)
        buttons.addWidget(self.clear_btn)
        layout.addLayout(buttons)

        self.input.returnPressed.connect(self._submit)
        self.send_btn.clicked.connect(self._submit)
        self.clear_btn.clicked.connect(self.clear)

        self.clear()

    def clear(self) -> None:
        self.output.setPlainText("")
        if self._welcome_text:
            self._append_raw(self._welcome_text, ensure_newline=True, kind="status")
        self._ensure_prompt()

    def append_output(self, text: str, ensure_newline: bool = True, *, kind: str = "stdout") -> None:
        if not text:
            return
        self._remove_trailing_prompt()
        self._append_raw(text, ensure_newline=ensure_newline, kind=kind)
        self._ensure_prompt()

    def render_events(self, events: list[ConsoleEvent]) -> None:
        for event in events:
            if event.kind == "clear":
                self.clear()
                continue
            if event.kind == "error":
                self.append_output(f"[Error] {event.text}", kind="error")
                continue
            if event.kind == "warning":
                self.append_output(f"[Warning] {event.text}", kind="warning")
                continue
            self.append_output(event.text, kind=event.kind)
        self._ensure_prompt()

    def submit_current_input(self) -> None:
        self._submit()

    def _submit(self) -> None:
        line = self.input.text()
        if not line.strip():
            self.input.clear()
            self.input.setFocus()
            return
        self.command_started.emit(line)
        self._append_prompt_line(line)
        self.input.clear()
        events = self.engine.execute_line(line)
        self.render_events(events)
        self.command_finished.emit(not any(event.kind == "error" for event in events))
        self.executed.emit()
        self.input.setFocus()

    def _append_prompt_line(self, line: str) -> None:
        self._remove_trailing_prompt()
        self._append_raw(f"{self.engine.prompt}{line}", ensure_newline=True, kind="prompt")

    def _ensure_prompt(self) -> None:
        if self.output.toPlainText().endswith(self.engine.prompt):
            return
        self._remove_trailing_prompt()
        self._append_raw(self.engine.prompt, ensure_newline=False, kind="prompt")

    def _remove_trailing_prompt(self) -> None:
        text = self.output.toPlainText()
        if not text.endswith(self.engine.prompt):
            return
        cursor = self.output.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        cursor.movePosition(
            QtGui.QTextCursor.MoveOperation.PreviousCharacter,
            QtGui.QTextCursor.MoveMode.KeepAnchor,
            len(self.engine.prompt),
        )
        cursor.removeSelectedText()
        self.output.setTextCursor(cursor)

    def _append_raw(self, text: str, *, ensure_newline: bool, kind: str) -> None:
        cursor = self.output.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        existing = self.output.toPlainText()
        if existing and not existing.endswith("\n"):
            cursor.insertText("\n", self._format_for_kind("stdout"))
        cursor.insertText(text, self._format_for_kind(kind))
        if ensure_newline and not text.endswith("\n"):
            cursor.insertText("\n", self._format_for_kind(kind))
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def _format_for_kind(self, kind: str) -> QtGui.QTextCharFormat:
        color = {
            "error": CONSOLE_ERROR,
            "warning": CONSOLE_WARNING,
            "prompt": CONSOLE_PROMPT,
            "status": CONSOLE_STATUS,
        }.get(kind, CONSOLE_PANEL_TEXT)
        fmt = QtGui.QTextCharFormat()
        fmt.setForeground(QtGui.QColor(color))
        return fmt

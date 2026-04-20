from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore

from console_engine import ConsoleEngine, ConsoleEvent


class ConsoleInput(QtWidgets.QLineEdit):  # type: ignore[misc]
    def __init__(self, engine: ConsoleEngine, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.setClearButtonEnabled(True)
        self.setPlaceholderText("Enter a MathLab command")
        self.setStyleSheet(
            """
            QLineEdit {
                background: #1b1b1d;
                color: #f4f4f4;
                font-family: Consolas;
                font-size: 11pt;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 6px 8px;
            }
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
            """
            QPlainTextEdit {
                background: #1b1b1d;
                color: #f4f4f4;
                font-family: Consolas;
                font-size: 11pt;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 4px;
            }
        """
        )

        self.input = ConsoleInput(engine, self)
        self.send_btn = QtWidgets.QPushButton("Send", self)
        self.clear_btn = QtWidgets.QPushButton("Clear", self)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
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
            self._append_raw(self._welcome_text, ensure_newline=True)
        self._ensure_prompt()

    def append_output(self, text: str, ensure_newline: bool = True) -> None:
        if not text:
            return
        self._remove_trailing_prompt()
        self._append_raw(text, ensure_newline=ensure_newline)
        self._ensure_prompt()

    def render_events(self, events: list[ConsoleEvent]) -> None:
        for event in events:
            if event.kind == "clear":
                self.clear()
                continue
            if event.kind == "error":
                self.append_output(f"[Error] {event.text}")
                continue
            if event.kind == "warning":
                self.append_output(f"[Warning] {event.text}")
                continue
            self.append_output(event.text)
        self._ensure_prompt()

    def submit_current_input(self) -> None:
        self._submit()

    def _submit(self) -> None:
        line = self.input.text()
        if not line.strip():
            self.input.clear()
            self.input.setFocus()
            return
        self._append_prompt_line(line)
        self.input.clear()
        events = self.engine.execute_line(line)
        self.render_events(events)
        self.executed.emit()
        self.input.setFocus()

    def _append_prompt_line(self, line: str) -> None:
        self._remove_trailing_prompt()
        self._append_raw(f"{self.engine.prompt}{line}", ensure_newline=True)

    def _ensure_prompt(self) -> None:
        if self.output.toPlainText().endswith(self.engine.prompt):
            return
        self._remove_trailing_prompt()
        self._append_raw(self.engine.prompt, ensure_newline=False)

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

    def _append_raw(self, text: str, *, ensure_newline: bool) -> None:
        cursor = self.output.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        existing = self.output.toPlainText()
        if existing and not existing.endswith("\n"):
            cursor.insertText("\n")
        cursor.insertText(text)
        if ensure_newline and not text.endswith("\n"):
            cursor.insertText("\n")
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

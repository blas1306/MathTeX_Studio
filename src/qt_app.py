
from __future__ import annotations

import io
import re
import shutil
import sys
import tempfile
import os
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from auto_compile import AutoCompileController, CompileTrigger
from app_preferences import AppPreferences, AppPreferencesStore
from autocomplete_engine import AutocompleteMatch, AutocompleteRequest, build_autocomplete_suggestions, detect_autocomplete_match
from command_catalog import CommandSuggestion
from diagnostics import diagnostic_line_offset
from editor_pdf_sync import EditorPdfSyncMap
from latex_lang import (
    env_ast,
    ejecutar_linea,
    register_console_clear_listener,
    register_plot_listener,
    reset_environment,
    set_plot_mode,
    unregister_console_clear_listener,
    unregister_plot_listener,
    change_working_dir,
    get_working_dir,
    workspace_snapshot,
)
from mtex_executor import (
    ejecutar_mtex,
    explain_latex_build_failure,
    split_code_statements,
    split_code_statements_with_lines,
    summarize_latex_build_failure,
)
from execution_results import StructuredLogCollector, variable_summaries_from_snapshot, ExecutionResult
from logs_output_widget import LogsOutputWidget
from pdf_preview import PdfPreviewWidget
from project_outputs import ProjectOutputManager
from project_system import ProjectInfo, ProjectManager, ProjectRegistry, default_projects_root
from project_widgets import ProjectCreationDialog, ProjectHomeWidget, ProjectWorkspaceWidget

try:  # pragma: no cover - depende de la instalacion del usuario
    from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore
except Exception as exc:  # pragma: no cover - no hay Qt disponible
    raise ImportError("PySide6 no esta disponible") from exc

EDITOR_KEYWORDS = (
    "for",
    "if",
    "elif",
    "else",
    "and",
    "or",
    "while",
    "function",
    "return",
    "repeat",
    "until",
    "end",
    "plot",
    "sum",
    "product",
)
KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(word) for word in EDITOR_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
LOGICAL_OPERATOR_PATTERN = re.compile(r"&&|\|\|")
COMMENT_PATTERN = re.compile(r"(?<!\\)%.*|#.*")
STRING_PATTERN = re.compile(r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')")
NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")
PUNCT_PATTERN = re.compile(r"[=+\-*/%^<>{}\[\](),.;:|]")
INDENTATION = " " * 4
EDITOR_BG = "#353535"
TEXT_FG = "#ffffff"
STRING_COLOR = "#f7dc6f"
NUMBER_COLOR = "#45b39d"
PUNCT_COLOR = "#000000"
SELECT_BG = "rgba(255, 159, 59, 110)"  # tono calido con algo de transparencia
FUNC_COLOR = "#3d5afe"
IMPORT_KEYWORD_COLOR = "#cc7832"
IMPORT_MODULE_COLOR = "#ce9178"
IMPORT_NAME_COLOR = "#9cdcfe"
FUNCTION_PATTERN = re.compile(r"\\[A-Za-z][A-Za-z0-9_]*")
FROM_IMPORT_PATTERN = re.compile(
    r"\bfrom\b\s+(?P<module>[A-Za-z_][\w]*)\s+(?:\bimport\b(?:\s+(?P<names>[A-Za-z0-9_,\s]*))?)?"
)
CODE_BLOCK_MARKER_PATTERN = re.compile(r"\\begin\{code\}|\\end\{code\}|\\codeblock|\\endcodeblock")

QT_AVAILABLE = True
AUTO_COMPILE_DEBOUNCE_MS = 900
EDITOR_PDF_SYNC_DEBOUNCE_MS = 350
INTERACTIVE_MENU_CONTEXT = "interactive"
STUDIO_MENU_CONTEXT = "studio"
SNIPPET_CURSOR_MARKER = "<|cursor|>"


class MathSyntaxHighlighter(QtGui.QSyntaxHighlighter):  # type: ignore[misc]
    _STATE_TEXT = 0
    _STATE_CODE = 1

    def __init__(self, document):
        super().__init__(document)
        assert QtGui is not None
        self._document_kind = "script"
        self._formats = {
            "keyword": self._make_format(QtGui.QColor("#a30101")),
            "comment": self._make_format(QtGui.QColor("#00aa00")),
            "string": self._make_format(QtGui.QColor(STRING_COLOR)),
            "number": self._make_format(QtGui.QColor(NUMBER_COLOR)),
            "punct": self._make_format(QtGui.QColor(PUNCT_COLOR)),
            "func": self._make_format(QtGui.QColor(FUNC_COLOR)),
            "import_kw": self._make_format(QtGui.QColor(IMPORT_KEYWORD_COLOR)),
            "import_mod": self._make_format(QtGui.QColor(IMPORT_MODULE_COLOR)),
            "import_name": self._make_format(QtGui.QColor(IMPORT_NAME_COLOR)),
        }
    def _make_format(self, color: QtGui.QColor) -> QtGui.QTextCharFormat:
        assert QtGui is not None
        fmt = QtGui.QTextCharFormat()
        fmt.setForeground(color)
        return fmt

    def set_document_kind(self, document_kind: str) -> None:
        normalized = "mtex_document" if document_kind == "mtex_document" else "script"
        if self._document_kind == normalized:
            return
        self._document_kind = normalized
        self.rehighlight()

    def _keyword_spans(self, text: str) -> list[tuple[int, int]]:
        if self._document_kind != "mtex_document":
            self.setCurrentBlockState(self._STATE_TEXT)
            return [(0, len(text))]

        spans: list[tuple[int, int]] = []
        in_code = self.previousBlockState() == self._STATE_CODE
        segment_start = 0

        for match in CODE_BLOCK_MARKER_PATTERN.finditer(text):
            marker = match.group(0)
            opens_code = marker in {r"\begin{code}", r"\codeblock"}
            if in_code and match.start() > segment_start:
                spans.append((segment_start, match.start()))
            if opens_code:
                in_code = True
                segment_start = match.end()
            else:
                in_code = False
                segment_start = match.end()

        if in_code and segment_start < len(text):
            spans.append((segment_start, len(text)))

        self.setCurrentBlockState(self._STATE_CODE if in_code else self._STATE_TEXT)
        return spans

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - API Qt
        for match in STRING_PATTERN.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self._formats["string"])
        for match in COMMENT_PATTERN.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self._formats["comment"])
        keyword_spans = self._keyword_spans(text)
        skip = []
        for match in STRING_PATTERN.finditer(text):
            skip.append((match.start(), match.end()))
        for match in COMMENT_PATTERN.finditer(text):
            skip.append((match.start(), match.end()))

        def _skipped(pos: int) -> bool:
            return any(a <= pos < b for a, b in skip)

        def _in_keyword_span(pos: int) -> bool:
            return any(start <= pos < end for start, end in keyword_spans)

        for match in KEYWORD_PATTERN.finditer(text):
            if _skipped(match.start()) or not _in_keyword_span(match.start()):
                continue
            self.setFormat(match.start(), match.end() - match.start(), self._formats["keyword"])
        for match in FROM_IMPORT_PATTERN.finditer(text):
            if _skipped(match.start()) or not _in_keyword_span(match.start()):
                continue
            from_start = match.start()
            self.setFormat(from_start, 4, self._formats["import_kw"])
            import_pos = text.rfind("import", match.start(), match.end())
            if import_pos != -1:
                self.setFormat(import_pos, 6, self._formats["import_kw"])
            mod_start, mod_end = match.span("module")
            self.setFormat(mod_start, mod_end - mod_start, self._formats["import_mod"])
            names_segment = match.group("names") or ""
            names_base = match.start("names") if match.start("names") != -1 else match.end()
            search_pos = 0
            for name in [n.strip() for n in names_segment.split(",") if n.strip()]:
                idx = names_segment.find(name, search_pos)
                if idx == -1:
                    continue
                name_start = names_base + idx
                if _skipped(name_start):
                    continue
                self.setFormat(name_start, len(name), self._formats["import_name"])
                search_pos = idx + len(name)
        for match in FUNCTION_PATTERN.finditer(text):
            if _skipped(match.start()):
                continue
            self.setFormat(match.start(), match.end() - match.start(), self._formats["func"])
        for match in NUMBER_PATTERN.finditer(text):
            if _skipped(match.start()):
                continue
            self.setFormat(match.start(), match.end() - match.start(), self._formats["number"])
        for match in PUNCT_PATTERN.finditer(text):
            if _skipped(match.start()):
                continue
            self.setFormat(match.start(), match.end() - match.start(), self._formats["punct"])
        for match in LOGICAL_OPERATOR_PATTERN.finditer(text):
            if _skipped(match.start()) or not _in_keyword_span(match.start()):
                continue
            self.setFormat(match.start(), match.end() - match.start(), self._formats["keyword"])


class LineNumberArea(QtWidgets.QWidget):  # type: ignore[misc]
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QtCore.QSize:  # noqa: D401
        return QtCore.QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):  # noqa: D401
        self._editor.line_number_area_paint_event(event)


@dataclass(frozen=True)
class EditorAutocompleteContext:
    block_position: int
    token: AutocompleteMatch


class QtAutocompletePopup(QtWidgets.QFrame):  # type: ignore[misc]
    def __init__(self, parent, *, on_accept) -> None:
        super().__init__(parent, QtCore.Qt.WindowType.Tool | QtCore.Qt.WindowType.FramelessWindowHint)
        self._on_accept = on_accept
        self._suggestions: list[CommandSuggestion] = []
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Plain)
        self.setStyleSheet(
            """
            QFrame {
                background: #2c2f33;
                border: 1px solid #5a6472;
                border-radius: 4px;
            }
            QListWidget {
                background: transparent;
                border: none;
                color: #f4f4f4;
                font-family: Consolas;
                font-size: 10pt;
                outline: none;
            }
            QListWidget::item {
                padding: 4px 8px;
            }
            QListWidget::item:selected {
                background: #5a6472;
                color: #ffffff;
            }
        """
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._list = QtWidgets.QListWidget(self)
        self._list.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setMouseTracking(True)
        self._list.itemClicked.connect(lambda _item: self.accept_current())
        self._list.itemDoubleClicked.connect(lambda _item: self.accept_current())
        layout.addWidget(self._list)

    def is_visible(self) -> bool:
        return self.isVisible()

    def show_suggestions(self, editor: "CodeEditor", suggestions: list[CommandSuggestion]) -> None:
        self._suggestions = list(suggestions)
        if not self._suggestions:
            self.hide_popup()
            return

        self._list.clear()
        for suggestion in self._suggestions:
            label = suggestion.label or suggestion.name
            item = QtWidgets.QListWidgetItem(f"{label}  {suggestion.description}")
            tooltip_lines = [label]
            if suggestion.signature and suggestion.signature != label:
                tooltip_lines.append(suggestion.signature)
            if suggestion.category:
                tooltip_lines.append(f"Category: {suggestion.category}")
            if suggestion.description:
                tooltip_lines.append(suggestion.description)
            item.setToolTip("\n".join(tooltip_lines))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, suggestion)
            self._list.addItem(item)

        self._list.setCurrentRow(0)
        self._position_for_editor(editor)
        self.show()
        self.raise_()

    def hide_popup(self) -> None:
        self._suggestions = []
        self.hide()

    def move_selection(self, delta: int) -> bool:
        if not self.isVisible() or not self._suggestions:
            return False
        current_row = max(0, self._list.currentRow())
        next_row = max(0, min(self._list.count() - 1, current_row + delta))
        self._list.setCurrentRow(next_row)
        item = self._list.item(next_row)
        if item is not None:
            self._list.scrollToItem(item)
        return True

    def current_suggestion(self) -> CommandSuggestion | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(QtCore.Qt.ItemDataRole.UserRole)

    def accept_current(self) -> bool:
        suggestion = self.current_suggestion()
        if suggestion is None:
            return False
        self._on_accept(suggestion)
        return True

    def reposition(self, editor: "CodeEditor") -> None:
        if self.isVisible():
            self._position_for_editor(editor)

    def _position_for_editor(self, editor: "CodeEditor") -> None:
        row_height = max(22, self._list.sizeHintForRow(0))
        visible_rows = min(max(1, self._list.count()), 8)
        frame = self.frameWidth() * 2
        scrollbar_width = self._list.verticalScrollBar().sizeHint().width()
        width = min(560, max(280, int(editor.viewport().width() * 0.55)))
        needs_scroll = self._list.count() > visible_rows
        height = row_height * visible_rows + frame + 4
        if needs_scroll:
            width += scrollbar_width
        self.resize(width, height)

        rect = editor.cursorRect()
        global_pos = editor.viewport().mapToGlobal(rect.bottomLeft())
        pos = QtCore.QPoint(global_pos.x(), global_pos.y() + 4)

        screen = editor.windowHandle().screen() if editor.windowHandle() else QtGui.QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            if pos.x() + self.width() > available.right():
                pos.setX(max(available.left(), available.right() - self.width()))
            if pos.y() + self.height() > available.bottom():
                pos.setY(max(available.top(), global_pos.y() - self.height() - rect.height()))

        self.move(pos)


class CodeEditor(QtWidgets.QPlainTextEdit):  # type: ignore[misc]
    def __init__(self, parent=None, *, enable_autocomplete: bool = False) -> None:
        super().__init__(parent)
        self._autocomplete_enabled = enable_autocomplete
        self._autocomplete_popup = QtAutocompletePopup(self, on_accept=self._accept_autocomplete_suggestion) if enable_autocomplete else None
        self._autocomplete_suspended = False
        self._autocomplete_document_kind = "script"
        self._autocomplete_workspace_provider: Callable[[], list[dict[str, str]]] | None = None
        self._autocomplete_ignored_cursor_hides = 0
        self.setTabChangesFocus(False)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QtGui.QFont("Consolas", 11))
        palette = self.palette()
        palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(EDITOR_BG))
        palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(TEXT_FG))
        self.setPalette(palette)
        self.setStyleSheet(
            f"""
            QPlainTextEdit {{
                selection-background-color: {SELECT_BG};
                selection-color: {TEXT_FG};
            }}
        """
        )
        self.highlighter = MathSyntaxHighlighter(self.document())
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        if self._autocomplete_enabled:
            self.textChanged.connect(self._on_text_autocomplete_trigger)
            self.cursorPositionChanged.connect(self._on_cursor_autocomplete_trigger)
            self.updateRequest.connect(lambda _rect, _dy: self._reposition_autocomplete())
            self.verticalScrollBar().valueChanged.connect(lambda _value: self._reposition_autocomplete())
            self.horizontalScrollBar().valueChanged.connect(lambda _value: self._reposition_autocomplete())
        self.update_line_number_area_width(0)
        self.highlight_current_line()

    def line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        space = 10 + self.fontMetrics().horizontalAdvance("9") * digits
        return space

    def update_line_number_area_width(self, _new_block_count: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect: QtCore.QRect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QtCore.QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))
        self._reposition_autocomplete()

    def line_number_area_paint_event(self, event) -> None:
        painter = QtGui.QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QtGui.QColor(EDITOR_BG))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(QtGui.QColor("#b0b0b0"))
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 6,
                    self.fontMetrics().height(),
                    QtCore.Qt.AlignmentFlag.AlignRight,
                    number,
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self) -> None:
        if self.isReadOnly():
            return
        selection = QtWidgets.QTextEdit.ExtraSelection()
        line_color = QtGui.QColor("#404040")
        line_color.setAlpha(80)
        selection.format.setBackground(line_color)  # type: ignore[attr-defined]
        selection.format.setProperty(QtGui.QTextFormat.Property.FullWidthSelection, True)  # type: ignore[attr-defined]
        selection.cursor = self.textCursor()  # type: ignore[attr-defined]
        selection.cursor.clearSelection()  # type: ignore[attr-defined]
        self.setExtraSelections([selection])

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        modifiers = event.modifiers()
        if self._autocomplete_enabled and self._key_event_may_edit_text(event):
            self._autocomplete_ignored_cursor_hides = max(self._autocomplete_ignored_cursor_hides, 2)
        if (
            self._autocomplete_enabled
            and key == QtCore.Qt.Key.Key_Space
            and modifiers & QtCore.Qt.KeyboardModifier.ControlModifier
        ):
            self._show_autocomplete_manually()
            return
        if self._autocomplete_enabled and self._handle_autocomplete_key(event):
            return
        if key in (QtCore.Qt.Key.Key_Tab, QtCore.Qt.Key.Key_Backtab):
            if key == QtCore.Qt.Key.Key_Tab and modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier:
                self._unindent_selection()
                return
            if key == QtCore.Qt.Key.Key_Backtab:
                self._unindent_selection()
                return
            self._indent_selection()
            return
        if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            self._handle_return()
            self._hide_autocomplete()
            return
        if key == QtCore.Qt.Key.Key_Backspace:
            cursor = self.textCursor()
            if cursor.hasSelection():
                super().keyPressEvent(event)
                return
            if self._backspace_indentation(cursor):
                return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        self._on_cursor_autocomplete_trigger()

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self._hide_autocomplete()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._hide_autocomplete()
        super().hideEvent(event)

    def _backspace_indentation(self, cursor: QtGui.QTextCursor) -> bool:
        position_in_block = cursor.positionInBlock()
        block_text = cursor.block().text()
        if position_in_block == 0:
            return False
        if block_text[:position_in_block].endswith(INDENTATION):
            cursor.beginEditBlock()
            for _ in range(len(INDENTATION)):
                cursor.deletePreviousChar()
            cursor.endEditBlock()
            return True
        return False

    def _handle_return(self) -> None:
        cursor = self.textCursor()
        block_text = cursor.block().text()
        position_in_block = cursor.positionInBlock()
        leading_spaces = len(block_text) - len(block_text.lstrip(" "))
        current_indent = block_text[:leading_spaces]
        opens_block = self._line_opens_block(block_text)
        block_keyword = re.match(r"\s*(for|while|if|function|repeat)\b", block_text, re.IGNORECASE)
        at_line_end = position_in_block == len(block_text)
        should_expand_block = bool(opens_block and block_keyword and at_line_end)
        cursor.beginEditBlock()
        if should_expand_block:
            cursor.insertText(f"\n{current_indent}{INDENTATION}\n{current_indent}end")
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.PreviousBlock)
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.EndOfBlock)
        else:
            extra = INDENTATION if opens_block and at_line_end else ""
            cursor.insertText(f"\n{current_indent}{extra}")
        cursor.endEditBlock()
        if should_expand_block:
            self.setTextCursor(cursor)

    def _indent_selection(self) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            start = min(cursor.selectionStart(), cursor.selectionEnd())
            end = max(cursor.selectionStart(), cursor.selectionEnd())
            cursor.beginEditBlock()
            cursor.setPosition(start)
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.StartOfBlock)
            while cursor.position() <= end:
                cursor.insertText(INDENTATION)
                end += len(INDENTATION)
                if not cursor.movePosition(QtGui.QTextCursor.MoveOperation.NextBlock):
                    break
            cursor.endEditBlock()
        else:
            cursor.insertText(INDENTATION)

    def _unindent_selection(self) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            start = min(cursor.selectionStart(), cursor.selectionEnd())
            end = max(cursor.selectionStart(), cursor.selectionEnd())
            cursor.beginEditBlock()
            cursor.setPosition(start)
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.StartOfBlock)
            while cursor.position() <= end:
                block_text = cursor.block().text()
                if block_text.startswith(" "):
                    remove = min(len(block_text) - len(block_text.lstrip(" ")), len(INDENTATION))
                    for _ in range(remove):
                        cursor.deleteChar()
                    end -= remove
                if not cursor.movePosition(QtGui.QTextCursor.MoveOperation.NextBlock):
                    break
            cursor.endEditBlock()
        else:
            block_text = cursor.block().text()
            remove = min(len(block_text) - len(block_text.lstrip(" ")), len(INDENTATION))
            if remove:
                cursor.beginEditBlock()
                for _ in range(remove):
                    cursor.deletePreviousChar()
                cursor.endEditBlock()

    def _line_opens_block(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if stripped.endswith(":"):
            return True
        lowered = stripped.lower()
        starters = ("for", "if", "elif", "else", "while", "function", "repeat", "until")
        return any(lowered.startswith(f"{w} ") or lowered == w for w in starters)

    def _handle_autocomplete_key(self, event) -> bool:
        popup = self._autocomplete_popup
        if popup is None or not popup.is_visible():
            return False

        key = event.key()
        modifiers = event.modifiers()
        blocked_modifiers = (
            QtCore.Qt.KeyboardModifier.ControlModifier
            | QtCore.Qt.KeyboardModifier.AltModifier
            | QtCore.Qt.KeyboardModifier.MetaModifier
        )
        if modifiers & blocked_modifiers:
            return False

        if key == QtCore.Qt.Key.Key_Up:
            popup.move_selection(-1)
            return True
        if key == QtCore.Qt.Key.Key_Down:
            popup.move_selection(1)
            return True
        if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            suggestion = popup.current_suggestion()
            if suggestion is None:
                return False
            self._accept_autocomplete_and_maybe_expand_block(suggestion)
            return True
        if key == QtCore.Qt.Key.Key_Escape:
            self._hide_autocomplete()
            return True
        return False

    def _key_event_may_edit_text(self, event) -> bool:
        key = event.key()
        modifiers = event.modifiers()
        blocked_modifiers = (
            QtCore.Qt.KeyboardModifier.ControlModifier
            | QtCore.Qt.KeyboardModifier.AltModifier
            | QtCore.Qt.KeyboardModifier.MetaModifier
        )
        if modifiers & blocked_modifiers:
            return False
        if key in (
            QtCore.Qt.Key.Key_Backspace,
            QtCore.Qt.Key.Key_Delete,
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.Key.Key_Enter,
            QtCore.Qt.Key.Key_Tab,
            QtCore.Qt.Key.Key_Backtab,
        ):
            return True
        return bool(event.text())

    def _on_cursor_autocomplete_trigger(self) -> None:
        if not self._autocomplete_enabled or self._autocomplete_suspended:
            return
        if self._autocomplete_ignored_cursor_hides > 0:
            self._autocomplete_ignored_cursor_hides -= 1
            return
        if self._autocomplete_popup is not None and self._autocomplete_popup.is_visible():
            self._hide_autocomplete()

    def _on_text_autocomplete_trigger(self) -> None:
        self._refresh_autocomplete(trigger="text")

    def _show_autocomplete_manually(self) -> None:
        self._refresh_autocomplete(trigger="manual")

    def _refresh_autocomplete(self, trigger: str = "text") -> None:
        if not self._autocomplete_enabled or self._autocomplete_suspended:
            return
        popup = self._autocomplete_popup
        if popup is None:
            return

        if trigger == "cursor" and not popup.is_visible():
            return

        context = self._current_autocomplete_context()
        if context is None:
            self._hide_autocomplete()
            return

        cursor = self.textCursor()
        workspace_items = self._autocomplete_workspace_provider() if self._autocomplete_workspace_provider else []
        suggestions = build_autocomplete_suggestions(
            AutocompleteRequest(
                line_text=cursor.block().text(),
                cursor_col=cursor.positionInBlock(),
                document_kind=self._autocomplete_document_kind,
                document_text=self.toPlainText()[: cursor.position()],
                workspace_items=workspace_items,
            )
        )
        if not suggestions:
            self._hide_autocomplete()
            return

        popup.show_suggestions(self, suggestions)

    def set_autocomplete_document_kind(self, document_kind: str) -> None:
        self._autocomplete_document_kind = document_kind
        self.highlighter.set_document_kind(document_kind)

    def set_autocomplete_workspace_provider(
        self,
        provider: Callable[[], list[dict[str, str]]] | None,
    ) -> None:
        self._autocomplete_workspace_provider = provider

    def _reposition_autocomplete(self) -> None:
        popup = self._autocomplete_popup
        if popup is not None and popup.is_visible():
            popup.reposition(self)

    def _hide_autocomplete(self) -> None:
        popup = self._autocomplete_popup
        if popup is not None:
            popup.hide_popup()

    def _current_autocomplete_context(self) -> EditorAutocompleteContext | None:
        cursor = self.textCursor()
        block = cursor.block()
        if not block.isValid():
            return None

        token = detect_autocomplete_match(block.text(), cursor.positionInBlock())
        if token is None:
            return None

        return EditorAutocompleteContext(
            block_position=block.position(),
            token=token,
        )

    def _accept_autocomplete_suggestion(self, suggestion: CommandSuggestion) -> None:
        context = self._current_autocomplete_context()
        if context is None:
            self._hide_autocomplete()
            return

        cursor = self.textCursor()
        start = context.block_position + context.token.token_start_col
        end = context.block_position + context.token.token_end_col
        suffix_text = cursor.block().text()[context.token.token_end_col :]
        insert_text = suggestion.insert_text
        cursor_backtrack = suggestion.cursor_backtrack
        if insert_text.endswith("()") and suffix_text.lstrip().startswith("("):
            insert_text = suggestion.name
            cursor_backtrack = None

        self._autocomplete_suspended = True
        try:
            cursor.beginEditBlock()
            cursor.setPosition(start)
            cursor.setPosition(end, QtGui.QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            cursor.insertText(insert_text)
            final_position = start + len(insert_text)
            if cursor_backtrack:
                final_position -= cursor_backtrack
            cursor.setPosition(final_position)
            cursor.endEditBlock()
            self.setTextCursor(cursor)
        finally:
            self._autocomplete_suspended = False
            self._hide_autocomplete()

    def _accept_autocomplete_and_maybe_expand_block(self, suggestion: CommandSuggestion) -> None:
        self._accept_autocomplete_suggestion(suggestion)
        if suggestion.kind != "keyword":
            return
        block_text = self.textCursor().block().text()
        if self._line_opens_block(block_text):
            self._handle_return()


_SubmitSignal = QtCore.Signal  # type: ignore[attr-defined]


class ConsoleEdit(QtWidgets.QTextEdit):  # type: ignore[misc]
    """QTextEdit that allows typing directly in the console and sending with Enter."""

    submitted = _SubmitSignal()
    PROMPT = "MathTeX> "

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setMinimumHeight(160)
        self.setStyleSheet(
            """
            QTextEdit {
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
        self._prompt_pos = 0
        self.clear_console()

    # ----- Prompt helpers -------------------------------------------------
    def ensure_prompt(self) -> None:
        text = self.toPlainText()
        cursor = self.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        if text and not text.endswith("\n") and not text.endswith(self.PROMPT):
            cursor.insertText("\n")
        if not text.endswith(self.PROMPT):
            cursor.insertText(self.PROMPT)
        self._prompt_pos = len(self.toPlainText())
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def remove_prompt(self) -> None:
        text = self.toPlainText()
        if not text.endswith(self.PROMPT):
            return
        cursor = self.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        cursor.movePosition(
            QtGui.QTextCursor.MoveOperation.PreviousCharacter,
            QtGui.QTextCursor.MoveMode.KeepAnchor,
            len(self.PROMPT),
        )
        cursor.removeSelectedText()
        self.setTextCursor(cursor)
        self._prompt_pos = len(self.toPlainText())

    def current_input(self) -> str:
        return self.toPlainText()[self._prompt_pos :]

    def clear_input(self) -> None:
        cursor = self.textCursor()
        cursor.setPosition(self._prompt_pos)
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End, QtGui.QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self.setTextCursor(cursor)

    # ----- Output helpers -------------------------------------------------
    def append_output(self, text: str, ensure_newline: bool = True) -> None:
        if not text:
            return
        self.remove_prompt()
        cursor = self.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        if ensure_newline and not text.endswith("\n"):
            cursor.insertText("\n")
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        self.ensure_prompt()

    def append_image(self, pixmap: QtGui.QPixmap, caption: str) -> None:
        max_width = 640
        if pixmap.width() > max_width:
            pixmap = pixmap.scaledToWidth(max_width, QtCore.Qt.TransformationMode.SmoothTransformation)
        self.remove_prompt()
        cursor = self.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        cursor.insertText(f"\n[Grafico: {caption}]\n")
        cursor.insertImage(pixmap.toImage())
        cursor.insertText("\n")
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        self.ensure_prompt()

    def clear_console(self) -> None:
        self.setPlainText("Welcome to MathTeX\nType commands below or build a script in the top panel.\n")
        self._prompt_pos = len(self.toPlainText())
        self.ensure_prompt()

    # ----- Events ---------------------------------------------------------
    def _is_cursor_before_prompt(self) -> bool:
        return self.textCursor().position() < self._prompt_pos

    def keyPressEvent(self, event):  # noqa: N802 - API Qt
        key = event.key()
        modifiers = event.modifiers()
        is_modifier_only = key in {
            QtCore.Qt.Key.Key_Control,
            QtCore.Qt.Key.Key_Shift,
            QtCore.Qt.Key.Key_Alt,
            QtCore.Qt.Key.Key_Meta,
            QtCore.Qt.Key.Key_AltGr,
        }
        is_copy_shortcut = event.matches(QtGui.QKeySequence.StandardKey.Copy)
        is_cut_shortcut = event.matches(QtGui.QKeySequence.StandardKey.Cut)
        is_select_all_shortcut = event.matches(QtGui.QKeySequence.StandardKey.SelectAll)
        is_undo_shortcut = event.matches(QtGui.QKeySequence.StandardKey.Undo)
        allows_readonly_selection = is_modifier_only or is_copy_shortcut or is_cut_shortcut or is_select_all_shortcut

        if is_undo_shortcut:
            event.accept()
            return

        if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter) and not (
            modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier
        ):
            self.submitted.emit()
            event.accept()
            return

        if key == QtCore.Qt.Key.Key_Home and not allows_readonly_selection:
            cursor = self.textCursor()
            cursor.setPosition(self._prompt_pos)
            self.setTextCursor(cursor)
            event.accept()
            return

        if key == QtCore.Qt.Key.Key_Backspace and self._is_cursor_before_prompt():
            event.ignore()
            return

        if key == QtCore.Qt.Key.Key_Left and self._is_cursor_before_prompt():
            event.ignore()
            return

        cursor = self.textCursor()
        if cursor.hasSelection():
            sel_start = min(cursor.selectionStart(), cursor.selectionEnd())
            if sel_start < self._prompt_pos and not allows_readonly_selection:
                cursor.clearSelection()
                cursor.setPosition(self._prompt_pos)
                self.setTextCursor(cursor)
                event.accept()
                return

        super().keyPressEvent(event)
        if self._is_cursor_before_prompt() and not allows_readonly_selection:
            cursor = self.textCursor()
            cursor.setPosition(self._prompt_pos)
            self.setTextCursor(cursor)


class ConsoleWidget(QtWidgets.QWidget):  # type: ignore[misc]
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.output = ConsoleEdit(self)
        # Compatibility with the rest of the code
        self.input = self.output
        self.send_btn = QtWidgets.QPushButton("Send", self)
        self.clear_btn = QtWidgets.QPushButton("Clear", self)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.send_btn)
        buttons.addWidget(self.clear_btn)
        layout.addWidget(self.output, 1)
        layout.addLayout(buttons)

    def append_output(self, text: str, ensure_newline: bool = True) -> None:
        self.output.append_output(text, ensure_newline=ensure_newline)

    def append_image(self, pixmap: QtGui.QPixmap, caption: str) -> None:
        self.output.append_image(pixmap, caption)

    def clear(self) -> None:
        self.output.clear_console()


class MathTeXQtWindow(QtWidgets.QMainWindow):  # type: ignore[misc]
    def __init__(self) -> None:
        super().__init__()
        set_plot_mode("interactive")
        self.setWindowTitle("MathTeX")
        self.resize(1200, 720)
        self._temp_preview_dir = tempfile.TemporaryDirectory(prefix="mathtex_preview_")
        self._temp_preview_path = Path(self._temp_preview_dir.name)
        self._temp_preview_path.mkdir(parents=True, exist_ok=True)
        self._plot_listener_registered = False
        self._console_clear_listener_registered = False
        self._plot_windows: list[QtWidgets.QMainWindow] = []
        self._untitled_counter = 1
        self.project_manager = ProjectManager()
        self.output_manager = ProjectOutputManager()
        self.project_registry = ProjectRegistry()
        self.preferences_store = AppPreferencesStore()
        self.current_project: ProjectInfo | None = None
        self.latest_mtex_execution_result: ExecutionResult | None = None
        self.project_stack: QtWidgets.QStackedWidget | None = None
        self.project_home_widget: ProjectHomeWidget | None = None
        self.project_workspace_widget: ProjectWorkspaceWidget | None = None
        self.logs_output_widget: LogsOutputWidget | None = None
        self.mtex_file_tree: QtWidgets.QTreeWidget | None = None
        self.mtex_editor: CodeEditor | None = None
        self.mtex_file_label: QtWidgets.QLabel | None = None
        self.auto_compile_checkbox: QtWidgets.QCheckBox | None = None
        self.build_status_label: QtWidgets.QLabel | None = None
        self.preview: PdfPreviewWidget | None = None
        self.current_mtex_path: Path | None = None
        self.script_docs: list[dict] = []
        self.last_generated_pdf: Path | None = None
        self._preview_message = "Compile an .mtex file to preview it."
        self.auto_compile_controller = AutoCompileController(enabled=False)
        self._ignore_mtex_text_changes = False
        self._auto_compile_timer = QtCore.QTimer(self)
        self._auto_compile_timer.setSingleShot(True)
        self._auto_compile_timer.setInterval(AUTO_COMPILE_DEBOUNCE_MS)
        self._auto_compile_timer.timeout.connect(self.trigger_auto_build)
        self._editor_pdf_sync = EditorPdfSyncMap()
        self._editor_pdf_sync_timer = QtCore.QTimer(self)
        self._editor_pdf_sync_timer.setSingleShot(True)
        self._editor_pdf_sync_timer.setInterval(EDITOR_PDF_SYNC_DEBOUNCE_MS)
        self._editor_pdf_sync_timer.timeout.connect(self._sync_editor_position_to_preview)
        self._last_structural_cursor_signature: tuple[int, str, str] | None = None
        self._last_synced_cursor_signature: tuple[int, str, str] | None = None
        self.console_dock: QtWidgets.QDockWidget | None = None
        self.console_toggle_btn: QtWidgets.QPushButton | None = None
        self.console_restore_btn: QtWidgets.QPushButton | None = None
        self.central_tabs: QtWidgets.QTabWidget | None = None
        self.dir_combo: QtWidgets.QComboBox | None = None
        self.workspace_dock: QtWidgets.QDockWidget | None = None
        self.workspace_table: QtWidgets.QTableWidget | None = None
        self._menu_actions: dict[str, QtGui.QAction] = {}
        self._register_plot_listener()
        self._register_console_clear_listener()
        self._build_ui()
        self._restore_ui_preferences()
        self._set_build_status("Build: Ready")
        self.console_widget.clear()
        self._build_console_dock()
        self._build_workspace_dock()
        self.logs_output_widget = LogsOutputWidget(self)
        self._sync_console_for_active_tab()
        self._load_recent_projects()

    # ----- UI -------------------------------------------------------------
    def _build_ui(self) -> None:
        central_tabs = QtWidgets.QTabWidget()
        central_tabs.addTab(self._build_script_tab(), "Interactive Editor")
        central_tabs.addTab(self._build_mtex_tab(), "MTeX Studio")
        central_tabs.currentChanged.connect(lambda _idx: self._handle_active_context_changed())
        self.central_tabs = central_tabs
        self.setCentralWidget(central_tabs)
        self._init_restore_buttons()

        self.console_widget = ConsoleWidget(self)
        self.console_widget.send_btn.clicked.connect(self.run_command)
        self.console_widget.clear_btn.clicked.connect(self.console_widget.clear)
        self.console_widget.input.submitted.connect(self.run_command)
        self._initialize_menu_actions()
        self._refresh_menu_bar_for_active_context()

    def _init_restore_buttons(self) -> None:
        status = self.statusBar()
        status.setSizeGripEnabled(False)
        self.console_restore_btn = QtWidgets.QPushButton("Restore Console to Panel")
        if self.console_restore_btn is not None:
            self.console_restore_btn.setVisible(False)
            self.console_restore_btn.clicked.connect(self._restore_console_dock)
            status.addPermanentWidget(self.console_restore_btn)

    def _theme_icon(
        self,
        names: tuple[str, ...],
        fallback: QtWidgets.QStyle.StandardPixmap | None = None,
    ) -> QtGui.QIcon:
        for name in names:
            icon = QtGui.QIcon.fromTheme(name)
            if not icon.isNull():
                return icon
        if fallback is not None:
            return self.style().standardIcon(fallback)
        return QtGui.QIcon()

    def _ibeam_icon(self, size: int = 12) -> QtGui.QIcon:
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        pen = QtGui.QPen(QtGui.QColor("#f2f2f2"))
        pen.setWidth(2)
        painter.setPen(pen)
        center_x = size // 2
        top = 2
        bottom = size - 3
        painter.drawLine(center_x, top, center_x, bottom)
        painter.drawLine(center_x - 3, top, center_x + 3, top)
        painter.drawLine(center_x - 3, bottom, center_x + 3, bottom)
        painter.end()
        return QtGui.QIcon(pixmap)

    def _compose_icon(
        self,
        base_icon: QtGui.QIcon,
        overlay_icon: QtGui.QIcon,
        size: int = 20,
    ) -> QtGui.QIcon:
        if base_icon.isNull():
            return overlay_icon
        base = base_icon.pixmap(size, size)
        if base.isNull():
            return base_icon
        overlay_size = max(10, int(size * 0.5))
        overlay = overlay_icon.pixmap(overlay_size, overlay_size)
        if overlay.isNull():
            return base_icon
        painter = QtGui.QPainter(base)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        x = size - overlay.width() - 1
        y = size - overlay.height() - 1
        painter.fillRect(x - 1, y - 1, overlay.width() + 2, overlay.height() + 2, QtGui.QColor(30, 30, 30, 220))
        painter.drawPixmap(x, y, overlay)
        painter.end()
        return QtGui.QIcon(base)

    def _make_script_icon_button(self, icon: QtGui.QIcon, tooltip: str) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton()
        button.setAutoRaise(False)
        button.setText("")
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setIcon(icon)
        button.setIconSize(QtCore.QSize(18, 18))
        button.setFixedSize(30, 28)
        return button

    def _initialize_menu_actions(self) -> None:
        if self._menu_actions:
            return
        self._menu_actions = {
            "interactive_new_script": self._make_menu_action("New Script", self._new_script_file),
            "interactive_open_script": self._make_menu_action("Open Script...", self._open_mtex_in_script),
            "interactive_save_script": self._make_menu_action("Save", self._save_script_file, shortcut="Ctrl+S"),
            "interactive_save_script_as": self._make_menu_action("Save As...", self._save_script_file_as, shortcut="Ctrl+Shift+S"),
            "interactive_close_script": self._make_menu_action("Close Script", self._close_current_script),
            "interactive_exit": self._make_menu_action("Exit", self.close),
            "interactive_show_console": self._make_menu_action("Show/Focus Console", self._show_console),
            "interactive_show_workspace": self._make_menu_action("Show/Focus Workspace", self._show_workspace_panel),
            "interactive_restore_console": self._make_menu_action("Restore Console to Panel", self._restore_console_dock),
            "interactive_reset_layout": self._make_menu_action("Reset Panel Layout", self._reset_interactive_panel_layout),
            "interactive_run_script": self._make_menu_action(
                "Run Script",
                self.run_script,
                shortcut=["Ctrl+Enter", "Ctrl+Return"],
            ),
            "interactive_run_selection": self._make_menu_action("Run Selection", self.run_selection),
            "interactive_clear_console": self._make_menu_action("Clear Console", self._clear_console_output),
            "interactive_choose_directory": self._make_menu_action("Choose Working Directory...", self._select_directory),
            "interactive_parent_directory": self._make_menu_action("Go to Parent Directory", self._go_parent_directory),
            "studio_new_project": self._make_menu_action("New Project", self._create_project),
            "studio_open_project": self._make_menu_action("Open Project...", self._choose_and_open_project),
            "studio_project_home": self._make_menu_action("Project Home", self._return_to_project_home),
            "studio_open_mtex": self._make_menu_action("Open .mtex File...", self._open_mtex_file),
            "studio_save_mtex": self._make_menu_action("Save", self._save_mtex_file, shortcut="Ctrl+S"),
            "studio_save_mtex_as": self._make_menu_action("Save As...", self._save_mtex_file_as, shortcut="Ctrl+Shift+S"),
            "studio_show_project_files": self._make_menu_action("Show Project Files", self._focus_project_files_panel),
            "studio_show_preview": self._make_menu_action("Show PDF Preview", self._focus_pdf_preview_panel),
            "studio_reveal_in_preview": self._make_menu_action("Reveal in Preview", self._reveal_current_editor_position_in_preview),
            "studio_show_logs": self._make_menu_action("Show Logs & Output Files", self._show_logs_output_widget),
            "studio_refresh_tree": self._make_menu_action("Refresh File Tree", self._refresh_mtex_file_tree),
            "studio_compile": self._make_menu_action(
                "Compile",
                self._compile_current_mtex,
                shortcut=["Ctrl+Enter", "Ctrl+Return"],
            ),
            "studio_toggle_auto_compile": self._make_menu_action(
                "Toggle Auto Compile",
                self._toggle_auto_compile_from_menu,
                checkable=True,
            ),
            "edit_undo": self._make_menu_action("Undo", lambda: self._invoke_context_editor("undo"), shortcut=QtGui.QKeySequence.StandardKey.Undo),
            "edit_redo": self._make_menu_action("Redo", lambda: self._invoke_context_editor("redo"), shortcut=QtGui.QKeySequence.StandardKey.Redo),
            "edit_cut": self._make_menu_action("Cut", lambda: self._invoke_context_editor("cut"), shortcut=QtGui.QKeySequence.StandardKey.Cut),
            "edit_copy": self._make_menu_action("Copy", lambda: self._invoke_context_editor("copy"), shortcut=QtGui.QKeySequence.StandardKey.Copy),
            "edit_paste": self._make_menu_action("Paste", lambda: self._invoke_context_editor("paste"), shortcut=QtGui.QKeySequence.StandardKey.Paste),
            "edit_select_all": self._make_menu_action(
                "Select All",
                lambda: self._invoke_context_editor("selectAll"),
                shortcut=QtGui.QKeySequence.StandardKey.SelectAll,
            ),
            "studio_insert_section": self._make_menu_action("Section", lambda: self._insert_named_mtex_snippet("section")),
            "studio_insert_subsection": self._make_menu_action("Subsection", lambda: self._insert_named_mtex_snippet("subsection")),
            "studio_insert_equation": self._make_menu_action("Equation Block", lambda: self._insert_named_mtex_snippet("equation")),
            "studio_insert_code": self._make_menu_action("Code Block", lambda: self._insert_named_mtex_snippet("verbatim")),
            "studio_insert_table": self._make_menu_action("Table Skeleton", lambda: self._insert_named_mtex_snippet("table")),
            "studio_insert_figure": self._make_menu_action("Figure Skeleton", lambda: self._insert_named_mtex_snippet("figure")),
            "studio_insert_mathtex": self._make_menu_action("MathTeX Block", lambda: self._insert_named_mtex_snippet("mathtex")),
            "help_about": self._make_menu_action("About MathTeX", self._show_about_dialog),
            "help_interactive": self._make_menu_action("Interactive Editor Help", self._show_interactive_help),
            "help_studio": self._make_menu_action("MTeX Studio Help", self._show_studio_help),
        }

    def _make_menu_action(
        self,
        text: str,
        slot,
        *,
        shortcut: str | QtGui.QKeySequence.StandardKey | list[str] | tuple[str, ...] | None = None,
        checkable: bool = False,
    ) -> QtGui.QAction:
        action = QtGui.QAction(text, self)
        if shortcut is not None:
            if isinstance(shortcut, (list, tuple)):
                action.setShortcuts([QtGui.QKeySequence(value) for value in shortcut])
            elif isinstance(shortcut, str):
                action.setShortcut(QtGui.QKeySequence(shortcut))
            else:
                action.setShortcuts(shortcut)
        action.setCheckable(checkable)
        action.triggered.connect(slot)
        return action

    def _current_menu_context(self) -> str:
        return STUDIO_MENU_CONTEXT if self._is_studio_tab_active() else INTERACTIVE_MENU_CONTEXT

    def _set_active_main_tab(self, index: int) -> None:
        tabs = self.central_tabs
        if tabs is None:
            return
        if tabs.currentIndex() != index:
            tabs.setCurrentIndex(index)
        else:
            self._handle_active_context_changed()

    def _handle_active_context_changed(self) -> None:
        self._sync_console_for_active_tab()
        self._refresh_menu_bar_for_active_context()

    def _refresh_menu_bar_for_active_context(self) -> None:
        if not self._menu_actions:
            return
        self._update_menu_action_states()
        menu_bar = self.menuBar()
        menu_bar.clear()
        if self._current_menu_context() == STUDIO_MENU_CONTEXT:
            self._build_studio_menus(menu_bar)
        else:
            self._build_interactive_menus(menu_bar)

    def _build_interactive_menus(self, menu_bar: QtWidgets.QMenuBar) -> None:
        self._add_menu(
            menu_bar,
            "File",
            [
                "interactive_new_script",
                "interactive_open_script",
                None,
                "interactive_save_script",
                "interactive_save_script_as",
                None,
                "interactive_close_script",
                None,
                "interactive_exit",
            ],
        )
        self._add_menu(
            menu_bar,
            "Edit",
            [
                "edit_undo",
                "edit_redo",
                None,
                "edit_cut",
                "edit_copy",
                "edit_paste",
                None,
                "edit_select_all",
            ],
        )
        self._add_menu(
            menu_bar,
            "View",
            [
                "interactive_show_console",
                "interactive_show_workspace",
                "interactive_restore_console",
                None,
                "interactive_reset_layout",
            ],
        )
        self._add_menu(
            menu_bar,
            "Run",
            [
                "interactive_run_script",
                "interactive_run_selection",
                None,
                "interactive_clear_console",
            ],
        )
        self._add_menu(
            menu_bar,
            "Tools",
            [
                "interactive_choose_directory",
                "interactive_parent_directory",
            ],
        )
        self._add_menu(menu_bar, "Help", ["help_about", "help_interactive"])

    def _build_studio_menus(self, menu_bar: QtWidgets.QMenuBar) -> None:
        self._add_menu(
            menu_bar,
            "File",
            [
                "studio_new_project",
                "studio_open_project",
                "studio_project_home",
                None,
                "studio_open_mtex",
                None,
                "studio_save_mtex",
                "studio_save_mtex_as",
            ],
        )
        self._add_menu(
            menu_bar,
            "Edit",
            [
                "edit_undo",
                "edit_redo",
                None,
                "edit_cut",
                "edit_copy",
                "edit_paste",
                None,
                "edit_select_all",
            ],
        )
        self._add_menu(
            menu_bar,
            "Insert",
            [
                "studio_insert_section",
                "studio_insert_subsection",
                None,
                "studio_insert_equation",
                "studio_insert_code",
                "studio_insert_table",
                "studio_insert_figure",
                "studio_insert_mathtex",
            ],
        )
        self._add_menu(
            menu_bar,
            "View",
            [
                "studio_show_project_files",
                "studio_show_preview",
                "studio_reveal_in_preview",
                "studio_show_logs",
                None,
                "studio_refresh_tree",
            ],
        )
        self._add_menu(
            menu_bar,
            "Build",
            [
                "studio_compile",
                "studio_toggle_auto_compile",
                None,
                "studio_show_logs",
            ],
        )
        self._add_menu(menu_bar, "Help", ["help_about", "help_studio"])

    def _add_menu(self, menu_bar: QtWidgets.QMenuBar, title: str, entries: list[str | None]) -> QtWidgets.QMenu:
        menu = menu_bar.addMenu(title)
        menu.aboutToShow.connect(self._update_menu_action_states)
        for entry in entries:
            if entry is None:
                menu.addSeparator()
                continue
            action = self._menu_actions.get(entry)
            if action is not None:
                menu.addAction(action)
        return menu

    def _update_menu_action_states(self) -> None:
        actions = self._menu_actions
        if not actions:
            return

        interactive_context_active = self._current_menu_context() == INTERACTIVE_MENU_CONTEXT
        studio_context_active = not interactive_context_active
        script_doc = self._current_script_doc() if hasattr(self, "script_tab_widget") else None
        has_script_doc = script_doc is not None
        script_editor = self._active_script_editor()
        context_editor = self._context_editor()
        has_editor = context_editor is not None
        studio_workspace_active = self._is_studio_workspace_active()
        has_project = self.current_project is not None
        has_current_mtex = studio_workspace_active and self.current_mtex_path is not None
        has_logs_or_project = has_project or self.latest_mtex_execution_result is not None

        for key in ("edit_undo", "edit_redo", "edit_cut", "edit_copy", "edit_paste", "edit_select_all"):
            actions[key].setEnabled(has_editor)

        actions["interactive_new_script"].setEnabled(interactive_context_active)
        actions["interactive_open_script"].setEnabled(interactive_context_active)
        actions["interactive_save_script"].setEnabled(interactive_context_active and has_script_doc)
        actions["interactive_save_script_as"].setEnabled(interactive_context_active and has_script_doc)
        actions["interactive_close_script"].setEnabled(interactive_context_active and has_script_doc)
        actions["interactive_run_script"].setEnabled(interactive_context_active and has_script_doc)
        actions["interactive_run_selection"].setEnabled(
            interactive_context_active and script_editor is not None and script_editor.textCursor().hasSelection()
        )
        actions["interactive_show_console"].setEnabled(interactive_context_active and self.console_dock is not None)
        actions["interactive_show_workspace"].setEnabled(interactive_context_active and self.workspace_dock is not None)
        actions["interactive_restore_console"].setEnabled(
            interactive_context_active and self.console_dock is not None and self.console_dock.isFloating()
        )
        actions["interactive_reset_layout"].setEnabled(
            interactive_context_active and (self.console_dock is not None or self.workspace_dock is not None)
        )
        actions["interactive_clear_console"].setEnabled(interactive_context_active)
        actions["interactive_choose_directory"].setEnabled(interactive_context_active)
        actions["interactive_parent_directory"].setEnabled(interactive_context_active)

        actions["studio_new_project"].setEnabled(studio_context_active)
        actions["studio_open_project"].setEnabled(studio_context_active)
        actions["studio_project_home"].setEnabled(studio_context_active and has_project)
        actions["studio_open_mtex"].setEnabled(studio_context_active and has_project)
        actions["studio_save_mtex"].setEnabled(studio_context_active and has_current_mtex)
        actions["studio_save_mtex_as"].setEnabled(studio_context_active and studio_workspace_active and self.mtex_editor is not None)
        actions["studio_show_project_files"].setEnabled(studio_context_active and studio_workspace_active and self.mtex_file_tree is not None)
        actions["studio_show_preview"].setEnabled(studio_context_active and studio_workspace_active and self.preview is not None)
        actions["studio_reveal_in_preview"].setEnabled(
            studio_context_active
            and studio_workspace_active
            and self.mtex_editor is not None
            and self.preview is not None
            and self.preview.current_pdf_path() is not None
        )
        actions["studio_show_logs"].setEnabled(studio_context_active and has_logs_or_project)
        actions["studio_refresh_tree"].setEnabled(studio_context_active and has_project)
        actions["studio_compile"].setEnabled(studio_context_active and has_project)
        actions["studio_toggle_auto_compile"].setEnabled(studio_context_active and has_project and self.auto_compile_checkbox is not None)
        if self.auto_compile_checkbox is not None:
            actions["studio_toggle_auto_compile"].setChecked(self.auto_compile_checkbox.isChecked())
        for key in (
            "studio_insert_section",
            "studio_insert_subsection",
            "studio_insert_equation",
            "studio_insert_code",
            "studio_insert_table",
            "studio_insert_figure",
            "studio_insert_mathtex",
        ):
            actions[key].setEnabled(studio_context_active and studio_workspace_active and self.mtex_editor is not None)

    def _build_script_tab(self) -> QtWidgets.QWidget:
        root = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        directory_row = QtWidgets.QHBoxLayout()
        directory_row.setSpacing(6)
        directory_label = QtWidgets.QLabel("Working Directory:")
        directory_label.setStyleSheet("color: #d8d8d8;")
        directory_row.addWidget(directory_label)

        self.dir_combo = QtWidgets.QComboBox()
        self.dir_combo.setEditable(True)
        self.dir_combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.dir_combo.setMinimumWidth(320)
        self.dir_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.dir_combo.setStyleSheet(
            """
            QComboBox {
                background: #2f2f2f;
                color: #f2f2f2;
                border: 1px solid #505050;
                border-radius: 4px;
                padding: 3px 8px;
            }
            QComboBox:focus {
                border: 1px solid #7aa2f7;
            }
            QComboBox QAbstractItemView {
                background: #2b2b2b;
                color: #f2f2f2;
                selection-background-color: #444c5a;
            }
        """
        )
        self.dir_combo.activated.connect(lambda _idx: self._apply_working_dir_from_text(self.dir_combo.currentText()))
        line_edit = self.dir_combo.lineEdit()
        if line_edit is not None:
            line_edit.returnPressed.connect(lambda: self._apply_working_dir_from_text(line_edit.text()))
        directory_row.addWidget(self.dir_combo, 1)

        style = self.style()
        up_btn = QtWidgets.QToolButton()
        up_btn.setToolTip("Go up one level")
        up_btn.setAutoRaise(True)
        up_btn.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowUp))
        up_btn.clicked.connect(self._go_parent_directory)
        directory_row.addWidget(up_btn)

        browse_btn = QtWidgets.QToolButton()
        browse_btn.setToolTip("Choose directory")
        browse_btn.setAutoRaise(True)
        browse_btn.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirClosedIcon))
        browse_btn.clicked.connect(self._select_directory)
        directory_row.addWidget(browse_btn)
        layout.addLayout(directory_row)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(6)
        new_icon = self._theme_icon(
            ("document-new-symbolic",),
            QtWidgets.QStyle.StandardPixmap.SP_FileIcon,
        )
        open_icon = self._theme_icon(
            ("folder-documents-symbolic", "document-open-symbolic"),
            QtWidgets.QStyle.StandardPixmap.SP_DirOpenIcon,
        )
        save_icon = self._theme_icon(
            ("document-save-symbolic", "media-floppy-symbolic"),
            QtWidgets.QStyle.StandardPixmap.SP_DialogSaveButton,
        )
        save_as_icon = self._theme_icon(
            ("document-save-as-symbolic",),
            QtWidgets.QStyle.StandardPixmap.SP_DialogSaveButton,
        )
        run_all_icon = self._theme_icon(
            ("media-playback-start-symbolic",),
            QtWidgets.QStyle.StandardPixmap.SP_MediaPlay,
        )
        cursor_icon = self._theme_icon(("insert-text-symbolic",))
        if cursor_icon.isNull():
            cursor_icon = self._ibeam_icon()
        run_sel_icon = self._compose_icon(run_all_icon, cursor_icon)

        new_btn = self._make_script_icon_button(new_icon, "New File")
        open_btn = self._make_script_icon_button(open_icon, "Open .mtx")
        save_btn = self._make_script_icon_button(save_icon, "Save")
        save_as_btn = self._make_script_icon_button(save_as_icon, "Save As...")
        run_all = self._make_script_icon_button(run_all_icon, "Run All (Ctrl+Enter)")
        run_sel = self._make_script_icon_button(run_sel_icon, "Run Selection")
        buttons.addWidget(new_btn)
        buttons.addWidget(open_btn)
        buttons.addWidget(save_btn)
        buttons.addWidget(save_as_btn)
        buttons.addWidget(run_all)
        buttons.addWidget(run_sel)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.script_tab_widget = QtWidgets.QTabWidget()
        self.script_tab_widget.setTabsClosable(True)
        self.script_tab_widget.tabCloseRequested.connect(self._request_close_script_tab)
        self.script_tab_widget.currentChanged.connect(lambda _idx: self._refresh_menu_bar_for_active_context())
        layout.addWidget(self.script_tab_widget, 1)

        run_all.clicked.connect(self.run_script)
        run_sel.clicked.connect(self.run_selection)
        new_btn.clicked.connect(lambda: self._new_script_file())
        open_btn.clicked.connect(self._open_mtex_in_script)
        save_btn.clicked.connect(self._save_script_file)
        save_as_btn.clicked.connect(self._save_script_file_as)

        # No se crea archivo vacio al iniciar; el usuario abre o crea manualmente.
        self._sync_working_dir_controls()
        return root

    def _apply_working_dir(self, path: Path) -> None:
        target = path.expanduser()
        if change_working_dir(target):
            self._sync_working_dir_controls()

    def _apply_working_dir_from_text(self, raw_text: str) -> None:
        text = (raw_text or "").strip()
        if not text:
            return
        self._apply_working_dir(Path(text))

    def _go_parent_directory(self) -> None:
        current = get_working_dir()
        parent = current.parent
        if parent != current:
            self._apply_working_dir(parent)

    def _sync_working_dir_controls(self) -> None:
        combo = self.dir_combo
        if combo is None:
            return
        current = str(get_working_dir())
        combo.blockSignals(True)
        if combo.findText(current) == -1:
            combo.insertItem(0, current)
        combo.setCurrentText(current)
        while combo.count() > 15:
            combo.removeItem(combo.count() - 1)
        combo.blockSignals(False)

    def _select_directory(self) -> None:
        current = str(get_working_dir())
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose Working Directory", current)
        if not directory:
            return
        self._apply_working_dir(Path(directory))

    # ----- Arbol de archivos (MTeX Studio) --------------------------------
    def _refresh_mtex_file_tree(self) -> None:
        if self.project_workspace_widget is None:
            return
        self.project_workspace_widget.refresh_file_tree()
        self._refresh_menu_bar_for_active_context()

    def _build_mtex_tab(self) -> QtWidgets.QWidget:
        root = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.project_stack = QtWidgets.QStackedWidget()
        self.project_home_widget = ProjectHomeWidget(root)
        self.project_workspace_widget = ProjectWorkspaceWidget(
            editor_factory=CodeEditor,
            preview_factory=PdfPreviewWidget,
            preview_message=self._preview_message,
            project_manager=self.project_manager,
            parent=root,
        )
        self.project_stack.addWidget(self.project_home_widget)
        self.project_stack.addWidget(self.project_workspace_widget)
        layout.addWidget(self.project_stack, 1)

        self.mtex_file_tree = self.project_workspace_widget.file_tree
        self.mtex_editor = self.project_workspace_widget.editor_widget
        self.mtex_file_label = self.project_workspace_widget.file_label
        self.auto_compile_checkbox = self.project_workspace_widget.auto_compile_checkbox
        self.build_status_label = self.project_workspace_widget.build_status_label
        self.preview = self.project_workspace_widget.preview_widget
        self.mtex_editor.set_autocomplete_document_kind("mtex_document")

        self.project_home_widget.new_project_requested.connect(self._create_project)
        self.project_home_widget.open_project_requested.connect(self._choose_and_open_project)
        self.project_home_widget.project_activated.connect(self._open_project_from_path)
        self.project_workspace_widget.home_requested.connect(self._return_to_project_home)
        self.project_workspace_widget.save_requested.connect(self._save_mtex_file)
        self.project_workspace_widget.save_as_requested.connect(self._save_mtex_file_as)
        self.project_workspace_widget.compile_requested.connect(self._compile_current_mtex)
        self.project_workspace_widget.logs_output_requested.connect(self._show_logs_output_widget)
        self.project_workspace_widget.file_open_requested.connect(self._handle_project_file_activation)
        self.mtex_editor.modificationChanged.connect(lambda changed: self._update_mtex_dirty(changed))
        self.mtex_editor.textChanged.connect(self._on_active_mtex_text_changed)
        self.mtex_editor.cursorPositionChanged.connect(self._on_mtex_cursor_position_changed)
        if self.auto_compile_checkbox is not None:
            self.auto_compile_checkbox.toggled.connect(self._set_auto_compile_enabled)

        self._show_project_home()
        return root

    # ----- Consola --------------------------------------------------------
    def append_output(self, text: str, ensure_newline: bool = True) -> None:
        self.console_widget.append_output(text, ensure_newline=ensure_newline)

    def _remove_trailing_prompt(self) -> None:
        try:
            self.console_widget.output.remove_prompt()
        except Exception:
            pass

    def _append_prompt(self) -> None:
        try:
            self.console_widget.output.ensure_prompt()
        except Exception:
            pass

    def _build_console_dock(self) -> None:
        dock = QtWidgets.QDockWidget("Console", self)
        dock.setWidget(self.console_widget)
        dock.setObjectName("consoleDock")
        dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        title = QtWidgets.QWidget()
        title_layout = QtWidgets.QHBoxLayout(title)
        title_layout.setContentsMargins(6, 2, 6, 2)
        title_label = QtWidgets.QLabel("Console")
        toggle_btn = QtWidgets.QPushButton("Undock")
        toggle_btn.setFixedHeight(22)
        toggle_btn.clicked.connect(self._toggle_console_dock)
        self.console_toggle_btn = toggle_btn
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        title_layout.addWidget(toggle_btn)
        dock.setTitleBarWidget(title)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        dock.topLevelChanged.connect(lambda _f: self._on_console_dock_state_changed())
        dock.visibilityChanged.connect(lambda _v: self._on_console_dock_state_changed())
        self.console_dock = dock
        self._on_console_dock_state_changed()

    def _show_console(self) -> None:
        self._restore_console_dock()

    def _toggle_console_dock(self) -> None:
        dock = self.console_dock
        if dock is None:
            return
        target_state = not dock.isFloating()
        dock.setFloating(target_state)
        dock.show()
        self._on_console_dock_state_changed()

    def _restore_console_dock(self) -> None:
        dock = self.console_dock
        if dock is None:
            return
        dock.setFloating(False)
        dock.show()
        dock.raise_()
        self._on_console_dock_state_changed()

    def _on_console_dock_state_changed(self) -> None:
        dock = self.console_dock
        if self._is_studio_tab_active():
            if self.console_restore_btn:
                self.console_restore_btn.setVisible(False)
            return
        floating = dock.isFloating() if dock else False
        visible = dock.isVisible() if dock else False
        need_restore = floating or not visible
        if self.console_restore_btn:
            self.console_restore_btn.setVisible(need_restore)
        if self.console_toggle_btn:
            self.console_toggle_btn.setText("Dock" if floating else "Undock")
        if dock and not visible:
            dock.show()
        if dock:
            dock.activateWindow()
        try:
            self.console_widget.input.setFocus()
        except Exception:
            pass

    def _is_studio_tab_active(self) -> bool:
        tabs = self.central_tabs
        if tabs is None:
            return False
        return tabs.currentIndex() == 1

    def _sync_console_for_active_tab(self) -> None:
        dock = self.console_dock
        if self._is_studio_tab_active():
            if dock is not None:
                dock.hide()
            if self.workspace_dock is not None:
                self.workspace_dock.hide()
            if self.console_restore_btn:
                self.console_restore_btn.setVisible(False)
            return
        if dock is not None:
            dock.show()
            self._on_console_dock_state_changed()
        if self.workspace_dock is not None:
            self.workspace_dock.show()

    def _show_workspace_panel(self) -> None:
        if self.workspace_dock is None:
            return
        self.workspace_dock.show()
        self.workspace_dock.raise_()
        if self.workspace_table is not None:
            self.workspace_table.setFocus()

    def _reset_interactive_panel_layout(self) -> None:
        docks: list[QtWidgets.QDockWidget] = []
        if self.console_dock is not None:
            self.console_dock.setFloating(False)
            self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, self.console_dock)
            self.console_dock.show()
            docks.append(self.console_dock)
        if self.workspace_dock is not None:
            self.workspace_dock.setFloating(False)
            self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, self.workspace_dock)
            self.workspace_dock.show()
            docks.append(self.workspace_dock)
        if self.console_dock is not None and self.workspace_dock is not None:
            self.splitDockWidget(self.console_dock, self.workspace_dock, QtCore.Qt.Orientation.Horizontal)
            self.resizeDocks([self.console_dock, self.workspace_dock], [830, 330], QtCore.Qt.Orientation.Horizontal)
        if docks:
            self._on_console_dock_state_changed()

    def _active_script_editor(self) -> CodeEditor | None:
        doc = self._current_script_doc()
        if not doc:
            return None
        widget = doc.get("widget")
        return widget if isinstance(widget, CodeEditor) else None

    def _is_studio_workspace_active(self) -> bool:
        return bool(
            self.current_project is not None
            and self.project_stack is not None
            and self.project_workspace_widget is not None
            and self.project_stack.currentWidget() is self.project_workspace_widget
        )

    def _active_mtex_editor(self) -> CodeEditor | None:
        if not self._is_studio_workspace_active() or self.mtex_editor is None:
            return None
        return self.mtex_editor

    def _context_editor(self) -> CodeEditor | None:
        if self._current_menu_context() == STUDIO_MENU_CONTEXT:
            return self._active_mtex_editor()
        return self._active_script_editor()

    def _invoke_context_editor(self, method_name: str) -> None:
        editor = self._context_editor()
        if editor is None:
            return
        handler = getattr(editor, method_name, None)
        if callable(handler):
            handler()
            editor.setFocus()

    # ----- Workspace ------------------------------------------------------
    def _build_workspace_dock(self) -> None:
        dock = QtWidgets.QDockWidget("Workspace", self)
        dock.setObjectName("workspaceDock")
        dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        table = QtWidgets.QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Name", "Type", "Size", "Summary"])
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        self._apply_workspace_column_layout(table)
        layout.addWidget(table)
        dock.setWidget(container)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        if self.console_dock is not None:
            self.splitDockWidget(self.console_dock, dock, QtCore.Qt.Orientation.Horizontal)
            self.resizeDocks([self.console_dock, dock], [830, 330], QtCore.Qt.Orientation.Horizontal)
        self.workspace_dock = dock
        self.workspace_table = table

    def _apply_workspace_column_layout(self, table: QtWidgets.QTableWidget) -> None:
        header = table.horizontalHeader()
        for col in range(4):
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        table.setColumnWidth(0, 110)
        table.setColumnWidth(1, 90)
        table.setColumnWidth(2, 90)
        table.setColumnWidth(3, 110)

    def refresh_workspace_view(self) -> None:
        try:
            items = workspace_snapshot()
        except Exception:
            items = []
        table = self.workspace_table
        if table is not None:
            table.setSortingEnabled(False)
            table.clearContents()
            table.setRowCount(len(items))
            for row_idx, info in enumerate(items):
                row_values = [
                    info.get("name", ""),
                    info.get("class", ""),
                    info.get("size", ""),
                    info.get("summary", ""),
                ]
                for col_idx, value in enumerate(row_values):
                    item = QtWidgets.QTableWidgetItem(str(value))
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                    table.setItem(row_idx, col_idx, item)
            table.setSortingEnabled(True)
            self._apply_workspace_column_layout(table)

    # ----- Script docs ----------------------------------------------------
    def _new_script_file(self, initial: bool = False) -> None:
        name = f"untitled_{self._untitled_counter}.mtx"
        self._untitled_counter += 1
        self._create_script_document(name=name, path=None, content="", announce=not initial)

    def _create_script_document(self, name: str, path: Path | None, content: str, announce: bool) -> None:
        editor = CodeEditor(enable_autocomplete=True)
        editor.set_autocomplete_document_kind("script")
        editor.set_autocomplete_workspace_provider(workspace_snapshot)
        editor.setPlainText(content)
        editor.textChanged.connect(lambda e=editor: self._mark_script_dirty(e))
        idx = self.script_tab_widget.addTab(editor, name)
        self.script_tab_widget.setCurrentIndex(idx)
        doc = {"widget": editor, "path": path, "name": name, "dirty": False, "tab_index": idx}
        self.script_docs.append(doc)
        self._update_script_tab_title(doc)
        self._refresh_menu_bar_for_active_context()

    def _current_script_doc(self):
        idx = self.script_tab_widget.currentIndex()
        if idx < 0:
            return None
        widget = self.script_tab_widget.widget(idx)
        for doc in self.script_docs:
            if doc["widget"] is widget:
                return doc
        return None

    def _update_script_tab_title(self, doc: dict) -> None:
        widget = doc.get("widget")
        if widget is None:
            return
        name = doc.get("name") or "untitled.mtx"
        title = f"*{name}" if doc.get("dirty") else name
        idx = self.script_tab_widget.indexOf(widget)
        if idx >= 0:
            self.script_tab_widget.setTabText(idx, title)

    def _mark_script_dirty(self, widget: CodeEditor) -> None:
        doc = next((d for d in self.script_docs if d["widget"] is widget), None)
        if not doc:
            return
        doc["dirty"] = True
        self._update_script_tab_title(doc)

    def _request_close_script_tab(self, index: int) -> None:
        widget = self.script_tab_widget.widget(index)
        doc = next((d for d in self.script_docs if d["widget"] is widget), None)
        if not doc:
            self.script_tab_widget.removeTab(index)
            return
        if doc.get("dirty"):
            choice = self._ask_close_confirmation(doc)
            if choice == "cancel":
                return
            if choice == "save" and not self._save_script_document(doc):
                return
        self._remove_script_doc(doc)

    def _remove_script_doc(self, doc: dict) -> None:
        widget = doc.get("widget")
        if widget:
            idx = self.script_tab_widget.indexOf(widget)
            if idx >= 0:
                self.script_tab_widget.removeTab(idx)
        if doc in self.script_docs:
            self.script_docs.remove(doc)

        self._refresh_menu_bar_for_active_context()

    def _close_current_script(self) -> None:
        if not hasattr(self, "script_tab_widget"):
            return
        index = self.script_tab_widget.currentIndex()
        if index >= 0:
            self._request_close_script_tab(index)
    def _ask_close_confirmation(self, doc: dict) -> str:
        path = doc.get("path")
        location = str(path) if path else doc.get("name", "unsaved file")
        dialog = QtWidgets.QMessageBox(self)
        dialog.setWindowTitle("Close File")
        dialog.setText(
            f"The file {location} is about to close with unsaved changes.\n"
            "Do you want to cancel, save, or discard those changes?"
        )
        dialog.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Save
            | QtWidgets.QMessageBox.StandardButton.Discard
            | QtWidgets.QMessageBox.StandardButton.Cancel
        )
        dialog.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Save)
        result = dialog.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Save:
            return "save"
        if result == QtWidgets.QMessageBox.StandardButton.Discard:
            return "discard"
        return "cancel"

    def _prompt_script_destination(self, doc=None):
        initial = "new_script.mtx"
        if doc and doc.get("path"):
            try:
                initial = Path(doc["path"]).name
            except Exception:
                initial = str(doc["path"])
        elif doc and doc.get("name"):
            initial = doc.get("name")
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save .mtx Script",
            str(get_working_dir() / initial),
            "MathTeX Files (*.mtx);;All Files (*)",
        )
        if not filename:
            return None
        path = Path(filename)
        if path.suffix.lower() != ".mtx":
            path = path.with_suffix(".mtx")
        return path

    def _write_script_document(self, doc: dict, path: Path) -> None:
        widget: CodeEditor | None = doc.get("widget")
        if not widget:
            return
        content = widget.toPlainText()
        path.write_text(content, encoding="utf-8")

    def _persist_script_document(self, doc: dict, path: Path) -> bool:
        try:
            self._write_script_document(doc, path)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "MathTeX", f"Could not save the file.\n{exc}")
            return False
        doc["path"] = path
        doc["name"] = path.name
        doc["dirty"] = False
        self._update_script_tab_title(doc)
        return True

    def _save_script_document(self, doc) -> bool:
        if not doc:
            return False
        destination = doc.get("path")
        if destination:
            return self._persist_script_document(doc, Path(destination))
        dest = self._prompt_script_destination(doc)
        if not dest:
            return False
        return self._persist_script_document(doc, dest)

    def _save_script_file(self) -> bool:
        doc = self._current_script_doc()
        if not doc:
            return False
        if doc.get("path") is None:
            return self._save_script_file_as() is not None
        return self._persist_script_document(doc, Path(doc["path"]))

    def _save_script_file_as(self):
        doc = self._current_script_doc()
        if not doc:
            return None
        destination = self._prompt_script_destination(doc)
        if not destination:
            return None
        if self._persist_script_document(doc, destination):
            return destination
        return None

    def _find_script_doc_by_path(self, path: Path):
        target = None
        try:
            target = Path(path).resolve()
        except Exception:
            target = None
        for doc in self.script_docs:
            existing = doc.get("path")
            if not existing:
                continue
            try:
                if Path(existing).resolve() == target:
                    return doc
            except Exception:
                continue
        return None

    def _open_mtex_in_script(self, path: Path | str | None = None) -> None:
        # The clicked signal from Qt can pass a boolean "checked" flag; normalize that away.
        if isinstance(path, bool):
            path = None
        if isinstance(path, str):
            path = Path(path)
        if path is None:
            filename, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Open .mtx File in Interactive Editor",
                str(get_working_dir()),
                "MathTeX Files (*.mtx);;All Files (*)",
            )
            if not filename:
                return
            path = Path(filename)
        existing_doc = self._find_script_doc_by_path(path)
        if existing_doc:
            widget = existing_doc.get("widget")
            if widget:
                idx = self.script_tab_widget.indexOf(widget)
                if idx >= 0:
                    self.script_tab_widget.setCurrentIndex(idx)
            self._set_active_main_tab(0)
            self.append_output(f"[Script] {path.name} was already open. Tab activated.")
            return
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "MathTeX", f"Could not open the file.\n{exc}")
            return
        self._create_script_document(name=path.name, path=path, content=content, announce=False)
        self._set_active_main_tab(0)
    # ----- MTeX workspace -------------------------------------------------
    def _load_recent_projects(self) -> None:
        self.project_registry.load()
        self.project_registry.remove_missing_projects()
        self.project_registry.save()
        self._refresh_project_home()

    def _refresh_project_home(self) -> None:
        if self.project_home_widget is None:
            return
        self.project_home_widget.set_projects(self.project_registry.list_projects())

    def _show_project_home(self) -> None:
        if self.project_stack is None or self.project_home_widget is None:
            return
        self.project_stack.setCurrentWidget(self.project_home_widget)
        self._set_active_main_tab(1)
        self._update_window_title()
        self._refresh_menu_bar_for_active_context()

    def _show_project_workspace(self) -> None:
        if self.project_stack is None or self.project_workspace_widget is None:
            return
        self.project_stack.setCurrentWidget(self.project_workspace_widget)
        self._set_active_main_tab(1)
        self._update_window_title()
        self._refresh_menu_bar_for_active_context()

    def _reset_auto_compile_runtime(self) -> None:
        self._auto_compile_timer.stop()
        self.auto_compile_controller.reset()

    def _restore_ui_preferences(self) -> None:
        preferences = self.preferences_store.load()
        if self.auto_compile_checkbox is None:
            self.auto_compile_controller.set_enabled(preferences.auto_compile_enabled)
            return
        self.auto_compile_checkbox.blockSignals(True)
        self.auto_compile_checkbox.setChecked(preferences.auto_compile_enabled)
        self.auto_compile_checkbox.blockSignals(False)
        self._set_auto_compile_enabled(preferences.auto_compile_enabled, persist=False)

    def _save_ui_preferences(self) -> None:
        enabled = self.auto_compile_checkbox.isChecked() if self.auto_compile_checkbox is not None else False
        try:
            self.preferences_store.save(AppPreferences(auto_compile_enabled=enabled))
        except OSError:
            pass

    def _set_build_status(self, text: str, tone: str = "neutral") -> None:
        if self.project_workspace_widget is not None:
            self.project_workspace_widget.set_build_status(text, tone=tone)
        self.statusBar().showMessage(text)

    def _set_auto_compile_enabled(self, enabled: bool, *, persist: bool = True) -> None:
        self.auto_compile_controller.set_enabled(enabled)
        if not enabled:
            self._auto_compile_timer.stop()
        elif self.mtex_editor is not None and self.mtex_editor.document().isModified():
            self.schedule_auto_build()
        if persist:
            self._save_ui_preferences()
        self._update_menu_action_states()

    def _is_auto_compile_target_active(self) -> bool:
        if self.current_project is None or self.current_mtex_path is None:
            return False
        if self.current_mtex_path.suffix.lower() != ".mtex":
            return False
        if self.project_stack is not None and self.project_workspace_widget is not None:
            return self.project_stack.currentWidget() is self.project_workspace_widget
        return True

    def _on_active_mtex_text_changed(self) -> None:
        self._refresh_editor_pdf_sync_source()
        if self._ignore_mtex_text_changes or not self._is_auto_compile_target_active():
            return
        self.schedule_auto_build()

    def schedule_auto_build(self) -> None:
        if not self._is_auto_compile_target_active():
            self._auto_compile_timer.stop()
            return
        decision = self.auto_compile_controller.on_document_edited()
        if decision.kind == "schedule":
            self._auto_compile_timer.start()
        elif decision.kind == "queued":
            self._auto_compile_timer.stop()

    def trigger_auto_build(self) -> None:
        self._auto_compile_timer.stop()
        self._request_current_mtex_compile("auto")

    def _clear_execution_result(self, message: str | None = None) -> None:
        self.latest_mtex_execution_result = None
        if self.logs_output_widget is not None:
            self.logs_output_widget.clear_result(message)

    def _show_logs_output_widget(self) -> None:
        if self.logs_output_widget is None:
            self.logs_output_widget = LogsOutputWidget(self)
        if self.latest_mtex_execution_result is not None:
            self.logs_output_widget.set_execution_result(self.latest_mtex_execution_result)
        self.logs_output_widget.show()
        self.logs_output_widget.raise_()
        self.logs_output_widget.activateWindow()

    def _focus_project_files_panel(self) -> None:
        if not self._is_studio_workspace_active() or self.mtex_file_tree is None:
            return
        self.mtex_file_tree.setFocus()

    def _focus_pdf_preview_panel(self) -> None:
        if not self._is_studio_workspace_active() or self.preview is None:
            return
        self.preview.setFocus()

    def _reveal_current_editor_position_in_preview(self) -> None:
        self._sync_editor_position_to_preview(force=True)
        self._focus_pdf_preview_panel()

    def _toggle_auto_compile_from_menu(self) -> None:
        if self.auto_compile_checkbox is None or not self._is_studio_workspace_active():
            return
        self.auto_compile_checkbox.toggle()
        self._update_menu_action_states()

    def _clear_console_output(self) -> None:
        if hasattr(self, "console_widget") and self.console_widget is not None:
            self.console_widget.clear()

    def _show_about_dialog(self) -> None:
        QtWidgets.QMessageBox.about(
            self,
            "About MathTeX",
            (
                "MathTeX combines two workflows in one Qt app:\n\n"
                "- Interactive Editor for .mtx scripts, console, workspace, and working directory.\n"
                "- MTeX Studio for projects, .mtex documents, PDF preview, and build outputs."
            ),
        )

    def _show_interactive_help(self) -> None:
        if self._open_documentation_file("docs/guia_de_uso.md"):
            self.append_output("[Help] Opened the MathTeX guide for the Interactive Editor workflow.")
            return
        QtWidgets.QMessageBox.information(
            self,
            "Interactive Editor Help",
            "The guide file could not be opened. You can still use commands like \\help, \\who, \\whos, and \\clear from the console.",
        )

    def _show_studio_help(self) -> None:
        if self._open_documentation_file("docs/guia_de_uso.md"):
            self.append_output("[Help] Opened the MathTeX guide for the MTeX Studio workflow.")
            return
        QtWidgets.QMessageBox.information(
            self,
            "MTeX Studio Help",
            "The guide file could not be opened. Check docs/guia_de_uso.md for .mtex syntax, code blocks, plots, and tables.",
        )

    def _open_documentation_file(self, relative_path: str) -> bool:
        doc_path = Path(__file__).resolve().parents[1] / relative_path
        if not doc_path.exists():
            return False
        return QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(doc_path)))

    def _insert_named_mtex_snippet(self, snippet_name: str) -> None:
        snippets = {
            "section": "\n\\section{" + SNIPPET_CURSOR_MARKER + "}\n\n",
            "subsection": "\n\\subsection{" + SNIPPET_CURSOR_MARKER + "}\n\n",
            "equation": "\n\\begin{equation}\n    " + SNIPPET_CURSOR_MARKER + "\n\\end{equation}\n",
            "verbatim": "\n\\begin{verbatim}\n" + SNIPPET_CURSOR_MARKER + "\n\\end{verbatim}\n",
            "table": (
                "\n\\begin{table}[ht]\n"
                "    \\centering\n"
                "    \\table{tabla_demo}\n"
                "    \\caption{" + SNIPPET_CURSOR_MARKER + "}\n"
                "    \\label{tab:demo}\n"
                "\\end{table}\n"
            ),
            "figure": (
                "\n\\begin{figure}[ht]\n"
                "    \\centering\n"
                "    \\plot{mi_plot}\n"
                "    \\caption{" + SNIPPET_CURSOR_MARKER + "}\n"
                "    \\label{fig:mi-plot}\n"
                "\\end{figure}\n"
            ),
            "mathtex": "\n\\begin{code}\n" + SNIPPET_CURSOR_MARKER + "\n\\end{code}\n",
        }
        template = snippets.get(snippet_name)
        if template is None:
            return
        self._insert_mtex_snippet(template)

    def _insert_mtex_snippet(self, template: str) -> None:
        editor = self._active_mtex_editor()
        if editor is None:
            return
        marker_index = template.find(SNIPPET_CURSOR_MARKER)
        text = template.replace(SNIPPET_CURSOR_MARKER, "")
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        cursor.insertText(text)
        if marker_index >= 0:
            backtrack = len(text) - marker_index
            if backtrack > 0:
                cursor.movePosition(
                    QtGui.QTextCursor.MoveOperation.Left,
                    QtGui.QTextCursor.MoveMode.MoveAnchor,
                    backtrack,
                )
        cursor.endEditBlock()
        editor.setTextCursor(cursor)
        editor.setFocus()
        self._refresh_menu_bar_for_active_context()

    def _update_window_title(self) -> None:
        self.setWindowTitle("MathTeX")

    def _project_root_dir(self) -> Path | None:
        if self.current_project is None:
            return None
        return self.current_project.path

    def _project_dialog_dir(self) -> Path:
        if self.current_mtex_path is not None:
            return self.current_mtex_path.parent
        root_dir = self._project_root_dir()
        if root_dir is not None:
            return root_dir
        return get_working_dir()

    def _is_inside_current_project(self, path: Path) -> bool:
        root_dir = self._project_root_dir()
        if root_dir is None:
            return False
        try:
            path.resolve().relative_to(root_dir.resolve())
            return True
        except ValueError:
            return False

    def _ensure_project_path(self, path: Path) -> bool:
        if self.current_project is None:
            QtWidgets.QMessageBox.information(self, "MathTeX", "Open a project first.")
            return False
        if self._is_inside_current_project(path):
            return True
        QtWidgets.QMessageBox.warning(
            self,
            "MathTeX",
            "Project files must stay inside the current project folder.",
        )
        return False

    def _ask_mtex_close_confirmation(self) -> str:
        location = str(self.current_mtex_path) if self.current_mtex_path else "current document"
        dialog = QtWidgets.QMessageBox(self)
        dialog.setWindowTitle("Unsaved Changes")
        dialog.setText(
            f"The file {location} has unsaved changes.\n"
            "Do you want to cancel, save, or discard those changes?"
        )
        dialog.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Save
            | QtWidgets.QMessageBox.StandardButton.Discard
            | QtWidgets.QMessageBox.StandardButton.Cancel
        )
        dialog.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Save)
        result = dialog.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Save:
            return "save"
        if result == QtWidgets.QMessageBox.StandardButton.Discard:
            return "discard"
        return "cancel"

    def _can_leave_project_workspace(self) -> bool:
        if self.mtex_editor is None or not self.mtex_editor.document().isModified():
            return True
        choice = self._ask_mtex_close_confirmation()
        if choice == "cancel":
            return False
        if choice == "save":
            return self._save_mtex_file()
        return True

    def _create_project(self) -> None:
        dialog = ProjectCreationDialog(default_projects_root(), self)
        if dialog.exec() != int(QtWidgets.QDialog.DialogCode.Accepted):
            return
        try:
            project = self.project_manager.create_project(dialog.project_name(), dialog.base_dir())
        except (FileExistsError, OSError, ValueError) as exc:
            QtWidgets.QMessageBox.critical(self, "New Project", str(exc))
            return
        self.project_registry.add_project(project)
        self.project_registry.save()
        self._refresh_project_home()
        self._open_project(project)

    def _choose_and_open_project(self) -> None:
        start_dir = self._project_root_dir() or default_projects_root()
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Open Project", str(start_dir))
        if not directory:
            return
        self._open_project_from_path(directory)

    def _open_project_from_path(self, path: str | Path) -> None:
        try:
            project = self.project_manager.open_project(path)
        except (FileNotFoundError, NotADirectoryError, OSError, ValueError) as exc:
            QtWidgets.QMessageBox.critical(self, "Open Project", str(exc))
            return
        self._open_project(project)

    def _open_project(self, project: ProjectInfo) -> None:
        if not self._can_leave_project_workspace():
            return
        self._reset_auto_compile_runtime()
        self._clear_editor_pdf_sync_state()
        self.current_project = project
        self.project_registry.add_project(project)
        self.project_registry.save()
        self._refresh_project_home()
        if self.project_workspace_widget is not None:
            self.project_workspace_widget.set_project(project)
        self.current_mtex_path = None
        self.last_generated_pdf = None
        self._clear_execution_result("Compile a project file to inspect logs, output files, and variables.")
        self._set_build_status("Build: Ready")
        self._open_mtex_file(project.main_path)
        self._show_project_workspace()
        self.append_output(f"[Project] Opened {project.name}")
        self._refresh_menu_bar_for_active_context()

    def _return_to_project_home(self) -> None:
        if not self._can_leave_project_workspace():
            return
        self._reset_auto_compile_runtime()
        self._clear_editor_pdf_sync_state()
        self.current_project = None
        self.current_mtex_path = None
        self.last_generated_pdf = None
        self._clear_execution_result("Open a project and compile to inspect logs, output files, and variables.")
        if self.project_workspace_widget is not None:
            self.project_workspace_widget.clear_workspace()
        self._set_build_status("Build: Ready")
        self._show_project_home()
        self._refresh_menu_bar_for_active_context()

    def _handle_project_file_activation(self, path: str) -> None:
        file_path = Path(path)
        if file_path.suffix.lower() == ".mtx":
            self._open_mtex_in_script(file_path)
            return
        self._open_mtex_file(file_path)

    def _update_mtex_dirty(self, changed: bool) -> None:
        if self.mtex_file_label is None:
            return
        if not self.current_mtex_path:
            self.mtex_file_label.setText("No file open")
            self._refresh_menu_bar_for_active_context()
            return
        mark = "*" if changed else ""
        self.mtex_file_label.setText(f"{mark}{self.current_mtex_path.name}")
        self._refresh_menu_bar_for_active_context()

    def _prompt_mtex_destination(self):
        initial = self.current_mtex_path.name if self.current_mtex_path else "main.mtex"
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save .mtex File",
            str(self._project_dialog_dir() / initial),
            "MathTeX Files (*.mtex);;All Files (*)",
        )
        if not filename:
            return None
        path = Path(filename)
        if path.suffix.lower() != ".mtex":
            path = path.with_suffix(".mtex")
        if not self._ensure_project_path(path):
            return None
        return path

    def _write_mtex_to_path(self, path: Path) -> None:
        if self.mtex_editor is None:
            raise RuntimeError("MTeX editor is not available.")
        content = self.mtex_editor.toPlainText()
        path.write_text(content, encoding="utf-8")

    def _persist_mtex(self, path: Path, announce: bool = False) -> bool:
        if not self._ensure_project_path(path):
            return False
        previous_path = self.current_mtex_path
        try:
            self._write_mtex_to_path(path)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "MathTeX", f"Could not save the file.\n{exc}")
            return False
        if (
            self.current_project is not None
            and previous_path is not None
            and previous_path.resolve() == self.current_project.main_path.resolve()
        ):
            relative_main = path.resolve().relative_to(self.current_project.path.resolve()).as_posix()
            self.current_project = replace(self.current_project, main_file=relative_main)
            self.project_manager.write_project_metadata(self.current_project)
        self.current_mtex_path = path
        if self.mtex_file_label is not None:
            self.mtex_file_label.setText(path.name)
        if self.mtex_editor is not None:
            self.mtex_editor.document().setModified(False)
        self._refresh_mtex_file_tree()
        self._refresh_menu_bar_for_active_context()
        return True

    def _open_mtex_file(self, path: Path | str | None = None) -> None:
        if isinstance(path, bool):
            path = None
        if isinstance(path, str):
            path = Path(path)
        if path is None:
            filename, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Open .mtex File",
                str(self._project_dialog_dir()),
                "MathTeX Files (*.mtex);;All Files (*)",
            )
            if not filename:
                return
            path = Path(filename)
        if not self._ensure_project_path(path):
            return
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "MathTeX", f"Could not open the file.\n{exc}")
            return
        if self.mtex_editor is None or self.preview is None:
            return
        self._auto_compile_timer.stop()
        self.auto_compile_controller.clear_pending_auto_rebuild()
        self._editor_pdf_sync_timer.stop()
        self._ignore_mtex_text_changes = True
        try:
            self.mtex_editor.setPlainText(content)
            self.mtex_editor.document().setModified(False)
            self.current_mtex_path = path
            if self.mtex_file_label is not None:
                self.mtex_file_label.setText(path.name)
            self._refresh_editor_pdf_sync_source(reset_cursor_signature=True)
            existing_pdf = self._derive_output_pdf_path(path)
            if existing_pdf.exists():
                self._load_pdf_preview(existing_pdf)
                self._refresh_editor_pdf_sync_artifacts(path)
            else:
                self.last_generated_pdf = None
                self._editor_pdf_sync.update_compiled_landmarks(toc_path=None, aux_path=None)
                self._last_synced_cursor_signature = None
                self.preview.set_message("Compile to refresh the preview.")
        finally:
            self._ignore_mtex_text_changes = False
        self._set_active_main_tab(1)
        self._refresh_menu_bar_for_active_context()

    def _save_mtex_file(self) -> bool:
        if self.current_mtex_path is None:
            return self._save_mtex_file_as() is not None
        return self._persist_mtex(self.current_mtex_path)

    def _save_mtex_file_as(self):
        destination = self._prompt_mtex_destination()
        if not destination:
            return None
        if self._persist_mtex(destination):
            return destination
        return None

    def _write_preview_temp_file(self):
        destination = self._temp_preview_path / "preview.mtex"
        try:
            self._write_mtex_to_path(destination)
        except OSError as exc:
            self.append_output(f"[MTeX] Could not write temporary draft: {exc}")
            return None
        return destination

    def _resolve_current_mtex_compile_path(self) -> Path | None:
        if self.current_project is None:
            QtWidgets.QMessageBox.information(self, "MathTeX", "Open a project before compiling.")
            return None
        if self.current_mtex_path:
            path = self.current_mtex_path
            if path.suffix.lower() != ".mtex":
                QtWidgets.QMessageBox.information(
                    self,
                    "MathTeX",
                    "Only .mtex documents can be compiled to PDF in MTeX Studio.\n"
                    "Open .mtx scripts in the Interactive Editor and use Run All instead.",
                )
                return None
            if not self._persist_mtex(path, announce=False):
                return None
        else:
            path = self._write_preview_temp_file()
            if not path:
                return None
        return path

    def _request_current_mtex_compile(self, trigger: CompileTrigger = "manual") -> None:
        if trigger == "manual":
            self._auto_compile_timer.stop()
            self.auto_compile_controller.clear_pending_auto_rebuild()
        decision = self.auto_compile_controller.request_build(trigger)
        if decision.kind != "start" or decision.trigger is None:
            return
        self._execute_current_mtex_compile(decision.trigger)

    def _execute_current_mtex_compile(self, trigger: CompileTrigger) -> None:
        next_trigger: CompileTrigger | None = trigger
        while next_trigger is not None:
            path = self._resolve_current_mtex_compile_path()
            if path is None:
                return
            self.auto_compile_controller.begin_build()
            follow_up = None
            try:
                self._run_mtex_compilation(path, trigger=next_trigger)
            finally:
                follow_up = self.auto_compile_controller.finish_build()
            if follow_up.kind == "start" and follow_up.trigger is not None:
                next_trigger = follow_up.trigger
            else:
                next_trigger = None

    def _compile_current_mtex(self) -> None:
        self._request_current_mtex_compile("manual")

    def _build_artifacts_for_source(self, source_path: Path):
        project_root = self.current_project.path if self.current_project is not None else source_path.parent
        output_basename = source_path.stem
        if self.current_project is not None:
            try:
                if source_path.resolve() == self.current_project.main_path.resolve():
                    output_basename = self.current_project.name
            except OSError:
                output_basename = source_path.stem
        return self.output_manager.artifacts_for_source(
            source_path,
            project_root=project_root,
            output_basename=output_basename,
        )

    def _derive_output_pdf_path(self, source_path: Path) -> Path:
        return self._build_artifacts_for_source(source_path).pdf_path

    def _load_pdf_preview(self, pdf_path: Path) -> None:
        if self.preview is None:
            return
        if not pdf_path or not pdf_path.exists():
            self.preview.set_message(f"Generated PDF not found.\n{pdf_path}")
            return
        if self.preview.load_pdf(pdf_path, preserve_state=True):
            self.last_generated_pdf = pdf_path

    def _capture_current_variable_summaries(self):
        try:
            return variable_summaries_from_snapshot(workspace_snapshot())
        except Exception:
            return []

    def _run_mtex_compilation(self, path: Path, trigger: CompileTrigger = "manual") -> None:
        artifacts = self._build_artifacts_for_source(path)
        artifacts.build_dir.mkdir(parents=True, exist_ok=True)
        collector = StructuredLogCollector()
        trigger_label = "Auto compile" if trigger == "auto" else "Manual compile"
        status_prefix = "Auto build" if trigger == "auto" else "Manual build"
        self._set_build_status(f"Build: {status_prefix} in progress...", tone="info")
        collector.add_entry(f"{trigger_label} started for {path}", source="app")
        collector.add_entry(f"Build directory: {artifacts.build_dir}", source="app")
        generated_pdf = None
        try:
            with redirect_stdout(collector.stream("stdout")), redirect_stderr(collector.stream("stderr")):
                generated_pdf = ejecutar_mtex(
                    str(path),
                    env_ast,
                    abrir_pdf=False,
                    build_dir=artifacts.build_dir,
                    output_basename=artifacts.tex_path.stem,
                )
        except Exception as exc:  # pragma: no cover - defensivo
            collector.add_entry(f"Unexpected error during compilation: {exc}", level="error", source="app")
        self._refresh_mtex_file_tree()
        generated_pdf_path = Path(generated_pdf) if generated_pdf else None
        success = generated_pdf_path is not None and generated_pdf_path.exists()
        available_pdf = generated_pdf_path if success else (artifacts.pdf_path if artifacts.pdf_path.exists() else None)
        kept_previous_pdf = False
        if success and generated_pdf_path is not None:
            collector.add_entry(f"{trigger_label} finished successfully. PDF updated: {generated_pdf_path}", source="app")
            self._load_pdf_preview(generated_pdf_path)
            self._refresh_editor_pdf_sync_artifacts(path)
            self._set_build_status(f"Build: {status_prefix} succeeded", tone="success")
        else:
            latex_summary = summarize_latex_build_failure(artifacts.compile_log_path)
            if latex_summary:
                collector.add_entry(f"LaTeX error summary: {latex_summary}", level="error", source="latex")
            latex_explanation = explain_latex_build_failure(artifacts.compile_log_path, artifacts.tex_path)
            if latex_explanation:
                collector.add_entry(f"Probable cause: {latex_explanation}", level="warning", source="latex")
            collector.add_entry(
                f"{trigger_label} failed or did not produce a new PDF.",
                level="error",
                source="app",
            )
            if available_pdf is not None:
                collector.add_entry(f"Keeping last available PDF preview: {available_pdf}", source="app")
                self.last_generated_pdf = available_pdf
                kept_previous_pdf = True
            elif self.last_generated_pdf is not None and self.last_generated_pdf.exists():
                collector.add_entry(
                    f"Keeping last available PDF preview: {self.last_generated_pdf}",
                    source="app",
                )
                available_pdf = self.last_generated_pdf
                kept_previous_pdf = True
            elif self.preview is not None:
                self.preview.set_message("Compilation failed. No PDF is available yet. Check the console output.")
            if kept_previous_pdf:
                self._refresh_editor_pdf_sync_artifacts(path)
                self._set_build_status(
                    f"Build: {status_prefix} failed, showing last valid PDF",
                    tone="warning",
                )
            else:
                self._set_build_status(f"Build: {status_prefix} failed", tone="error")
        collector.add_entry(f"{trigger_label} finished.", source="app")

        result = collector.build_result(
            success=success,
            source_path=path,
            pdf_path=available_pdf,
            build_dir=artifacts.build_dir,
            output_files=self.output_manager.list_output_files(artifacts.build_dir),
            variables=self._capture_current_variable_summaries(),
        )
        self.latest_mtex_execution_result = result
        if self.logs_output_widget is not None:
            self.logs_output_widget.set_execution_result(result)

    def _get_current_pdf_path(self):
        if self.last_generated_pdf and Path(self.last_generated_pdf).exists():
            return Path(self.last_generated_pdf)
        if self.current_mtex_path:
            candidate = self._derive_output_pdf_path(self.current_mtex_path)
            if candidate.exists():
                return candidate
        return None

    def _download_mtex_pdf(self) -> None:
        pdf_path = self._get_current_pdf_path()
        if not pdf_path:
            QtWidgets.QMessageBox.information(self, "MathTeX", "Compile an .mtex file before downloading the PDF.")
            return
        destination, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Download PDF",
            str(self._project_dialog_dir() / pdf_path.name),
            "PDF (*.pdf);;All Files (*)",
        )
        if not destination:
            return
        try:
            shutil.copyfile(pdf_path, destination)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "MathTeX", f"Could not copy the PDF.\n{exc}")
            return
        self.append_output(f"[MTeX] PDF exportado a {destination}")
    # ----- Ejecucion ------------------------------------------------------
    def _looks_like_error(self, text: str) -> bool:
        error_prefixes = (
            "error",
            "parse error",
            "block error",
            "runtime error",
            "build error",
            "syntax error",
            "usage",
            "warning",
            "invalid",
        )
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # Evita falsos positivos en asignaciones tipo "error = 0"
            if re.match(r"^[A-Za-z_]\w*\s*=", stripped):
                continue
            lowered = stripped.lower()
            if any(lowered.startswith(prefix) for prefix in error_prefixes):
                return True
            if "error:" in lowered:
                return True
        return False

    def _execute_line(self, line: str, echo: bool = True) -> bool:
        stripped = line.strip()
        if not stripped:
            return True
        if echo:
            self.append_output(f"MathTeX> {stripped}")
        out_buffer = io.StringIO()
        err_buffer = io.StringIO()
        try:
            with redirect_stdout(out_buffer), redirect_stderr(err_buffer):
                ejecutar_linea(stripped)
        except Exception as exc:  # pragma: no cover - defensivo
            err_buffer.write(f"Unexpected error: {exc}\n")
        output = out_buffer.getvalue()
        errors = err_buffer.getvalue()
        has_error = False
        if output:
            self.append_output(output, ensure_newline=False)
            if self._looks_like_error(output):
                has_error = True
        if errors:
            self.append_output(errors, ensure_newline=False)
            has_error = True
        self.refresh_workspace_view()
        return not has_error

    def run_command(self) -> None:
        comando = self.console_widget.output.current_input().strip("\n")
        self.console_widget.output.clear_input()
        self._remove_trailing_prompt()
        lines = split_code_statements(comando)
        if not lines:
            self._append_prompt()
            self.console_widget.input.setFocus()
            return
        for line in lines:
            self.append_output(f"MathTeX> {line}")
            self._execute_line(line, echo=False)
        self._append_prompt()
        self.console_widget.input.setFocus()

    def run_script(self) -> None:
        doc = self._current_script_doc()
        if not doc:
            self.append_output("There is no active editor to run.")
            return
        widget: CodeEditor = doc["widget"]
        contenido = widget.toPlainText()
        statements = split_code_statements_with_lines(contenido)
        if not statements:
            self.append_output("There is no code to run.")
            return
        reset_environment()
        self.refresh_workspace_view()
        self.append_output("[Running script]")
        aborted = False
        try:
            for statement in statements:
                with diagnostic_line_offset(statement.start_line - 1):
                    ok = self._execute_line(statement.text, echo=False)
                if not ok:
                    aborted = True
                    self.append_output("[Execution stopped due to an error]\n")
                    break
            if not aborted:
                self.append_output("[Script finished]\n")
        finally:
            self._append_prompt()
            self.refresh_workspace_view()

    def run_selection(self) -> None:
        doc = self._current_script_doc()
        if not doc:
            self.append_output("There is no active editor to run.")
            return
        widget: CodeEditor = doc["widget"]
        cursor = widget.textCursor()
        if not cursor.hasSelection():
            self.append_output("Select a block in the editor to run only that part.")
            return
        seleccion = cursor.selectedText().replace("\u2029", "\n")
        selection_start = min(cursor.selectionStart(), cursor.selectionEnd())
        selection_start_line = widget.document().findBlock(selection_start).blockNumber() + 1
        statements = split_code_statements_with_lines(seleccion)
        if not statements:
            self.append_output("The selection is empty.")
            return
        self.append_output("[Running selection]")
        aborted = False
        try:
            for statement in statements:
                with diagnostic_line_offset(selection_start_line + statement.start_line - 2):
                    ok = self._execute_line(statement.text, echo=False)
                if not ok:
                    aborted = True
                    self.append_output("[Execution stopped due to an error]\n")
                    break
            if not aborted:
                self.append_output("[Selection finished]\n")
        finally:
            self._append_prompt()
            self.refresh_workspace_view()

    # ----- Plot listener --------------------------------------------------
    def _register_plot_listener(self) -> None:
        if self._plot_listener_registered:
            return
        try:
            register_plot_listener(self._handle_plot_generated)
            self._plot_listener_registered = True
        except Exception:
            self._plot_listener_registered = False

    def _unregister_plot_listener(self) -> None:
        if not self._plot_listener_registered:
            return
        try:
            unregister_plot_listener(self._handle_plot_generated)
        except Exception:
            pass
        finally:
            self._plot_listener_registered = False

    def _register_console_clear_listener(self) -> None:
        if self._console_clear_listener_registered:
            return
        try:
            register_console_clear_listener(self._handle_console_clean)
            self._console_clear_listener_registered = True
        except Exception:
            self._console_clear_listener_registered = False

    def _unregister_console_clear_listener(self) -> None:
        if not self._console_clear_listener_registered:
            return
        try:
            unregister_console_clear_listener(self._handle_console_clean)
        except Exception:
            pass
        finally:
            self._console_clear_listener_registered = False

    def _handle_console_clean(self) -> None:
        if self.console_widget is not None:
            self.console_widget.clear()

    def _handle_plot_generated(self, filepath: str, plot_name: str | None) -> None:
        path = Path(filepath)
        if not path.exists():
            return
        pixmap = QtGui.QPixmap(str(path))
        caption = plot_name or path.stem
        if pixmap.isNull():
            self.append_output(f"[Grafico: {caption}] {filepath}")
            return
        window = QtWidgets.QMainWindow(self)
        window.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.setWindowTitle(f"Figura - {caption}")
        window.resize(960, 700)

        scroll = QtWidgets.QScrollArea(window)
        scroll.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)

        label = QtWidgets.QLabel()
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        label.setPixmap(pixmap)
        layout.addWidget(label)

        scroll.setWidget(container)
        window.setCentralWidget(scroll)
        window.show()
        window.raise_()
        window.activateWindow()

        self._plot_windows.append(window)
        window.destroyed.connect(lambda *_: self._plot_windows.remove(window) if window in self._plot_windows else None)

    def _clear_editor_pdf_sync_state(self) -> None:
        self._editor_pdf_sync_timer.stop()
        self._editor_pdf_sync.clear()
        self._last_structural_cursor_signature = None
        self._last_synced_cursor_signature = None

    def _refresh_editor_pdf_sync_source(self, *, reset_cursor_signature: bool = False) -> None:
        if self.mtex_editor is None:
            self._editor_pdf_sync.update_source("")
            self._last_structural_cursor_signature = None
            self._last_synced_cursor_signature = None
            return
        self._editor_pdf_sync.update_source(self.mtex_editor.toPlainText())
        if reset_cursor_signature:
            self._last_structural_cursor_signature = None
            self._last_synced_cursor_signature = None

    def _refresh_editor_pdf_sync_artifacts(self, source_path: Path | None) -> None:
        if source_path is None:
            self._editor_pdf_sync.update_compiled_landmarks(toc_path=None, aux_path=None)
            self._last_synced_cursor_signature = None
            return
        artifacts = self._build_artifacts_for_source(source_path)
        # Prefer compiled TOC/AUX data over PDF text heuristics in this first stage.
        self._editor_pdf_sync.update_compiled_landmarks(
            toc_path=artifacts.toc_path,
            aux_path=artifacts.aux_path,
        )
        self._last_synced_cursor_signature = None

    def _current_mtex_cursor_line(self) -> int | None:
        if self.mtex_editor is None:
            return None
        return self.mtex_editor.textCursor().blockNumber() + 1

    def _on_mtex_cursor_position_changed(self) -> None:
        if self._ignore_mtex_text_changes or not self._is_studio_workspace_active():
            return
        line_number = self._current_mtex_cursor_line()
        if line_number is None:
            return
        landmark = self._editor_pdf_sync.current_landmark_for_line(line_number)
        signature = landmark.signature if landmark is not None else None
        if signature == self._last_structural_cursor_signature:
            return
        self._last_structural_cursor_signature = signature
        self._editor_pdf_sync_timer.stop()
        if signature is not None:
            self._editor_pdf_sync_timer.start()

    def _sync_editor_position_to_preview(self, *, force: bool = False) -> None:
        if not self._is_studio_workspace_active() or self.preview is None:
            return
        if self.preview.current_pdf_path() is None:
            return
        line_number = self._current_mtex_cursor_line()
        if line_number is None:
            return
        target = self._editor_pdf_sync.resolve_target_for_line(line_number)
        if target is None:
            return
        signature = target.landmark.signature
        current_page = self.preview.current_page_index()
        if not force and signature == self._last_synced_cursor_signature and current_page == target.page_index:
            return
        if current_page == target.page_index:
            self._last_synced_cursor_signature = signature
            return
        if self.preview.jump_to_page_index(target.page_index):
            self._last_synced_cursor_signature = signature

    # ----- Eventos --------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._can_leave_project_workspace():
            event.ignore()
            return
        self._unregister_plot_listener()
        self._unregister_console_clear_listener()
        for win in list(self._plot_windows):
            try:
                win.close()
            except Exception:
                pass
        self._plot_windows = []
        if self._temp_preview_dir is not None:
            try:
                self._temp_preview_dir.cleanup()
            except Exception:
                pass
            self._temp_preview_dir = None
        super().closeEvent(event)


def launch_qt_gui() -> bool:
    """Try to open the Qt interface. Return False if it is not possible."""
    if not QT_AVAILABLE:
        return False
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    window = MathTeXQtWindow()
    window.show()
    try:
        app.exec()
    except KeyboardInterrupt:
        return False
    except Exception:
        return False
    return True

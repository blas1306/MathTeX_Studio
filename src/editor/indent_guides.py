from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PySide6 import QtCore, QtGui, QtWidgets


@dataclass(frozen=True)
class IndentGuide:
    column: int
    start_block: int
    end_block: int
    active: bool = False


def visual_indent_width(text: str, *, tab_size: int = 4) -> int:
    """Return the visual width of the leading whitespace."""
    tab_size = max(1, tab_size)
    width = 0
    for char in text:
        if char == " ":
            width += 1
        elif char == "\t":
            width += tab_size - (width % tab_size)
        else:
            break
    return width


def guide_columns_for_line(text: str, *, indent_width: int = 4, tab_size: int = 4) -> tuple[int, ...]:
    indent = visual_indent_width(text, tab_size=tab_size)
    return _guide_columns_for_indent(indent, indent_width=indent_width)


def active_guide_column(
    lines: list[str],
    cursor_block: int,
    *,
    indent_width: int = 4,
    tab_size: int = 4,
) -> int | None:
    if not lines:
        return None

    cursor_block = max(0, min(cursor_block, len(lines) - 1))
    indent = _line_indent_for_guides(lines, cursor_block, indent_width=indent_width, tab_size=tab_size)
    columns = _guide_columns_for_indent(indent, indent_width=indent_width)
    if not columns:
        return None
    return columns[-1]


def calculate_indent_guides(
    lines: list[str],
    cursor_block: int,
    *,
    indent_width: int = 4,
    tab_size: int = 4,
) -> list[IndentGuide]:
    """Build contiguous indent guide ranges from plain text indentation."""
    if not lines:
        return []

    indent_width = max(1, indent_width)
    active_column = active_guide_column(
        lines,
        cursor_block,
        indent_width=indent_width,
        tab_size=tab_size,
    )
    cursor_block = max(0, min(cursor_block, len(lines) - 1))
    open_guides: dict[int, int] = {}
    guides: list[IndentGuide] = []

    for block_number, line in enumerate(lines):
        indent = _line_indent_for_guides(lines, block_number, indent_width=indent_width, tab_size=tab_size)
        columns = set(_guide_columns_for_indent(indent, indent_width=indent_width))

        for column in sorted(set(open_guides) - columns):
            start_block = open_guides.pop(column)
            guides.append(
                IndentGuide(
                    column=column,
                    start_block=start_block,
                    end_block=block_number - 1,
                    active=column == active_column and start_block <= cursor_block <= block_number - 1,
                )
            )

        for column in sorted(columns - set(open_guides)):
            open_guides[column] = block_number

    last_block = len(lines) - 1
    for column, start_block in sorted(open_guides.items()):
        guides.append(
            IndentGuide(
                column=column,
                start_block=start_block,
                end_block=last_block,
                active=column == active_column and start_block <= cursor_block <= last_block,
            )
        )

    return sorted(guides, key=lambda guide: (guide.start_block, guide.column, guide.end_block))


class QtIndentGuideRenderer:
    def __init__(
        self,
        editor: "QtWidgets.QPlainTextEdit",
        *,
        indent_width: int = 4,
        color: str = "#ffffff",
        active_color: str = "#f7dc6f",
        alpha: int = 34,
        active_alpha: int = 92,
    ) -> None:
        self._editor = editor
        self._indent_width = max(1, indent_width)
        self._color = color
        self._active_color = active_color
        self._alpha = max(0, min(alpha, 255))
        self._active_alpha = max(0, min(active_alpha, 255))

    def paint(self, event: "QtGui.QPaintEvent") -> None:
        from PySide6 import QtCore, QtGui

        lines = _document_lines(self._editor)
        if not lines:
            return

        cursor_block = self._editor.textCursor().blockNumber()
        guides = calculate_indent_guides(
            lines,
            cursor_block,
            indent_width=self._indent_width,
            tab_size=self._tab_size_columns(),
        )
        if not guides:
            return

        guides_by_block = _guides_by_block(guides)
        painter = QtGui.QPainter(self._editor.viewport())
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        regular_pen = self._pen(QtGui.QColor(self._color), self._alpha)
        active_pen = self._pen(QtGui.QColor(self._active_color), self._active_alpha)

        space_width = max(1.0, float(self._editor.fontMetrics().horizontalAdvance(" ")))
        content_x = float(self._editor.contentOffset().x())
        block = self._editor.firstVisibleBlock()
        top = self._editor.blockBoundingGeometry(block).translated(self._editor.contentOffset()).top()
        bottom = top + self._editor.blockBoundingRect(block).height()
        rect = event.rect()

        while block.isValid() and top <= rect.bottom():
            block_number = block.blockNumber()
            if block.isVisible() and bottom >= rect.top():
                for guide in guides_by_block.get(block_number, ()):
                    x = content_x + guide.column * space_width
                    if -2 <= x <= self._editor.viewport().width() + 2:
                        painter.setPen(active_pen if guide.active else regular_pen)
                        painter.drawLine(QtCore.QPointF(x + 0.5, top), QtCore.QPointF(x + 0.5, bottom))

            block = block.next()
            top = bottom
            bottom = top + self._editor.blockBoundingRect(block).height()

    def _pen(self, color: "QtGui.QColor", alpha: int) -> "QtGui.QPen":
        from PySide6 import QtCore, QtGui

        color.setAlpha(alpha)
        pen = QtGui.QPen(color)
        pen.setWidthF(1.0)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.FlatCap)
        return pen

    def _tab_size_columns(self) -> int:
        space_width = max(1.0, float(self._editor.fontMetrics().horizontalAdvance(" ")))
        return max(1, round(float(self._editor.tabStopDistance()) / space_width))


def _line_indent_for_guides(lines: list[str], block_number: int, *, indent_width: int, tab_size: int) -> int:
    line = lines[block_number]
    if line.strip():
        return visual_indent_width(line, tab_size=tab_size)

    before = _nearest_nonblank_indent(lines, block_number, -1, indent_width=indent_width, tab_size=tab_size)
    after = _nearest_nonblank_indent(lines, block_number, 1, indent_width=indent_width, tab_size=tab_size)
    if before is None:
        return after or 0
    if after is None:
        return before
    return min(before, after)


def _nearest_nonblank_indent(
    lines: list[str],
    start: int,
    step: int,
    *,
    indent_width: int,
    tab_size: int,
) -> int | None:
    index = start + step
    while 0 <= index < len(lines):
        if lines[index].strip():
            return visual_indent_width(lines[index], tab_size=tab_size)
        index += step
    return None


def _guide_columns_for_indent(indent: int, *, indent_width: int) -> tuple[int, ...]:
    if indent <= 0:
        return ()
    indent_width = max(1, indent_width)
    return tuple(range(0, indent, indent_width))


def _document_lines(editor: "QtWidgets.QPlainTextEdit") -> list[str]:
    lines: list[str] = []
    block = editor.document().firstBlock()
    while block.isValid():
        lines.append(block.text())
        block = block.next()
    return lines


def _guides_by_block(guides: list[IndentGuide]) -> dict[int, list[IndentGuide]]:
    by_block: dict[int, list[IndentGuide]] = {}
    for guide in guides:
        for block_number in range(guide.start_block, guide.end_block + 1):
            by_block.setdefault(block_number, []).append(guide)
    return by_block

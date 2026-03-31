from __future__ import annotations

from qt_app import CodeEditor


def _block_format_colors(editor: CodeEditor, block_number: int) -> list[tuple[int, int, str]]:
    block = editor.document().findBlockByNumber(block_number)
    layout = block.layout()
    return [
        (fmt.start, fmt.length, fmt.format.foreground().color().name())
        for fmt in layout.formats()
    ]


def _has_color_at(editor: CodeEditor, block_number: int, start: int, length: int, color: str) -> bool:
    for fmt_start, fmt_length, fmt_color in _block_format_colors(editor, block_number):
        if fmt_color != color:
            continue
        fmt_end = fmt_start + fmt_length
        target_end = start + length
        if fmt_start <= start and target_end <= fmt_end:
            return True
    return False


def test_script_keywords_are_highlighted_but_not_inside_comments(qapp) -> None:
    editor = CodeEditor()
    editor.set_autocomplete_document_kind("script")
    editor.setPlainText("if x\n# if comment\n")
    qapp.processEvents()

    assert _has_color_at(editor, 0, 0, 2, "#a30101")
    assert not _has_color_at(editor, 1, 2, 2, "#a30101")

    editor.close()


def test_mtex_keywords_are_highlighted_only_inside_code_blocks(qapp) -> None:
    editor = CodeEditor()
    editor.set_autocomplete_document_kind("mtex_document")
    editor.setPlainText(
        "if outside\n"
        "\\begin{code}\n"
        "if inside\n"
        "% if comment\n"
        "\\end{code}\n"
        "if outside again\n"
    )
    qapp.processEvents()

    assert not _has_color_at(editor, 0, 0, 2, "#a30101")
    assert _has_color_at(editor, 2, 0, 2, "#a30101")
    assert not _has_color_at(editor, 3, 2, 2, "#a30101")
    assert not _has_color_at(editor, 5, 0, 2, "#a30101")

    editor.close()

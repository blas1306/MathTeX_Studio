from __future__ import annotations

import pytest

from qt_app import CodeEditor


@pytest.fixture()
def editor(qapp):
    widget = CodeEditor(enable_autocomplete=True)
    widget.set_autocomplete_document_kind("script")
    widget.set_autocomplete_workspace_provider(lambda: [])
    widget.resize(640, 320)
    widget.show()
    widget.setFocus()
    qapp.processEvents()
    yield widget
    widget.close()
    qapp.processEvents()


def test_moving_cursor_to_complete_word_does_not_open_popup_automatically(editor: CodeEditor, qapp) -> None:
    editor.setPlainText("function y = demo(x)")
    qapp.processEvents()
    editor._hide_autocomplete()

    cursor = editor.textCursor()
    cursor.setPosition(0)
    editor.setTextCursor(cursor)
    qapp.processEvents()

    cursor.setPosition(len("function"))
    editor.setTextCursor(cursor)
    qapp.processEvents()

    assert editor._autocomplete_popup is not None
    assert editor._autocomplete_popup.is_visible() is False
    assert editor._autocomplete_popup.current_suggestion() is None


def test_editing_existing_word_can_open_popup_again(editor: CodeEditor, qapp) -> None:
    editor.setPlainText("function")
    qapp.processEvents()
    editor._hide_autocomplete()

    cursor = editor.textCursor()
    cursor.setPosition(len("function"))
    editor.setTextCursor(cursor)
    qapp.processEvents()

    cursor = editor.textCursor()
    cursor.deletePreviousChar()
    editor.setTextCursor(cursor)
    qapp.processEvents()
    editor._refresh_autocomplete(trigger="text")
    qapp.processEvents()

    assert editor._autocomplete_popup is not None
    current = editor._autocomplete_popup.current_suggestion()
    assert current is not None
    assert current.name == "function"


def test_manual_autocomplete_invocation_still_works_on_complete_word(editor: CodeEditor, qapp) -> None:
    editor.setPlainText("function")
    qapp.processEvents()
    editor._hide_autocomplete()

    cursor = editor.textCursor()
    cursor.setPosition(len("function"))
    editor.setTextCursor(cursor)
    qapp.processEvents()

    editor._show_autocomplete_manually()
    qapp.processEvents()

    assert editor._autocomplete_popup is not None
    current = editor._autocomplete_popup.current_suggestion()
    assert current is not None
    assert current.name == "function"


def test_normal_writing_still_opens_popup_for_partial_tokens(editor: CodeEditor, qapp) -> None:
    editor.setPlainText(r"\pl")
    qapp.processEvents()
    editor._hide_autocomplete()

    cursor = editor.textCursor()
    cursor.setPosition(len(r"\pl"))
    editor.setTextCursor(cursor)
    qapp.processEvents()
    editor._refresh_autocomplete(trigger="text")
    qapp.processEvents()

    assert editor._autocomplete_popup is not None
    current = editor._autocomplete_popup.current_suggestion()
    assert current is not None
    assert current.name == r"\plot()"


def test_popup_is_child_of_editor_viewport_and_opens_below_cursor(editor: CodeEditor, qapp) -> None:
    editor.setPlainText(r"\pl")
    qapp.processEvents()
    editor._hide_autocomplete()

    cursor = editor.textCursor()
    cursor.setPosition(len(r"\pl"))
    editor.setTextCursor(cursor)
    qapp.processEvents()
    editor._refresh_autocomplete(trigger="text")
    qapp.processEvents()

    popup = editor._autocomplete_popup
    assert popup is not None
    assert popup.is_visible() is True
    assert popup.parentWidget() is editor.viewport()
    assert popup.isWindow() is False

    popup_rect = popup.geometry()
    viewport_rect = editor.viewport().rect()
    assert viewport_rect.contains(popup_rect)
    assert popup_rect.top() >= editor.cursorRect().bottom()


def test_editor_suggests_document_symbols_without_runtime_state(editor: CodeEditor, qapp) -> None:
    editor.setPlainText("A = [1,2;3,4]\nA")
    qapp.processEvents()
    editor._hide_autocomplete()

    cursor = editor.textCursor()
    cursor.setPosition(len("A = [1,2;3,4]\nA"))
    editor.setTextCursor(cursor)
    qapp.processEvents()
    editor._refresh_autocomplete(trigger="text")
    qapp.processEvents()

    assert editor._autocomplete_popup is not None
    current = editor._autocomplete_popup.current_suggestion()
    assert current is not None
    assert current.name == "A"
    assert current.source == "document"


def test_editor_ignores_document_symbols_defined_after_the_cursor(editor: CodeEditor, qapp) -> None:
    editor.setPlainText("la\nlaterValue = 1")
    qapp.processEvents()
    editor._hide_autocomplete()

    cursor = editor.textCursor()
    cursor.setPosition(len("la"))
    editor.setTextCursor(cursor)
    qapp.processEvents()
    editor._refresh_autocomplete(trigger="text")
    qapp.processEvents()

    assert editor._autocomplete_popup is not None
    assert editor._autocomplete_popup.is_visible() is False
    assert editor._autocomplete_popup.current_suggestion() is None


def test_enter_on_keyword_autocomplete_expands_block_immediately(editor: CodeEditor, qapp) -> None:
    editor.setPlainText("for")
    qapp.processEvents()
    editor._hide_autocomplete()

    cursor = editor.textCursor()
    cursor.setPosition(len("for"))
    editor.setTextCursor(cursor)
    qapp.processEvents()
    editor._refresh_autocomplete(trigger="text")
    qapp.processEvents()

    assert editor._autocomplete_popup is not None
    current = editor._autocomplete_popup.current_suggestion()
    assert current is not None
    assert current.name == "for"
    assert current.kind == "snippet"

    editor._accept_autocomplete_and_maybe_expand_block(current)
    qapp.processEvents()

    assert editor.toPlainText() == "for x in iterable {\n    \n}"
    cursor = editor.textCursor()
    assert cursor.blockNumber() == 0
    assert cursor.selectionStart() == len("for ")
    assert cursor.selectionEnd() == len("for x")


def test_enter_before_existing_for_line_does_not_expand_block(editor: CodeEditor, qapp) -> None:
    editor.setPlainText("for i = 1:3")
    qapp.processEvents()

    cursor = editor.textCursor()
    cursor.setPosition(0)
    editor.setTextCursor(cursor)
    qapp.processEvents()

    editor._handle_return()
    qapp.processEvents()

    assert editor.toPlainText() == "\nfor i = 1:3"

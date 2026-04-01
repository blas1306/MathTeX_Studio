from __future__ import annotations

from pathlib import Path

import pytest
from PySide6 import QtGui

from project_system import ProjectManager
from qt_app import MathTeXQtWindow


@pytest.fixture()
def studio_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    window = MathTeXQtWindow()
    manager = ProjectManager()
    project = manager.create_project("EditorSyncProject", tmp_path)
    window._open_project(project)
    qapp.processEvents()
    yield window
    if window.mtex_editor is not None:
        window.mtex_editor.document().setModified(False)
    window._reset_auto_compile_runtime()
    window.current_project = None
    window.current_mtex_path = None
    window.close()
    qapp.processEvents()


def _move_cursor_to_line(window: MathTeXQtWindow, line_number: int, qapp) -> None:
    assert window.mtex_editor is not None
    cursor = window.mtex_editor.textCursor()
    cursor.movePosition(QtGui.QTextCursor.MoveOperation.Start)
    cursor.movePosition(
        QtGui.QTextCursor.MoveOperation.Down,
        QtGui.QTextCursor.MoveMode.MoveAnchor,
        max(0, line_number - 1),
    )
    window.mtex_editor.setTextCursor(cursor)
    qapp.processEvents()


def test_editor_sync_jumps_only_when_cursor_enters_a_new_structural_region(
    studio_window: MathTeXQtWindow,
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    assert studio_window.current_mtex_path is not None
    assert studio_window.preview is not None

    source_path = studio_window.current_mtex_path
    source_path.write_text(
        "\\section{Intro}\n"
        "Intro line one.\n"
        "Intro line two.\n"
        "\\subsection{Details}\n"
        "Details line.\n"
        "\\section{Conclusion}\n"
        "Done.\n",
        encoding="utf-8",
    )

    artifacts = studio_window._build_artifacts_for_source(source_path)
    artifacts.build_dir.mkdir(parents=True, exist_ok=True)
    artifacts.pdf_path.write_bytes(b"%PDF-1.4\n%editor-sync\n")
    artifacts.toc_path.write_text(
        r"\contentsline {section}{\numberline {1}Intro}{2}{section.1}%" "\n"
        r"\contentsline {subsection}{\numberline {1.1}Details}{3}{subsection.1.1}%" "\n"
        r"\contentsline {section}{\numberline {2}Conclusion}{5}{section.2}%" "\n",
        encoding="utf-8",
    )

    current_page = {"value": 0}
    jumps: list[int] = []
    monkeypatch.setattr(studio_window.preview, "current_pdf_path", lambda: artifacts.pdf_path)
    monkeypatch.setattr(studio_window.preview, "current_page_index", lambda: current_page["value"])

    def _fake_jump(page_index: int) -> bool:
        jumps.append(page_index)
        current_page["value"] = page_index
        return True

    monkeypatch.setattr(studio_window.preview, "jump_to_page_index", _fake_jump)

    studio_window._open_mtex_file(source_path)
    qapp.processEvents()

    _move_cursor_to_line(studio_window, 2, qapp)
    assert studio_window._editor_pdf_sync_timer.isActive() is True
    studio_window._editor_pdf_sync_timer.stop()
    studio_window._sync_editor_position_to_preview()
    assert jumps == [1]

    _move_cursor_to_line(studio_window, 3, qapp)
    assert studio_window._editor_pdf_sync_timer.isActive() is False
    studio_window._sync_editor_position_to_preview()
    assert jumps == [1]

    _move_cursor_to_line(studio_window, 5, qapp)
    assert studio_window._editor_pdf_sync_timer.isActive() is True
    studio_window._editor_pdf_sync_timer.stop()
    studio_window._sync_editor_position_to_preview()
    assert jumps == [1, 2]

    _move_cursor_to_line(studio_window, 7, qapp)
    assert studio_window._editor_pdf_sync_timer.isActive() is True
    studio_window._editor_pdf_sync_timer.stop()
    studio_window._sync_editor_position_to_preview()
    assert jumps == [1, 2, 4]

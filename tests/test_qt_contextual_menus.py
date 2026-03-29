from __future__ import annotations

from pathlib import Path

from PySide6 import QtGui  # type: ignore

from qt_app import MathTeXQtWindow
from project_system import ProjectManager


def _menu_titles(window: MathTeXQtWindow) -> list[str]:
    return [action.text().replace("&", "") for action in window.menuBar().actions()]


def _menu_actions(window: MathTeXQtWindow, menu_title: str) -> list[str]:
    for action in window.menuBar().actions():
        if action.text().replace("&", "") != menu_title:
            continue
        menu = action.menu()
        if menu is None:
            return []
        return [entry.text() for entry in menu.actions() if not entry.isSeparator()]
    return []


def test_menu_bar_switches_between_interactive_and_studio(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    window = MathTeXQtWindow()

    try:
        qapp.processEvents()

        assert _menu_titles(window) == ["File", "Edit", "View", "Run", "Tools", "Help"]

        assert _menu_actions(window, "Run") == [
            "Run Script",
            "Run Selection",
            "Clear Console",
        ]

        assert window.central_tabs is not None
        window.central_tabs.setCurrentIndex(1)
        qapp.processEvents()

        assert _menu_titles(window) == ["File", "Edit", "Insert", "View", "Build", "Help"]
        assert _menu_actions(window, "Build") == [
            "Compile",
            "Toggle Auto Compile",
            "Show Logs & Output Files",
        ]
    finally:
        window.close()
        qapp.processEvents()


def test_studio_insert_menu_inserts_mathtex_block(
    tmp_path: Path,
    monkeypatch,
    qapp,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    window = MathTeXQtWindow()
    manager = ProjectManager()
    project = manager.create_project("MenuProject", tmp_path)

    try:
        window._open_project(project)
        assert window.central_tabs is not None
        window.central_tabs.setCurrentIndex(1)
        qapp.processEvents()

        assert window.mtex_editor is not None
        window.mtex_editor.setPlainText("")
        window.mtex_editor.moveCursor(QtGui.QTextCursor.MoveOperation.End)

        insert_entries = _menu_actions(window, "Insert")
        assert "MathTeX Block" in insert_entries

        action = window._menu_actions["studio_insert_mathtex"]
        action.trigger()
        qapp.processEvents()

        text = window.mtex_editor.toPlainText()
        assert "\\begin{code}" in text
        assert "\\end{code}" in text
    finally:
        if window.mtex_editor is not None:
            window.mtex_editor.document().setModified(False)
        window._reset_auto_compile_runtime()
        window.current_project = None
        window.current_mtex_path = None
        window.close()
        qapp.processEvents()

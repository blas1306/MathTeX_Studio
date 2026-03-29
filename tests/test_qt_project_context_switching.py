from __future__ import annotations

from pathlib import Path

import pytest

from qt_app import MathTeXQtWindow
from project_system import ProjectManager


@pytest.fixture()
def studio_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    window = MathTeXQtWindow()
    manager = ProjectManager()
    project = manager.create_project("ContextSwitchProject", tmp_path)
    yield window, project
    if window.mtex_editor is not None:
        window.mtex_editor.document().setModified(False)
    window._reset_auto_compile_runtime()
    window.current_project = None
    window.current_mtex_path = None
    window.close()
    qapp.processEvents()


def test_open_project_switches_main_view_to_studio_tab(studio_window, qapp) -> None:
    window, project = studio_window

    assert window.central_tabs is not None
    assert window.central_tabs.currentIndex() == 0

    window._open_project(project)
    qapp.processEvents()

    assert window.central_tabs.currentIndex() == 1
    assert window._current_menu_context() == "studio"


def test_opening_project_mtx_file_switches_to_interactive_tab(studio_window, qapp) -> None:
    window, project = studio_window
    script_path = project.path / "solver.mtx"
    script_path.write_text("x = 1;\n", encoding="utf-8")

    window._open_project(project)
    qapp.processEvents()
    assert window.central_tabs is not None
    assert window.central_tabs.currentIndex() == 1

    window._handle_project_file_activation(str(script_path))
    qapp.processEvents()

    assert window.central_tabs.currentIndex() == 0
    assert window._current_menu_context() == "interactive"
    assert len(window.script_docs) == 1
    assert window.script_docs[0]["path"] == script_path


def test_compile_guides_user_when_active_project_file_is_mtx(
    studio_window,
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    window, project = studio_window
    script_path = project.path / "solver.mtx"
    script_path.write_text("x = 1;\n", encoding="utf-8")

    window._open_project(project)
    qapp.processEvents()
    window.current_mtex_path = script_path

    messages: list[str] = []
    compile_calls: list[Path] = []

    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.information",
        lambda *args, **kwargs: messages.append(str(args[2] if len(args) >= 3 else kwargs.get("text", ""))),
    )
    monkeypatch.setattr(window, "_run_mtex_compilation", lambda path, trigger="manual": compile_calls.append(Path(path)))

    window._compile_current_mtex()

    assert compile_calls == []
    assert messages == [
        "Only .mtex documents can be compiled to PDF in MTeX Studio.\n"
        "Open .mtx scripts in the Interactive Editor and use Run All instead."
    ]


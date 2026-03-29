from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from project_system import PROJECT_METADATA_FILENAME, ProjectInfo, ProjectManager

from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore

_Signal = QtCore.Signal  # type: ignore[attr-defined]


def _format_timestamp(raw_value: str | None) -> str:
    if not raw_value:
        return "Unknown"
    try:
        timestamp = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return raw_value
    return timestamp.strftime("%Y-%m-%d %H:%M")


class ProjectHomeWidget(QtWidgets.QWidget):  # type: ignore[misc]
    new_project_requested = _Signal()
    open_project_requested = _Signal()
    project_activated = _Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(18)

        title = QtWidgets.QLabel("MTeX Studio")
        title_font = QtGui.QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        subtitle = QtWidgets.QLabel("Open a recent project or create a new workspace.")
        subtitle.setStyleSheet("color: #6f6f6f;")
        layout.addWidget(subtitle)

        buttons = QtWidgets.QHBoxLayout()
        self.new_project_btn = QtWidgets.QPushButton("New Project")
        self.open_project_btn = QtWidgets.QPushButton("Open Project")
        buttons.addWidget(self.new_project_btn)
        buttons.addWidget(self.open_project_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

        recent_label = QtWidgets.QLabel("Recent Projects")
        recent_font = QtGui.QFont()
        recent_font.setPointSize(12)
        recent_font.setBold(True)
        recent_label.setFont(recent_font)
        layout.addWidget(recent_label)

        self.project_list = QtWidgets.QListWidget()
        self.project_list.setAlternatingRowColors(True)
        self.project_list.itemActivated.connect(self._emit_selected_project)
        layout.addWidget(self.project_list, 1)

        self.empty_label = QtWidgets.QLabel("No recent projects yet.")
        self.empty_label.setStyleSheet("color: #7a7a7a;")
        layout.addWidget(self.empty_label)

        self.new_project_btn.clicked.connect(self.new_project_requested.emit)
        self.open_project_btn.clicked.connect(self.open_project_requested.emit)
        self._update_empty_state()

    def set_projects(self, projects: list[ProjectInfo]) -> None:
        self.project_list.clear()
        for project in projects:
            item = QtWidgets.QListWidgetItem(project.name)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, str(project.path))
            item.setToolTip(str(project.path))
            item.setText(
                f"{project.name}\n{project.path}\nLast opened: {_format_timestamp(project.last_opened)}"
            )
            self.project_list.addItem(item)
        self._update_empty_state()

    def _emit_selected_project(self, item: QtWidgets.QListWidgetItem) -> None:
        project_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if project_path:
            self.project_activated.emit(str(project_path))

    def _update_empty_state(self) -> None:
        is_empty = self.project_list.count() == 0
        self.empty_label.setVisible(is_empty)
        self.project_list.setVisible(not is_empty)


class ProjectCreationDialog(QtWidgets.QDialog):  # type: ignore[misc]
    def __init__(self, default_base_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.resize(520, 150)

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        self.name_input = QtWidgets.QLineEdit()
        self.name_input.setPlaceholderText("Project name")
        form.addRow("Name", self.name_input)

        location_row = QtWidgets.QHBoxLayout()
        self.location_input = QtWidgets.QLineEdit(str(default_base_dir))
        browse_btn = QtWidgets.QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_for_location)
        location_row.addWidget(self.location_input, 1)
        location_row.addWidget(browse_btn)
        form.addRow("Location", location_row)
        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.name_input.setFocus()

    def project_name(self) -> str:
        return self.name_input.text().strip()

    def base_dir(self) -> Path:
        return Path(self.location_input.text().strip()).expanduser()

    def _browse_for_location(self) -> None:
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose Project Location",
            self.location_input.text().strip() or str(Path.home()),
        )
        if selected:
            self.location_input.setText(selected)

    def _validate_and_accept(self) -> None:
        name = self.project_name()
        if not name:
            QtWidgets.QMessageBox.warning(self, "New Project", "Project name cannot be empty.")
            return
        if any(char in '<>:"/\\|?*' for char in name):
            QtWidgets.QMessageBox.warning(self, "New Project", "Project name contains invalid characters.")
            return
        if not self.location_input.text().strip():
            QtWidgets.QMessageBox.warning(self, "New Project", "Choose a location for the project.")
            return
        self.accept()


class ProjectWorkspaceWidget(QtWidgets.QWidget):  # type: ignore[misc]
    home_requested = _Signal()
    save_requested = _Signal()
    save_as_requested = _Signal()
    compile_requested = _Signal()
    logs_output_requested = _Signal()
    file_open_requested = _Signal(str)

    def __init__(
        self,
        editor_factory: Callable[[], QtWidgets.QWidget],
        preview_factory: Callable[[], QtWidgets.QWidget],
        preview_message: str,
        project_manager: ProjectManager | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._project: ProjectInfo | None = None
        self._preview_message = preview_message
        self._project_manager = project_manager or ProjectManager()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        header = QtWidgets.QHBoxLayout()
        self.home_btn = QtWidgets.QPushButton("Project Home")
        self.project_name_label = QtWidgets.QLabel("No project open")
        title_font = QtGui.QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        self.project_name_label.setFont(title_font)
        self.project_path_label = QtWidgets.QLabel("")
        self.project_path_label.setStyleSheet("color: #7a7a7a;")
        header.addWidget(self.home_btn)
        header.addSpacing(10)
        header.addWidget(self.project_name_label)
        header.addStretch()
        header.addWidget(self.project_path_label)
        layout.addLayout(header)

        toolbar = QtWidgets.QHBoxLayout()
        self.save_btn = QtWidgets.QPushButton("Save")
        self.save_as_btn = QtWidgets.QPushButton("Save As...")
        self.compile_btn = QtWidgets.QPushButton("Compile")
        self.auto_compile_checkbox = QtWidgets.QCheckBox("Auto compile")
        self.auto_compile_checkbox.setChecked(False)
        self.auto_compile_checkbox.setToolTip("Automatically compile the active .mtex document after a short pause.")
        self.logs_output_btn = QtWidgets.QPushButton("Logs & Output Files")
        self.build_status_label = QtWidgets.QLabel()
        self.build_status_label.setMinimumWidth(240)
        self.file_label = QtWidgets.QLabel("No file open")
        self.file_label.setStyleSheet("color: #7a7a7a;")
        toolbar.addWidget(self.save_btn)
        toolbar.addWidget(self.save_as_btn)
        toolbar.addWidget(self.compile_btn)
        toolbar.addWidget(self.auto_compile_checkbox)
        toolbar.addWidget(self.logs_output_btn)
        toolbar.addWidget(self.build_status_label)
        toolbar.addStretch()
        toolbar.addWidget(self.file_label)
        layout.addLayout(toolbar)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 6, 0)
        tree_header = QtWidgets.QHBoxLayout()
        tree_header.setContentsMargins(0, 0, 0, 0)
        tree_header.setSpacing(6)
        tree_title = QtWidgets.QLabel("Project Files")
        tree_header.addWidget(tree_title)
        tree_header.addStretch()
        self.new_file_btn = self._make_tree_action_button("New File", "Create a file in the selected folder")
        self.new_folder_btn = self._make_tree_action_button("New Folder", "Create a folder in the selected folder")
        self.upload_btn = self._make_tree_action_button("Upload", "Copy files into the selected folder")
        self.refresh_tree_btn = self._make_tree_action_button("Refresh", "Refresh the project file tree")
        tree_header.addWidget(self.new_file_btn)
        tree_header.addWidget(self.new_folder_btn)
        tree_header.addWidget(self.upload_btn)
        tree_header.addWidget(self.refresh_tree_btn)
        left_layout.addLayout(tree_header)
        self.file_tree = QtWidgets.QTreeWidget()
        self.file_tree.setHeaderHidden(True)
        self.file_tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.file_tree.itemExpanded.connect(self._on_item_expanded)
        self.file_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        left_layout.addWidget(self.file_tree, 1)
        splitter.addWidget(left_panel)

        self.editor_widget = editor_factory()
        if isinstance(self.editor_widget, QtWidgets.QPlainTextEdit):
            self.editor_widget.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth)
        editor_panel = QtWidgets.QWidget()
        editor_layout = QtWidgets.QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(0, 0, 6, 0)
        editor_layout.addWidget(QtWidgets.QLabel("MathTeX Content (.mtex)"))
        editor_layout.addWidget(self.editor_widget, 1)
        splitter.addWidget(editor_panel)

        self.preview_widget = preview_factory()
        preview_panel = QtWidgets.QWidget()
        preview_layout = QtWidgets.QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(6, 0, 0, 0)
        preview_layout.addWidget(QtWidgets.QLabel("PDF Preview"))
        preview_layout.addWidget(self.preview_widget, 1)
        splitter.addWidget(preview_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        layout.addWidget(splitter, 1)

        self.home_btn.clicked.connect(self.home_requested.emit)
        self.save_btn.clicked.connect(self.save_requested.emit)
        self.save_as_btn.clicked.connect(self.save_as_requested.emit)
        self.compile_btn.clicked.connect(self.compile_requested.emit)
        self.logs_output_btn.clicked.connect(self.logs_output_requested.emit)
        self.new_file_btn.clicked.connect(self._create_new_file)
        self.new_folder_btn.clicked.connect(self._create_new_folder)
        self.upload_btn.clicked.connect(self._upload_files)
        self.refresh_tree_btn.clicked.connect(lambda _checked=False: self.refresh_file_tree())

        self.clear_workspace()

    @property
    def project(self) -> ProjectInfo | None:
        return self._project

    def set_project(self, project: ProjectInfo | None) -> None:
        self._project = project
        if project is None:
            self.clear_workspace()
            return
        self.project_name_label.setText(project.name)
        self.project_path_label.setText(str(project.path))
        self.refresh_file_tree(selected_path=project.path)

    def clear_workspace(self) -> None:
        self._project = None
        self.file_tree.clear()
        self.project_name_label.setText("No project open")
        self.project_path_label.setText("")
        self.file_label.setText("No file open")
        self.set_build_status("Build: Ready")
        if isinstance(self.editor_widget, QtWidgets.QPlainTextEdit):
            self.editor_widget.setPlainText("")
            self.editor_widget.document().setModified(False)
        preview = getattr(self.preview_widget, "set_message", None)
        if callable(preview):
            preview(self._preview_message)
        self._update_tree_actions_enabled()

    def refresh_file_tree(self, selected_path: str | Path | None = None) -> None:
        current_selection = self._current_tree_path()
        expanded_paths = self._expanded_tree_paths()
        self.file_tree.clear()
        self._update_tree_actions_enabled()
        if self._project is None:
            return
        root_path = self._project.path
        root_item = QtWidgets.QTreeWidgetItem([root_path.name or str(root_path)])
        root_item.setData(0, QtCore.Qt.ItemDataRole.UserRole, str(root_path))
        self.file_tree.addTopLevelItem(root_item)
        root_item.setExpanded(True)
        self._populate_children(root_item, root_path)
        for expanded_path in expanded_paths:
            if expanded_path == root_path:
                continue
            self._expand_to_path(expanded_path)
        target_path = Path(selected_path) if selected_path is not None else current_selection
        if target_path is not None:
            self._select_tree_path(target_path)
        else:
            self.file_tree.setCurrentItem(root_item)

    def set_current_file_label(self, filename: str) -> None:
        self.file_label.setText(filename)

    def set_build_status(self, text: str, tone: str = "neutral") -> None:
        palette = {
            "neutral": ("#d6d6d6", "#2f3a40", "#54606b"),
            "info": ("#d9ecff", "#1f3a56", "#4f8cc9"),
            "success": ("#daf5d4", "#234a2b", "#5ea36b"),
            "warning": ("#fff2cf", "#5a4217", "#d5a84a"),
            "error": ("#ffd7d7", "#5a2222", "#d47b7b"),
        }
        fg, bg, border = palette.get(tone, palette["neutral"])
        self.build_status_label.setText(text)
        self.build_status_label.setStyleSheet(
            f"""
            QLabel {{
                color: {fg};
                background: {bg};
                border: 1px solid {border};
                border-radius: 11px;
                padding: 3px 10px;
            }}
        """
        )

    def _populate_children(self, item: QtWidgets.QTreeWidgetItem, path: Path) -> None:
        try:
            entries = sorted(
                (entry for entry in path.iterdir() if self._should_show_entry(entry)),
                key=lambda entry: (not entry.is_dir(), entry.name.lower()),
            )
        except OSError:
            return
        while item.childCount():
            item.takeChild(0)
        for entry in entries:
            child = QtWidgets.QTreeWidgetItem([entry.name])
            child.setData(0, QtCore.Qt.ItemDataRole.UserRole, str(entry))
            item.addChild(child)
            if entry.is_dir():
                placeholder = QtWidgets.QTreeWidgetItem(["(loading)"])
                placeholder.setData(0, QtCore.Qt.ItemDataRole.UserRole, "__placeholder__")
                child.addChild(placeholder)

    def _should_show_entry(self, entry: Path) -> bool:
        return entry.name != PROJECT_METADATA_FILENAME

    def _on_item_expanded(self, item: QtWidgets.QTreeWidgetItem) -> None:
        path_value = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if not path_value:
            return
        path = Path(path_value)
        if path.is_dir():
            self._populate_children(item, path)

    def _on_item_double_clicked(self, item: QtWidgets.QTreeWidgetItem, _column: int) -> None:
        path_value = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if not path_value:
            return
        path = Path(path_value)
        if path.is_dir():
            item.setExpanded(not item.isExpanded())
            if item.isExpanded():
                self._populate_children(item, path)
            return
        if path.suffix.lower() in {".mtex", ".mtx"}:
            self.file_open_requested.emit(str(path))

    def _make_tree_action_button(self, text: str, tooltip: str) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setAutoRaise(False)
        button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet("QToolButton { padding: 3px 8px; }")
        return button

    def _update_tree_actions_enabled(self) -> None:
        enabled = self._project is not None
        for button in (self.new_file_btn, self.new_folder_btn, self.upload_btn, self.refresh_tree_btn):
            button.setEnabled(enabled)

    def _current_tree_path(self) -> Path | None:
        item = self.file_tree.currentItem()
        if item is None:
            return None
        return self._item_path(item)

    def _expanded_tree_paths(self) -> set[Path]:
        expanded_paths: set[Path] = set()
        for index in range(self.file_tree.topLevelItemCount()):
            self._collect_expanded_paths(self.file_tree.topLevelItem(index), expanded_paths)
        return expanded_paths

    def _collect_expanded_paths(
        self,
        item: QtWidgets.QTreeWidgetItem,
        expanded_paths: set[Path],
    ) -> None:
        path = self._item_path(item)
        if path is not None and item.isExpanded():
            expanded_paths.add(path)
        for child_index in range(item.childCount()):
            self._collect_expanded_paths(item.child(child_index), expanded_paths)

    def _item_path(self, item: QtWidgets.QTreeWidgetItem) -> Path | None:
        path_value = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if not path_value or path_value == "__placeholder__":
            return None
        return Path(path_value)

    def _expand_to_path(self, target_path: Path) -> QtWidgets.QTreeWidgetItem | None:
        if self.file_tree.topLevelItemCount() == 0 or self._project is None:
            return None
        root_item = self.file_tree.topLevelItem(0)
        root_path = self._item_path(root_item)
        if root_path is None:
            return None
        try:
            relative_parts = target_path.resolve().relative_to(root_path.resolve()).parts
        except ValueError:
            return None
        current_item = root_item
        current_path = root_path
        for part in relative_parts:
            self._populate_children(current_item, current_path)
            next_item = None
            next_path: Path | None = None
            for child_index in range(current_item.childCount()):
                child = current_item.child(child_index)
                child_path = self._item_path(child)
                if child_path is not None and child_path.name == part:
                    next_item = child
                    next_path = child_path
                    break
            if next_item is None:
                return None
            current_item = next_item
            if next_path is None:
                return None
            current_path = next_path
            if current_path.is_dir():
                current_item.setExpanded(True)
        return current_item

    def _select_tree_path(self, target_path: Path) -> None:
        item = self._expand_to_path(target_path)
        if item is None:
            return
        self.file_tree.setCurrentItem(item)
        self.file_tree.scrollToItem(item)

    def _prompt_for_entry_name(self, title: str, label: str, default_value: str) -> str | None:
        name, accepted = QtWidgets.QInputDialog.getText(self, title, label, text=default_value)
        if not accepted:
            return None
        return name

    def _selected_project_entry(self) -> Path | None:
        return self._current_tree_path()

    def _create_new_file(self) -> None:
        if self._project is None:
            return
        name = self._prompt_for_entry_name("New File", "File name", "untitled.mtex")
        if name is None:
            return
        try:
            created_path = self._project_manager.create_project_file(
                self._project.path,
                self._selected_project_entry(),
                name,
            )
        except (FileExistsError, FileNotFoundError, OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "New File", str(exc))
            return
        self.refresh_file_tree(selected_path=created_path)
        if created_path.suffix.lower() in {".mtex", ".mtx"}:
            self.file_open_requested.emit(str(created_path))

    def _create_new_folder(self) -> None:
        if self._project is None:
            return
        name = self._prompt_for_entry_name("New Folder", "Folder name", "untitled-folder")
        if name is None:
            return
        try:
            created_path = self._project_manager.create_project_folder(
                self._project.path,
                self._selected_project_entry(),
                name,
            )
        except (FileExistsError, FileNotFoundError, OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "New Folder", str(exc))
            return
        self.refresh_file_tree(selected_path=created_path)

    def _upload_files(self) -> None:
        if self._project is None:
            return
        filenames, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Upload Files",
            str(self._project.path),
            "All Files (*)",
        )
        if not filenames:
            return
        selected_entry = self._selected_project_entry()
        try:
            target_directory = self._project_manager.resolve_target_directory(self._project.path, selected_entry)
            result = self._project_manager.upload_files(
                self._project.path,
                selected_entry,
                filenames,
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "Upload Files", str(exc))
            return
        self.refresh_file_tree(selected_path=target_directory)
        if result.skipped_existing:
            skipped_names = "\n".join(path.name for path in result.skipped_existing)
            QtWidgets.QMessageBox.warning(
                self,
                "Upload Files",
                f"These files already exist and were skipped:\n{skipped_names}",
            )

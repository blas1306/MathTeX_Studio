from __future__ import annotations

import pytest

from pdf_preview import PdfPreviewWidget


@pytest.fixture()
def preview_widget(qapp):
    widget = PdfPreviewWidget()
    widget.resize(800, 600)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()
    qapp.processEvents()


def _configure_preview_state(
    preview_widget: PdfPreviewWidget,
    monkeypatch: pytest.MonkeyPatch,
    *,
    total_pages: int = 7,
    current_page: int = 3,
) -> dict[str, int]:
    state = {"current_page": current_page}
    monkeypatch.setattr(preview_widget, "_document_is_ready", lambda: True)
    monkeypatch.setattr(preview_widget, "_document_page_count", lambda: total_pages)
    monkeypatch.setattr(preview_widget, "_current_page_number", lambda: state["current_page"])
    preview_widget._update_controls()
    return state


def test_confirming_valid_page_input_navigates_to_requested_page(
    preview_widget: PdfPreviewWidget,
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    state = _configure_preview_state(preview_widget, monkeypatch, total_pages=7, current_page=3)
    navigations: list[int] = []

    def _fake_go_to_page(page_number: int) -> None:
        navigations.append(page_number)
        state["current_page"] = page_number

    monkeypatch.setattr(preview_widget, "_go_to_page_number", _fake_go_to_page)

    preview_widget.page_input.setText("5")
    preview_widget._on_page_input_edited("5")
    preview_widget.page_input.editingFinished.emit()
    qapp.processEvents()

    assert navigations == [5]
    assert preview_widget.page_input.text() == "5"
    assert preview_widget.page_total_label.text() == "/ 7"


@pytest.mark.parametrize(
    ("typed_page", "expected_page"),
    [
        ("0", 1),
        ("99", 7),
    ],
)
def test_confirming_out_of_range_page_input_clamps_to_document_bounds(
    preview_widget: PdfPreviewWidget,
    monkeypatch: pytest.MonkeyPatch,
    qapp,
    typed_page: str,
    expected_page: int,
) -> None:
    state = _configure_preview_state(preview_widget, monkeypatch, total_pages=7, current_page=3)
    navigations: list[int] = []

    def _fake_go_to_page(page_number: int) -> None:
        navigations.append(page_number)
        state["current_page"] = page_number

    monkeypatch.setattr(preview_widget, "_go_to_page_number", _fake_go_to_page)

    preview_widget.page_input.setText(typed_page)
    preview_widget._on_page_input_edited(typed_page)
    preview_widget.page_input.editingFinished.emit()
    qapp.processEvents()

    assert navigations == [expected_page]
    assert preview_widget.page_input.text() == str(expected_page)


def test_scroll_updates_page_input_when_user_is_not_editing(
    preview_widget: PdfPreviewWidget,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _configure_preview_state(preview_widget, monkeypatch, total_pages=7, current_page=2)

    assert preview_widget.page_input.text() == "2"

    state["current_page"] = 4
    preview_widget._on_scrollbar_value_changed(120)

    assert preview_widget.page_input.text() == "4"
    assert preview_widget.page_total_label.text() == "/ 7"


def test_typed_page_waits_for_confirmation_and_is_not_overwritten_by_scroll(
    preview_widget: PdfPreviewWidget,
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    state = _configure_preview_state(preview_widget, monkeypatch, total_pages=7, current_page=2)
    navigations: list[int] = []

    def _fake_go_to_page(page_number: int) -> None:
        navigations.append(page_number)
        state["current_page"] = page_number

    monkeypatch.setattr(preview_widget, "_go_to_page_number", _fake_go_to_page)

    preview_widget.page_input.setText("6")
    preview_widget._on_page_input_edited("6")
    qapp.processEvents()

    assert navigations == []

    state["current_page"] = 4
    preview_widget._on_scrollbar_value_changed(180)

    assert navigations == []
    assert preview_widget.page_input.text() == "6"

    preview_widget.page_input.editingFinished.emit()
    qapp.processEvents()

    assert navigations == [6]
    assert preview_widget.page_input.text() == "6"

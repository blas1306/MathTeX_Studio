from __future__ import annotations

from editor_pdf_sync import (
    EditorPdfSyncMap,
    extract_source_landmarks,
    parse_aux_landmarks,
    parse_toc_landmarks,
)


def test_extract_source_landmarks_tracks_heading_hierarchy() -> None:
    text = (
        "\\section{Intro}\n"
        "Body.\n"
        "\\subsection{Details}\n"
        "More.\n"
        "\\subsubsection{Deep Dive}\n"
    )

    landmarks = extract_source_landmarks(text)

    assert [(landmark.command, landmark.title, landmark.line_number) for landmark in landmarks] == [
        ("section", "Intro", 1),
        ("subsection", "Details", 3),
        ("subsubsection", "Deep Dive", 5),
    ]
    assert landmarks[0].parent_index is None
    assert landmarks[1].parent_index == 0
    assert landmarks[2].parent_index == 1


def test_parse_toc_and_aux_landmarks_read_compiled_heading_pages() -> None:
    toc_text = (
        r"\contentsline {section}{\numberline {1}Experiment Description}{3}{section.1}%" "\n"
        r"\contentsline {subsection}{\numberline {1.1}Setup}{4}{subsection.1.1}%" "\n"
    )
    aux_text = (
        r"\@writefile{toc}{\contentsline {section}{\numberline {1}Experiment Description}{3}{section.1}\protected@file@percent }" "\n"
        r"\@writefile{toc}{\contentsline {subsection}{\numberline {1.1}Setup}{4}{subsection.1.1}\protected@file@percent }" "\n"
    )

    toc_landmarks = parse_toc_landmarks(toc_text)
    aux_landmarks = parse_aux_landmarks(aux_text)

    assert [(landmark.command, landmark.normalized_title, landmark.page_index) for landmark in toc_landmarks] == [
        ("section", "experiment description", 2),
        ("subsection", "setup", 3),
    ]
    assert [(landmark.command, landmark.normalized_title, landmark.page_index) for landmark in aux_landmarks] == [
        ("section", "experiment description", 2),
        ("subsection", "setup", 3),
    ]


def test_sync_map_resolves_current_heading_page_and_falls_back_to_parent(tmp_path) -> None:
    source_text = (
        "\\section{Intro}\n"
        "Intro body.\n"
        "\\subsection{Details}\n"
        "Detail body.\n"
        "\\section{Conclusion}\n"
        "Wrap up.\n"
    )
    toc_path = tmp_path / "demo.toc"
    toc_path.write_text(
        r"\contentsline {section}{\numberline {1}Intro}{2}{section.1}%" "\n"
        r"\contentsline {section}{\numberline {2}Conclusion}{5}{section.2}%" "\n",
        encoding="utf-8",
    )

    sync_map = EditorPdfSyncMap()
    sync_map.update_source(source_text)
    sync_map.update_compiled_landmarks(toc_path=toc_path, aux_path=None)

    intro_target = sync_map.resolve_target_for_line(2)
    detail_target = sync_map.resolve_target_for_line(4)
    conclusion_target = sync_map.resolve_target_for_line(6)

    assert intro_target is not None
    assert intro_target.landmark.title == "Intro"
    assert intro_target.page_index == 1

    assert detail_target is not None
    assert detail_target.landmark.title == "Intro"
    assert detail_target.page_index == 1

    assert conclusion_target is not None
    assert conclusion_target.landmark.title == "Conclusion"
    assert conclusion_target.page_index == 4

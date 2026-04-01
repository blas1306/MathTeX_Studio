from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
import re


_HEADING_LEVELS = {
    "chapter": 0,
    "section": 1,
    "subsection": 2,
    "subsubsection": 3,
}
_HEADING_PATTERN = re.compile(r"\\(?P<command>chapter|section|subsection|subsubsection)\*?")
_CONTROL_SEQUENCE_RE = re.compile(r"\\([A-Za-z]+)\*?|\\.")
_WHITESPACE_RE = re.compile(r"\s+")
_NUMBERLINE_RE = re.compile(r"\\numberline\s*\{[^{}]*\}")


@dataclass(frozen=True)
class SourceLandmark:
    command: str
    title: str
    normalized_title: str
    line_number: int
    level: int
    parent_index: int | None

    @property
    def signature(self) -> tuple[int, str, str]:
        return (self.line_number, self.command, self.normalized_title)


@dataclass(frozen=True)
class PdfLandmark:
    command: str
    title: str
    normalized_title: str
    page_index: int


@dataclass(frozen=True)
class ResolvedSyncTarget:
    landmark: SourceLandmark
    page_index: int


def _strip_line_comment(text: str) -> str:
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "%":
            return text[:index]
    return text


def _parse_braced_group(text: str, start_index: int) -> tuple[str, int] | None:
    if start_index >= len(text) or text[start_index] != "{":
        return None
    depth = 0
    chars: list[str] = []
    index = start_index
    while index < len(text):
        char = text[index]
        if char == "{":
            if depth > 0:
                chars.append(char)
            depth += 1
            index += 1
            continue
        if char == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                return ("".join(chars), index + 1)
            chars.append(char)
            index += 1
            continue
        if char == "\\" and index + 1 < len(text):
            chars.append(char)
            chars.append(text[index + 1])
            index += 2
            continue
        chars.append(char)
        index += 1
    return None


def _skip_optional_bracket_group(text: str, start_index: int) -> int:
    index = start_index
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text) or text[index] != "[":
        return index
    depth = 0
    while index < len(text):
        char = text[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return start_index


def _normalize_title(title: str) -> str:
    cleaned = _NUMBERLINE_RE.sub(" ", title)
    cleaned = _CONTROL_SEQUENCE_RE.sub(lambda match: f" {match.group(1) or ' '} ", cleaned)
    cleaned = cleaned.replace("{", " ").replace("}", " ").replace("~", " ")
    return _WHITESPACE_RE.sub(" ", cleaned).strip().lower()


def extract_source_landmarks(text: str) -> list[SourceLandmark]:
    landmarks: list[SourceLandmark] = []
    active_by_level: dict[int, int] = {}

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = _strip_line_comment(raw_line)
        match = _HEADING_PATTERN.search(line)
        if match is None:
            continue
        command = match.group("command")
        level = _HEADING_LEVELS[command]
        index = _skip_optional_bracket_group(line, match.end())
        while index < len(line) and line[index].isspace():
            index += 1
        title_group = _parse_braced_group(line, index)
        if title_group is None:
            continue
        title, _end_index = title_group
        normalized_title = _normalize_title(title)
        parent_index = None
        for parent_level in range(level - 1, -1, -1):
            if parent_level in active_by_level:
                parent_index = active_by_level[parent_level]
                break
        landmarks.append(
            SourceLandmark(
                command=command,
                title=title.strip(),
                normalized_title=normalized_title,
                line_number=line_number,
                level=level,
                parent_index=parent_index,
            )
        )
        active_by_level[level] = len(landmarks) - 1
        for stale_level in tuple(key for key in active_by_level if key > level):
            active_by_level.pop(stale_level, None)

    return landmarks


def _parse_contentsline_entry(entry_text: str) -> PdfLandmark | None:
    entry = entry_text.strip()
    if not entry.startswith(r"\contentsline"):
        return None
    index = len(r"\contentsline")
    groups: list[str] = []
    for _ in range(4):
        while index < len(entry) and entry[index].isspace():
            index += 1
        if index >= len(entry) or entry[index] != "{":
            break
        parsed = _parse_braced_group(entry, index)
        if parsed is None:
            break
        value, index = parsed
        groups.append(value)

    if len(groups) < 3:
        return None

    command = groups[0].strip()
    if command not in _HEADING_LEVELS:
        return None

    normalized_title = _normalize_title(groups[1])
    if not normalized_title:
        return None

    try:
        page_number = int(groups[2].strip())
    except ValueError:
        return None

    return PdfLandmark(
        command=command,
        title=groups[1].strip(),
        normalized_title=normalized_title,
        page_index=max(0, page_number - 1),
    )


def parse_toc_landmarks(text: str) -> list[PdfLandmark]:
    landmarks: list[PdfLandmark] = []
    for raw_line in text.splitlines():
        parsed = _parse_contentsline_entry(raw_line)
        if parsed is not None:
            landmarks.append(parsed)
    return landmarks


def parse_aux_landmarks(text: str) -> list[PdfLandmark]:
    landmarks: list[PdfLandmark] = []
    prefix = r"\@writefile{toc}"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith(prefix):
            continue
        index = len(prefix)
        while index < len(line) and line[index].isspace():
            index += 1
        if index >= len(line) or line[index] != "{":
            continue
        parsed = _parse_braced_group(line, index)
        if parsed is None:
            continue
        entry_text, _end_index = parsed
        parsed_entry = _parse_contentsline_entry(entry_text)
        if parsed_entry is not None:
            landmarks.append(parsed_entry)
    return landmarks


def load_compiled_pdf_landmarks(
    toc_path: str | Path | None,
    aux_path: str | Path | None = None,
) -> list[PdfLandmark]:
    for candidate, parser in (
        (toc_path, parse_toc_landmarks),
        (aux_path, parse_aux_landmarks),
    ):
        if candidate is None:
            continue
        path = Path(candidate)
        if not path.exists():
            continue
        try:
            return parser(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return []


class EditorPdfSyncMap:
    """Keeps a conservative stage-1 heading-to-page map based on compiled LaTeX outputs."""

    def __init__(self) -> None:
        self._source_landmarks: list[SourceLandmark] = []
        self._line_numbers: list[int] = []
        self._pdf_landmarks: list[PdfLandmark] = []
        self._page_by_source_index: dict[int, int] = {}

    def clear(self) -> None:
        self._source_landmarks = []
        self._line_numbers = []
        self._pdf_landmarks = []
        self._page_by_source_index = {}

    def update_source(self, text: str) -> None:
        self._source_landmarks = extract_source_landmarks(text)
        self._line_numbers = [landmark.line_number for landmark in self._source_landmarks]
        self._rebuild_page_map()

    def update_compiled_landmarks(
        self,
        *,
        toc_path: str | Path | None,
        aux_path: str | Path | None = None,
    ) -> None:
        self._pdf_landmarks = load_compiled_pdf_landmarks(toc_path, aux_path)
        self._rebuild_page_map()

    def current_landmark_for_line(self, line_number: int) -> SourceLandmark | None:
        if not self._line_numbers:
            return None
        index = bisect_right(self._line_numbers, max(1, line_number)) - 1
        if index < 0:
            return None
        return self._source_landmarks[index]

    def resolve_target_for_line(self, line_number: int) -> ResolvedSyncTarget | None:
        if not self._line_numbers:
            return None
        index = bisect_right(self._line_numbers, max(1, line_number)) - 1
        if index < 0:
            return None
        while index is not None and index >= 0:
            page_index = self._page_by_source_index.get(index)
            if page_index is not None:
                return ResolvedSyncTarget(self._source_landmarks[index], page_index)
            index = self._source_landmarks[index].parent_index
        return None

    def _rebuild_page_map(self) -> None:
        page_by_source_index: dict[int, int] = {}
        pdf_index = 0
        for source_index, source_landmark in enumerate(self._source_landmarks):
            matched_page = None
            for candidate_index in range(pdf_index, len(self._pdf_landmarks)):
                pdf_landmark = self._pdf_landmarks[candidate_index]
                if pdf_landmark.command != source_landmark.command:
                    continue
                if pdf_landmark.normalized_title != source_landmark.normalized_title:
                    continue
                matched_page = pdf_landmark.page_index
                pdf_index = candidate_index + 1
                break
            if matched_page is not None:
                page_by_source_index[source_index] = matched_page
        self._page_by_source_index = page_by_source_index

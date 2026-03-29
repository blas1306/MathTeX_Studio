from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Sequence

from command_catalog import COMMAND_CATALOG, CommandSuggestion
from document_symbols import DocumentSymbol, extract_document_symbols


COMMENT_PATTERN = re.compile(r"(?<!\\)%.*|#.*")
AutocompleteKind = Literal["command", "identifier"]
DocumentKind = Literal["script", "mtex_document"]


@dataclass(frozen=True)
class AutocompleteMatch:
    kind: AutocompleteKind
    prefix: str
    token_start_col: int
    token_end_col: int


@dataclass(frozen=True)
class AutocompleteRequest:
    line_text: str
    cursor_col: int
    document_kind: DocumentKind = "script"
    document_text: str = ""
    workspace_items: Sequence[dict[str, str]] = ()


def _is_command_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _is_identifier_start_char(char: str) -> bool:
    return char.isalpha() or char == "_"


def _is_identifier_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _keyword_entry(
    name: str,
    description: str,
    *,
    insert_text: str | None = None,
    signature: str | None = None,
    category: str = "keywords",
    priority: int = 120,
) -> CommandSuggestion:
    resolved_insert = insert_text or name
    resolved_signature = signature or resolved_insert
    return CommandSuggestion(
        name=name,
        label=name,
        insert_text=resolved_insert,
        signature=resolved_signature,
        description=description,
        category=category,
        kind="keyword",
        source="language",
        priority=priority,
        match_text=name,
    )


KEYWORD_SUGGESTIONS: tuple[CommandSuggestion, ...] = (
    _keyword_entry("for", "Start a for-loop block.", insert_text="for ", signature="for ... end", category="control"),
    _keyword_entry("while", "Start a while-loop block.", insert_text="while ", signature="while ... end", category="control"),
    _keyword_entry("if", "Start a conditional block.", insert_text="if ", signature="if ... end", category="control"),
    _keyword_entry("elif", "Add a conditional branch.", insert_text="elif ", signature="elif ...", category="control"),
    _keyword_entry("else", "Add an else branch.", category="control"),
    _keyword_entry("function", "Start a user function definition.", insert_text="function ", signature="function out = name(args)", category="definitions"),
    _keyword_entry("return", "Return from the current function.", category="control"),
    _keyword_entry("repeat", "Start a repeat-until block.", insert_text="repeat", signature="repeat ... until", category="control"),
    _keyword_entry("until", "Close a repeat-until block condition.", insert_text="until ", category="control"),
    _keyword_entry("end", "Close the current block.", category="control"),
    _keyword_entry("and", "Logical conjunction.", category="operators", priority=90),
    _keyword_entry("or", "Logical disjunction.", category="operators", priority=90),
    _keyword_entry("from", "Start an import statement.", insert_text="from ", signature="from module import name", category="imports"),
    _keyword_entry("import", "Import names from a module.", insert_text="import ", signature="import name", category="imports"),
)


def _comment_start_col(line_text: str) -> int | None:
    match = COMMENT_PATTERN.search(line_text)
    if match is None:
        return None
    return match.start()


def is_comment_context(line_text: str, cursor_col: int) -> bool:
    if cursor_col < 0 or cursor_col > len(line_text):
        return False
    comment_start = _comment_start_col(line_text)
    return comment_start is not None and cursor_col > comment_start


def detect_command_prefix(line_text: str, cursor_col: int) -> AutocompleteMatch | None:
    if cursor_col < 0 or cursor_col > len(line_text):
        return None
    if is_comment_context(line_text, cursor_col):
        return None

    start = cursor_col
    while start > 0 and _is_command_char(line_text[start - 1]):
        start -= 1

    if start == 0 or line_text[start - 1] != "\\":
        return None

    token_start = start - 1
    token_end = cursor_col
    while token_end < len(line_text) and _is_command_char(line_text[token_end]):
        token_end += 1

    return AutocompleteMatch(
        kind="command",
        prefix=line_text[token_start:cursor_col],
        token_start_col=token_start,
        token_end_col=token_end,
    )


def detect_identifier_prefix(line_text: str, cursor_col: int) -> AutocompleteMatch | None:
    if cursor_col < 0 or cursor_col > len(line_text):
        return None
    if is_comment_context(line_text, cursor_col):
        return None

    start = cursor_col
    while start > 0 and _is_identifier_char(line_text[start - 1]):
        start -= 1

    if start >= cursor_col:
        return None
    if start > 0 and line_text[start - 1] == "\\":
        return None
    if not _is_identifier_start_char(line_text[start]):
        return None

    token_end = cursor_col
    while token_end < len(line_text) and _is_identifier_char(line_text[token_end]):
        token_end += 1

    return AutocompleteMatch(
        kind="identifier",
        prefix=line_text[start:cursor_col],
        token_start_col=start,
        token_end_col=token_end,
    )


def detect_autocomplete_match(line_text: str, cursor_col: int) -> AutocompleteMatch | None:
    return detect_command_prefix(line_text, cursor_col) or detect_identifier_prefix(line_text, cursor_col)


def _match_prefix(candidate: str, prefix: str) -> bool:
    return candidate.casefold().startswith(prefix.casefold())


def _format_workspace_variable_description(item: dict[str, str]) -> str:
    value_type = str(item.get("class", "")).strip()
    size = str(item.get("size", "")).strip()
    summary = str(item.get("summary", "")).strip()
    parts = [part for part in (value_type, size) if part and part != "function"]
    lead = " ".join(parts).strip()
    if summary and summary != str(item.get("name", "")).strip():
        return f"{lead}: {summary}" if lead else summary
    return lead or "Workspace value."


def _workspace_suggestions(prefix: str, workspace_items: Sequence[dict[str, str]]) -> list[CommandSuggestion]:
    suggestions: list[CommandSuggestion] = []
    for item in workspace_items:
        name = str(item.get("name", "")).strip()
        if not name or not _match_prefix(name, prefix):
            continue
        cls = str(item.get("class", "")).strip()
        signature = str(item.get("summary", "")).strip() or name
        if cls in {"UserFunction", "function"}:
            suggestions.append(
                CommandSuggestion(
                    name=name,
                    label=name,
                    insert_text=f"{name}()",
                    signature=signature,
                    description="User function from the current workspace.",
                    category="workspace",
                    kind="function",
                    source="workspace",
                    priority=260,
                    match_text=name,
                    cursor_backtrack=1,
                )
            )
            continue
        suggestions.append(
            CommandSuggestion(
                name=name,
                label=name,
                insert_text=name,
                signature=name,
                description=_format_workspace_variable_description(item),
                category="workspace",
                kind="variable",
                source="workspace",
                priority=240,
                match_text=name,
            )
        )
    return suggestions


def _document_symbol_description(symbol: DocumentSymbol) -> str:
    if symbol.kind == "function":
        return "User function defined earlier in the current document."
    if symbol.origin == "for_loop_variable":
        return "Loop variable defined earlier in the current document."
    return "Variable defined earlier in the current document."


def _document_symbol_suggestions(prefix: str, document_text: str) -> list[CommandSuggestion]:
    suggestions: list[CommandSuggestion] = []
    for symbol in extract_document_symbols(document_text):
        if not _match_prefix(symbol.name, prefix):
            continue
        priority = 310 + symbol.statement_index if symbol.kind == "function" else 290 + symbol.statement_index
        if symbol.kind == "function":
            suggestions.append(
                CommandSuggestion(
                    name=symbol.name,
                    label=symbol.name,
                    insert_text=f"{symbol.name}()",
                    signature=symbol.signature,
                    description=_document_symbol_description(symbol),
                    category="document",
                    kind="function",
                    source="document",
                    priority=priority,
                    match_text=symbol.name,
                    cursor_backtrack=1,
                )
            )
            continue
        suggestions.append(
            CommandSuggestion(
                name=symbol.name,
                label=symbol.name,
                insert_text=symbol.name,
                signature=symbol.signature,
                description=_document_symbol_description(symbol),
                category="document",
                kind="variable",
                source="document",
                priority=priority,
                match_text=symbol.name,
            )
        )
    return suggestions


def _keyword_suggestions(prefix: str) -> list[CommandSuggestion]:
    return [item for item in KEYWORD_SUGGESTIONS if _match_prefix(item.match_text or item.name, prefix)]


def _next_non_space_char(line_text: str, cursor_col: int) -> str | None:
    idx = cursor_col
    while idx < len(line_text) and line_text[idx].isspace():
        idx += 1
    if idx >= len(line_text):
        return None
    return line_text[idx]


def _looks_like_code_line(line_text: str) -> bool:
    stripped = line_text.strip()
    if not stripped:
        return False
    if stripped.startswith("\\"):
        return False
    if "=" in stripped:
        return True
    starters = ("for", "while", "if", "elif", "else", "function", "repeat", "until", "return", "from", "import")
    return any(stripped.lower().startswith(f"{name} ") or stripped.lower() == name for name in starters)


def _score_suggestion(
    suggestion: CommandSuggestion,
    match: AutocompleteMatch,
    *,
    line_text: str,
    document_kind: DocumentKind,
) -> tuple[int, int, int, str]:
    candidate = suggestion.match_text or suggestion.label or suggestion.name
    prefix = match.prefix
    candidate_cf = candidate.casefold()
    prefix_cf = prefix.casefold()
    score = suggestion.priority

    if candidate_cf == prefix_cf:
        score += 220
    elif candidate_cf.startswith(prefix_cf):
        score += 120

    if candidate.startswith(prefix):
        score += 35

    if match.kind == "command":
        if suggestion.kind == "command":
            score += 150
    else:
        if suggestion.kind == "function":
            score += 90
        elif suggestion.kind == "variable":
            score += 70
        elif suggestion.kind == "keyword":
            score += 35

    next_char = _next_non_space_char(line_text, match.token_end_col)
    if next_char == "(":
        if suggestion.kind == "function":
            score += 75
        elif suggestion.kind == "variable":
            score -= 40

    if document_kind == "mtex_document" and suggestion.kind == "keyword":
        score -= 25

    exact_case_bias = 1 if candidate.startswith(prefix) else 0
    length_bias = -len(candidate)
    return (score, exact_case_bias, length_bias, candidate.casefold())


def _dedupe_suggestions(
    suggestions: Sequence[CommandSuggestion],
    match: AutocompleteMatch,
    *,
    line_text: str,
    document_kind: DocumentKind,
) -> list[CommandSuggestion]:
    ranked: dict[str, tuple[tuple[int, int, int, str], CommandSuggestion]] = {}
    for suggestion in suggestions:
        key = (suggestion.label or suggestion.name).casefold()
        score = _score_suggestion(suggestion, match, line_text=line_text, document_kind=document_kind)
        current = ranked.get(key)
        if current is None or score > current[0]:
            ranked[key] = (score, suggestion)
    ordered = sorted(ranked.values(), key=lambda item: item[0], reverse=True)
    return [suggestion for _score, suggestion in ordered]


def build_autocomplete_suggestions(
    request: AutocompleteRequest,
    *,
    catalog: Sequence[CommandSuggestion] = COMMAND_CATALOG,
) -> list[CommandSuggestion]:
    match = detect_autocomplete_match(request.line_text, request.cursor_col)
    if match is None:
        return []

    if match.kind == "command":
        raw = [item for item in catalog if _match_prefix(item.match_text or item.name, match.prefix)]
        return _dedupe_suggestions(raw, match, line_text=request.line_text, document_kind=request.document_kind)

    should_suggest_identifiers = request.document_kind == "script" or _looks_like_code_line(request.line_text)
    raw: list[CommandSuggestion] = []
    if should_suggest_identifiers and request.document_text:
        raw.extend(_document_symbol_suggestions(match.prefix, request.document_text))
    raw.extend(_workspace_suggestions(match.prefix, request.workspace_items))
    if should_suggest_identifiers:
        raw.extend(_keyword_suggestions(match.prefix))
    return _dedupe_suggestions(raw, match, line_text=request.line_text, document_kind=request.document_kind)


def filter_command_suggestions(
    prefix: str,
    suggestions: Sequence[CommandSuggestion] = COMMAND_CATALOG,
) -> list[CommandSuggestion]:
    request = AutocompleteRequest(line_text=prefix, cursor_col=len(prefix))
    return build_autocomplete_suggestions(request, catalog=suggestions)

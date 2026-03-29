from __future__ import annotations

import io
from contextlib import redirect_stdout
from typing import cast

import pytest

from latex_lang import _build_parser_context, _run_oct_block, env_ast, parse_mathtex_line, reset_environment
from mathtex_ast import AssignNode, BinOpNode, CallNode, ExprStmtNode, MatrixLiteralNode, NumberNode


@pytest.fixture(autouse=True)
def _fresh_runtime():
    reset_environment()
    yield
    reset_environment()


def test_parser_nested_parentheses_with_power_and_mul():
    ctx = _build_parser_context()

    node = parse_mathtex_line("x = (1 + 2) * (3 + 4^2)", ctx)

    assert isinstance(node, AssignNode)
    node = cast(AssignNode, node)
    assert isinstance(node.expr, BinOpNode)
    assert node.expr.op == "*"
    assert node.expr.left == BinOpNode("+", NumberNode(1), NumberNode(2))
    assert isinstance(node.expr.right, BinOpNode)
    assert node.expr.right.op == "+"
    assert node.expr.right.left == NumberNode(3)
    assert node.expr.right.right == BinOpNode("**", NumberNode(4), NumberNode(2))


def test_parser_chained_transpose_and_power_expression():
    ctx = _build_parser_context()

    node = parse_mathtex_line("A.' * A^2", ctx)

    assert isinstance(node, ExprStmtNode)
    node = cast(ExprStmtNode, node)
    assert isinstance(node.expr, CallNode)
    assert node.expr.func_name == "_mt_mul"
    assert len(node.expr.args) == 2
    assert isinstance(node.expr.args[0], CallNode)
    assert node.expr.args[0].func_name == "_mt_transpose"
    assert isinstance(node.expr.args[1], CallNode)
    assert node.expr.args[1].func_name == "_mt_pow"


def test_parser_nested_matrix_literal_keeps_expression_entries():
    ctx = _build_parser_context()

    node = parse_mathtex_line("A = [[1 + 2, 3 * 4], [5 - 1, 2 ^ 3]]", ctx)

    assert isinstance(node, AssignNode)
    node = cast(AssignNode, node)
    assert isinstance(node.expr, MatrixLiteralNode)
    assert len(node.expr.values) == 2
    first_row = cast(MatrixLiteralNode, node.expr.values[0])
    second_row = cast(MatrixLiteralNode, node.expr.values[1])
    assert first_row.values[0] == BinOpNode("+", NumberNode(1), NumberNode(2))
    assert first_row.values[1] == BinOpNode("*", NumberNode(3), NumberNode(4))
    assert second_row.values[0] == BinOpNode("-", NumberNode(5), NumberNode(1))
    assert second_row.values[1] == BinOpNode("**", NumberNode(2), NumberNode(3))


def test_parser_invalid_nested_parenthesis_fails_cleanly():
    ctx = _build_parser_context()

    with pytest.raises(SyntaxError, match="never closed|unmatched"):
        parse_mathtex_line("a = ((2 + 3) * 4", ctx)


def test_parser_missing_end_in_nested_block_fails_cleanly():
    output = io.StringIO()

    with redirect_stdout(output):
        _run_oct_block(
            [
                "for i = 1:2",
                "if i > 1",
                "x = i;",
                "end",
            ]
        )

    assert "missing 'end'" in output.getvalue()
    assert "x" not in env_ast
    assert "i" not in env_ast

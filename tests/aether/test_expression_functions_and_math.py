from __future__ import annotations

import pytest

from aether.errors import AetherTypeError
from aether.runner import run_aether


def test_global_math_builtins() -> None:
    result = run_aether(
        """
println(sqrt(9.0));
println(sin(0.0));
println(cos(0.0));
println(exp(0.0));
println(ln(exp(1.0)));
println(abs(-5));
"""
    )

    values = [float(line) for line in result.output.strip().splitlines()]
    assert values[0] == pytest.approx(3.0)
    assert values[1] == pytest.approx(0.0)
    assert values[2] == pytest.approx(1.0)
    assert values[3] == pytest.approx(1.0)
    assert values[4] == pytest.approx(1.0)
    assert values[5] == pytest.approx(5.0)


def test_log_is_base_10_and_ln_is_natural_log() -> None:
    result = run_aether("println(log(100.0)); println(ln(exp(1.0)));")

    values = [float(line) for line in result.output.strip().splitlines()]
    assert values == pytest.approx([2.0, 1.0])


def test_expression_function_single_parameter() -> None:
    result = run_aether("f(x) = x^2 + 1; println(f(3));")

    assert result.output == "10\n"


def test_expression_function_multiple_parameters() -> None:
    result = run_aether("g(x, y) = x^2 + y^2; println(g(3, 4));")

    assert result.output == "25\n"


def test_expression_function_can_call_math_builtins() -> None:
    result = run_aether("f(x) = sin(x)^2 + cos(x)^2; println(f(0.0));")

    assert float(result.output.strip()) == pytest.approx(1.0)


def test_expression_function_can_use_global_variable() -> None:
    result = run_aether("a = 2; f(x) = a*x + 1; println(f(3));")

    assert result.output == "7\n"


def test_expression_function_wrong_arity_is_error() -> None:
    with pytest.raises(AetherTypeError, match="expects 2 arguments but got 1"):
        run_aether("g(x, y) = x + y; println(g(1));")


def test_expression_function_coexists_with_block_function() -> None:
    result = run_aether(
        """
f(x) = x + 1;
int g(int x) {
    return x * 2;
}
println(f(3));
println(g(3));
"""
    )

    assert result.output == "4\n6\n"


def test_expression_function_duplicate_name_is_error() -> None:
    with pytest.raises(AetherTypeError, match="already defined"):
        run_aether("f(x) = x + 1; int f(int x) { return x; }")


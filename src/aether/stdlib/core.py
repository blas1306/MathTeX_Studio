from __future__ import annotations

from math import sqrt

from ..errors import AetherRuntimeError, AetherTypeError
from ..formatting import format_value
from ..types import (
    AetherType,
    AetherValue,
    ArrayType,
    NUMERIC_TYPES,
    coerce_array_literal_value,
    explicit_cast,
    is_array_type,
    is_matrix_type,
    type_to_string,
)
from .registry import BuiltinDefinition, BuiltinFunction, OutputWriter, RuntimeFactory


CAST_BUILTINS = {"int", "float", "double", "string", "boolean"}


def builtin_definitions() -> list[BuiltinDefinition]:
    definitions = [
        BuiltinDefinition("print", _make_print_builtin, _print_type),
        BuiltinDefinition("println", _make_println_builtin, _print_type),
        BuiltinDefinition("length", _constant_runtime(length_builtin), _length_type, _exactly_one("length")),
        BuiltinDefinition("array", _constant_runtime(array_builtin), _array_type, _array_arity),
        BuiltinDefinition("rows", _constant_runtime(rows_builtin), _rows_type, _exactly_one("rows")),
        BuiltinDefinition("cols", _constant_runtime(cols_builtin), _cols_type, _exactly_one("cols")),
        BuiltinDefinition("sqrt", _constant_runtime(sqrt_builtin), _sqrt_type, _exactly_one("sqrt")),
    ]
    definitions.extend(
        BuiltinDefinition(
            type_name,
            _constant_runtime(cast_builtin(type_name)),
            _cast_type(type_name),
            _exactly_one(type_name),
        )
        for type_name in sorted(CAST_BUILTINS)
    )
    return definitions


def _constant_runtime(function: BuiltinFunction) -> RuntimeFactory:
    def factory(_write_output: OutputWriter) -> BuiltinFunction:
        return function

    return factory


def _exactly_one(label: str):
    def validate(arg_count: int) -> None:
        if arg_count != 1:
            raise AetherTypeError(f"{label}(...) expects exactly one argument.")

    return validate


def _array_arity(arg_count: int) -> None:
    if arg_count == 0:
        raise AetherTypeError("array(...) cannot infer the type of an empty array.")


def _make_print_builtin(write_output: OutputWriter) -> BuiltinFunction:
    def print_builtin(args: list[AetherValue]) -> AetherValue:
        if not args:
            raise AetherRuntimeError("print expects at least one argument.")
        write_output("".join(format_value(arg) for arg in args))
        return AetherValue("boolean", True)

    return print_builtin


def _make_println_builtin(write_output: OutputWriter) -> BuiltinFunction:
    def println_builtin(args: list[AetherValue]) -> AetherValue:
        if not args:
            raise AetherRuntimeError("println expects at least one argument.")
        write_output("".join(format_value(arg) for arg in args) + "\n")
        return AetherValue("boolean", True)

    return println_builtin


def cast_builtin(target_type: str) -> BuiltinFunction:
    def cast(args: list[AetherValue]) -> AetherValue:
        if len(args) != 1:
            raise AetherTypeError(f"{target_type}(...) expects exactly one argument.")
        return explicit_cast(target_type, args[0])

    return cast


def length_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError("length(...) expects exactly one argument.")
    value = args[0]
    if not is_array_type(value.type_name):
        raise AetherTypeError(f"length(...) expects an array argument, got '{type_to_string(value.type_name)}'.")
    return AetherValue("int", len(value.value))


def array_builtin(args: list[AetherValue]) -> AetherValue:
    if not args:
        raise AetherTypeError("array(...) cannot infer the type of an empty array.")
    element_type = common_primitive_type([arg.type_name for arg in args], label="array")
    array_type = ArrayType(element_type)
    return coerce_array_literal_value(AetherValue(array_type, args), array_type)


def rows_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError("rows(...) expects exactly one argument.")
    value = args[0]
    if not is_matrix_type(value.type_name):
        raise AetherTypeError(f"rows(...) expects a matrix argument, got '{type_to_string(value.type_name)}'.")
    return AetherValue("int", len(value.value))


def cols_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError("cols(...) expects exactly one argument.")
    value = args[0]
    if not is_matrix_type(value.type_name):
        raise AetherTypeError(f"cols(...) expects a matrix argument, got '{type_to_string(value.type_name)}'.")
    return AetherValue("int", len(value.value[0].value) if value.value else 0)


def sqrt_builtin(args: list[AetherValue]) -> AetherValue:
    if len(args) != 1:
        raise AetherTypeError("sqrt(...) expects exactly one argument.")
    value = args[0]
    if value.type_name not in NUMERIC_TYPES:
        raise AetherTypeError(f"sqrt(...) expects a numeric argument, got '{type_to_string(value.type_name)}'.")
    if value.value < 0:
        raise AetherRuntimeError("sqrt(...) is only defined for non-negative real numbers in Aether v0.")
    return AetherValue("double", sqrt(value.value))


def _print_type(arg_types: list[AetherType | None]) -> AetherType | None:
    return "boolean"


def _length_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError("length(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    if not is_array_type(argument_type):
        raise AetherTypeError(f"length(...) expects an array argument, got '{type_to_string(argument_type)}'.")
    return "int"


def _array_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if not arg_types:
        raise AetherTypeError("array(...) cannot infer the type of an empty array.")
    if any(argument_type is None for argument_type in arg_types):
        return None
    if not all(isinstance(argument_type, str) for argument_type in arg_types):
        raise AetherTypeError("array(...) expects scalar primitive homogeneous compatible elements.")
    return ArrayType(common_primitive_type(arg_types, label="array"))


def _rows_type(arg_types: list[AetherType | None]) -> AetherType | None:
    return _matrix_dimension_type(arg_types, "rows")


def _cols_type(arg_types: list[AetherType | None]) -> AetherType | None:
    return _matrix_dimension_type(arg_types, "cols")


def _matrix_dimension_type(arg_types: list[AetherType | None], label: str) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError(f"{label}(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    if not is_matrix_type(argument_type):
        raise AetherTypeError(f"{label}(...) expects a matrix argument, got '{type_to_string(argument_type)}'.")
    return "int"


def _sqrt_type(arg_types: list[AetherType | None]) -> AetherType | None:
    if len(arg_types) != 1:
        raise AetherTypeError("sqrt(...) expects exactly one argument.")
    argument_type = arg_types[0]
    if argument_type is None:
        return None
    if argument_type not in NUMERIC_TYPES:
        raise AetherTypeError(f"sqrt(...) expects a numeric argument, got '{type_to_string(argument_type)}'.")
    return "double"


def _cast_type(target_type: str):
    def infer(arg_types: list[AetherType | None]) -> AetherType | None:
        if len(arg_types) != 1:
            raise AetherTypeError(f"{target_type}(...) expects exactly one argument.")
        return target_type

    return infer


def common_primitive_type(primitive_types: list[AetherType | None], *, label: str) -> str:
    if not all(isinstance(type_name, str) for type_name in primitive_types):
        raise AetherTypeError(f"{label}(...) expects scalar primitive homogeneous compatible elements.")
    unique_types = set(primitive_types)
    if len(unique_types) == 1:
        return primitive_types[0]
    if unique_types <= NUMERIC_TYPES:
        if "double" in unique_types:
            return "double"
        if "float" in unique_types:
            return "float"
        return "int"
    raise AetherTypeError(f"{label}(...) expects scalar primitive homogeneous compatible elements.")

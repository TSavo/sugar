# SPDX-License-Identifier: MIT OR Apache-2.0

from __future__ import annotations

import textwrap

from .factory.source_fragment import SourceFragment
from .ir import (
    Formula,
    and_,
    bool_const,
    comparison_with_none_guard,
    ctor,
    eq,
    make_var,
    not_,
    num,
    or_,
    str_const,
)


def parse_contract_expression(expr: str, available_names: list[str]) -> Formula:
    """Parse a string contract expression into a canonical IR formula."""
    source = textwrap.dedent(expr).strip()
    root = SourceFragment.from_source(source, "<contract>")
    for fragment in root.walk():
        if fragment.observed == "Expr":
            return _translate_expr(fragment.expr_value(), available_names)
    raise ValueError(f"empty contract expression: {expr!r}")


_COMPARE_OPS = {
    "Eq": "=",
    "NotEq": "≠",
    "Lt": "<",
    "LtE": "≤",
    "Gt": ">",
    "GtE": "≥",
    "Is": "=",
    "IsNot": "≠",
}


def _translate_expr(fragment: SourceFragment, available_names: list[str]) -> Formula:
    observed = fragment.observed

    if observed == "BoolOp":
        operands = [
            _translate_expr(value, available_names)
            for value in fragment.boolop_values()
        ]
        kind = fragment.boolop_op_kind()
        if kind == "and":
            return and_(operands)
        if kind == "or":
            return or_(operands)
        raise ValueError(f"unsupported bool op: {observed}")

    if observed == "UnaryOp" and fragment.operator_kind() == "Not":
        return not_(_translate_expr(fragment.unaryop_operand(), available_names))

    if observed == "Compare":
        operators = fragment.compare_ops()
        comparators = fragment.compare_comparators()
        if len(operators) != 1 or len(comparators) != 1:
            raise ValueError("chained comparisons are not supported")
        symbol = _COMPARE_OPS.get(operators[0])
        if symbol is None:
            raise ValueError(f"unsupported comparison: {operators[0]}")
        left = _translate_term(fragment.compare_left(), available_names)
        right = _translate_term(comparators[0], available_names)
        return comparison_with_none_guard(symbol, left, right)

    if observed == "BinOp" and fragment.operator_kind() == "Add":
        left = _translate_term(fragment.binop_left(), available_names)
        right = _translate_term(fragment.binop_right(), available_names)
        term = ctor("+", [left, right])
        return eq(term, term)

    term = _translate_term(fragment, available_names)
    return eq(term, bool_const(True))


def _translate_term(fragment: SourceFragment, available_names: list[str]):
    observed = fragment.observed

    if observed == "Name":
        name = fragment.name_id()
        if name == "None":
            return ctor("None", [])
        if name == "True":
            return bool_const(True)
        if name == "False":
            return bool_const(False)
        return make_var(name)

    if observed == "PrimitiveLiteral":
        value = fragment.literal_value()
        if isinstance(value, bool):
            return bool_const(value)
        if isinstance(value, int):
            return num(value)
        if isinstance(value, str):
            return str_const(value)
        if value is None:
            return ctor("None", [])
        raise ValueError(f"unsupported constant: {type(value).__name__}")

    if observed == "UnaryOp" and fragment.operator_kind() == "USub":
        operand = fragment.unaryop_operand()
        if operand.observed == "PrimitiveLiteral":
            value = operand.literal_value()
            if isinstance(value, int):
                return num(-value)
        raise ValueError("unary minus only supported on integer literals")

    if observed == "Call":
        if fragment.call_is_method_call():
            raise ValueError("only simple-name calls are supported")
        name = fragment.call_target_name()
        if name is None:
            raise ValueError("only simple-name calls are supported")
        arguments = [
            _translate_term(argument, available_names)
            for argument in fragment.call_args()
        ]
        return ctor(name, arguments)

    if observed == "BinOp":
        operator = fragment.operator_kind()
        left = _translate_term(fragment.binop_left(), available_names)
        right = _translate_term(fragment.binop_right(), available_names)
        symbols = {"Add": "+", "Sub": "-", "Mult": "*", "Div": "/"}
        symbol = symbols.get(operator)
        if symbol is None:
            raise ValueError(f"unsupported binary op: {operator}")
        return ctor(symbol, [left, right])

    raise ValueError(f"unsupported expression: {observed}")

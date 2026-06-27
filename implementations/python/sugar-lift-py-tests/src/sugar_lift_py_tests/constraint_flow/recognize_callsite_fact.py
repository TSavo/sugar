from __future__ import annotations

import ast
from typing import Any

from .callsite_constraint_fact import CallsiteConstraintFact
from .ge_field_fact import ge_field_fact


def recognize_callsite_fact(
    node: ast.AST,
    *,
    source_memento: dict[str, Any],
) -> CallsiteConstraintFact | None:
    if not isinstance(node, ast.Assert):
        return None
    compare = node.test
    if not (
        isinstance(compare, ast.Compare)
        and len(compare.ops) == 1
        and isinstance(compare.ops[0], ast.GtE)
        and len(compare.comparators) == 1
    ):
        return None

    left = compare.left
    right = compare.comparators[0]
    if not (
        isinstance(left, ast.Attribute)
        and isinstance(left.value, ast.Call)
        and isinstance(left.value.func, ast.Name)
        and isinstance(right, ast.Constant)
        and isinstance(right.value, int)
    ):
        return None

    owner = left.value.func.id
    field = left.attr
    return CallsiteConstraintFact(
        sugar_name="python.vendor-test.callsite-assert",
        callsite=ast.unparse(left.value),
        subject=f"{owner}.{field}",
        fact=ge_field_fact(owner, field, int(right.value)),
        source_memento=dict(source_memento),
        target_symbol=owner,
    )

from __future__ import annotations

from typing import Literal

from sugar_lift_py_tests.ir import Formula, gt, gte, lt, lte, py_ge, py_gt, py_le, py_lt

from .equality_atom import _sort_warrant
from .floor_value import FloorValue

ComparisonOperator = Literal["lt", "le", "gt", "ge"]


def resolve_comparison_atom(
    operator: ComparisonOperator,
    left: FloorValue,
    right: FloorValue,
    *,
    owner: str,
) -> Formula:
    """Resolve one Python comparison where both operand sort warrants are known."""
    left_term = left.to_term(owner=owner)
    right_term = right.to_term(owner=owner)
    left_sort = _sort_warrant(left, left_term, owner=owner)
    right_sort = _sort_warrant(right, right_term, owner=owner)

    if left_sort is not None and left_sort == right_sort:
        return {
            "lt": lt,
            "le": lte,
            "gt": gt,
            "ge": gte,
        }[
            operator
        ](left_term, right_term)

    return {
        "lt": py_lt,
        "le": py_le,
        "gt": py_gt,
        "ge": py_ge,
    }[
        operator
    ](left_term, right_term)

"""A formula as deep as the body that folded it still has its free variables.

The lane's mint of ``pandas/tests/config/test_config.py`` (and ten other
pandas files, two numpy files) died with ``maximum recursion depth exceeded``
inside ``_free_vars_in_ir_formula``: a body folds its guards into a
connective nested once per statement, and the recursive walk ran out of
Python stack, so the file packaged no proof at all. The reader is now one
iterative walk over the shared DAG.

Both halves: the deep formula reports exactly the names that are free in it
(every ``x<i>`` and ``y``), and a name a quantifier binds is never reported
free however deep it sits (the lying reading would report ``z``).
"""

from __future__ import annotations

import sys

from sugar_lift_py_tests.ir import Int, and_, atomic, forall, make_var, not_
from sugar_lift_py_tests.proofir.formulas import (
    _free_vars_in_ir_formula,
    formula_from_ir,
)

DEPTH = 4 * sys.getrecursionlimit()


def _deep(depth: int):
    formula = atomic("q", [make_var("y")])
    for index in range(depth):
        formula = and_([atomic("p", [make_var(f"x{index % 7}")]), not_(formula)])
    return formula


def test_a_formula_deeper_than_the_stack_reports_its_free_names():
    formula = _deep(DEPTH)
    expected = frozenset({"y", *(f"x{index}" for index in range(7))})
    assert _free_vars_in_ir_formula(formula) == expected
    assert formula_from_ir(formula, var_sorts={}).free_vars == expected


def test_a_bound_name_deep_in_the_formula_is_never_free():
    body = and_([atomic("r", [make_var("z")]), _deep(DEPTH)])
    bound = forall("z", Int(), body)
    free = _free_vars_in_ir_formula(bound)
    assert "z" not in free
    assert "z" in _free_vars_in_ir_formula(body)
    assert free == _free_vars_in_ir_formula(body) - {"z"}

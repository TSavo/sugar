"""Unwarranted symbolic comparisons stay operator-indexed atoms.

Construction may emit FOL equality only when both operand sorts are warranted;
a sort-neutral symbol therefore remains ``py.eq``.
"""

from __future__ import annotations

from factory_reduce import reduce_value

from sugar_lift_py_tests.floor import PredicateValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var, py_eq


def test_symbolic_equals_emits_py_eq_not_smt_eq() -> None:
    # No receiver/sort testimony exists at this construction site.
    value = reduce_value("z == z", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, PredicateValue)
    assert value.formula == py_eq(make_var("z"), make_var("z"))

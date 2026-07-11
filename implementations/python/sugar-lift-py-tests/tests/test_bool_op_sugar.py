"""BoolOpSugar: `a and b` / `a or b` return an OPERAND, not a bool.

`1 and 2` is 2; `0 or 3` is 3; `1 or 2` is 1. Ground folds via the truth floor;
symbolic emits the py.and / py.or coordinate -- never a constant pick."""

from __future__ import annotations

import ast

import pytest
from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import NoneValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, make_var, num


def test_and_folds_to_the_right_operand_value() -> None:
    # Python: 1 and 2 is 2 -- the value, not True.
    assert reduce_value("1 and 2") == TermValue(2)


def test_or_folds_to_the_left_when_truthy() -> None:
    # Python: 1 or 2 is 1 -- proves it returns the operand, not a bool, and
    # picks the left when truthy (discrimination against always-right).
    assert reduce_value("1 or 2") == TermValue(1)


def test_or_folds_to_the_right_when_left_is_falsy() -> None:
    assert reduce_value("0 or 3") == TermValue(3)


def test_and_short_circuits_to_none() -> None:
    # None is falsy: `None and 5` is None -- the left operand, unevaluated right.
    assert reduce_value("None and 5") == NoneValue()


def test_chained_and_folds_left_to_last_truthy() -> None:
    assert reduce_value("1 and 2 and 3") == TermValue(3)


def test_symbolic_and_emits_py_and_coordinate() -> None:
    value = reduce_value("z and 1", binds={"z": SymbolicValue(make_var("z"))})
    assert type(value) is SymbolicValue
    assert value.term == ctor("py.and", [make_var("z"), num(1)])


def test_symbolic_or_emits_py_or_coordinate() -> None:
    value = reduce_value("z or 1", binds={"z": SymbolicValue(make_var("z"))})
    assert type(value) is SymbolicValue
    assert value.term == ctor("py.or", [make_var("z"), num(1)])


def test_bool_op_selects_on_bool_op_site() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("1 and 2", mode="eval").body
    result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)
    assert result.audit_row.selected == "BoolOpSugar"


def test_bool_op_does_not_own_compare_or_binop() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    compare = build_node(
        ast.parse("1 < 2", mode="eval").body,
        filename="t.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )
    assert compare.audit_row.selected != "BoolOpSugar"
    binop = build_node(
        ast.parse("1 + 2", mode="eval").body,
        filename="t.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )
    assert binop.audit_row.selected != "BoolOpSugar"

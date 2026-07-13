"""`is` / `is not` stand on the identity floor. Identity is reflexive, sort-independent,
and total (nan is nan is True even when nan == nan is False). Folds only for language
singletons (None, True, False); symbolic cases emit ir.identity."""

from __future__ import annotations

import ast

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import PredicateValue, SymbolicValue, UniverseValue
from sugar_lift_py_tests.ir import (
    and_,
    ctor,
    eq,
    identity,
    implies,
    make_var,
    not_,
    num,
)
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


def _universe(source: str) -> UniverseValue:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    result = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    value = complete_value(result.sugar.desugar(ctx), owner="test")
    assert isinstance(value, UniverseValue)
    return value


def test_none_is_none_folds_true() -> None:
    value = reduce_value("None is None")
    assert isinstance(value, TrueBoolLiteralSugar)


def test_none_is_not_none_folds_false() -> None:
    value = reduce_value("None is not None")
    assert isinstance(value, FalseBoolLiteralSugar)


def test_symbolic_is_none_emits_identity() -> None:
    value = reduce_value("z is None", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, PredicateValue)
    assert value.formula == identity(make_var("z"), ctor("None", []))


def test_symbolic_is_not_none_emits_negated_identity() -> None:
    value = reduce_value("z is not None", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, PredicateValue)
    assert value.formula == not_(identity(make_var("z"), ctor("None", [])))


def test_is_none_guard_emits_guarded_implications() -> None:
    universe = _universe(
        "def A(z):\n" "    if z is None:\n" "        return 0\n" "    return z\n"
    )
    guard = identity(make_var("z"), ctor("None", []))
    assert universe.post() == and_(
        [
            implies(guard, eq(make_var("out"), num(0))),
            implies(not_(guard), eq(make_var("out"), make_var("z"))),
        ]
    )

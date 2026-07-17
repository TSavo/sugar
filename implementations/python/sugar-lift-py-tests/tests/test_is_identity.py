"""`is` / `is not` stand on the identity floor. Identity is reflexive, sort-independent,
and total (nan is nan is True even when nan == nan is False). Folds only for language
singletons (None, True, False); symbolic cases emit ir.identity."""

from __future__ import annotations

import ast
from pathlib import Path

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import (
    PredicateValue,
    SymbolicValue,
    TermValue,
    UniverseValue,
)
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
from sugar_lift_py_tests.sugar.is_not_op_sugar import IsNotOpSugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


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


def test_constructed_tuple_is_not_none_folds_true() -> None:
    value = reduce_value("(5, 3, 3) is not None")
    assert isinstance(value, TrueBoolLiteralSugar)


def test_constructed_string_identity_against_none_is_decidable() -> None:
    assert isinstance(reduce_value("'label' is None"), FalseBoolLiteralSugar)
    assert isinstance(reduce_value("'label' is not None"), TrueBoolLiteralSugar)


def test_ifexp_selects_from_constructed_string_identity() -> None:
    assert reduce_value("1 if 'label' is not None else 2") == TermValue(1)


def test_ground_string_is_not_none_witness_refutes_wrong_twin(
    tmp_path: Path,
) -> None:
    pair = next(
        witness
        for witness in IsNotOpSugar.witnesses()
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "ground_string_is_not_none"
    )
    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_exact_builtin_type_identity_folds_by_type_coordinate() -> None:
    assert isinstance(reduce_value("bool is bool"), TrueBoolLiteralSugar)
    assert isinstance(reduce_value("bool is int"), FalseBoolLiteralSugar)


def test_ifexp_selects_from_decidable_identity_conditions() -> None:
    tuple_selected = reduce_value("1 if (5, 3, 3) is not None else 0")
    type_selected = reduce_value("1 if bool is bool else 0")
    assert tuple_selected == TermValue(1)
    assert type_selected == TermValue(1)


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

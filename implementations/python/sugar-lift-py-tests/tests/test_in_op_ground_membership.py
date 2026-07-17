from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import PredicateValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _term(source: str, *, symbolic_names: tuple[str, ...] = ()):
    ctx = FactoryBuildContext(filename="membership.py", catalog=default_catalog())
    for name in symbolic_names:
        ctx = ctx.with_temporal(
            ctx.temporal.bind_value(name, SymbolicValue(make_var(name)))
        )
    node = ast.parse(source, mode="eval").body
    sugar = build_node(
        node,
        filename="membership.py",
        role=SugarRole.TERM,
        ctx=ctx,
    ).sugar
    return sugar.desugar(ctx).value


def test_ground_set_membership_folds_both_boolean_faces() -> None:
    assert isinstance(_term('"var" in {"var", "std"}'), TrueBoolLiteralSugar)
    assert isinstance(_term('"sem" in {"var", "std"}'), FalseBoolLiteralSugar)


def test_ground_mixed_primitive_membership_is_still_decidable() -> None:
    assert isinstance(_term('"1" in {1, "2"}'), FalseBoolLiteralSugar)
    assert isinstance(_term('1 in {True, "2"}'), TrueBoolLiteralSugar)


def test_symbolic_set_membership_remains_a_predicate() -> None:
    assert isinstance(
        _term('method in {"var", "std"}', symbolic_names=("method",)),
        PredicateValue,
    )


def test_ground_set_membership_truthful_and_lying_twins_refute(tmp_path) -> None:
    prefix = (
        "def A():\n"
        '    if "sem" in {"var", "std"}:\n'
        "        return 0\n"
        "    return 1\n"
        "\n"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "ground-membership-truthful",
        prefix + "def test_a():\n    assert A() == 1\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "ground-membership-lying",
        prefix + "def test_a():\n    assert A() == 0\n",
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "InOpSugar" in truthful.selected_sugars
    assert "InOpSugar" in lying.selected_sugars

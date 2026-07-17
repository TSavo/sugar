"""The `%` operator (ModuloOpSugar): reduce left, reduce right, ask left for the
remainder by right (the modulo floor). Numbers fold; modulo by a concrete zero is
a runtime effect (Incomplete), not a lift-side panic. String formatting stays
unowned for free."""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import ModuloRuntimeEffect
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import CallSiteValue, TermValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.modulo_op_sugar import ModuloOpSugar
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _condition(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    sugar = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx).sugar
    return sugar.condition.reduce(ctx)


def _term(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source, mode="eval").body
    sugar = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx).sugar
    return sugar.desugar(ctx)


def test_modulo_folds_to_true_when_remainder_matches() -> None:
    assert isinstance(
        _condition("if 7 % 3 == 1:\n    pass").value, TrueBoolLiteralSugar
    )


def test_modulo_folds_to_false_when_remainder_mismatches() -> None:
    assert isinstance(
        _condition("if 7 % 3 == 2:\n    pass").value, FalseBoolLiteralSugar
    )


def test_modulo_folds_collapsed_number() -> None:
    assert isinstance(
        _condition("if 5.5 % 2 == 1.5:\n    pass").value, TrueBoolLiteralSugar
    )


def test_modulo_by_zero_stays_a_loud_decidable_construction_gap() -> None:
    with pytest.raises(FactoryPanic, match="owner=modulo"):
        _term("1 % 0")


def test_unowned_string_modulo_operand_panics_for_free() -> None:
    with pytest.raises(FactoryPanic):
        _term('"%s" % ["b"]')


def test_term_modulo_opaque_call_result_is_witnessed() -> None:
    site = SourceFragment.from_source("15 % td\n", "t.py").statements()[0]
    right = CallSiteValue(
        target_name="Timedelta",
        arg_values=(TermValue(3),),
        parameters=(),
        term=ctor("call:Timedelta", [TermValue(3).to_term(owner="test")]),
        body=None,
        site=site,
    )

    outcome = TermValue(15).modulo(right, site)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, ModuloRuntimeEffect)
    operand = ctor("%", [TermValue(15).to_term(owner="test"), right.term])
    assert outcome.effect.runtime_operand.term == operand
    assert outcome.effect.witness.operand == operand
    assert outcome.effect.witness.operation == ctor("py.modulo", [operand])
    assert outcome.effect.witness.locus == "t.py:1:0"


def test_term_modulo_diggable_call_peer_is_not_a_runtime_effect() -> None:
    site = SourceFragment.from_source("15 % known()\n", "t.py").statements()[0]
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    body = ctx.build_body(ast.parse("3", mode="eval").body, SugarRole.TERM)
    right = CallSiteValue(
        target_name="known",
        arg_values=(),
        parameters=(),
        term=ctor("call:known", []),
        body=body,
        site=site,
    )

    with pytest.raises(FactoryPanic, match="owner=modulo"):
        TermValue(15).modulo(right, site)


def test_modulo_truthful_and_lying_twins_reach_opposite_verdicts(tmp_path) -> None:
    witness = ModuloOpSugar.witnesses()
    truthful = run_source_through_real_solver(
        tmp_path / "truthful", witness.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", witness.lying.source)

    assert truthful.verdict == witness.truthful.expected == "sat"
    assert lying.verdict == witness.lying.expected == "unsat"
    assert "ModuloOpSugar" in truthful.selected_sugars
    assert "ModuloOpSugar" in lying.selected_sugars

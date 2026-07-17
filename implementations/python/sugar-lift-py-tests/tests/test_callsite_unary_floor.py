import ast
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue, TermValue
from sugar_lift_py_tests.idd.sugar_witness_instruments import evaluate_seed_witnesses
from sugar_lift_py_tests.ir import _Ctor, ctor
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar


def test_callsite_unary_minus_cites_the_existing_call_coordinate() -> None:
    value = CallSiteValue(
        target_name="timedelta",
        arg_values=(TermValue(1),),
        parameters=(),
        term=ctor("call:timedelta", [TermValue(1).to_term(owner="test")]),
        body=None,
        site="datetime.py:510:12",
    )

    outcome = value.unary_minus("datetime.py:510:11")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, SymbolicValue)
    term = outcome.value.to_term(owner="test")
    assert isinstance(term, _Ctor)
    assert term.name == "py.neg"
    assert term.args == (value.term,)


def test_bodyless_callsite_unary_plus_is_authenticated_runtime_effect() -> None:
    site = SourceFragment.from_source("+Series(values)\n", "series.py").statements()[0]
    value = CallSiteValue(
        target_name="Series",
        arg_values=(),
        parameters=(),
        term=ctor("call:Series", []),
        body=None,
        site=site,
    )

    outcome = value.unary_plus(site)

    assert isinstance(outcome, Incomplete)
    assert type(outcome.effect).__name__ == "UnaryPlusRuntimeEffect"
    assert outcome.effect.runtime_operand.term == value.term
    assert outcome.effect.witness.operand == value.term


def test_diggable_callsite_unary_plus_stays_construct_or_panic() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    body = ctx.build_body(ast.parse('"not-numeric"', mode="eval").body, SugarRole.TERM)
    value = CallSiteValue(
        target_name="known",
        arg_values=(),
        parameters=(),
        term=ctor("call:known", []),
        body=body,
        site="t.py:1:0",
    )

    with pytest.raises(FactoryPanic, match="owner=unary_plus"):
        value.unary_plus("t.py:1:0")


def test_callsite_unary_plus_typed_red_witness_discriminates(
    tmp_path: Path,
) -> None:
    witness = next(
        pair
        for pair in UnaryOpSugar.witnesses()
        if pair.name == "runtime_callsite_unary_plus"
    )

    assert evaluate_seed_witnesses((witness,), tmp_path).is_zero

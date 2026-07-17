from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import MatrixMultiplyRuntimeEffect
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import CallSiteValue, ListValue, TermValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.matrix_multiply_op_sugar import MatrixMultiplyOpSugar
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _right(*, body):
    site = SourceFragment.from_source("[3, 4] @ col\n", "t.py").statements()[0]
    return (
        CallSiteValue(
            target_name="col",
            arg_values=(TermValue(1),),
            parameters=(),
            term=ctor("call:col", [TermValue(1).to_term(owner="test")]),
            body=body,
            site=site,
        ),
        site,
    )


def test_list_matmul_bodyless_callsite_is_authenticated_runtime_effect() -> None:
    right, site = _right(body=None)
    left = ListValue((TermValue(3), TermValue(4)))
    outcome = left.matrix_multiply(right, site)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, MatrixMultiplyRuntimeEffect)
    operand = ctor("@", [left.to_term(owner="test"), right.term])
    assert outcome.effect.runtime_operand.term == operand


def test_list_matmul_diggable_callsite_wrong_twin_stays_loud() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    body = ctx.build_body(ast.parse("3", mode="eval").body, SugarRole.TERM)
    right, site = _right(body=body)

    with pytest.raises(FactoryPanic, match="owner=matrix_multiply"):
        ListValue((TermValue(3),)).matrix_multiply(right, site)


def test_matrix_multiply_truthful_and_lying_twins_reach_opposite_verdicts(
    tmp_path,
) -> None:
    witness = MatrixMultiplyOpSugar.witnesses()
    truthful = run_source_through_real_solver(
        tmp_path / "truthful", witness.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", witness.lying.source)

    assert truthful.verdict == witness.truthful.expected == "sat"
    assert lying.verdict == witness.lying.expected == "unsat"
    assert "MatrixMultiplyOpSugar" in truthful.selected_sugars
    assert "MatrixMultiplyOpSugar" in lying.selected_sugars

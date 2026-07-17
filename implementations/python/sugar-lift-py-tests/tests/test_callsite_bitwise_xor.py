from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import BitwiseXorRuntimeEffect
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import CallSiteValue, TermValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Incomplete


def _call(*, body):
    site = SourceFragment.from_source("left ^ 1\n", "t.py").statements()[0]
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


def test_bodyless_callsite_xor_is_authenticated_runtime_effect() -> None:
    left, site = _call(body=None)
    outcome = left.bitwise_xor(TermValue(1), site)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, BitwiseXorRuntimeEffect)
    operand = ctor("^", [left.term, TermValue(1).to_term(owner="test")])
    assert outcome.effect.runtime_operand.term == operand
    assert outcome.effect.witness.operand == operand


def test_diggable_callsite_xor_wrong_twin_stays_loud() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    body = ctx.build_body(ast.parse('"not-an-int"', mode="eval").body, SugarRole.TERM)
    left, site = _call(body=body)

    with pytest.raises(FactoryPanic, match="owner=bitwise_xor"):
        left.bitwise_xor(TermValue(1), site)

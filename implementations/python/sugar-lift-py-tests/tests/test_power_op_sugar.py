from __future__ import annotations

import ast

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import PowerRuntimeEffect
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    GuardedValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import atomic, ctor, make_var, num
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


@pytest.mark.parametrize("source", ["2 ** 53", "10 ** -2", "(-2) ** 3"])
def test_concrete_power_folds_exactly_like_python(source: str) -> None:
    value = reduce_value(source)

    assert value == TermValue(eval(source))


def test_symbolic_power_uses_the_native_operator_coordinate() -> None:
    value = reduce_value(
        "base ** exponent",
        {
            "base": SymbolicValue(make_var("base")),
            "exponent": SymbolicValue(make_var("exponent")),
        },
    )

    assert value == SymbolicValue(ctor("**", [make_var("base"), make_var("exponent")]))


def test_concrete_base_with_symbolic_exponent_uses_the_same_coordinate() -> None:
    value = reduce_value(
        "2 ** exponent", {"exponent": SymbolicValue(make_var("exponent"))}
    )

    assert value == SymbolicValue(ctor("**", [num(2), make_var("exponent")]))


def test_concrete_base_with_len_exponent_uses_the_native_coordinate() -> None:
    value = reduce_value(
        "10 ** len(items)", {"items": SymbolicValue(make_var("items"))}
    )

    assert value == SymbolicValue(
        ctor(
            "**",
            [
                num(10),
                ctor(
                    "call:len",
                    [make_var("items")],
                    symbol_kind="method-coordinate",
                ),
            ],
        )
    )


def test_opaque_call_result_base_is_a_witnessed_power_runtime_effect() -> None:
    site = SourceFragment.from_source(
        "runtime_base(value) ** 2\n", "t.py"
    ).statements()[0]
    base = CallSiteValue(
        target_name="runtime_base",
        arg_values=(SymbolicValue(make_var("value")),),
        parameters=(),
        term=ctor("call:runtime_base", [make_var("value")]),
        body=None,
        site=site,
    )
    outcome = base.power(TermValue(2), site)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, PowerRuntimeEffect)
    operand = ctor("**", [ctor("call:runtime_base", [make_var("value")]), num(2)])
    assert outcome.effect.witness.operand == operand
    assert outcome.effect.witness.operation == ctor("py.power", [operand])
    assert outcome.effect.witness.locus == "t.py:1:0"


def test_power_truthful_and_lying_twins_reach_opposite_verdicts(tmp_path) -> None:
    prefix = "def A():\n    return 2 ** 3\n\n"
    truthful = run_source_through_real_solver(
        tmp_path / "truthful",
        prefix + "def test_a():\n    assert A() == 8\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying",
        prefix + "def test_a():\n    assert A() == 9\n",
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "PowerOpSugar" in truthful.selected_sugars
    assert "PowerOpSugar" in lying.selected_sugars


def test_concrete_base_distributes_over_guarded_integer_exponent() -> None:
    guard = atomic("loop_face", [])
    exponent = GuardedValue(guard, TermValue(1), TermValue(2))

    outcome = TermValue(2).power(
        exponent, SourceFragment.from_source("2 ** bit\n", "t.py").statements()[0]
    )

    assert outcome == Complete(GuardedValue(guard, TermValue(2), TermValue(4)))


def test_concrete_base_accepts_range_iteration_integer_exponent() -> None:
    site = SourceFragment.from_source("2 ** bit\n", "t.py").statements()[0]
    range_call = CallSiteValue(
        target_name="range",
        arg_values=(TermValue(3),),
        parameters=(),
        term=ctor("call:range", [num(3)]),
        body=None,
        site=site,
    )
    bit = CallSiteValue(
        target_name="iter_elem",
        arg_values=(range_call,),
        parameters=(),
        term=ctor("python:iter_elem", [range_call.term]),
        body=None,
        site=site,
    )

    outcome = TermValue(2).power(bit, site)

    assert outcome == Complete(SymbolicValue(ctor("**", [num(2), bit.term])))


def test_power_owner_selects_only_pow_binop() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    pow_result = build_node(
        ast.parse("2 ** 3", mode="eval").body,
        filename="t.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )

    assert pow_result.audit_row.selected == "PowerOpSugar"
    with pytest.raises(FactoryPanic, match="observed=BinOp requested=term"):
        build_node(
            ast.parse("2 | 3", mode="eval").body,
            filename="t.py",
            role=SugarRole.TERM,
            ctx=ctx,
        )

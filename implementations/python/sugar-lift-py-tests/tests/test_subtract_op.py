"""The `-` operator (SubtractOpSugar): reduce left, reduce right, ask left to
subtract right (the subtraction floor). Concrete numbers fold to a TermValue;
strings do not stand on the floor and the default panics."""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import SubtractRuntimeEffect, TypeErrorRuntimeEffect
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ComprehensionValue,
    NativeCallableValue,
    NoneValue,
    SetValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.subtract_op_sugar import SubtractOpSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _condition(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    sugar = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx).sugar
    return sugar.condition.reduce(ctx)


def _build_term(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source, mode="eval").body
    return build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx).sugar, ctx


def test_subtract_folds_to_true_when_difference_matches() -> None:
    assert isinstance(
        _condition("if 3 - 1 == 2:\n    pass").value, TrueBoolLiteralSugar
    )


def test_subtract_folds_to_false_when_difference_mismatches() -> None:
    assert isinstance(
        _condition("if 3 - 1 == 5:\n    pass").value, FalseBoolLiteralSugar
    )


def test_subtract_floats_on_collapsed_number() -> None:
    # the collapsed Number: float and int share the subtraction floor
    assert isinstance(
        _condition("if 2.5 - 1 == 1.5:\n    pass").value, TrueBoolLiteralSugar
    )


def test_string_subtract_panics_on_the_floor() -> None:
    sugar, ctx = _build_term('"a" - "b"')
    with pytest.raises(FactoryPanic, match="write more Floor"):
        sugar.desugar(ctx)


def test_bool_subtraction_uses_python_integer_coordinates() -> None:
    site = SourceFragment.from_source("False - value\n", "t.py").statements()[0]
    value = SymbolicValue(make_var("value"))

    assert FalseBoolLiteralSugar(site).subtract(value, site) == Complete(
        SymbolicValue(ctor("-", [num(0), make_var("value")]))
    )
    assert TrueBoolLiteralSugar(site).subtract(TermValue(2), site) == Complete(
        TermValue(-1)
    )


def test_bool_subtraction_truthful_and_lying_twins_refute(tmp_path) -> None:
    pair = next(
        pair for pair in SubtractOpSugar.witnesses() if pair.name == "bool_subtract"
    )
    truthful = run_source_through_real_solver(
        tmp_path / "bool-subtract-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "bool-subtract-lying", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_none_subtract_is_a_witnessed_type_error_boundary() -> None:
    """Part of #4103: NoneValue.subtract constructs TypeError, never panics.

    requests.utils.super_len rejoins total_length with a None face; after
    `if total_length is None: total_length = 0` residual None arms still hit
    the subtraction floor. The None-ness IS the type — Python raises TypeError
    for `None - x`, so the floor is a witnessed boundary.
    """
    site = SourceFragment.from_source("None - 1\n", "t.py").statements()[0]
    outcome = NoneValue().subtract(TermValue(1), site)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, TypeErrorRuntimeEffect)
    assert outcome.effect.witness is not None
    operand = ctor(
        "call:NoneType.__sub__",
        [NoneValue().to_term(owner="test"), TermValue(1).to_term(owner="test")],
    )
    assert outcome.effect.witness.operand == operand
    assert outcome.effect.witness.operation == ctor("py.subtract", [operand])
    assert "NoneType" in outcome.effect.reason


def test_none_minus_int_expression_constructs_type_error_effect() -> None:
    sugar, ctx = _build_term("None - 1")
    outcome = sugar.desugar(ctx)
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, TypeErrorRuntimeEffect)


def test_none_minus_symbolic_uses_the_opaque_right_as_evidence() -> None:
    site = SourceFragment.from_source("None - runtime_n\n", "t.py").statements()[0]
    right = SymbolicValue(make_var("runtime_n"))
    outcome = NoneValue().subtract(right, site)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, TypeErrorRuntimeEffect)
    assert outcome.effect.witness.operand == make_var("runtime_n")
    assert outcome.effect.witness.operation == ctor(
        "py.subtract", [make_var("runtime_n")]
    )


def test_requests_super_len_none_face_subtract_does_not_panic() -> None:
    """Vendor residual shape from requests/utils.py:228 (Guarded None - pos)."""
    source = (
        "def super_len(o):\n"
        "    total_length = None\n"
        "    current_position = 0\n"
        "    if hasattr(o, '__len__'):\n"
        "        total_length = len(o)\n"
        "    elif hasattr(o, 'len'):\n"
        "        total_length = o.len\n"
        "    elif hasattr(o, 'fileno'):\n"
        "        try:\n"
        "            total_length = o.fileno()\n"
        "        except (OSError, AttributeError):\n"
        "            pass\n"
        "        else:\n"
        "            total_length = total_length\n"
        "    if hasattr(o, 'tell'):\n"
        "        try:\n"
        "            current_position = o.tell()\n"
        "        except OSError:\n"
        "            if total_length is not None:\n"
        "                current_position = total_length\n"
        "        else:\n"
        "            if hasattr(o, 'seek') and total_length is None:\n"
        "                try:\n"
        "                    o.seek(0, 2)\n"
        "                    total_length = o.tell()\n"
        "                    o.seek(current_position or 0)\n"
        "                except OSError:\n"
        "                    total_length = 0\n"
        "    if total_length is None:\n"
        "        total_length = 0\n"
        "    return max(0, total_length - current_position)\n"
    )
    payload, gaps = audit_lift_file(source, "requests/utils_super_len.py")
    assert gaps == []
    assert len(payload.ir) == 1


def test_string_minus_opaque_call_result_is_a_witnessed_runtime_effect() -> None:
    site = SourceFragment.from_source('"1" - runtime_right()\n', "t.py").statements()[0]
    right = CallSiteValue(
        target_name="runtime_right",
        arg_values=(),
        parameters=(),
        term=ctor("call:runtime_right", []),
        body=None,
        site=site,
    )

    outcome = StringValue("1").subtract(right, site)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SubtractRuntimeEffect)
    operand = ctor("-", [StringValue("1").to_term(owner="test"), right.term])
    assert outcome.effect.witness.operand == operand
    assert outcome.effect.witness.operation == ctor("py.subtract", [operand])


def test_string_minus_decidable_call_result_wrong_twin_panics() -> None:
    site = SourceFragment.from_source('"1" - known_right()\n', "t.py").statements()[0]
    known_body, _ = _build_term("1")
    right = CallSiteValue(
        target_name="known_right",
        arg_values=(),
        parameters=(),
        term=ctor("call:known_right", []),
        body=SugarBody(sugar=known_body, role=SugarRole.TERM),
        site=site,
    )

    with pytest.raises(FactoryPanic, match="write more Floor"):
        StringValue("1").subtract(right, site)


def test_string_minus_opaque_native_result_conserves_the_assertion() -> None:
    source = (
        "from pandas import Timedelta\n"
        "\n"
        "def test_a():\n"
        '    item = "1"\n'
        '    td = Timedelta("1 day")\n'
        "    assert item - td == 0\n"
    )

    payload, gaps = audit_lift_file(source, "representative.py")
    rpc = payload.to_rpc()
    assertions = account_lift_coverage(
        census_source(source, file="representative.py"), rpc
    ).to_json()["assertions"]

    assert gaps == []
    assert assertions["stated"] == 1
    assert assertions["lifted_cited"] == 1
    assert assertions["refused_loud"] == 0
    assert assertions["silently_unaccounted"] == 0
    assert [effect["kind"] for effect in rpc["effects"]] == ["effect"]
    assert "runtime __sub__/__rsub__ dispatch" in rpc["effects"][0]["reason"]


def test_numeric_symbolic_subtraction_uses_native_coordinate() -> None:
    site = SourceFragment.from_source("4 - runtime_n\n", "t.py").statements()[0]

    outcome = TermValue(4).subtract(SymbolicValue(make_var("runtime_n")), site)

    assert outcome == Complete(
        SymbolicValue(ctor("-", [num(4), make_var("runtime_n")]))
    )


def test_concrete_set_difference_constructs_exact_members() -> None:
    site = SourceFragment.from_source("left - right\n", "t.py").statements()[0]
    left = SetValue((TermValue(1), TermValue(2), TermValue(3)))
    right = SetValue((TermValue(2), TermValue(4)))

    outcome = left.subtract(right, site)

    assert outcome == Complete(SetValue((TermValue(1), TermValue(3))))


@pytest.mark.parametrize(
    "left",
    (
        TermValue(4),
        ComprehensionValue(ctor("python:set_comprehension", [make_var("item")])),
        NativeCallableValue("pandas.NaT", "/native/pandas.so"),
    ),
)
def test_opaque_call_result_subtraction_is_a_witnessed_runtime_effect(left) -> None:
    site = SourceFragment.from_source("left - runtime_right()\n", "t.py").statements()[
        0
    ]
    right = CallSiteValue(
        target_name="runtime_right",
        arg_values=(),
        parameters=(),
        term=ctor("call:runtime_right", []),
        body=None,
        site=site,
    )

    outcome = left.subtract(right, site)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SubtractRuntimeEffect)
    operand = ctor("-", [left.to_term(owner="test"), right.to_term(owner="test")])
    assert outcome.effect.witness.operand == operand
    assert outcome.effect.witness.operation == ctor("py.subtract", [operand])
    assert outcome.effect.witness.locus == "t.py:1:0"


def test_subtract_truthful_and_lying_twins_reach_opposite_verdicts(tmp_path) -> None:
    prefix = "def A():\n    return 7 - 2\n\n"
    truthful = run_source_through_real_solver(
        tmp_path / "truthful", prefix + "def test_a():\n    assert A() == 5\n"
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying", prefix + "def test_a():\n    assert A() == 6\n"
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "SubtractOpSugar" in truthful.selected_sugars
    assert "SubtractOpSugar" in lying.selected_sugars

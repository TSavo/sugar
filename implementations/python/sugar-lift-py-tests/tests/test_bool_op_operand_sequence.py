"""Python ``and``/``or`` are operand-selecting, short-circuit sequences."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import FloorValue, SymbolicValue, TermValue
from sugar_lift_py_tests.floor.ground_exit import ground_type_error
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, make_var, str_const
from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted, outcome_to_exitset
from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import BoolOp
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class _Site:
    filename: str = "test_bool_op_operand_sequence.py"
    line: int = 1
    col: int = 0
    source: str = "result = left and right"


@dataclass(frozen=True)
class _Operand(FloorValue):
    label: str
    truth_outcome: object
    truth_calls: list[str] = field(compare=False)

    def denotes_value(self) -> bool:
        return True

    def runtime_type_is_decided(self) -> bool:
        return True

    def truth(self, site):
        del site
        self.truth_calls.append(self.label)
        return self.truth_outcome


@dataclass(frozen=True)
class _ProbeSugar(Sugar):
    label: str
    value: FloorValue
    evaluations: list[str] = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        self.evaluations.append(self.label)
        return Complete(self.value)


@dataclass(frozen=True)
class _ExceptionalTruth(FloorValue):
    def denotes_value(self) -> bool:
        return True

    def runtime_type_is_decided(self) -> bool:
        return True

    def truth(self, site):
        return ground_type_error(site=site, owner="_ExceptionalTruth.truth")

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor

        return ctor("python:boolop_exceptional_truth_probe", [])


def _truth(value: bool):
    site = _Site()
    literal = TrueBoolLiteralSugar(site) if value else FalseBoolLiteralSugar(site)
    return Complete(literal)


def _completed_value(outcome):
    exits = outcome_to_exitset(outcome).exits
    assert len(exits) == 1
    face = exits[0]
    assert not isinstance(face, Halted)
    return face.value


def _formal_carrier():
    source = "def choose(left, right):\n    return left and right\n"
    node = next(
        item
        for item in SourceFile(
            (source, "boolop_caller.py", blake3_512_of(source.encode()))
        ).nodes()
        if isinstance(item, BoolOp)
    )
    span = node.fragment.line_col_span
    locus = SourceFragmentCoordinateV1(
        node.fragment.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    formal = FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=locus.source_cid,
        owner_definition_locus=locus,
        declaration_locus=locus,
        ordinal=0,
        parameter_kind="positional-or-keyword",
        declared_name="left",
        sort=PrimitiveSort("Value"),
    )
    evaluations: list[str] = []
    right = _Operand("right", _truth(True), [])
    outcome = BoolOpSugar(
        "And",
        (
            _ProbeSugar(
                "left", SymbolicValue(make_var("left"), formal), evaluations
            ),
            _ProbeSugar("right", right, evaluations),
        ),
        node.fragment,
    ).desugar()
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    return outcome, formal, evaluations, right


class _ExpectedType:
    def __init__(self, name: str):
        self._identity = ctor(
            "python:exception_type_identity",
            [str_const("builtins"), str_const(name)],
        )

    def exception_type_identity(self):
        return self._identity


def test_left_operand_is_evaluated_and_truth_tested_exactly_once() -> None:
    evaluations: list[str] = []
    truth_calls: list[str] = []
    left = _Operand("left", _truth(True), truth_calls)
    right = _Operand("right", _truth(False), truth_calls)

    result = BoolOpSugar(
        "And",
        (
            _ProbeSugar("left", left, evaluations),
            _ProbeSugar("right", right, evaluations),
        ),
        _Site(),
    ).desugar()

    assert evaluations == ["left", "right"]
    assert truth_calls == ["left"]
    assert _completed_value(result) is right


def test_false_left_returns_left_without_giving_right_any_outcome() -> None:
    evaluations: list[str] = []
    truth_calls: list[str] = []
    left = _Operand("left", _truth(False), truth_calls)
    right = _Operand("right", _truth(True), truth_calls)

    result = BoolOpSugar(
        "And",
        (
            _ProbeSugar("left", left, evaluations),
            _ProbeSugar("right", right, evaluations),
        ),
        _Site(),
    ).desugar()

    assert evaluations == ["left"]
    assert truth_calls == ["left"]
    assert _completed_value(result) is left


def test_true_left_continues_to_right_without_truth_testing_final_operand() -> None:
    evaluations: list[str] = []
    truth_calls: list[str] = []
    left = _Operand("left", _truth(True), truth_calls)
    right = _Operand("right", _truth(False), truth_calls)

    result = BoolOpSugar(
        "And",
        (
            _ProbeSugar("left", left, evaluations),
            _ProbeSugar("right", right, evaluations),
        ),
        _Site(),
    ).desugar()

    assert evaluations == ["left", "right"]
    assert truth_calls == ["left"]
    assert _completed_value(result) is right


def test_halted_left_truth_test_propagates_and_never_reaches_right() -> None:
    evaluations: list[str] = []
    truth_calls: list[str] = []
    effect = RaiseEffect(occurrence=AuthenticatedRaiseLocus.of('test_bool_op_operand_sequence.py:1:0'), exception_name='LeftTruthError', blame='test_bool_op_operand_sequence.py:1:0')
    left = _Operand("left", ExitSet.halted(effect), truth_calls)
    right = _Operand("right", _truth(True), truth_calls)

    result = BoolOpSugar(
        "And",
        (
            _ProbeSugar("left", left, evaluations),
            _ProbeSugar("right", right, evaluations),
        ),
        _Site(),
    ).desugar()

    exits = outcome_to_exitset(result).exits
    assert evaluations == ["left"]
    assert truth_calls == ["left"]
    assert len(exits) == 1
    assert isinstance(exits[0], Halted)
    assert exits[0].effect is effect


def test_boolop_result_is_selected_operand_never_coerced_boolean() -> None:
    evaluations: list[str] = []
    truth_calls: list[str] = []
    left = _Operand("non_bool_left", _truth(False), truth_calls)
    right = _Operand("non_bool_right", _truth(True), truth_calls)

    stopped = BoolOpSugar(
        "And",
        (
            _ProbeSugar("left", left, evaluations),
            _ProbeSugar("right", right, evaluations),
        ),
        _Site(),
    ).desugar()
    continued = BoolOpSugar(
        "Or",
        (
            _ProbeSugar("left", left, evaluations),
            _ProbeSugar("right", right, evaluations),
        ),
        _Site(),
    ).desugar()

    assert _completed_value(stopped) is left
    assert _completed_value(continued) is right
    assert not isinstance(_completed_value(stopped), FalseBoolLiteralSugar)
    assert not isinstance(_completed_value(continued), TrueBoolLiteralSugar)


def test_formal_boolop_defers_truth_to_existing_unary_carrier() -> None:
    carrier, formal, evaluations, _ = _formal_carrier()
    assert carrier.demand.operator == "boolop_truth"
    assert carrier.demand.operand_coordinate_cids == (formal.coordinate_cid,)
    assert evaluations == ["left"]


def test_false_caller_actual_returns_that_actual_and_never_reaches_right() -> None:
    carrier, formal, evaluations, _ = _formal_carrier()
    actual = TermValue(0)
    exits = carrier.discharge({formal.coordinate_cid: actual})
    assert evaluations == ["left"]
    assert len(exits.exits) == 1
    assert not isinstance(exits.exits[0], Halted)
    assert exits.exits[0].value is actual


def test_true_caller_actual_reaches_and_returns_right_operand() -> None:
    carrier, formal, evaluations, right = _formal_carrier()
    exits = carrier.discharge({formal.coordinate_cid: TermValue(1)})
    assert evaluations == ["left", "right"]
    assert len(exits.exits) == 1
    assert exits.exits[0].value is right


def test_halted_caller_truth_propagates_and_never_reaches_right() -> None:
    carrier, formal, evaluations, _ = _formal_carrier()
    exits = carrier.discharge({formal.coordinate_cid: _ExceptionalTruth()})
    assert evaluations == ["left"]
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Halted)
    assert exits.exits[0].effect.exception_type_coordinate == _identity('TypeError')


def test_wrong_boundary_type_does_not_consume_caller_truth_halt() -> None:
    """The assertion expectation verifies; it never creates the producer type."""
    carrier, formal, _, _ = _formal_carrier()
    produced = carrier.discharge({formal.coordinate_cid: _ExceptionalTruth()})
    original = produced.exits[0]
    assert isinstance(original, Halted)

    routed = produced.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(_ExpectedType("ValueError"))
        ),
    )
    surviving = [
        face
        for face in routed.exits
        if isinstance(face, Halted) and face.effect is original.effect
    ]
    assert len(surviving) == 1


def test_undecided_caller_actual_remains_named_refusal() -> None:
    carrier, formal, _, _ = _formal_carrier()
    with pytest.raises(SugarNotWritten) as caught:
        carrier.discharge(
            {formal.coordinate_cid: SymbolicValue(make_var("still_unknown"))}
        )
    assert caught.value.owner == "boolean_operation_exception_floor"


def test_lying_bool_coercion_cannot_replace_selected_operand() -> None:
    carrier, formal, evaluations, _ = _formal_carrier()
    actual = TermValue(0)
    selected = carrier.discharge({formal.coordinate_cid: actual}).exits[0].value
    assert selected is actual
    assert not isinstance(selected, FalseBoolLiteralSugar)
    assert evaluations == ["left"]

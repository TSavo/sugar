"""Python ``and``/``or`` are operand-selecting, short-circuit sequences."""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted, outcome_to_exitset
from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


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
    effect = RaiseEffect(
        exception_name="LeftTruthError",
        occurrence="test_bool_op_operand_sequence.py:1:0",
        blame="test_bool_op_operand_sequence.py:1:0",
    )
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

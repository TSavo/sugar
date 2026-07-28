"""BoolOpSugar ground and mixed operands — exact formula twins.

Permanent floor: a ground boolean (None → False, True, False) must not raise a
bare NotImplementedError. Formulas must be the FOL truth values (or the
symbolic atom with ground identities absorbed), not merely "some PredicateValue".
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor.predicate_value import PredicateValue
from sugar_lift_py_tests.ir import make_var, num, py_eq
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.outcome import Complete, outcome_to_exitset
from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar
from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.name_sugar import NameSugar
from sugar_lift_py_tests.sugar.none_literal_sugar import NoneLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


@dataclass(frozen=True)
class _Site:
    filename: str = "test_bool_op_ground_operand.py"
    line: int = 1
    col: int = 0
    source: str = "None and True"

    def compare_left(self):
        # EqualityOpSugar refinement path; ground/symbolic fold tests do not
        # need a real coordinate.
        class _Left:
            def dotted_expr_name(self):
                return None

        return _Left()


def _bool_op(kind: str, *operands: object):
    site = _Site()
    sugar = BoolOpSugar(op_kind=kind, values=operands, site=site)
    return sugar.desugar(None)


def _completed_values(outcome):
    return tuple(
        face.value
        for face in outcome_to_exitset(outcome).exits
        if hasattr(face, "value")
    )


def _has_symbolic_formula(outcome) -> bool:
    return any(
        isinstance(value, PredicateValue) and value.formula == _symbolic_z_eq_1()
        for value in _completed_values(outcome)
    )


def _z_eq_1() -> EqualityOpSugar:
    site = _Site()
    return EqualityOpSugar(
        left=NameSugar(name="z", site=site),
        right=IntLiteralSugar(value=1, site=site),
        site=site,
    )


def _symbolic_z_eq_1():
    return py_eq(make_var("z"), num(1))


def test_none_and_true_is_false() -> None:
    site = _Site()
    outcome = _bool_op(
        "And",
        NoneLiteralSugar(site=site),
        TrueBoolLiteralSugar(site=site),
    )
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, NoneValue)


def test_true_and_false_is_false() -> None:
    site = _Site()
    outcome = _bool_op(
        "And",
        TrueBoolLiteralSugar(site=site),
        FalseBoolLiteralSugar(site=site),
    )
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, FalseBoolLiteralSugar)


def test_none_or_true_is_true() -> None:
    site = _Site()
    outcome = _bool_op(
        "Or",
        NoneLiteralSugar(site=site),
        TrueBoolLiteralSugar(site=site),
    )
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)


def test_symbolic_and_true_absorbs_to_symbolic() -> None:
    """(z == 1) and True → py.eq(z, 1); True is identity of ∧."""
    site = _Site()
    outcome = _bool_op("And", _z_eq_1(), TrueBoolLiteralSugar(site=site))
    assert _has_symbolic_formula(outcome)
    assert any(
        isinstance(value, TrueBoolLiteralSugar) for value in _completed_values(outcome)
    )


def test_true_and_symbolic_absorbs_to_symbolic() -> None:
    """True and (z == 1) → py.eq(z, 1); order must not matter for absorption."""
    site = _Site()
    outcome = _bool_op("And", TrueBoolLiteralSugar(site=site), _z_eq_1())
    assert _has_symbolic_formula(outcome)


def test_symbolic_or_false_absorbs_to_symbolic() -> None:
    """(z == 1) or False → py.eq(z, 1); False is identity of ∨."""
    site = _Site()
    outcome = _bool_op("Or", _z_eq_1(), FalseBoolLiteralSugar(site=site))
    assert _has_symbolic_formula(outcome)
    assert any(
        isinstance(value, FalseBoolLiteralSugar) for value in _completed_values(outcome)
    )


def test_false_and_symbolic_is_false() -> None:
    """False and (z == 1) → false; proves ∧ selects false, not the symbolic."""
    site = _Site()
    outcome = _bool_op("And", FalseBoolLiteralSugar(site=site), _z_eq_1())
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, FalseBoolLiteralSugar)


def test_true_or_symbolic_is_true() -> None:
    """True or (z == 1) → true; proves ∨ selects true, not the symbolic."""
    site = _Site()
    outcome = _bool_op("Or", TrueBoolLiteralSugar(site=site), _z_eq_1())
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)


def test_symbolic_and_false_is_false() -> None:
    site = _Site()
    outcome = _bool_op("And", _z_eq_1(), FalseBoolLiteralSugar(site=site))
    assert _has_symbolic_formula(outcome)
    assert any(
        isinstance(value, FalseBoolLiteralSugar) for value in _completed_values(outcome)
    )


def test_symbolic_or_true_is_true() -> None:
    site = _Site()
    outcome = _bool_op("Or", _z_eq_1(), TrueBoolLiteralSugar(site=site))
    assert _has_symbolic_formula(outcome)
    assert any(
        isinstance(value, TrueBoolLiteralSugar) for value in _completed_values(outcome)
    )

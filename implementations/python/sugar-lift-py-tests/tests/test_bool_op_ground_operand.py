"""BoolOpSugar ground and mixed operands — exact formula twins.

Permanent floor: a ground boolean (None → False, True, False) must not raise a
bare NotImplementedError. Formulas must be the FOL truth values (or the
symbolic atom with ground identities absorbed), not merely "some PredicateValue".
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor.predicate_value import PredicateValue
from sugar_lift_py_tests.ir import make_var, num, py_eq
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard
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


def _bool_op(kind: str, *operands: object) -> PredicateValue:
    site = _Site()
    sugar = BoolOpSugar(op_kind=kind, values=operands, site=site)
    out = sugar.desugar(None)
    assert isinstance(out, Complete), out
    assert isinstance(out.value, PredicateValue), type(out.value)
    return out.value


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
    value = _bool_op(
        "And",
        NoneLiteralSugar(site=site),
        TrueBoolLiteralSugar(site=site),
    )
    assert value.formula == false_guard()


def test_true_and_false_is_false() -> None:
    site = _Site()
    value = _bool_op(
        "And",
        TrueBoolLiteralSugar(site=site),
        FalseBoolLiteralSugar(site=site),
    )
    assert value.formula == false_guard()


def test_none_or_true_is_true() -> None:
    site = _Site()
    value = _bool_op(
        "Or",
        NoneLiteralSugar(site=site),
        TrueBoolLiteralSugar(site=site),
    )
    assert value.formula == true_guard()


def test_symbolic_and_true_absorbs_to_symbolic() -> None:
    """(z == 1) and True → py.eq(z, 1); True is identity of ∧."""
    site = _Site()
    value = _bool_op("And", _z_eq_1(), TrueBoolLiteralSugar(site=site))
    assert value.formula == _symbolic_z_eq_1()


def test_true_and_symbolic_absorbs_to_symbolic() -> None:
    """True and (z == 1) → py.eq(z, 1); order must not matter for absorption."""
    site = _Site()
    value = _bool_op("And", TrueBoolLiteralSugar(site=site), _z_eq_1())
    assert value.formula == _symbolic_z_eq_1()


def test_symbolic_or_false_absorbs_to_symbolic() -> None:
    """(z == 1) or False → py.eq(z, 1); False is identity of ∨."""
    site = _Site()
    value = _bool_op("Or", _z_eq_1(), FalseBoolLiteralSugar(site=site))
    assert value.formula == _symbolic_z_eq_1()


def test_false_and_symbolic_is_false() -> None:
    """False and (z == 1) → false; proves ∧ selects false, not the symbolic."""
    site = _Site()
    value = _bool_op("And", FalseBoolLiteralSugar(site=site), _z_eq_1())
    assert value.formula == false_guard()


def test_true_or_symbolic_is_true() -> None:
    """True or (z == 1) → true; proves ∨ selects true, not the symbolic."""
    site = _Site()
    value = _bool_op("Or", TrueBoolLiteralSugar(site=site), _z_eq_1())
    assert value.formula == true_guard()


def test_symbolic_and_false_is_false() -> None:
    site = _Site()
    value = _bool_op("And", _z_eq_1(), FalseBoolLiteralSugar(site=site))
    assert value.formula == false_guard()


def test_symbolic_or_true_is_true() -> None:
    site = _Site()
    value = _bool_op("Or", _z_eq_1(), TrueBoolLiteralSugar(site=site))
    assert value.formula == true_guard()

"""A complex literal stands on the arithmetic floor for the whole numeric tower.

``1 + 1j`` was the largest remaining desugar construction panic on the installed
pandas tree (``owner=add observed=TermValue``). The mechanism is the closed
numeric tower -- int/float/bool/complex are closed under +, -, * -- not a
per-operand spelling.

Python is the reference: every folded result is asserted against Python's own
evaluation of the same expression, so the floor is a faithful mirror rather than
a re-derivation.

Each positive arm carries a discriminating arm: a shape that must NOT enter the
complex field.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ComplexValue,
    ListValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.floor.complex_arithmetic import complex_field_coordinate
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

SITE = "complex-site"


def _folded(outcome) -> complex:
    assert isinstance(outcome, Complete)
    assert type(outcome.value) is ComplexValue
    return complex(outcome.value.real, outcome.value.imag)


# -- positive arm: the mixed-operand pairs the census actually found ----------


def test_int_plus_complex_literal_is_pythons_own_sum() -> None:
    """The exact pandas shape: `1 + 1j`."""
    assert _folded(TermValue(1).add(ComplexValue(0.0, 1.0), SITE)) == 1 + 1j


def test_complex_literal_plus_int_is_pythons_own_sum() -> None:
    assert _folded(ComplexValue(0.0, 1.0).add(TermValue(1), SITE)) == 1j + 1


def test_float_plus_complex_literal_is_pythons_own_sum() -> None:
    """The exact pandas shape: `1.0 + 1.0j`."""
    assert _folded(TermValue(1.0).add(ComplexValue(0.0, 1.0), SITE)) == 1.0 + 1.0j


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    (
        (TermValue(1), ComplexValue(0.0, 2.0), 1 + 2j),
        (ComplexValue(3.0, 4.0), ComplexValue(1.0, 2.0), (3 + 4j) + (1 + 2j)),
        (ComplexValue(3.0, 4.0), TermValue(2.5), (3 + 4j) + 2.5),
        (TermValue(True), ComplexValue(0.0, 1.0), True + 1j),
        (TrueBoolLiteralSugar(site=SITE), ComplexValue(0.0, 1.0), 1 + 1j),
        (FalseBoolLiteralSugar(site=SITE), ComplexValue(0.0, 1.0), 0 + 1j),
    ),
)
def test_addition_mirrors_python_for_every_field_member(left, right, expected) -> None:
    assert _folded(left.add(right, SITE)) == expected


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    (
        (TermValue(1), ComplexValue(0.0, 1.0), 1 - 1j),
        (ComplexValue(0.0, 1.0), TermValue(1), 1j - 1),
        (ComplexValue(3.0, 4.0), ComplexValue(1.0, 2.0), (3 + 4j) - (1 + 2j)),
    ),
)
def test_subtraction_mirrors_python(left, right, expected) -> None:
    assert _folded(left.subtract(right, SITE)) == expected


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    (
        (TermValue(2), ComplexValue(0.0, 1.0), 2 * 1j),
        (ComplexValue(0.0, 1.0), ComplexValue(0.0, 1.0), 1j * 1j),
        (ComplexValue(1.0, 2.0), ComplexValue(3.0, 4.0), (1 + 2j) * (3 + 4j)),
        (ComplexValue(1.0, 2.0), TermValue(3.0), (1 + 2j) * 3.0),
    ),
)
def test_multiplication_mirrors_python(left, right, expected) -> None:
    assert _folded(left.multiply(right, SITE)) == expected


def test_i_squared_is_exactly_negative_one() -> None:
    """The identity that makes the field a field, asserted exactly."""
    product = ComplexValue(0.0, 1.0).multiply(ComplexValue(0.0, 1.0), SITE).value

    assert product.real == -1.0
    assert product.imag == 0.0


# -- discriminating arm: nothing else is widened into the field ---------------


def test_two_integers_still_fold_on_the_number_floor() -> None:
    """No operand was silently widened: int + int is still an int TermValue."""
    outcome = TermValue(3).add(TermValue(4), SITE)

    assert isinstance(outcome, Complete)
    assert type(outcome.value) is TermValue
    assert outcome.value.value == 7
    assert type(outcome.value.value) is int


def test_two_floats_still_fold_on_the_number_floor() -> None:
    outcome = TermValue(1.5).add(TermValue(2.5), SITE)

    assert type(outcome.value) is TermValue
    assert outcome.value.value == 4.0


@pytest.mark.parametrize(
    "off_field",
    (
        TermValue("1"),
        TermValue(None),
        TermValue(b"1"),
        ListValue((TermValue(1),)),
        StringValue("1"),
    ),
)
def test_a_non_member_operand_keeps_the_complex_floor_loud(off_field) -> None:
    """`panic = gap`: the field law admits members, and refuses to invent for
    anything else -- including values Python itself would reject."""
    with pytest.raises(ConstructionPanic) as raised:
        ComplexValue(0.0, 1.0).add(off_field, SITE)

    info = raised.value.info
    assert info.owner == "add"
    assert info.observed == "ComplexValue"
    assert type(off_field).__name__ in info.fix


def test_an_integer_too_large_for_the_float_field_stays_loud() -> None:
    """Python raises OverflowError here. No arm constructs that exit, so the
    pair stays a named gap rather than a fabricated value."""
    assert complex_field_coordinate(TermValue(10**400)) is None

    with pytest.raises(ConstructionPanic) as raised:
        TermValue(10**400).add(ComplexValue(0.0, 1.0), SITE)

    info = raised.value.info
    assert info.owner == "add"
    assert info.observed == "TermValue"
    assert "ComplexValue" in info.fix


def test_a_result_that_overflows_the_float_field_stays_loud() -> None:
    """Folding opened an edge no source literal could reach.

    `(1e308+0j) * (1e308+0j)` is an infinity in Python -- a real IEEE result.
    But ComplexValue.to_term projects through a canonical decimal string and has
    no coordinate for it: before this guard the fold produced
    ``_ConstReal(value='Infinity', sort=Real)``, the TEXT "Infinity" standing in
    a Real slot, which the theory cannot read back. Constructing that is
    inventing a preimage, so the pair stays loud.
    """
    huge = ComplexValue(1e308, 0.0)

    with pytest.raises(ConstructionPanic) as raised:
        huge.multiply(huge, SITE)

    assert raised.value.info.owner == "multiply"


def test_a_nan_result_stays_loud() -> None:
    """inf * 0 is NaN in Python; NaN has no canonical decimal string either."""
    with pytest.raises(ConstructionPanic):
        ComplexValue(float("inf"), 0.0).multiply(ComplexValue(0.0, 0.0), SITE)


def test_a_finite_result_at_the_edge_of_the_field_still_folds() -> None:
    """The discrimination: the guard is about REPRESENTABILITY, not magnitude.

    A guard that refused by size would be the same kind of cardinality cap this
    floor deleted from sequence repetition. 1e308 + 1.0 is finite, so it folds.
    """
    outcome = ComplexValue(1e308, 0.0).add(ComplexValue(1.0, 0.0), SITE)

    assert isinstance(outcome, Complete)
    assert outcome.value.real == 1e308 + 1.0


def test_no_folded_result_ever_projects_a_non_numeric_real() -> None:
    """The law behind the guard, stated on the term the theory actually reads."""
    from sugar_lift_py_tests.ir import _ConstReal

    outcome = ComplexValue(1e200, 0.0).multiply(ComplexValue(1e-200, 0.0), SITE)
    term = outcome.value.to_term(owner=SITE)

    for arg in term.args:
        assert isinstance(arg, _ConstReal)
        assert float(arg.value) == float(arg.value)  # not NaN
        assert abs(float(arg.value)) != float("inf")


def test_an_opaque_operand_keeps_the_undecided_third_value_loud() -> None:
    """A complex plus an opaque callsite is not a field member; the complex
    floor must not swallow it into a fabricated concrete complex.

    What this arm pinned was the REFUSAL to fabricate a complex, and that is
    unchanged: the outcome below is not a ``ComplexValue``. What it also
    asserted -- a completed symbolic coordinate -- erased the exceptional face.
    An unexecuted call's result type is undecided, so Python's own operator
    dispatch for the pair is undecided and remains a named producer gap.

    See ``tests/test_undecided_binary_operand_law.py``.
    """
    opaque = CallSiteValue("vendor.op", (), (), ctor("call:vendor.op", []), None)

    assert complex_field_coordinate(opaque) is None

    with pytest.raises(ConstructionPanic) as raised:
        ComplexValue(0.0, 1.0).add(opaque, SITE)
    assert raised.value.info.owner == "binary_operation_exception_floor"


def test_an_integer_plus_a_symbolic_operand_is_still_undecided() -> None:
    """The complex arm sits AFTER the symbolic arms and stole none of them."""
    symbolic = SymbolicValue(TermValue(2).to_term(owner=SITE))

    with pytest.raises(ConstructionPanic) as raised:
        TermValue(1).add(symbolic, SITE)
    assert raised.value.info.owner == "binary_operation_exception_floor"


# -- the field coordinate is read from the value, not from a name -------------


def test_the_field_coordinate_comes_from_the_constructed_value() -> None:
    assert complex_field_coordinate(ComplexValue(1.0, 2.0)) == 1 + 2j
    assert complex_field_coordinate(TermValue(7)) == 7 + 0j
    assert complex_field_coordinate(TermValue(7.5)) == 7.5 + 0j
    assert complex_field_coordinate(TrueBoolLiteralSugar(site=SITE)) == 1 + 0j
    assert complex_field_coordinate(FalseBoolLiteralSugar(site=SITE)) == 0j

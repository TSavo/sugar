"""The closed arithmetic law for Python's complex field.

``1 + 1j`` was the largest remaining desugar construction panic on the
installed pandas tree: ``owner=add observed=TermValue``. The left value
(a number) stands on the addition floor, but no arm named its right operand,
so the pair fell through to the loud default.

The mechanism is the numeric tower, not a spelling: int, float, bool and
complex are CLOSED under addition, subtraction and multiplication, and the
result of mixing any of them with a complex is a complex. That is one law over
a value category, mirroring ``TermValue``'s own closed int/float arithmetic and
``SetValue``'s closed-equality membership rather than inventing per-operand
semantics.

Two things this law deliberately does NOT do:

* It never engages unless one operand is genuinely a ``ComplexValue``, so
  int-with-int arithmetic keeps folding on the ``TermValue`` floor and no value
  is silently widened into the complex field.
* It never invents a result when Python itself would not produce one. An
  integer too large to enter the float field raises ``OverflowError`` in
  Python; this law has no arm for that exceptional exit, so the pair stays
  loud. ``panic = gap``.

The operand's category is read from its own authenticated construction type
(``ComplexValue`` carries its real/imaginary parts; ``TermValue`` carries its
Python payload) -- never from a lexical type name at the call site.
"""

from __future__ import annotations

from typing import Callable, Optional


def complex_field_coordinate(value) -> Optional[complex]:
    """This value's coordinate in Python's complex field, or ``None``.

    ``None`` means "not a member of the field as constructed" -- the caller
    must fall through to its own loud arm, never substitute a default.
    """
    from sugar_lift_py_tests.floor.complex_value import ComplexValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    if type(value) is ComplexValue:
        return complex(value.real, value.imag)
    if type(value) is TermValue and type(value.value) in (int, float, bool):
        try:
            return complex(value.value)
        except OverflowError:
            # Python's own OverflowError boundary. No arm here constructs that
            # exceptional exit, so the caller's loud gap is the honest answer.
            return None
    if type(value) is TrueBoolLiteralSugar:
        return complex(1)
    if type(value) is FalseBoolLiteralSugar:
        return complex(0)
    return None


def closed_complex_operation(
    left,
    right,
    site,
    *,
    operate: Callable[[complex, complex], complex],
):
    """``operate(left, right)`` in the complex field, or ``None`` to fall through.

    ``None`` is returned -- never a panic -- so that each floor keeps ownership
    of its own gap testimony and reports its own (owner, pair).
    """
    del site
    from sugar_lift_py_tests.floor.complex_value import ComplexValue
    from sugar_lift_py_tests.outcome import Complete

    if type(left) is not ComplexValue and type(right) is not ComplexValue:
        return None
    left_coordinate = complex_field_coordinate(left)
    right_coordinate = complex_field_coordinate(right)
    if left_coordinate is None or right_coordinate is None:
        return None
    try:
        product = operate(left_coordinate, right_coordinate)
    except OverflowError:
        return None
    import math

    if not (math.isfinite(product.real) and math.isfinite(product.imag)):
        # Python's own answer here is an infinity or a NaN. Those are real IEEE
        # results, but ``ComplexValue.to_term`` projects through a canonical
        # decimal string and has no coordinate for them: it emits
        # ``_ConstReal(value='Infinity', sort=Real)`` -- the TEXT "Infinity"
        # standing in a Real slot, a preimage no source literal could produce
        # and the theory cannot read back. Constructing the value would be
        # inventing that preimage, so the pair stays loud instead.
        return None
    return Complete(ComplexValue(product.real, product.imag))


def complex_add(left, right, site):
    return closed_complex_operation(left, right, site, operate=lambda a, b: a + b)


def complex_subtract(left, right, site):
    return closed_complex_operation(left, right, site, operate=lambda a, b: a - b)


def complex_multiply(left, right, site):
    return closed_complex_operation(left, right, site, operate=lambda a, b: a * b)

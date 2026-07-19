"""#4135: unary floor verbs and expression statements on non-Term values.

Bool literals are their own floor values. Without FloorValue inheritance they
raised AttributeError on unary_minus/plus/bitwise_invert and on
as_expression_statement -- a hard crash that escaped the audit door. After
the fix they hit the FloorValue base defaults (FactoryPanic / SupportValue).
"""

from __future__ import annotations

import pytest

from factory_reduce import compose_block, reduce_value

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

# -- anti-hard-crash teeth: FactoryPanic, never AttributeError --------------


@pytest.mark.parametrize(
    ("expr", "expected"),
    [("-True", -1), ("~True", -2), ("-False", 0), ("~False", -1)],
)
def test_bool_integer_unary_operators_construct_exact_values(
    expr: str, expected: int
) -> None:
    assert reduce_value(expr) == TermValue(expected)


def test_unbuilt_bool_unary_plus_panics_cleanly_not_attribute_error() -> None:
    """The still-unbuilt bool unary-plus floor stays a loud FactoryPanic."""
    with pytest.raises(FactoryPanic) as raised:
        reduce_value("+True")
    assert raised.value.info.gap_kind.name == "FLOOR" or (
        raised.value.info.requested
        and "unary" in raised.value.info.requested
        or "bitwise" in raised.value.info.requested
    )
    # Observed is the bool sugar type -- clean Floor gap, not a Python crash.
    assert raised.value.info.observed in {
        "TrueBoolLiteralSugar",
        "FalseBoolLiteralSugar",
    }


def test_not_true_as_expression_statement_does_not_attribute_error() -> None:
    """Bare `not True` as a statement: handled via as_expression_statement.

    Before: AttributeError on FalseBoolLiteralSugar.as_expression_statement.
    After: FloorValue default discards to Support (or clean panic) -- never crash.
    """
    # compose_block threads the expression statement then returns.
    block = compose_block("    not True\n    return 1\n")
    assert isinstance(block, BlockValue)
    assert any(
        isinstance(s, ReturnValue) and s.value == TermValue(1) for s in block.statements
    )


def test_audit_lift_constructs_bool_unary_minus_function_contract() -> None:
    """Normal audit over return -True constructs the exact integer result.

    (x = -True alone does not reduce the unary -- BoundVar holds the source
    until a use recomposes it. return -True forces desugar of the unary.)
    """
    source = "def f():\n    return -True\n"
    payload, gaps = audit_lift_file(source, "t.py")

    assert not gaps
    assert any(getattr(row, "kind", None) == "function-contract" for row in payload.ir)


# -- do not regress ground folds -------------------------------------------


def test_not_true_still_folds_false() -> None:
    assert isinstance(reduce_value("not True"), FalseBoolLiteralSugar)


def test_not_false_still_folds_true() -> None:
    assert isinstance(reduce_value("not False"), TrueBoolLiteralSugar)


def test_unary_minus_five_still_folds() -> None:
    assert reduce_value("-5") == TermValue(-5)


def test_bitwise_invert_zero_still_folds() -> None:
    assert reduce_value("~0") == TermValue(-1)


def test_unary_plus_three_still_folds() -> None:
    assert reduce_value("+3") == TermValue(3)

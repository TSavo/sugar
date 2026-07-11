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
    "expr",
    ["-True", "+True", "~True", "-False", "~False"],
)
def test_bool_unary_panics_cleanly_not_attribute_error(expr: str) -> None:
    """Repro inputs that AttributeError'd before #4135 now FactoryPanic."""
    with pytest.raises(FactoryPanic) as raised:
        reduce_value(expr)
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
    assert any(isinstance(s, ReturnValue) and s.value == TermValue(1) for s in block.statements)


def test_audit_door_holds_unary_on_bool_as_floor_gap() -> None:
    """audit_lift_file over return -True yields a Floor gap row, not a crash.

    (x = -True alone does not reduce the unary -- BoundVar holds the source
    until a use recomposes it. return -True forces desugar of the unary.)
    """
    source = "def f():\n    return -True\n"
    payload, gaps = audit_lift_file(source, "t.py", hold_panic=True)
    assert gaps, "audit door must hold the Floor gap, not crash"
    assert any(
        g.info.get("observed") == "TrueBoolLiteralSugar"
        and "unary-minus" in g.info.get("requested", "")
        for g in gaps
    ) or any(g.info.get("gap_kind") == "Floor" for g in gaps), [g.info for g in gaps]
    # The def panicked -- no function-contract row; the gap is the signal.
    assert not any(getattr(row, "kind", None) == "function-contract" for row in payload.ir)


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

from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import SetValue, TermValue
from sugar_lift_py_tests.outcome import Complete


def test_set_bitwise_or_constructs_exact_union() -> None:
    left = SetValue((TermValue(1), TermValue(2)))
    right = SetValue((TermValue(2), TermValue(3)))

    assert left.bitwise_or(right, "t.py:1") == Complete(
        SetValue((TermValue(1), TermValue(2), TermValue(3)))
    )


def test_set_bitwise_or_unsupported_concrete_twin_stays_loud() -> None:
    with pytest.raises(FactoryPanic, match="owner=bitwise_or"):
        SetValue((TermValue(1),)).bitwise_or(TermValue(2), "t.py:1")

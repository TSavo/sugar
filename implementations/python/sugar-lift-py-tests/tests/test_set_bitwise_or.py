from __future__ import annotations

import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.floor import SetValue, TermValue
from sugar_lift_py_tests.outcome import ExitSet


def test_set_bitwise_or_constructs_exact_union() -> None:
    left = fresh(SetValue, (TermValue(1), TermValue(2)))
    right = fresh(SetValue, (TermValue(2), TermValue(3)))

    assert left.bitwise_or(right, "t.py:1", None) == ExitSet.completed(
        fresh(SetValue, (TermValue(1), TermValue(2), TermValue(3)))
    )


def test_set_bitwise_or_unsupported_concrete_twin_stays_loud() -> None:
    with pytest.raises(ConstructionPanic, match="owner=bitwise_or"):
        fresh(SetValue, (TermValue(1),)).bitwise_or(TermValue(2), "t.py:1", None)

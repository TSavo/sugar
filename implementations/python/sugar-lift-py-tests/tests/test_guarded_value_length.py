from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import (
    FloorValue,
    GuardedValue,
    ListValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import atomic
from sugar_lift_py_tests.outcome import Complete


def test_guarded_length_distributes_to_both_truthful_arms():
    guard = atomic("test.guard", [])
    value = GuardedValue(
        guard,
        TupleValue((TermValue(1), TermValue(2))),
        ListValue((TermValue(3),)),
    )

    outcome = value.length("length-site")

    assert isinstance(outcome, Complete)
    assert outcome.value == GuardedValue(guard, TermValue(2), TermValue(1))


def test_guarded_length_keeps_one_arm_missing_floor_loud():
    value = GuardedValue(
        atomic("test.guard", []),
        TupleValue((TermValue(1),)),
        FloorValue(),
    )

    with pytest.raises(ConstructionPanic) as raised:
        value.length("lying-length-site")

    assert raised.value.info.owner == "length"
    assert raised.value.info.observed == "FloorValue"

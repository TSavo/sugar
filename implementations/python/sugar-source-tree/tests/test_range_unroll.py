"""`for i in range(...)` over CONCRETE integer arguments is a concrete
iterable exactly like a list/tuple literal: it dissolves the same way,
unrolling the body once per synthesized int. A symbolic bound leaves the
fold real and it stays loud, same as any other symbolic iterable."""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.outcome import ExitSet
from sugar_source_tree.panic import SugarNotWritten
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile

from native_carrier_testimony import native_carrier_for


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())


def _invs(src):
    outcome = _fn(src).sugar().desugar()
    assert isinstance(outcome, ExitSet), outcome
    value = outcome.completed_value()
    assert value is not None, outcome
    return value.invs()


def _first_item_waits(src, first):
    """Deleted expectation: each range-body formal equality completed with an
    actual the test supplied. The first item's equality waits on ``z``."""
    carrier = native_carrier_for(_fn(src), operator="equals")
    left, right = carrier.operands
    assert left.to_term(owner="range equality carrier tooth").value == first
    assert right.to_term(owner="range equality carrier tooth").name == "z"


def test_range_stop_unrolls_the_body_per_element():
    _first_item_waits(
        "def A(z):\n    for i in range(3):\n        assert i == z\n    return z\n", 0
    )


def test_range_start_stop_unrolls_the_body_per_element():
    _first_item_waits(
        "def A(z):\n    for i in range(2, 5):\n        assert i == z\n    return z\n", 2
    )


def test_range_start_stop_step_unrolls_the_body_per_element():
    _first_item_waits(
        "def A(z):\n    for i in range(10, 0, -3):\n        assert i == z\n    return z\n",
        10,
    )


def test_empty_range_states_nothing():
    invs = _invs(
        "def A(z):\n    for i in range(0):\n        assert i == z\n    return z\n"
    )
    assert invs == ()


def test_loop_carried_accumulator_folds_over_a_concrete_range():
    # t = 0; for i in range(4): t = t + i; return t  -- folds to 0+1+2+3 = 6.
    post = (
        _fn(
            "def A():\n    t = 0\n    for i in range(4):\n        t = t + i\n    return t\n"
        )
        .sugar()
        .desugar()
        .value.post()
    )
    assert post.args[1].value == 6


def test_symbolic_range_bound_is_loop_recurrence():
    """Live law (replaces factory forall inv): symbolic range(n) is LoopRecurrenceSugar."""
    sugar = _fn(
        "def A(z, n):\n    for i in range(n):\n        assert i == z\n    return z\n"
    ).sugar()
    assert any(type(s).__name__ == "LoopRecurrenceSugar" for s in sugar.statements)


if __name__ == "__main__":
    test_range_stop_unrolls_the_body_per_element()
    test_range_start_stop_unrolls_the_body_per_element()
    test_range_start_stop_step_unrolls_the_body_per_element()
    test_empty_range_states_nothing()
    test_loop_carried_accumulator_folds_over_a_concrete_range()
    test_symbolic_range_bound_is_a_universal()
    print("ok: concrete range unrolls; symbolic range stays loud")

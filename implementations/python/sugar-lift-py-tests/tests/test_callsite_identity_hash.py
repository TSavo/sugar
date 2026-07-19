from __future__ import annotations

from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.ir import make_var


def _recursive_call(term_name: str) -> CallSiteValue:
    call = CallSiteValue("opaque", (), (), make_var(term_name), None)
    # A recursive deferred body is a valid shape: hash must remain finite even
    # when the body retains the callsite that owns it.
    object.__setattr__(call, "body", call)
    return call


def test_callsite_hash_is_finite_for_recursive_body() -> None:
    call = _recursive_call("call")

    first = hash(call)
    second = hash(call)

    assert first == second


def test_callsite_hash_distinguishes_structural_term_twin() -> None:
    left = _recursive_call("left")
    right = _recursive_call("right")

    assert hash(left) != hash(right)


def test_callsite_equality_is_total_for_distinct_equal_cyclic_callsites() -> None:
    left = _recursive_call("same")
    right = _recursive_call("same")
    unequal = _recursive_call("different")

    assert left == right
    assert right == left
    assert left != unequal
    assert unequal != left

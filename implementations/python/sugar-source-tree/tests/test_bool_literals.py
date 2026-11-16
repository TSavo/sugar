"""The `True` / `False` literals -- their sugar source was rebuilt (it had been
deleted in the factory nuke, leaving only a .pyc). Each stands as its own bool
floor value: `return True` -> out == True; a ground `assert True` states nothing
(support, absorbed); `x == True` -> py.eq(x, True)."""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile

from native_carrier_testimony import native_carrier_for


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())


def _uni(src):
    outcome = _fn(src).sugar().desugar()
    assert isinstance(outcome, ExitSet), outcome
    value = outcome.completed_value()
    assert value is not None, outcome
    return value


def test_return_true_and_false_are_bool_consts():
    t = _uni("def A():\n    return True\n").post().args[1]
    assert type(t).__name__ == "_ConstBool" and t.value is True
    f = _uni("def A():\n    return False\n").post().args[1]
    assert type(f).__name__ == "_ConstBool" and f.value is False


def test_ground_assert_true_states_nothing():
    # assert True is support -- absorbed, no inv emitted.
    v = _uni("def A(z):\n    assert True\n    return z\n")
    assert v.invs() == ()


def test_bool_composes_in_equality():
    """Deleted expectation: a formal equality completed with an actual the
    test supplied; no caller supplies one (the function's own proof
    discharges the carrier with none). The literal is the equality's operand."""
    carrier = native_carrier_for(
        _fn("def A(x):\n    assert x == True\n    return x\n"), operator="equals"
    )
    left, right = carrier.operands
    assert left.to_term(owner="bool equality carrier tooth").name == "x"
    assert right.to_term(owner="bool equality carrier tooth").value is True


if __name__ == "__main__":
    test_return_true_and_false_are_bool_consts()
    test_ground_assert_true_states_nothing()
    test_bool_composes_in_equality()
    print("ok: True/False literals rebuilt and lifting")

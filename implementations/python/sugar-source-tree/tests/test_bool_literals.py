"""The `True` / `False` literals -- their sugar source was rebuilt (it had been
deleted in the factory nuke, leaving only a .pyc). Each stands as its own bool
floor value: `return True` -> out == True; a ground `assert True` states nothing
(support, absorbed); `x == True` -> py.eq(x, True)."""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.tree import SourceFile

from native_carrier_testimony import authenticated_function_value


def _uni(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    function = next(SourceFile(path_source(path)).functions())
    outcome = function.sugar().desugar()
    if isinstance(outcome, Complete):
        return outcome.value
    # Deleted expectation: a formal equality was an immediate completed universe.
    return authenticated_function_value(function, operator="equals")


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
    v = _uni("def A(x):\n    assert x == True\n    return x\n")
    assert v.invs()[0].name == "py.eq"
    assert v.invs()[0].args[1].value is True


if __name__ == "__main__":
    test_return_true_and_false_are_bool_consts()
    test_ground_assert_true_states_nothing()
    test_bool_composes_in_equality()
    print("ok: True/False literals rebuilt and lifting")

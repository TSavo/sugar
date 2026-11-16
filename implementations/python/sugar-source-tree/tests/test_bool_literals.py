"""The `True` / `False` literals -- their sugar source was rebuilt (it had been
deleted in the factory nuke, leaving only a .pyc). Each stands as its own bool
floor value: `return True` -> out == True; a ground `assert True` states only
the decided fact `true` (support, absorbed, no failing arm); `x == True` ->
py.eq(x, True)."""

import tempfile
from pathlib import Path

from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.outcome.exit_set import _is_true

from native_carrier_testimony import undecided_function_value


def _uni(src):
    # The one construction door, under a workspace: an ``assert`` that can
    # fail halts at a ground ``AssertionError`` exit whose locus is
    # workspace-relative (``ground_exit``), as every lifted file's is.
    root = Path(tempfile.mkdtemp())
    path = root / "m.py"
    path.write_text(src, encoding="utf-8")
    function = next(open_source_file_for_construction(path, root=root).functions())
    outcome = function.sugar().desugar()
    if isinstance(outcome, ExitSet) and outcome.completed_value() is not None:
        return outcome.completed_value()
    # A formal equality is the undecided equality's two faces: the universe
    # completes under its own ``python:compare.completes`` atom (#7757 NEW-1).
    return undecided_function_value(function, owner="UndecidedCompare:Eq")


def test_return_true_and_false_are_bool_consts():
    t = _uni("def A():\n    return True\n").post().args[1]
    assert type(t).__name__ == "_ConstBool" and t.value is True
    f = _uni("def A():\n    return False\n").post().args[1]
    assert type(f).__name__ == "_ConstBool" and f.value is False


def test_ground_assert_true_states_nothing():
    # assert True is support -- absorbed: the reduction decided its test
    # true, so the only fact it states is ``true`` and no arm can fail.
    v = _uni("def A(z):\n    assert True\n    return z\n")
    assert all(_is_true(inv) for inv in v.invs()), v.invs()


def test_bool_composes_in_equality():
    v = _uni("def A(x):\n    assert x == True\n    return x\n")
    # The undecided ``==``, keyed per evaluation (#7757 NEW-1):
    # the truth of ``python:compare_result("Eq", x, True, <key>)``.
    assert v.invs()[0].name == "python:truth_result"
    compared = v.invs()[0].args[0]
    assert compared.name == "python:compare_result"
    assert compared.args[0].value == "Eq"
    assert compared.args[2].value is True


if __name__ == "__main__":
    test_return_true_and_false_are_bool_consts()
    test_ground_assert_true_states_nothing()
    test_bool_composes_in_equality()
    print("ok: True/False literals rebuilt and lifting")

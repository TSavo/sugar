"""A function's module global bound on two arms of a module statement is
stated at the arm the module's run took, and at no value where the run did
not decide it (#7757, steps 5 and 6).

A module ``if`` binding ``X`` on both arms leaves the final binding a phi
over the ``if``'s slot, read through both arms' keys
(``global_input_keys``).  The function's contract reads its free
``global:X`` input (#8704).  Where the run decided the slot (a ground
test), the value is that arm's, and the row states it
(``stated_global_values``, ``_keys_on_the_arm_the_run_took``).  Where the
run did not (a symbolic module test), no value is stated: a claim that
reads ``X`` is decided for every value of it at prove (#8843), and no flag
selects an arm for the solver (#7757).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _function(source: str, name: str = "f"):
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import FunctionDef
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )
    return function


_GROUND = """\
DEBUG = False
if DEBUG:
    X = 1
else:
    X = 2


def f():
    return X
"""

_SYMBOLIC = """\
def g():
    return None


if g() is None:
    X = 1
else:
    X = 2


def f():
    return X
"""

_TEST = "\n\ndef test_f():\n    assert f() == {v}\n"


def test_the_arm_a_ground_module_test_took_is_stated() -> None:
    from sugar_lift_py_tests.ir import num
    from sugar_lift_py_tests.sugar.call_site_sugar import stated_global_values

    assert dict(stated_global_values(_function(_GROUND))) == {"global:X": num(2)}


def test_the_ground_truthful_half_is_never_refuted(tmp_path: Path) -> None:
    result = run_source_through_real_solver(
        tmp_path / "t", (_GROUND + _TEST).format(v=2)
    )
    assert result.verdict != "unsat"


def test_the_ground_lying_half_is_never_sat(tmp_path: Path) -> None:
    result = run_source_through_real_solver(
        tmp_path / "l", (_GROUND + _TEST).format(v=1)
    )
    assert result.verdict != "sat"


def test_the_symbolic_truthful_half_is_never_refuted(tmp_path: Path) -> None:
    result = run_source_through_real_solver(
        tmp_path / "st", (_SYMBOLIC + _TEST).format(v=1)
    )
    assert result.verdict != "unsat"


@pytest.mark.parametrize("lie", [2, 3])
def test_the_symbolic_lying_half_is_never_sat(lie: int, tmp_path: Path) -> None:
    # The module run does not decide the test for the function's proof, so
    # no value of ``X`` is stated and no flag picks the else arm's.
    result = run_source_through_real_solver(
        tmp_path / "sl", (_SYMBOLIC + _TEST).format(v=lie)
    )
    assert result.verdict != "sat"

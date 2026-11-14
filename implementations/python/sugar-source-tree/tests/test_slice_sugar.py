"""A slice `lower:upper:step` is the py.slice coordinate; omitted bounds are None.

Projection note: a formal's subscript is decided by the caller's actual (the
``subscript`` carrier).  Read the slice term at the formal's own symbolic
stand-in — never via ``UniverseValue.post`` while demands pend.
"""

from __future__ import annotations

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _sub(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.outcome import Completed

    sugar = next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions()).sugar()
    outcome = sugar.desugar()
    if isinstance(outcome, NativeOperationExitCarrierV1):
        outcome = outcome.discharge(
            None,
            {
                coordinate.coordinate_cid: SymbolicValue(
                    make_var(coordinate.declared_name)
                )
                for coordinate in sugar.formal_coordinates
            },
        )
    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    universe = done.value
    for entry in universe.record.statements:
        if type(entry).__name__ == "ReturnValue":
            return entry.value.term
    raise AssertionError(
        f"no subscript term: {[type(s).__name__ for s in universe.record.statements]}"
    )


def test_full_slice():
    sub = _sub("def A(xs):\n    return xs[1:2]\n")
    assert sub.name == "py.subscript"
    sl = sub.args[1]
    assert sl.name == "py.slice"
    assert sl.args[0].value == 1 and sl.args[1].value == 2


def test_omitted_bounds_are_none():
    sl = _sub("def A(xs):\n    return xs[::2]\n").args[1]
    assert sl.name == "py.slice"
    assert sl.args[0].name == "None" and sl.args[1].name == "None"
    assert sl.args[2].value == 2  # step

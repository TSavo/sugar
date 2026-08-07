"""A slice `lower:upper:step` is the py.slice coordinate; omitted bounds are None.

Projection note: formal-parameter subscript operations leave pending
parameter-contract candidates. Read the slice term from the conditional
construction value — never via ``UniverseValue.post`` while demands pend.
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
    universe = next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions()).sugar().desugar().value
    for entry in universe.record.statements:
        if type(entry).__name__ == "ReturnValue":
            return entry.value.term
        if type(entry).__name__ == "ContractConditionalConstructionV1":
            ret = entry.value
            if type(ret).__name__ == "ReturnValue":
                return ret.value.term
            return getattr(ret, "term", ret)
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

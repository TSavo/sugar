"""A definition's branch-suite ``with`` constructs when the definition is accounted (#7699).

#7697 carries a ``with`` of an ``if`` suite as ``BranchSuiteWithV1``, built when
its suite is reduced.  The census accounts a file through
``roll_call.discharge``, which constructs every definition and reduces none,
so no suite was ever selected and the ``with`` was never demanded: a file
ended ``completed`` with its ``with`` unconstructed
(``pandas/plotting/_matplotlib/__init__.py:67``).  An undecided guard leaves
its suite reachable, so the discharge constructs the ``with`` with its
definition: built when its manager has a contract, refused by the same named
``With`` refusal when it has none.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_source_tree.nodes import FunctionDef, With
from sugar_source_tree.panic import SourceTreePanic
from sugar_source_tree.roll_call import discharge

import test_contextlib_suppress_source_exit_faces as opener
from test_contextlib_suppress_source_exit_faces import _corpus


_LOCAL_MANAGER = (
    "from contextlib import contextmanager\n"
    "@contextmanager\n"
    "def cm():\n"
    "    yield 1\n"
)


def _guarded(manager_head: str) -> str:
    return (
        f"{_LOCAL_MANAGER}"
        "def f(c):\n"
        "    if c:\n"
        f"        with {manager_head}:\n"
        "            pass\n"
        "    return 7\n"
    )


def _open(tmp_path: Path, source: str):
    return opener._open(_corpus(tmp_path, source))


def test_a_reachable_branch_with_is_constructed_by_the_discharge(tmp_path):
    source_file = _open(tmp_path, _guarded("cm()"))
    report = discharge(source_file)
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    line = with_node.line_col_span().start_line
    assert [e for e in report.present if e.kind == "With" and e.start_line == line]
    assert type(with_node.sugar()) is WithSourceResourceSugar


def _with_refusals(source_file):
    return [
        str(panic)
        for node, panic in source_file.reporter.gaps
        if isinstance(node, With)
    ]


def test_a_reachable_branch_with_without_a_contract_is_refused(tmp_path):
    # The lying twin: before #7699 this discharge answered clean while the
    # ``with`` under the undecided ``if c:`` was never constructed.
    source_file = _open(tmp_path, _guarded("unknown_manager()"))
    f = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    f.sugar()  # constructing the definition alone defers the with ...
    assert _with_refusals(source_file) == []
    report = discharge(source_file)  # ... accounting it refuses it, by name
    (refusal,) = _with_refusals(source_file)
    assert "CONTEXT MANAGER RESOLUTION GAP" in refusal
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    line = with_node.line_col_span().start_line
    assert not [e for e in report.present if e.kind == "With" and e.start_line == line]
    with pytest.raises(SourceTreePanic, match="CONTEXT MANAGER RESOLUTION GAP"):
        with_node.sugar()

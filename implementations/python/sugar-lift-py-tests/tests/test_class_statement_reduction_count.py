"""Plan row 1 (step 6): reading a class's content address reduces nothing.

``a = Box(1)`` builds an object place state during the temporal rewrite. That
used to reduce ``Box``'s class statement twice per class call: once inside the
call (``ClassConstructorBodySugar.desugar`` reduces its ``definition``), and a
second time only to read ``class_definition_cid``, which the statement's sugar
already holds as a property. The second one is deleted.

The first one is still a reduction of the statement at every call, where the
standard is one reduction of one statement ("reduce once"). It is carried by
how the temporal rewrite substitutes a module-level definition into each
function, so it is #7794 (plan row 7, the temporal row) and is not fixed here.
The count below is today's measured number, one per class call, not a target:
when #7794 lands this test goes red because the count dropped, and the number
is then lowered to one per statement.

The solver twin differs in one literal: the field read off the constructed
receiver is decided by the floor, truthful ``sat``, lying ``unsat``.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_TWIN = (
    "class Box:\n"
    "    def __init__(self, n):\n"
    "        self.n = n\n"
    "\n"
    "\n"
    "def test_box():\n"
    "    a = Box(1)\n"
    "    assert a.n == {claim}\n"
)


def test_a_field_of_a_constructed_receiver_reaches_the_solver(tmp_path: Path) -> None:
    truthful = run_source_through_real_solver(tmp_path / "t", _TWIN.format(claim=1))
    lying = run_source_through_real_solver(tmp_path / "l", _TWIN.format(claim=2))
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"


_ONE_CALL = _TWIN.format(claim=1)
_TWO_CALLS = (
    "class Box:\n"
    "    def __init__(self, n):\n"
    "        self.n = n\n"
    "\n"
    "\n"
    "def test_box():\n"
    "    a = Box(1)\n"
    "    b = Box(2)\n"
    "    assert a.n == 1\n"
)


def _class_statement_reductions(source: str, monkeypatch) -> int:
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.sugar.class_definition_sugar import ClassDefinitionSugar
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree.nodes import FunctionDef
    from sugar_source_tree.tree import SourceFile

    reductions: Counter[str] = Counter()
    reduce_statement = ClassDefinitionSugar.desugar

    def counted(self, ctx=None):
        reductions[self.class_name] += 1
        return reduce_statement(self, ctx)

    monkeypatch.setattr(ClassDefinitionSugar, "desugar", counted)
    tree = SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name.startswith("test_")
    )
    assert isinstance(function_universe_outcome(function), Complete)
    return reductions["Box"]


@pytest.mark.parametrize(
    ("source", "class_calls"),
    [(_ONE_CALL, 1), (_TWO_CALLS, 2)],
    ids=["one-call", "two-calls"],
)
def test_reading_the_class_address_does_not_reduce_the_statement(
    source: str, class_calls: int, monkeypatch
) -> None:
    """The probe: reductions of ``Box``'s class statement in one function.

    Two per class call before this deletion (2 and 4 for these sources), one
    per class call after it (1 and 2). The one left is #7794.
    """

    assert _class_statement_reductions(source, monkeypatch) == class_calls

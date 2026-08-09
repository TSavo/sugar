"""A `while` over CONCRETE state dissolves: each iteration is one more
substitution, the condition ground-decided structurally against the carried
state.

Symbolic and `while True:` cases are no longer factory-era `SugarNotWritten`
refusals. They construct as ``LoopRecurrenceSugar`` with exhaustion faces
(see ``test_live_loop_post_projection``). This file keeps the concrete-unroll
laws and rewrites the "stays loud" cases to the live recurrence shape.
"""

from __future__ import annotations

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())


def _out(src):
    return _fn(src).sugar().desugar().value.post().args[1]


def test_concrete_counter_unrolls():
    # i = 0; while i < 3: i = i + 1; return i  ->  out == 3
    assert (
        _out(
            "def A():\n    i = 0\n    while i < 3:\n        i = i + 1\n    return i\n"
        ).value
        == 3
    )


def test_concrete_accumulator_unrolls():
    # sum 0..3 through a while: out == 6
    assert (
        _out(
            "def A():\n    i = 0\n    t = 0\n    while i < 4:\n        t = t + i\n"
            "        i = i + 1\n    return t\n"
        ).value
        == 6
    )


def test_false_condition_skips_the_body():
    assert (
        _out(
            "def A():\n    i = 5\n    while False:\n        i = 9\n    return i\n"
        ).value
        == 5
    )


def test_while_true_constructs_as_loop_recurrence():
    """Live law (replaces factory SugarNotWritten): infinite while is recurrence.

    Fuel exhaustion is projected as a NormalExhaustion face under
    LoopGuardedProjection — not a silent complete without loop structure.
    """
    sugar = _fn(
        "def A():\n    i = 0\n    while True:\n        i = i + 1\n    return i\n"
    ).sugar()
    loop = next(
        s for s in sugar.statements if type(s).__name__ == "LoopRecurrenceSugar"
    )
    assert type(loop).__name__ == "LoopRecurrenceSugar"


def test_symbolic_condition_constructs_as_loop_recurrence():
    """Live law (replaces factory SugarNotWritten): symbolic while is recurrence."""
    sugar = _fn(
        "def A(n):\n    i = 0\n    while i < n:\n        i = i + 1\n    return i\n"
    ).sugar()
    loop = next(
        s for s in sugar.statements if type(s).__name__ == "LoopRecurrenceSugar"
    )
    assert type(loop).__name__ == "LoopRecurrenceSugar"
    # Tail read is a guarded projection over exhaustion faces.
    post_read = sugar.statements[-1].value
    assert type(post_read).__name__ == "GuardedBindingReadSugar"
    assert type(post_read.state).__name__ == "LoopGuardedProjection"

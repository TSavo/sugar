from __future__ import annotations

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    return next(SourceFile(path_source(path)).functions())


def test_live_for_projects_break_and_exhaustion_before_tail_substitution():
    function = _function(
        """
def arbitrary(items, stop):
    carried = 0
    for renamed in items:
        if renamed == stop:
            break
        carried = carried + renamed
    return carried
"""
    )

    constructed = function.sugar()

    assert type(constructed.statements[1]).__name__ == "LoopRecurrenceSugar"
    recurrence = constructed.statements[1].desugar().value
    assert len(recurrence.inv_contribution()) == 1
    equation = recurrence.inv_contribution()[0]
    assert equation.name == "="
    assert equation.args[1].name == "python:loop.step"
    assert equation.args[1].args[0] == equation.args[0]
    post_read = constructed.statements[2].value
    assert type(post_read).__name__ == "GuardedBindingReadSugar"
    assert type(post_read.state).__name__ == "LoopGuardedProjection"
    assert {
        face.completion_kind for face in post_read.state.completed_faces
    } == {"BreakExit", "NormalExhaustion"}


def test_renamed_lying_twin_does_not_authorize_loop_target_by_spelling():
    truthful = _function(
        """
def arbitrary(items):
    carried = 0
    for renamed in items:
        carried = carried + renamed
    return carried
"""
    ).sugar()
    lying = _function(
        """
def arbitrary(items):
    carried = 0
    renamed = 99
    for other in items:
        carried = carried + other
    return carried
"""
    ).sugar()

    truthful_loop = truthful.statements[1]
    lying_loop = lying.statements[2]
    assert truthful_loop.target_cid != lying_loop.target_cid


def test_live_symbolic_while_projects_false_test_exhaustion_before_tail():
    function = _function(
        """
def arbitrary(limit):
    carried = 0
    while carried < limit:
        carried = carried + 1
    return carried
"""
    )

    constructed = function.sugar()

    assert type(constructed.statements[1]).__name__ == "LoopRecurrenceSugar"
    post_read = constructed.statements[2].value
    assert type(post_read.state).__name__ == "LoopGuardedProjection"
    assert {
        face.completion_kind for face in post_read.state.completed_faces
    } == {"NormalExhaustion"}

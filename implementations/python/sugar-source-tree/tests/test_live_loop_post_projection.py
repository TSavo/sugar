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
    function = _function("""
def arbitrary(items, stop):
    carried = 0
    for renamed in items:
        if renamed == stop:
            break
        carried = carried + renamed
    return carried
""")

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
    assert {face.completion_kind for face in post_read.state.completed_faces} == {
        "BreakExit",
        "NormalExhaustion",
    }


def test_renamed_lying_twin_does_not_authorize_loop_target_by_spelling():
    truthful = _function("""
def arbitrary(items):
    carried = 0
    for renamed in items:
        carried = carried + renamed
    return carried
""").sugar()
    lying = _function("""
def arbitrary(items):
    carried = 0
    renamed = 99
    for other in items:
        carried = carried + other
    return carried
""").sugar()

    truthful_loop = truthful.statements[1]
    lying_loop = lying.statements[2]
    assert truthful_loop.target_cid != lying_loop.target_cid


def test_live_symbolic_while_projects_false_test_exhaustion_before_tail():
    function = _function("""
def arbitrary(limit):
    carried = 0
    while carried < limit:
        carried = carried + 1
    return carried
""")

    constructed = function.sugar()

    assert type(constructed.statements[1]).__name__ == "LoopRecurrenceSugar"
    post_read = constructed.statements[2].value
    assert type(post_read.state).__name__ == "LoopGuardedProjection"
    assert {face.completion_kind for face in post_read.state.completed_faces} == {
        "NormalExhaustion"
    }


def test_live_for_else_projects_else_state_only_on_normal_exhaustion():
    constructed = _function("""
def arbitrary(items, stop):
    carried = 0
    for renamed in items:
        if renamed == stop:
            break
        carried = renamed
    else:
        carried = 42
    return carried
""").sugar()

    loop = constructed.statements[1]
    graph = loop.construction.wire_graph()
    root = graph["root"]
    assert root["elseBodyCid"] is not None
    assert root["elseExhaustionObligationCid"] is not None

    post = constructed.statements[2].value.state
    by_kind = {face.completion_kind: face for face in post.completed_faces}
    assert set(by_kind) == {"BreakExit", "NormalExhaustion"}
    exhaustion = by_kind["NormalExhaustion"].state
    assert type(exhaustion).__name__ == "IntLiteralSugar"
    assert exhaustion.value == 42
    assert type(by_kind["BreakExit"].state).__name__ == "LoopBindingRefSugar"


def test_renamed_else_lying_twin_cannot_run_else_on_break_face():
    constructed = _function("""
def arbitrary(items, gate):
    result = 0
    for renamed in items:
        if renamed == gate:
            break
    else:
        result = 9
    return result
""").sugar()

    post = constructed.statements[2].value.state
    by_kind = {face.completion_kind: face for face in post.completed_faces}
    assert by_kind["NormalExhaustion"].state.value == 9
    assert type(by_kind["BreakExit"].state).__name__ == "LoopBindingRefSugar"


def test_live_while_else_uses_false_test_face_before_tail_substitution():
    constructed = _function("""
def arbitrary(limit):
    carried = 0
    while carried < limit:
        carried = carried + 1
    else:
        carried = 17
    return carried
""").sugar()

    loop = constructed.statements[1]
    root = loop.construction.wire_graph()["root"]
    assert root["elseBodyCid"] is not None
    post = constructed.statements[2].value.state
    assert len(post.completed_faces) == 1
    assert post.completed_faces[0].completion_kind == "NormalExhaustion"
    assert post.completed_faces[0].state.value == 17


def test_guarded_return_in_live_loop_is_an_outward_halted_face():
    constructed = _function("""
def arbitrary(items, stop):
    carried = 0
    for renamed in items:
        carried = renamed
        if renamed == stop:
            return carried
    return carried
""").sugar()

    loop = constructed.statements[1]
    root = loop.construction.wire_graph()["root"]
    assert len(root["outwardHaltedFaceCids"]) == 1
    halted_state = loop.outward_faces[0].state[0]
    assert (
        halted_state.coordinate.cid
        == constructed.statements[2]
        .value.state.completed_faces[0]
        .state.binding_coordinate_cid
    )
    assert type(halted_state.state.sugar()).__name__ != "IntLiteralSugar"
    exits = loop.desugar()
    assert type(exits).__name__ == "ExitSet"
    assert any(
        type(face).__name__ == "Completed" and not face.value.can_fall_through
        for face in exits.exits
    )


def test_guarded_raise_in_live_while_is_an_outward_halted_face():
    constructed = _function("""
def arbitrary(limit, stop):
    carried = 0
    while carried < limit:
        if carried == stop:
            raise ValueError(carried)
        carried = carried + 1
    return carried
""").sugar()

    loop = constructed.statements[1]
    root = loop.construction.wire_graph()["root"]
    assert len(root["outwardHaltedFaceCids"]) == 1
    exits = loop.desugar()
    assert type(exits).__name__ == "ExitSet"
    assert any(
        type(face).__name__ == "Halted" and type(face.effect).__name__ == "RaiseEffect"
        for face in exits.exits
    )

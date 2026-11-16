from __future__ import annotations

from pathlib import Path
from tempfile import mkdtemp

from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted


def _function(source: str):
    # The one door a file is opened by: seated in its own workspace, so every
    # locus it cites is workspace-relative (a ground exit's included).
    directory = Path(mkdtemp())
    path = directory / "live_loop_post_projection.py"
    path.write_text(source)
    return next(open_source_file_for_construction(path, root=directory).functions())


def _returned(function):
    """What a function whose loop ran in hand returns: its one completed arm."""
    outcome = function.sugar().desugar()
    assert isinstance(outcome, ExitSet), outcome
    value = outcome.completed_value()
    assert value is not None, outcome.exits
    return value.post().args[1].value


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
    # The loop is reduced where it runs, in its function's block: ``carried``
    # is bound before it there, and nowhere when the loop statement is
    # desugared alone.  ``iter(items)``, ``renamed == stop`` and
    # ``carried + renamed`` each keep their halt beside the completion.
    outcome = function.sugar().desugar()
    assert isinstance(outcome, ExitSet), outcome
    assert outcome.halts(), outcome.exits
    completed = [
        face for face in outcome.normalize().exits if isinstance(face, Completed)
    ]
    assert completed, outcome.exits
    # One step equation per name the loop writes: ``carried`` under its
    # binding coordinate, ``renamed`` under its post-loop key.
    stated = []
    for arm in completed:
        equations = [
            inv
            for inv in arm.value.invs()
            if getattr(inv, "name", None) == "="
            and getattr(inv.args[1], "name", None) == "python:loop.step"
        ]
        if equations:
            stated.append(equations)
    assert stated, completed
    for equations in stated:
        assert len(equations) == 2
        for equation in equations:
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
    # Every face reads what the loop publishes under its own key as it
    # leaves by that face (``LoopRecurrenceSugar._publication``); the
    # exhaustion face's publication is what the ``else`` suite left, the
    # break face's is what the breaking item left.  Neither reads the else
    # suite's statement keys, which are bound only where the suite ran.
    for kind, face in by_kind.items():
        assert type(face.state).__name__ == "LoopBindingRefSugar"
        assert face.state.completion_kind == kind
        assert face.state.name == "carried"


def test_live_for_else_runs_the_else_only_when_the_loop_is_exhausted():
    # Run in hand: the reduction decides the exit, and the read after the
    # loop takes that face's publication (``decided_loop_exit``).
    source = """
def arbitrary():
    carried = 0
    for renamed in [1, 2, 3]:
        if renamed == STOP:
            break
        carried = renamed
    else:
        carried = 42
    return carried
"""
    # Never broken: every item ran, then the else.
    assert _returned(_function(source.replace("STOP", "7"))) == 42
    # Broken at 2: the else never ran, ``carried`` is what item 1 left.
    assert _returned(_function(source.replace("STOP", "2"))) == 1


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
    assert set(by_kind) == {"BreakExit", "NormalExhaustion"}
    for kind, face in by_kind.items():
        assert type(face.state).__name__ == "LoopBindingRefSugar"
        assert face.state.completion_kind == kind


def test_renamed_else_lying_twin_never_publishes_the_else_on_a_break() -> None:
    # The twin whose items break: the else's ``result = 9`` never runs, so
    # the read after the loop is the pre-loop 0, never the else's 9.
    source = """
def arbitrary():
    result = 0
    for renamed in [1, 2, 3]:
        if renamed == GATE:
            break
    else:
        result = 9
    return result
"""
    assert _returned(_function(source.replace("GATE", "2"))) == 0
    assert _returned(_function(source.replace("GATE", "5"))) == 9


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
    exhaustion = post.completed_faces[0].state
    assert type(exhaustion).__name__ == "LoopBindingRefSugar"
    assert exhaustion.completion_kind == "NormalExhaustion"


def test_live_while_else_publishes_the_elses_write() -> None:
    # Run in hand (the test decides at every item): after the test is false
    # the else runs, and the read after the loop is its 17, never the 3 the
    # last item left.
    function = _function("""
def arbitrary():
    carried = 0
    while carried < 3:
        carried = carried + 1
    else:
        carried = 17
    return carried
""")
    assert _returned(function) == 17


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
    function = _function("""
def arbitrary(limit, stop):
    carried = 0
    while carried < limit:
        if carried == stop:
            raise ValueError(carried)
        carried = carried + 1
    return carried
""")
    constructed = function.sugar()

    loop = constructed.statements[1]
    root = loop.construction.wire_graph()["root"]
    assert len(root["outwardHaltedFaceCids"]) == 1
    # Reduced where it runs, in the function's block, after ``carried = 0``:
    # the loop statement desugared alone reads ``carried`` with nothing bound.
    exits = function.sugar().desugar()
    assert isinstance(exits, ExitSet)
    assert any(
        isinstance(face, Halted)
        and type(face.effect).__name__ == "RaiseEffect"
        and face.effect.exception_name == "ValueError"
        for face in exits.exits
    )

"""#7827: suspected dropped faces from the halt-spellings map, each with a twin.

Tests only; no lifter change. Each suspected site from #7827 is either
confirmed by a smallest program and pinned ``xfail(strict=True)``, with the
reason naming the site and the face lost, or struck with evidence that the
source cannot reach it.

The truthful half of each twin is the same program without the operation the
site mishandles, and it keeps every face. The lying half exercises the site.
Where the solver cannot tell the halves apart, because a claim over an
unbound formal stays ``open`` (#7766), the twin is also pinned at the
reduction level, where the lost face is visible.

Confirmed (pinned expected-red):

1. ``floor/guarded_value.py`` ``GuardedValue._map``: an ``Incomplete`` on the
   true arm returns at once, and the false arm is never evaluated. ``x = [] if
   c else [2]; return x[0]`` keeps a completed face under ``not c``, but it
   holds no ``ReturnValue``; Python returns ``2`` there.

Confirmed and fixed by H2 of #7825 (the store family answers its two faces
at the producer, ``store_faces``):

4. ``generator_construction.py`` attribute-store step: a generator manager
   whose body stores ``o.x = 1`` before ``yield`` reaches its yield on the
   store's completed face.
6. ``o.x += 1`` (through ``ExitSet.and_then`` in ``AugAssignSugar``) keeps
   the face where getattr, add and setattr all complete.

Struck (each test below records why): ``sugar/for_universal_sugar.py``
(since deleted),
``sugar/exit_set_routing.py`` ``exitset_to_outcome`` (since deleted, #7826),
``sugar/match_sugar.py`` ``_outcome_as_exitset`` / ``_incomplete_as_halted``,
and of item 6: ``sugar_outcome_to_exitset``, ``Incomplete.and_then`` and
``caller_parameter_contract.py``'s ``undischarged`` arm.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    WitnessPipelineError,
    run_source_through_real_solver,
)


def _tree(source: str):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree.tree import SourceFile

    return SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def _function(source: str, name: str = "test_f"):
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree import nodes

    (function,) = tuple(
        node
        for node in _tree(source).nodes()
        if isinstance(node, nodes.FunctionDef) and node.name == name
    )
    return function_universe_outcome(function)


def _faces(outcome) -> tuple[int, tuple[str, ...]]:
    """(completed faces, the effect type of each halted face)."""
    from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted

    if isinstance(outcome, Complete):
        assert outcome.follow().continues, outcome
        return 1, ()
    assert isinstance(outcome, ExitSet), outcome
    return (
        sum(isinstance(face, Completed) for face in outcome.exits),
        tuple(
            type(face.effect).__name__
            for face in outcome.exits
            if isinstance(face, Halted)
        ),
    )


def _verdict(tmp_path: Path, source: str) -> str:
    try:
        return run_source_through_real_solver(tmp_path, source).verdict
    except WitnessPipelineError as exc:
        if "no assertion rows" in str(exc):
            return "no assertion rows"
        raise


# ---------------------------------------------------------------------------
# 1. floor/guarded_value.py GuardedValue._map: confirmed.
# ---------------------------------------------------------------------------

_GUARDED = (
    "def test_f(xs):\n    c = xs is None\n    x = {arm} if c else [2]\n    {tail}"
)
_GUARDED_ASSERT = "y = x[0]\n    assert c or y == 2\n"
_GUARDED_RETURN = "return x[0]\n"


@pytest.mark.parametrize("arm", ["[1]", "[]"], ids=["truthful", "lying"])
def test_guarded_value_twin_through_the_solver_is_open_on_both_halves(
    arm: str, tmp_path: Path
) -> None:
    """The solver cannot tell the halves apart: the claim is over an unbound
    formal and stays open (#7766). The drop is pinned at the reduction level."""
    source = _GUARDED.format(arm=arm, tail=_GUARDED_ASSERT)

    assert _verdict(tmp_path, source) == "open"


def _completed_returns(outcome) -> list:
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet

    if isinstance(outcome, Complete):
        records = [outcome.value]
    else:
        assert isinstance(outcome, ExitSet), outcome
        records = [face.value for face in outcome.exits if isinstance(face, Completed)]
    return [
        statement
        for record in records
        for statement in getattr(getattr(record, "record", record), "statements", ())
        if isinstance(statement, ReturnValue)
    ]


def test_guarded_value_truthful_half_returns_on_its_completed_face() -> None:
    outcome = _function(_GUARDED.format(arm="[1]", tail=_GUARDED_RETURN))

    assert len(_completed_returns(outcome)) == 1


@pytest.mark.xfail(
    strict=True,
    reason=(
        "floor/guarded_value.py GuardedValue._map: the true arm's Incomplete "
        "(IndexError from [][0]) returns before the false arm is evaluated, so "
        "the completed face under `not c` has no ReturnValue; Python returns 2 "
        "there (#7827 item 1)"
    ),
)
def test_guarded_value_lying_half_returns_the_false_arm_on_its_completed_face() -> None:
    outcome = _function(_GUARDED.format(arm="[]", tail=_GUARDED_RETURN))

    assert len(_completed_returns(outcome)) == 1


# ---------------------------------------------------------------------------
# 2. sugar/for_universal_sugar.py: struck, then deleted (inventory item 38).
#    No source node constructed ForUniversalSugar. A source `for` goes through
#    the loop recurrence, which keeps the body's halt beside the completion.
# ---------------------------------------------------------------------------

_FOR = "def test_f(xs):\n    for x in xs:\n        {body}\n    assert 1 == 1\n"


def test_for_universal_sugar_is_never_reached_from_source() -> None:
    """The second reducer of a ``for`` loop is gone; a source loop still
    reduces, through the one loop recurrence."""
    import importlib.util

    assert (
        importlib.util.find_spec("sugar_lift_py_tests.sugar.for_universal_sugar")
        is None
    )

    _function(_FOR.format(body="raise ValueError"))
    _function(_FOR.format(body="y = 1"))


@pytest.mark.parametrize(
    ("body", "faces", "verdict"),
    [
        ("y = 1", (1, ()), "sat"),
        ("raise ValueError", (1, ("RaiseEffect",)), "open"),
    ],
    ids=["truthful", "lying"],
)
def test_a_source_loop_keeps_its_body_halt_beside_the_completion(
    body: str, faces, verdict: str, tmp_path: Path
) -> None:
    source = _FOR.format(body=body)

    assert _faces(_function(source)) == faces
    assert _verdict(tmp_path, source) == verdict


# ---------------------------------------------------------------------------
# 3. sugar/exit_set_routing.py exitset_to_outcome: deleted (#7826). The try
#    family hands back its own faces; no converter projects them onto a
#    linear record, so none can drop an untyped completed arm.
# ---------------------------------------------------------------------------


def test_the_linear_projection_of_a_boundary_is_gone() -> None:
    import sugar_lift_py_tests.sugar.exit_set_routing as routing

    assert not hasattr(routing, "exitset_to_outcome")
    assert not hasattr(routing, "promote_raise_halts")


# ---------------------------------------------------------------------------
# 4. generator_construction.py attribute-store step: confirmed. Reachable
#    only through an installed generator manager, so this twin is at the
#    reduction level; the one-file solver harness cannot install a package.
# ---------------------------------------------------------------------------


def _generator_resume_faces(tmp_path: Path, body: str):
    from test_sole_path_manager_construction import _installed_generator_with

    from sugar_lift_py_tests.outcome import Completed, ExitSet
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset

    boundary = _installed_generator_with(
        tmp_path,
        f"def make_guard(o):\n    {body}\n    yield o\n",
        "import arbitrary\ndef use(o):\n    with arbitrary.make_guard(o):\n        pass\n",
    )
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    entered = machine.resume()
    faces = entered.exits if isinstance(entered, ExitSet) else (entered,)
    return [
        (
            type(face.value).__name__
            if isinstance(face, Completed)
            else type(face).__name__
        )
        for face in faces
    ]


def test_generator_truthful_half_reaches_its_yield(tmp_path: Path) -> None:
    assert _generator_resume_faces(tmp_path, "y = 1") == ["YieldEffect"]


def test_generator_lying_half_reaches_its_yield_when_the_store_completes(
    tmp_path: Path,
) -> None:
    faces = _generator_resume_faces(tmp_path, "o.x = 1")

    assert "YieldEffect" in faces


# ---------------------------------------------------------------------------
# 5. sugar/match_sugar.py _outcome_as_exitset / _incomplete_as_halted:
#    struck. A guarded case has no sugar (Match.sugar refuses by name), and a
#    halting subject is handed back before either converter runs.
# ---------------------------------------------------------------------------


def test_a_guarded_case_refuses_by_name() -> None:
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(SugarNotWritten, match="Match.sugar"):
        _function(
            "def test_f(c):\n    match 5:\n        case 5 if c:\n"
            "            a = 1\n    return 3\n"
        )


@pytest.mark.parametrize(
    ("arm", "faces"),
    [("[1]", (1, ())), ("[]", (1, ("RaiseEffect",)))],
    ids=["truthful", "lying"],
)
def test_a_guarded_halting_subject_keeps_both_faces_without_the_converters(
    arm: str, faces, monkeypatch
) -> None:
    import sugar_lift_py_tests.sugar.match_sugar as match_sugar

    def refuse(*args):
        raise AssertionError("converter reached")

    monkeypatch.setattr(match_sugar, "_incomplete_as_halted", refuse)
    outcome = _function(
        f"def test_f(xs):\n    c = xs is None\n    x = {arm} if c else [2]\n"
        "    match x[0]:\n        case 2:\n            a = 1\n    return 3\n"
    )

    assert _faces(outcome) == faces


# ---------------------------------------------------------------------------
# 6. The store family read as a plain halt.
#    Confirmed at outcome/exit_set.py outcome_to_exitset, reached by
#    `o.x += 1` (ExitSet.and_then in AugAssignSugar).
#    Struck: sugar_outcome_to_exitset (its ten callers pass a with-manager,
#    __enter__ or __exit__ expression outcome, never a store);
#    Incomplete.and_then (no expression step runs after a store: a chained
#    target store is sequenced by the block reducer, pinned below);
#    caller_parameter_contract.py's undischarged arm (the native projector is
#    not called from source reduction; a formal store's call reduces the
#    callee with its actuals bound).
# ---------------------------------------------------------------------------

_STORE = "import mod\n\n\ndef test_f():\n    o = mod.make()\n    {line}\n    {tail}"


def test_augassign_truthful_half_keeps_a_completed_face(tmp_path: Path) -> None:
    source = _STORE.format(line="y = o.x + 1", tail="assert 1 == 1\n")

    assert _faces(_function(source))[0] == 1
    assert _verdict(tmp_path, source) == "open"


def test_augassign_lying_half_keeps_a_completed_face(tmp_path: Path) -> None:
    source = _STORE.format(line="o.x += 1", tail="assert 1 == 1\n")

    assert _faces(_function(source))[0] == 1
    assert _verdict(tmp_path, source) == "open"


def test_a_chained_target_store_keeps_its_completed_face() -> None:
    """Struck for Incomplete.and_then: the store before the next target is
    sequenced by the block reducer, which keeps both of its faces."""
    completed, halts = _faces(
        _function(_STORE.format(line="o.x = a = 1", tail="return a\n"))
    )

    assert completed == 1
    assert "AttributeStoreRuntimeEffect" in halts
